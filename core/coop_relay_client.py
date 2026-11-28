"""Cliente WebSocket saliente del Host hacia el Relay (Protocolo v1.3).

Corre en un hilo dedicado con asyncio y nunca toca widgets de Tkinter directamente:
deposita voz y acciones en GuestInbox y expone métodos thread-safe para enviar
decisiones de lobby, state_sync, permisos y moderación.
"""

import asyncio
import hashlib
import json
import random
import secrets
import ssl
import threading

import websockets

from core.app_constants import log_debug
from core.relay_schemas import PROTOCOL_VERSION, SchemaError, parse_json_strict


class CoopRelayClient:
    """Cliente WebSocket del Host con reconexión automática y TLS verificado."""

    def __init__(self, app, on_join_request=None, on_status_change=None):
        self.app = app
        self.on_join_request = on_join_request
        self.on_status_change = on_status_change
        self.relay_url = ""
        self.room_code = None
        self.host_secret = secrets.token_urlsafe(24)
        self.invite_token = secrets.token_urlsafe(24)
        self.pin_kdf = None
        self._running = False
        self._thread = None
        self._loop = None
        self._ws = None
        self.connected = False

    def set_pin(self, pin: str = ""):
        """Configura o limpia el PIN opcional de la sala derivando scrypt localmente."""
        clean = str(pin or "").strip()
        if not clean:
            self.pin_kdf = None
            return None
        salt = secrets.token_hex(16)
        n, r, p = 16384, 8, 1
        derived = hashlib.scrypt(
            clean.encode("utf-8"),
            salt=salt.encode("utf-8"),
            n=n,
            r=r,
            p=p,
            dklen=32,
        ).hex()
        self.pin_kdf = {
            "alg": "scrypt",
            "salt": salt,
            "params": {"N": n, "r": r, "p": p},
            "hash": derived,
        }
        return self.pin_kdf

    def rotate_invite_token(self):
        self.invite_token = secrets.token_urlsafe(24)
        inv_hash = hashlib.sha256(self.invite_token.encode("utf-8")).hexdigest()
        self.send_control({"v": PROTOCOL_VERSION, "t": "rotate_invite", "invite_token_hash": inv_hash})
        return self.invite_token

    def start(self, relay_url, allow_insecure_local=False):
        url = str(relay_url or "").strip()
        if url.startswith("ws://"):
            if not (allow_insecure_local and (url.startswith("ws://127.0.0.1") or url.startswith("ws://localhost"))):
                raise ValueError("Solo se permite wss:// en conexiones remotas")
        elif not url.startswith("wss://"):
            raise ValueError("URL del Relay debe iniciar con wss://")

        self.stop()
        self.relay_url = url
        self._running = True
        self._thread = threading.Thread(target=self._run_thread, name="CoopRelayClient", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self.connected = False
        loop = self._loop
        ws = self._ws
        if loop and ws:
            try:
                asyncio.run_coroutine_threadsafe(ws.close(1000, "Host cerrado"), loop)
            except Exception:
                pass

    def send_control(self, payload: dict):
        loop = self._loop
        ws = self._ws
        if not (loop and ws and self.connected):
            return False
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            asyncio.run_coroutine_threadsafe(ws.send(raw), loop)
            return True
        except Exception:
            return False

    def send_join_decision(self, req_id: str, allow: bool, slot: int, permissions: dict):
        return self.send_control(
            {
                "v": PROTOCOL_VERSION,
                "t": "join_decision",
                "req_id": req_id,
                "allow": bool(allow),
                "slot": int(slot),
                "permissions": dict(permissions),
            }
        )

    def send_kick(self, slot: int, ban: bool = False):
        return self.send_control({"v": PROTOCOL_VERSION, "t": "kick", "slot": int(slot), "ban": bool(ban)})

    def send_kick_all(self):
        return self.send_control({"v": PROTOCOL_VERSION, "t": "kick_all"})

    def _run_thread(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_loop())
        finally:
            self._loop.close()
            self._loop = None

    async def _connect_loop(self):
        backoff = 1.0
        while self._running:
            try:
                ssl_ctx = ssl.create_default_context() if self.relay_url.startswith("wss://") else None
                async with websockets.connect(
                    self.relay_url,
                    ssl=ssl_ctx,
                    origin=None,
                    compression=None,
                    open_timeout=5.0,
                ) as ws:
                    self._ws = ws
                    inv_hash = hashlib.sha256(self.invite_token.encode("utf-8")).hexdigest()
                    auth_msg = {
                        "v": PROTOCOL_VERSION,
                        "t": "auth_host",
                        "host_secret": self.host_secret,
                        "room_code": self.room_code,
                        "invite_token_hash": inv_hash,
                    }
                    if self.pin_kdf:
                        auth_msg["pin_kdf"] = self.pin_kdf
                    await ws.send(json.dumps(auth_msg, separators=(",", ":")))

                    backoff = 1.0
                    await self._recv_loop(ws)
            except Exception as exc:
                log_debug(f"[RELAY] Desconectado: {type(exc).__name__}")
            finally:
                self._ws = None
                self.connected = False
                if self.on_status_change:
                    try:
                        self.on_status_change(False, self.room_code)
                    except Exception:
                        pass

            if not self._running:
                break
            await asyncio.sleep(backoff + random.uniform(0.0, 0.5))
            backoff = min(30.0, backoff * 2.0)

    async def _recv_loop(self, ws):
        inbox = self.app.guest_inbox
        async for raw in ws:
            if not isinstance(raw, str):
                continue
            try:
                msg = parse_json_strict(raw, 16384)
            except SchemaError:
                continue
            t = msg.get("t")

            if t == "room_created":
                self.room_code = msg.get("room_code")
                self.connected = True
                log_debug(f"[RELAY-CLIENT] Sala creada: {self.room_code}")
                if self.on_status_change:
                    self.on_status_change(True, self.room_code)

            elif t == "voice":
                slot = msg.get("from")
                try:
                    inbox.push_voice(slot, {"v": 1, "t": "voice", "seq": msg.get("seq"), "level": msg.get("level")})
                except SchemaError:
                    pass

            elif t == "action":
                slot = msg.get("from")
                act_payload = {"v": 1, "t": "action", "seq": msg.get("seq"), "action": msg.get("action")}
                if "id" in msg:
                    act_payload["id"] = msg["id"]
                if "enabled" in msg:
                    act_payload["enabled"] = msg["enabled"]
                try:
                    inbox.push_action(slot, act_payload)
                except SchemaError:
                    pass

            elif t == "presence":
                inbox.set_presence(msg.get("from"), bool(msg.get("foreground", True)))

            elif t == "guest_joined":
                inbox.on_guest_joined(
                    msg.get("slot"),
                    display_name=msg.get("display_name", ""),
                    tag=msg.get("tag", ""),
                    reconnected=bool(msg.get("reconnected", False)),
                )

            elif t == "guest_left":
                inbox.on_guest_left(msg.get("slot"))

            elif t == "join_request":
                log_debug(f"[RELAY-CLIENT] Solicitud de entrada recibida: #{msg.get('tag')}")
                if self.on_join_request:
                    try:
                        self.on_join_request(msg)
                    except Exception:
                        pass
