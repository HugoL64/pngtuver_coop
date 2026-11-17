"""
Receptor local ligero de alertas (HTTP/Webhook) para integrarse con
Streamer.bot, Mix It Up, SAMMI, Touch Portal o scripts locales de Twitch.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class TwitchAlertServer:
    """Servidor HTTP local en 127.0.0.1 sin dependencias externas."""

    def __init__(self, on_event_callback):
        self.on_event_callback = on_event_callback
        self._server = None
        self._thread = None
        self.port = 8765
        self.running = False
        self.last_error = ""

    def start(self, port=8765):
        self.stop()
        self.last_error = ""
        try:
            self.port = int(port)
        except Exception:
            self.port = 8765
        if not (1024 <= self.port <= 65535):
            self.port = 8765

        callback = self.on_event_callback

        class AlertHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                # Silenciar logs HTTP en consola para no ensuciar ni gastar I/O
                return

            def _send_json(self, code, payload):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path in ("/", "/status", "/health"):
                    self._send_json(200, {"ok": True, "service": "pngtuber-twitch-alerts"})
                    return
                if parsed.path in ("/trigger", "/alert"):
                    qs = parse_qs(parsed.query)
                    payload = {k: (v[0] if isinstance(v, list) and v else "") for k, v in qs.items()}
                    if not payload.get("event"):
                        self._send_json(400, {"ok": False, "error": "Falta el parámetro 'event'"})
                        return
                    if callback:
                        callback(payload)
                    self._send_json(200, {"ok": True, "queued": True, "event": payload.get("event")})
                    return
                self._send_json(404, {"ok": False, "error": "Ruta no encontrada"})

            def do_POST(self):
                parsed = urlparse(self.path)
                if parsed.path not in ("/trigger", "/alert"):
                    self._send_json(404, {"ok": False, "error": "Ruta no encontrada"})
                    return
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(min(length, 65536)) if length > 0 else b""
                payload = {}
                qs = parse_qs(parsed.query)
                for k, v in qs.items():
                    payload[k] = v[0] if isinstance(v, list) and v else ""
                if raw:
                    try:
                        data = json.loads(raw.decode("utf-8"))
                        if isinstance(data, dict):
                            payload.update(data)
                    except Exception:
                        pass
                if not payload.get("event"):
                    self._send_json(400, {"ok": False, "error": "Falta el campo 'event'"})
                    return
                if callback:
                    callback(payload)
                self._send_json(200, {"ok": True, "queued": True, "event": payload.get("event")})

        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", self.port), AlertHandler)
            self._server.daemon_threads = True
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            self.running = True
            return True
        except Exception as e:
            self.last_error = str(e)
            self._server = None
            self._thread = None
            self.running = False
            return False

    def stop(self):
        self.running = False
        srv = self._server
        self._server = None
        self._thread = None
        if srv is not None:
            try:
                srv.shutdown()
            except Exception:
                pass
            try:
                srv.server_close()
            except Exception:
                pass

