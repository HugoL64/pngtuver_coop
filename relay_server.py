"""Micro-servidor Relay WebSocket para PNGTuber Co-op (Protocolo v1.3).

Implementa topología en estrella (Host <-> Relay <-> Guests 2..4),
validación estricta de esquemas, anti-enumeración, rotación de session_token
con ventana de gracia de 60s y rate limiting por dirección.
"""

import asyncio
import hashlib
import hmac
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

    def __init__(self, allowed_guest_origins=None, require_guest_origin=True):
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
        self.rooms = {}
        self.unauth_by_ip = {}
        self.room_creations_by_ip = {}
        self.join_rate_by_ip = {}

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

    def _get_ip(self, ws) -> str:
        try:
            addr = ws.remote_address
            return str(addr[0]) if addr else "unknown"
        except Exception:
            return "unknown"

    async def handle_connection(self, ws):
        ip = self._get_ip(ws)
        cur_unauth = self.unauth_by_ip.get(ip, 0)
        if cur_unauth >= MAX_UNAUTH_PER_IP:
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
                _release_unauth()
                await self._handle_guest_session(ws, ip, data)
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
                        await self._send_json(s_info["ws"], {"v": 1, "t": "permissions", "permissions": perms})

                elif t == "kick":
                    kd = validate_kick(msg)
                    s_info = room.slots.pop(kd["slot"], None)
                    if s_info:
                        try:
                            await s_info["ws"].close(4006, "Expulsado")
                        except Exception:
                            pass
                    if kd["ban"]:
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
            "session_hash": _sha256_hex(new_tok),
            "prev_hash": None,
            "prev_until": 0.0,
            "prev_used": False,
            "tag": tag,
            "display_name": pend["display_name"],
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

    async def _handle_guest_session(self, ws, ip: str, data: dict):
        # Indistinguibilidad total: siempre respondemos join_pending primero
        await self._send_json(ws, {"v": 1, "t": "join_pending"})

        room = self.rooms.get(data["room_code"])
        if room is None or len(room.total_sockets) >= MAX_SOCKETS_PER_ROOM:
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

            info = room.slots[matched_slot]
            old_ws = info["ws"]
            new_tok = secrets.token_urlsafe(24)
            info["prev_hash"] = None if used_prev else info["session_hash"]
            info["prev_until"] = now + SESSION_GRACE_SEC
            info["prev_used"] = used_prev
            info["session_hash"] = _sha256_hex(new_tok)
            info["ws"] = ws
            if old_ws is not ws:
                try:
                    await old_ws.close(4005, "Reemplazado")
                except Exception:
                    pass
            await self._send_json(
                ws,
                {"v": 1, "t": "joined", "slot": matched_slot, "session_token": new_tok, "permissions": {}},
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

        # 2. Nuevo ingreso: rate limit ANTES de KDF
        if not self._check_join_rate(ip):
            await self._close_uniform_fail(ws)
            return

        inv_hash = _sha256_hex(data["invite_token"])
        valid_inv = hmac.compare_digest(inv_hash, room.invite_token_hash)
        valid_pin = _verify_scrypt_pin(data.get("pin") or "", room.pin_kdf)

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

        log_debug(f"[RELAY-SRV] Enviando join_request al Host: {data['display_name']}#{tag} (slot={room.free_slot()})")
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


async def run_relay(host="127.0.0.1", port=8766):
    srv = RelayServer()
    async with websockets.serve(srv.handle_connection, host, port, compression=None):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(run_relay())
