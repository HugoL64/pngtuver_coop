import asyncio
import hashlib
import os
import secrets
import time
import unittest
from types import SimpleNamespace

from core.coop_relay_client import CoopRelayClient
from core.relay_schemas import validate_pin_kdf
from core.twitch_alerts import TwitchAlertServer
from relay_server import MAX_GLOBAL_CONNECTIONS, RelayServer, _Room, _verify_scrypt_pin
from services.local_coop_host import _CLOUDFLARED_RELEASES, _make_static_http_hook
from services.remote_control import _parse_duration, _parse_optional_bool


class TestSecurityControls(unittest.TestCase):
    def test_relay_is_direct_local_rejects_proxy_headers_and_remote_ips(self):
        srv = RelayServer(local_host_only=True)

        def ws_mock(ip, headers=None):
            return SimpleNamespace(
                remote_address=(ip, 50000) if ip else None,
                request=SimpleNamespace(headers=headers or {}),
            )

        self.assertTrue(srv._is_direct_local(ws_mock("127.0.0.1")))
        self.assertTrue(srv._is_direct_local(ws_mock("::1")))
        self.assertTrue(srv._is_direct_local(ws_mock("::ffff:127.0.0.1")))
        self.assertFalse(srv._is_direct_local(ws_mock("127.0.0.1", {"CF-Connecting-IP": "1.2.3.4"})))
        self.assertFalse(srv._is_direct_local(ws_mock("127.0.0.1", {"X-Forwarded-For": "1.2.3.4"})))
        self.assertFalse(srv._is_direct_local(ws_mock("127.0.0.1", {"X-Real-IP": "1.2.3.4"})))
        self.assertFalse(srv._is_direct_local(ws_mock("127.0.0.1", {"CF-Ray": "xyz"})))
        self.assertFalse(srv._is_direct_local(ws_mock("192.168.1.20")))
        self.assertFalse(srv._is_direct_local(ws_mock(None)))

    def test_coop_relay_client_set_pin_matches_server_kdf(self):
        client = CoopRelayClient(app=None)
        kdf = client.set_pin("mi-pin-123")
        validated = validate_pin_kdf(kdf)
        self.assertTrue(_verify_scrypt_pin("mi-pin-123", validated))
        self.assertFalse(_verify_scrypt_pin("otro-pin", validated))
        self.assertIsNone(client.set_pin(""))
        self.assertIsNone(client.pin_kdf)

    def test_twitch_alert_server_token_and_rate_limit(self):
        srv = TwitchAlertServer(on_event_callback=lambda p: None)
        t1 = srv.auth_token
        t2 = srv.rotate_token()
        self.assertNotEqual(t1, t2)
        self.assertGreaterEqual(len(t2), 32)
        # Rate limit permite hasta 60 peticiones por ventana y luego bloquea
        for _ in range(60):
            self.assertTrue(srv._allow_rate("127.0.0.1:test"))
        self.assertFalse(srv._allow_rate("127.0.0.1:test"))

    def test_remote_control_parsers(self):
        self.assertEqual(_parse_duration("5.5"), 5.5)
        self.assertEqual(_parse_duration(999), 10.0)
        self.assertEqual(_parse_duration(float("nan")), 0.0)
        self.assertEqual(_parse_duration(True), 0.0)
        self.assertTrue(_parse_optional_bool("true"))
        self.assertFalse(_parse_optional_bool("0"))
        self.assertIsNone(_parse_optional_bool(""))

    def test_static_http_hook_security_headers_and_traversal(self):
        web_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web_guest"))
        hook = _make_static_http_hook(web_dir)

        req_ok = SimpleNamespace(path="/", headers={})
        resp_ok = hook(None, req_ok)
        self.assertEqual(resp_ok.status_code, 200)
        self.assertEqual(resp_ok.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(resp_ok.headers.get("Referrer-Policy"), "no-referrer")
        csp = resp_ok.headers.get("Content-Security-Policy", "")
        self.assertIn("frame-ancestors 'none'", csp)

        req_trav = SimpleNamespace(path="/../main.py", headers={})
        resp_trav = hook(None, req_trav)
        self.assertEqual(resp_trav.status_code, 404)

    def test_cloudflared_releases_pinned_with_sha256(self):
        for plat in ("win32", "linux"):
            rel = _CLOUDFLARED_RELEASES[plat]
            self.assertIn("/releases/download/", rel["url"])
            self.assertNotIn("/releases/latest/", rel["url"])
            self.assertEqual(len(rel["sha256"]), 64)
            int(rel["sha256"], 16)

    def test_relay_global_connection_limit_and_room_bans(self):
        srv = RelayServer(require_guest_origin=False)
        srv.active_connections = MAX_GLOBAL_CONNECTIONS
        closed = []

        class _FakeWS:
            remote_address = ("203.0.113.10", 12345)
            request = SimpleNamespace(headers={})

            async def send(self, _data):
                pass

            async def close(self, code, reason):
                closed.append((code, reason))

        asyncio.run(srv.handle_connection(_FakeWS()))
        self.assertEqual(closed, [(1013, "Servidor ocupado")])

        # Verificar que IP baneada o en cooldown de rechazo falla de forma uniforme
        inv_tok = "tok_" + "a" * 20
        room = _Room(
            "ROOM1234",
            hashlib.sha256(b"host_secret").hexdigest(),
            hashlib.sha256(inv_tok.encode("utf-8")).hexdigest(),
            None,
            "127.0.0.1",
        )
        room.host_ws = _FakeWS()
        room.banned_ips.add("198.51.100.5")
        room.rejected_ips["198.51.100.6"] = time.monotonic() + 30.0
        srv.rooms["ROOM1234"] = room

        async def _try_join(ip):
            ws = _FakeWS()
            ws.remote_address = (ip, 44444)
            orig_sleep = asyncio.sleep
            asyncio.sleep = lambda _t: orig_sleep(0)
            try:
                await srv._handle_guest_session(
                    ws,
                    ip,
                    {
                        "room_code": "ROOM1234",
                        "invite_token": inv_tok,
                        "display_name": "Guest",
                        "pin": None,
                        "session_token": None,
                    },
                )
            finally:
                asyncio.sleep = orig_sleep

        asyncio.run(_try_join("198.51.100.5"))
        asyncio.run(_try_join("198.51.100.6"))
        self.assertEqual(room.pending, {})
        self.assertEqual(closed[-2:], [(4002, "No autorizado o expirado"), (4002, "No autorizado o expirado")])


if __name__ == "__main__":
    unittest.main()
