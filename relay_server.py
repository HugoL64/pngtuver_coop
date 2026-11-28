"""Micro-servidor Relay WebSocket para PNGTuber Co-op (Protocolo v1.3).

Implementa topología en estrella (Host <-> Relay <-> Guests 2..4),
validación estricta de esquemas, anti-enumeración, rotación de session_token
con ventana de gracia de 60s y rate limiting por dirección.
"""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import time
from collections import deque

import websockets
from websockets.exceptions import ConnectionClosed

from core.app_constants import log_debug

from core.relay_schemas import (
    PROTOCOL_VERSION,
    SchemaError,
    VALID_SLOTS,
    parse_json_strict,
    validate_auth_host,
    validate_guest_action,
    validate_guest_voice,
    validate_join,
    validate_join_decision,
    validate_kick,
    validate_permissions,
    validate_presence,
    validate_rotate_invite,
    validate_state_sync,
)

AUTH_TIMEOUT_SEC = 5.0
LOBBY_TIMEOUT_SEC = 45.0
HOST_OFFLINE_TTL_SEC = 15 * 60.0
ROOM_MAX_TTL_SEC = 12 * 3600.0
SESSION_TTL_SEC = 5 * 3600.0
SESSION_GRACE_SEC = 60.0
RECONNECT_GRACE_SEC = 30.0

MAX_UNAUTH_PER_IP = 2
MAX_AUTH_PER_ROOM_IP = 8
MAX_SOCKETS_PER_ROOM = 12
MAX_PENDING_PER_ROOM = 3
MAX_ROOMS_PER_IP_HOUR = 5
MAX_ACTIVE_ROOMS_PER_IP = 3
MAX_GLOBAL_ROOMS = 500
MAX_GLOBAL_CONNECTIONS = 100
REJECTION_COOLDOWN_SEC = 30.0
CLEANUP_INTERVAL_SEC = 30.0

MAX_GUEST_BYTES = 512
MAX_HOST_CONTROL_BYTES = 1024
MAX_STATE_SYNC_BYTES = 8192

BASE32_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _sha256_hex(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _verify_scrypt_pin(pin: str, pin_kdf: dict) -> bool:
    if not pin_kdf:
        return True
    if not isinstance(pin, str) or not pin:
        return False
    p = pin_kdf["params"]
    derived = hashlib.scrypt(
        pin.encode("utf-8"),
        salt=pin_kdf["salt"].encode("utf-8"),
        n=p["N"],
        r=p["r"],
        p=p["p"],
        dklen=32,
    ).hex()
    return hmac.compare_digest(derived, pin_kdf["hash"])


class _TokenBucket:
    def __init__(self, rate_per_sec: float, burst: float):
        self.rate = rate_per_sec
        self.burst = burst
        self.tokens = burst
        self.last = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class _Room:
    def __init__(self, room_code: str, host_secret_hash: str, invite_token_hash: str, pin_kdf, owner_ip: str):
        self.room_code = room_code
        self.host_secret_hash = host_secret_hash
        self.invite_token_hash = invite_token_hash
        self.pin_kdf = pin_kdf
        self.owner_ip = owner_ip
        self.created_at = time.monotonic()
        self.host_ws = None
        self.host_offline_since = None
        self.slots = {}  # slot -> {"ws", "session_hash", "prev_hash", "prev_until", "prev_used", "tag", "display_name", "expires_at"}
        self.pending = {}  # req_id -> {"ws", "ip", "display_name", "tag", "created_at", "valid"}
        self.total_sockets = set()
        self.ip_auth_counts = {}
        self.banned_ips = set()
        self.rejected_ips = {}  # ip -> monotonic_until
        self.hmac_key = secrets.token_bytes(32)

    def stable_tag(self, seed: str) -> str:
        return hmac.new(self.hmac_key, seed.encode("utf-8"), hashlib.sha256).hexdigest()[:3].upper()

    def free_slot(self):
        for s in VALID_SLOTS:
            if s not in self.slots:
                return s
        return None


class RelayServer:
    """Servidor Relay WebSocket en estrella (Protocolo v1.3)."""

    def __init__(self, allowed_guest_origins=None, require_guest_origin=True, trusted_proxies=None, local_host_only=False):
        # Si es True, `auth_host` solo se acepta desde loopback directo (sin pasar por túnel/proxy).
        self.local_host_only = bool(local_host_only)
        self._kdf_sem = asyncio.Semaphore(2)
        self.allowed_guest_origins = set(
            allowed_guest_origins
            or {
                "http://127.0.0.1:8766",
                "http://localhost:8766",
                "http://127.0.0.1:8000",
                "http://localhost:8000",
                "http://127.0.0.1:8765",
                "http://localhost:8765",
                "https://localhost",
            }
        )
        self.require_guest_origin = require_guest_origin
        self.trusted_proxies = set(trusted_proxies if trusted_proxies is not None else {"127.0.0.1", "::1"})
        self.rooms = {}
        self.unauth_by_ip = {}
        self.room_creations_by_ip = {}
        self.join_rate_by_ip = {}
        self.active_connections = 0

    def allow_origin(self, origin: str):
        if origin:
            self.allowed_guest_origins.add(origin.rstrip("/"))

    def _gen_room_code(self) -> str:
        for _ in range(16):
            code = "".join(secrets.choice(BASE32_ALPHABET) for _ in range(8))
            if code not in self.rooms:
                return code
        raise RuntimeError("No se pudo generar room_code")

    def _check_room_quota(self, ip: str) -> bool:
        if len(self.rooms) >= MAX_GLOBAL_ROOMS:
            return False
        now = time.monotonic()
        q = self.room_creations_by_ip.setdefault(ip, deque())
        while q and (now - q[0]) > 3600.0:
            q.popleft()
        active = sum(1 for r in self.rooms.values() if r.owner_ip == ip)
        if len(q) >= MAX_ROOMS_PER_IP_HOUR or active >= MAX_ACTIVE_ROOMS_PER_IP:
            return False
        q.append(now)
        return True

    def _check_join_rate(self, ip: str) -> bool:
        now = time.monotonic()
        q = self.join_rate_by_ip.setdefault(ip, deque())
        while q and (now - q[0]) > 10.0:
            q.popleft()
        if len(q) >= 10:
            return False
        q.append(now)
        return True

    async def _send_json(self, ws, obj: dict):
        try:
            await ws.send(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        except Exception:
            pass

    async def _close_uniform_fail(self, ws, wait_sec=LOBBY_TIMEOUT_SEC):
        await asyncio.sleep(wait_sec)
        try:
            await ws.close(4002, "No autorizado o expirado")
        except Exception:
            pass

    def _get_origin(self, ws):
        try:
            return ws.request.headers.get("Origin")
        except Exception:
            return None

    @staticmethod
    def _parse_ip(raw: str):
        try:
            return str(ipaddress.ip_address(raw.strip()))
        except ValueError:
            return None

    def _get_ip(self, ws) -> str:
        try:
            addr = ws.remote_address
            peer_ip = str(addr[0]) if addr else "unknown"
        except Exception:
            return "unknown"

        if peer_ip in self.trusted_proxies:
            try:
                headers = ws.request.headers
            except Exception:
                headers = {}
            cf_ip = headers.get("CF-Connecting-IP")
            if cf_ip:
                parsed = self._parse_ip(cf_ip)
                if parsed:
                    return parsed
            xff = headers.get("X-Forwarded-For")
            if xff:
                parts = [self._parse_ip(p) for p in xff.split(",")]
                valid = [p for p in parts if p]
                for candidate in reversed(valid):
                    if candidate not in self.trusted_proxies:
                        return candidate
                if valid:
                    return valid[0]
            x_real = headers.get("X-Real-IP")
            if x_real:
                parsed = self._parse_ip(x_real)
                if parsed:
                    return parsed

        return peer_ip

    _PROXY_HEADERS = ("CF-Connecting-IP", "CF-Ray", "X-Forwarded-For", "X-Real-IP", "Forwarded")

    def _is_direct_local(self, ws) -> bool:
        """True si el socket viene de loopback y NO fue reenviado por un túnel/proxy (p. ej. cloudflared)."""
        try:
            addr = ws.remote_address
            peer = ipaddress.ip_address(str(addr[0]).strip()) if addr else None
        except Exception:
            return False
        if peer is None:
            return False
        mapped = getattr(peer, "ipv4_mapped", None)
        if not (peer.is_loopback or (mapped is not None and mapped.is_loopback)):
            return False
        try:
            headers = ws.request.headers
        except Exception:
            return False
        return not any(headers.get(h) for h in self._PROXY_HEADERS)

    async def _verify_pin_async(self, pin: str, pin_kdf) -> bool:
        """Verifica el PIN con scrypt fuera del event loop y con concurrencia acotada."""
        if not pin_kdf:
            return True
        async with self._kdf_sem:
            try:
                return await asyncio.to_thread(_verify_scrypt_pin, pin, pin_kdf)
            except Exception:
                return False

    async def handle_connection(self, ws):
        if self.active_connections >= MAX_GLOBAL_CONNECTIONS:
            await ws.close(1013, "Servidor ocupado")
            return
        self.active_connections += 1
        ip = self._get_ip(ws)
        cur_unauth = self.unauth_by_ip.get(ip, 0)
        if cur_unauth >= MAX_UNAUTH_PER_IP:
            self.active_connections = max(0, self.active_connections - 1)
            await ws.close(1013, "Demasiadas conexiones sin autenticar")
            return
        self.unauth_by_ip[ip] = cur_unauth + 1
        unauth_released = False

        def _release_unauth():
            nonlocal unauth_released
            if not unauth_released:
                unauth_released = True
                c = self.unauth_by_ip.get(ip, 1) - 1
                if c <= 0:
                    self.unauth_by_ip.pop(ip, None)
                else:
                    self.unauth_by_ip[ip] = c

        try:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                await ws.close(4001, "Timeout de autenticación")
                return

            if not isinstance(raw, str):
                await ws.close(1003, "Solo frames de texto")
                return

            msg = parse_json_strict(raw, MAX_HOST_CONTROL_BYTES)
            t = msg.get("t")
            origin = self._get_origin(ws)

            if t == "auth_host":
                if origin is not None:
                    await ws.close(1008, "Host no debe enviar Origin")
                    return
                if self.local_host_only and not self._is_direct_local(ws):
                    log_debug("[RELAY-SRV] auth_host rechazado: no proviene de loopback directo")
                    await ws.close(1008, "Handshake inválido")
                    return
                data = validate_auth_host(msg)
                _release_unauth()
                await self._handle_host_session(ws, ip, data)
                return

            if t == "join":
                if self.require_guest_origin and (not origin or origin not in self.allowed_guest_origins):
                    log_debug(f"[RELAY-SRV] join rechazado por Origin no permitido: {origin}")
                    await ws.close(1008, "Origin no permitido")
                    return
                data = validate_join(msg)
                await self._handle_guest_session(ws, ip, data, _release_unauth)
                return

            await ws.close(1008, "Handshake inválido")
        except SchemaError as exc:
            try:
                await ws.close(exc.close_code, str(exc)[:100])
            except Exception:
                pass
        except ConnectionClosed:
            pass
        finally:
            _release_unauth()
            self.active_connections = max(0, self.active_connections - 1)

    async def _handle_host_session(self, ws, ip: str, data: dict):
        rc = data["room_code"]
        sec_hash = _sha256_hex(data["host_secret"])

        if rc is None:
            if not self._check_room_quota(ip):
                await ws.close(4007, "Cuota de salas excedida")
                return
            rc = self._gen_room_code()
            room = _Room(rc, sec_hash, data["invite_token_hash"], data.get("pin_kdf"), ip)
            self.rooms[rc] = room
        else:
            room = self.rooms.get(rc)
            if room is None or not hmac.compare_digest(sec_hash, room.host_secret_hash):
                await ws.close(4002, "No autorizado")
                return
            if "invite_token_hash" in data:
                room.invite_token_hash = data["invite_token_hash"]
            if "pin_kdf" in data:
                room.pin_kdf = data["pin_kdf"]
            if room.host_ws is not None and room.host_ws is not ws:
                try:
                    await room.host_ws.close(4005, "Host reemplazado")
                except Exception:
                    pass

        room.host_ws = ws
        room.host_offline_since = None
        room.total_sockets.add(ws)
        await self._send_json(ws, {"v": 1, "t": "room_created", "room_code": rc, "ttl_sec": int(ROOM_MAX_TTL_SEC)})

        for s_info in room.slots.values():
            await self._send_json(s_info["ws"], {"v": 1, "t": "host_online"})

        ctrl_bucket = _TokenBucket(5.0, 5.0)
        sync_bucket = _TokenBucket(6.0, 6.0)

        try:
            async for raw in ws:
                if not isinstance(raw, str):
                    await ws.close(1003, "Solo texto")
                    break
                msg = parse_json_strict(raw, MAX_STATE_SYNC_BYTES)
                v = msg.get("v")
                if v != PROTOCOL_VERSION:
                    await ws.close(4008, "Versión no soportada")
                    break
                t = msg.get("t")

                if t == "state_sync":
                    if not sync_bucket.allow():
                        continue
                    clean = validate_state_sync(msg)
                    slot = clean["to"]
                    s_info = room.slots.get(slot)
                    if s_info is not None:
                        await self._send_json(
                            s_info["ws"],
                            {
                                "v": 1,
                                "t": "state_sync",
                                "state_version": clean["state_version"],
                                "state": clean["state"],
                            },
                        )
                    continue

                if len(raw.encode("utf-8")) > MAX_HOST_CONTROL_BYTES:
                    await ws.close(1009, "Control demasiado grande")
                    break
                if not ctrl_bucket.allow():
                    await self._send_json(ws, {"v": 1, "t": "error", "code": "E_RATE"})
                    continue

                if t == "join_decision":
                    dec = validate_join_decision(msg)
                    pend = room.pending.pop(dec["req_id"], None)
                    if pend is None:
                        await self._send_json(ws, {"v": 1, "t": "error", "code": "E_SLOT"})
                        continue
                    slot = dec["slot"]
                    if not dec["allow"]:
                        pend_ip = pend.get("ip")
                        if pend_ip:
                            room.rejected_ips[pend_ip] = time.monotonic() + REJECTION_COOLDOWN_SEC
                        try:
                            await pend["ws"].close(4002, "Rechazado")
                        except Exception:
                            pass
                        continue
                    if slot in room.slots:
                        room.pending[dec["req_id"]] = pend
                        await self._send_json(ws, {"v": 1, "t": "error", "code": "E_SLOT"})
                        continue
                    await self._admit_guest(room, pend, slot, dec["permissions"])

                elif t == "permissions":
                    slot = msg.get("slot")
                    if isinstance(slot, bool) or slot not in VALID_SLOTS:
                        raise SchemaError("slot inválido")
                    perms = validate_permissions(msg.get("permissions"))
                    s_info = room.slots.get(slot)
                    if s_info:
                        s_info["permissions"] = perms
                        await self._send_json(s_info["ws"], {"v": 1, "t": "permissions", "permissions": perms})

                elif t == "kick":
                    kd = validate_kick(msg)
                    s_info = room.slots.pop(kd["slot"], None)
                    if s_info:
                        room.total_sockets.discard(s_info["ws"])
                        if kd["ban"] and s_info.get("ip"):
                            room.banned_ips.add(s_info["ip"])
                        try:
                            await s_info["ws"].close(4006, "Expulsado")
                        except Exception:
                            pass
                    if kd["ban"]:
                        room.invite_token_hash = None
                        await self._cancel_all_pending(room)

                elif t == "kick_all":
                    for slot in list(room.slots.keys()):
                        s_info = room.slots.pop(slot)
                        try:
                            await s_info["ws"].close(4006, "Expulsado")
                        except Exception:
                            pass
                    await self._cancel_all_pending(room)

                elif t == "rotate_invite":
                    ri = validate_rotate_invite(msg)
                    room.invite_token_hash = ri["invite_token_hash"]
                    await self._cancel_all_pending(room)

                else:
                    raise SchemaError("Tipo de mensaje no permitido para Host")

        except SchemaError as exc:
            try:
                await ws.close(exc.close_code, str(exc)[:100])
            except Exception:
                pass
        except ConnectionClosed:
            pass
        finally:
            room.total_sockets.discard(ws)
            if room.host_ws is ws:
                room.host_ws = None
                room.host_offline_since = time.monotonic()
                await self._cancel_all_pending(room)
                for s_info in room.slots.values():
                    await self._send_json(s_info["ws"], {"v": 1, "t": "host_offline"})

    async def _cancel_all_pending(self, room: _Room):
        for req_id in list(room.pending.keys()):
            pend = room.pending.pop(req_id)
            try:
                await pend["ws"].close(4002, "Cancelado")
            except Exception:
                pass

    async def _admit_guest(self, room: _Room, pend: dict, slot: int, perms: dict):
        new_tok = secrets.token_urlsafe(24)
        tag = room.stable_tag(new_tok)
        room.slots[slot] = {
            "ws": pend["ws"],
            "ip": pend.get("ip", ""),
            "session_hash": _sha256_hex(new_tok),
            "prev_hash": None,
            "prev_until": 0.0,
            "prev_used": False,
            "tag": tag,
            "display_name": pend["display_name"],
            "permissions": dict(perms),
            "expires_at": time.monotonic() + SESSION_TTL_SEC,
            "admitted_event": pend.get("admitted_event"),
            "slot": slot,
        }
        if pend.get("admitted_event"):
            pend["admitted_event"].set()
        await self._send_json(
            pend["ws"],
            {"v": 1, "t": "joined", "slot": slot, "session_token": new_tok, "permissions": perms},
        )
        if room.host_ws is not None:
            await self._send_json(
                room.host_ws,
                {
                    "v": 1,
                    "t": "guest_joined",
                    "slot": slot,
                    "display_name": pend["display_name"],
                    "tag": tag,
                    "reconnected": False,
                },
            )

    async def _handle_guest_session(self, ws, ip: str, data: dict, release_unauth=None):
        # Indistinguibilidad total: siempre respondemos join_pending primero
        await self._send_json(ws, {"v": 1, "t": "join_pending"})

        room = self.rooms.get(data["room_code"])
        if room is None or len(room.total_sockets) >= MAX_SOCKETS_PER_ROOM or ip in room.banned_ips:
            await self._close_uniform_fail(ws)
            return

        # 1. Intento de reconexión con session_token
        if data.get("session_token"):
            tok_hash = _sha256_hex(data["session_token"])
            now = time.monotonic()
            matched_slot = None
            used_prev = False
            for s, info in list(room.slots.items()):
                if now > info["expires_at"]:
                    continue
                if hmac.compare_digest(tok_hash, info["session_hash"]):
                    matched_slot = s
                    break
                if info["prev_hash"] and now <= info["prev_until"] and hmac.compare_digest(tok_hash, info["prev_hash"]):
                    if info["prev_used"]:
                        # Posible robo de sesión: invalidar ambos y cerrar slot
                        room.slots.pop(s, None)
                        room.total_sockets.discard(info["ws"])
                        try:
                            await info["ws"].close(4006, "Reuso de sesión detectado")
                        except Exception:
                            pass
                        if room.host_ws:
                            await self._send_json(
                                room.host_ws,
                                {"v": 1, "t": "guest_left", "slot": s, "session_reuse_detected": True},
                            )
                        await self._close_uniform_fail(ws, wait_sec=0.35)
                        return
                    matched_slot = s
                    used_prev = True
                    break

            if matched_slot is None:
                await self._close_uniform_fail(ws)
                return

            if release_unauth:
                release_unauth()
            info = room.slots[matched_slot]
            old_ws = info["ws"]
            new_tok = secrets.token_urlsafe(24)
            info["prev_hash"] = None if used_prev else info["session_hash"]
            info["prev_until"] = now + SESSION_GRACE_SEC
            info["prev_used"] = used_prev
            info["session_hash"] = _sha256_hex(new_tok)
            info["ip"] = ip
            info["ws"] = ws
            room.total_sockets.add(ws)
            if old_ws is not ws:
                room.total_sockets.discard(old_ws)
                try:
                    await old_ws.close(4005, "Reemplazado")
                except Exception:
                    pass
            await self._send_json(
                ws,
                {
                    "v": 1,
                    "t": "joined",
                    "slot": matched_slot,
                    "session_token": new_tok,
                    "permissions": dict(info.get("permissions") or {}),
                },
            )
            if room.host_ws:
                await self._send_json(
                    room.host_ws,
                    {
                        "v": 1,
                        "t": "guest_joined",
                        "slot": matched_slot,
                        "display_name": info["display_name"],
                        "tag": info["tag"],
                        "reconnected": True,
                    },
                )
            await self._guest_loop(ws, room, matched_slot)
            return

        # 2. Nuevo ingreso: cooldown por rechazo + rate limit ANTES de KDF
        if now_rej := room.rejected_ips.get(ip):
            if time.monotonic() < now_rej:
                await self._close_uniform_fail(ws)
                return
            room.rejected_ips.pop(ip, None)

        if not self._check_join_rate(ip):
            await self._close_uniform_fail(ws)
            return

        inv_hash = _sha256_hex(data["invite_token"])
        valid_inv = bool(room.invite_token_hash) and hmac.compare_digest(inv_hash, room.invite_token_hash)
        # El KDF solo se calcula si el invite es válido (todos los fallos ya esperan 45 s de forma
        # uniforme, así que omitirlo no filtra información por tiempo) y nunca bloquea el loop.
        valid_pin = False
        if valid_inv:
            valid_pin = await self._verify_pin_async(data.get("pin") or "", room.pin_kdf)

        if not (valid_inv and valid_pin) or room.host_ws is None or len(room.pending) >= MAX_PENDING_PER_ROOM:
            log_debug(
                f"[RELAY-SRV] join denegado: valid_inv={valid_inv} valid_pin={valid_pin} "
                f"host_online={room.host_ws is not None} pending={len(room.pending)}"
            )
            await self._close_uniform_fail(ws)
            return

        if any(p["ip"] == ip for p in room.pending.values()):
            await self._close_uniform_fail(ws)
            return

        req_id = secrets.token_urlsafe(16)
        admitted_event = asyncio.Event()
        tag = room.stable_tag(req_id)
        room.pending[req_id] = {
            "ws": ws,
            "ip": ip,
            "display_name": data["display_name"],
            "tag": tag,
            "admitted_event": admitted_event,
        }
        room.total_sockets.add(ws)
        if release_unauth:
            release_unauth()

        log_debug(f"[RELAY-SRV] Enviando join_request al Host: #{tag} (slot={room.free_slot()})")
        await self._send_json(
            room.host_ws,
            {
                "v": 1,
                "t": "join_request",
                "req_id": req_id,
                "display_name": data["display_name"],
                "tag": tag,
                "suggested_slot": room.free_slot(),
            },
        )

        try:
            await asyncio.wait_for(admitted_event.wait(), timeout=LOBBY_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            room.pending.pop(req_id, None)
            room.total_sockets.discard(ws)
            await ws.close(4002, "Timeout de lobby")
            return

        # Encontrar slot asignado
        assigned_slot = next((s for s, info in room.slots.items() if info["ws"] is ws), None)
        if assigned_slot is None:
            return
        await self._guest_loop(ws, room, assigned_slot)

    async def _guest_loop(self, ws, room: _Room, slot: int):
        voice_bucket = _TokenBucket(30.0, 30.0)
        action_bucket = _TokenBucket(4.0, 3.0)
        last_action_ts = {}
        last_seq = -1

        try:
            async for raw in ws:
                if not isinstance(raw, str):
                    await ws.close(1003, "Solo texto")
                    break
                msg = parse_json_strict(raw, MAX_GUEST_BYTES)
                v = msg.get("v")
                if v != PROTOCOL_VERSION:
                    await ws.close(4008, "Versión no soportada")
                    break
                t = msg.get("t")

                # Sin buffering si el Host está offline
                if room.host_ws is None:
                    continue

                if t == "voice":
                    if not voice_bucket.allow():
                        await ws.close(1008, "Rate limit voice")
                        break
                    clean = validate_guest_voice(msg)
                    if clean["seq"] <= last_seq:
                        continue
                    last_seq = clean["seq"]
                    await self._send_json(
                        room.host_ws,
                        {"v": 1, "from": slot, "seq": clean["seq"], "t": "voice", "level": clean["level"]},
                    )

                elif t == "action":
                    if not action_bucket.allow():
                        await ws.close(1008, "Rate limit action")
                        break
                    clean = validate_guest_action(msg)
                    if clean["seq"] <= last_seq:
                        continue
                    last_seq = clean["seq"]
                    now = time.monotonic()
                    act = clean["action"]
                    if now - last_action_ts.get(act, 0.0) < 0.30:
                        continue
                    last_action_ts[act] = now
                    envelope = {"v": 1, "from": slot, "seq": clean["seq"], "t": "action", "action": act}
                    if "id" in clean:
                        envelope["id"] = clean["id"]
                    if "enabled" in clean:
                        envelope["enabled"] = clean["enabled"]
                    await self._send_json(room.host_ws, envelope)

                elif t == "presence":
                    clean = validate_presence(msg)
                    if clean["seq"] <= last_seq:
                        continue
                    last_seq = clean["seq"]
                    await self._send_json(
                        room.host_ws,
                        {"v": 1, "from": slot, "seq": clean["seq"], "t": "presence", "foreground": clean["foreground"]},
                    )

                else:
                    raise SchemaError("Tipo de mensaje no permitido para Guest")

        except SchemaError as exc:
            try:
                await ws.close(exc.close_code, str(exc)[:100])
            except Exception:
                pass
        except ConnectionClosed:
            pass
        finally:
            room.total_sockets.discard(ws)
            info = room.slots.get(slot)
            if info and info["ws"] is ws:
                room.slots.pop(slot, None)
                if room.host_ws is not None:
                    await self._send_json(room.host_ws, {"v": 1, "t": "guest_left", "slot": slot})


    async def cleanup_expired(self):
        now = time.monotonic()
        for rc, room in list(self.rooms.items()):
            room_expired = (now - room.created_at) >= ROOM_MAX_TTL_SEC
            host_expired = (
                room.host_ws is None
                and room.host_offline_since is not None
                and (now - room.host_offline_since) >= HOST_OFFLINE_TTL_SEC
            )
            if room_expired or host_expired:
                self.rooms.pop(rc, None)
                reason = "Sala expirada" if room_expired else "Host desconectado"
                await self._cancel_all_pending(room)
                for s_info in list(room.slots.values()):
                    try:
                        await s_info["ws"].close(4003, reason)
                    except Exception:
                        pass
                room.slots.clear()
                if room.host_ws is not None:
                    try:
                        await room.host_ws.close(4003, reason)
                    except Exception:
                        pass
                room.total_sockets.clear()
                continue

            for slot, s_info in list(room.slots.items()):
                if now > s_info["expires_at"]:
                    room.slots.pop(slot, None)
                    room.total_sockets.discard(s_info["ws"])
                    try:
                        await s_info["ws"].close(4003, "Sesión expirada")
                    except Exception:
                        pass
                    if room.host_ws is not None:
                        await self._send_json(room.host_ws, {"v": 1, "t": "guest_left", "slot": slot})

            for rej_ip, until in list(room.rejected_ips.items()):
                if now >= until:
                    room.rejected_ips.pop(rej_ip, None)

        for ip, q in list(self.room_creations_by_ip.items()):
            while q and (now - q[0]) > 3600.0:
                q.popleft()
            if not q:
                self.room_creations_by_ip.pop(ip, None)

        for ip, q in list(self.join_rate_by_ip.items()):
            while q and (now - q[0]) > 10.0:
                q.popleft()
            if not q:
                self.join_rate_by_ip.pop(ip, None)

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL_SEC)
            try:
                await self.cleanup_expired()
            except Exception as exc:
                log_debug(f"[RELAY-SRV] Error en cleanup_expired: {type(exc).__name__}")


async def run_relay(host="127.0.0.1", port=8766):
    srv = RelayServer()
    cleanup_task = asyncio.create_task(srv._cleanup_loop())
    try:
        async with websockets.serve(srv.handle_connection, host, port, compression=None):
            await asyncio.Future()
    finally:
        cleanup_task.cancel()


if __name__ == "__main__":
    asyncio.run(run_relay())
