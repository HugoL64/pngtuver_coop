"""
Receptor local ligero (HTTP/Webhook) endurecido para integrarse con Streamer.bot,
Mix It Up, SAMMI, Touch Portal o clientes locales autorizados.
"""

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MAX_BODY_BYTES = 4096
MAX_CONCURRENT_CONNS = 16
MAX_CONNS_PER_IP = 4
REQUEST_DEADLINE_SEC = 10.0
RATE_LIMIT_WINDOW_SEC = 10.0
RATE_LIMIT_MAX_REQS = 60
RATE_LIMIT_MAX_KEYS = 256


def _reject_json_constant(val):
    raise ValueError(f"Constante JSON no permitida: {val}")


def _sanitize_log(val, max_len=120):
    s = str(val or "").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return s[:max_len]


class _HardenedHTTPServer(ThreadingHTTPServer):
    request_queue_size = 32
    daemon_threads = True


class TwitchAlertServer:
    """Servidor HTTP local endurecido sin dependencias externas."""

    def __init__(self, on_event_callback, on_state_callback=None, on_action_callback=None):
        self.on_event_callback = on_event_callback
        self.on_state_callback = on_state_callback
        self.on_action_callback = on_action_callback
        self._server = None
        self._thread = None
        self.port = 8765
        self.bind_host = "127.0.0.1"
        self.auth_token = secrets.token_urlsafe(32)
        self.running = False
        self.last_error = ""
        self._conn_sem = threading.BoundedSemaphore(MAX_CONCURRENT_CONNS)
        self._ip_conn_lock = threading.Lock()
        self._ip_conns = {}
        self._rate_lock = threading.Lock()
        self._rate_buckets = {}

    def rotate_token(self):
        """Genera un nuevo token de acceso aleatorio."""
        self.auth_token = secrets.token_urlsafe(32)
        return self.auth_token

    def _acquire_ip_slot(self, client_ip):
        with self._ip_conn_lock:
            cur = self._ip_conns.get(client_ip, 0)
            if cur >= MAX_CONNS_PER_IP:
                return False
            self._ip_conns[client_ip] = cur + 1
            return True

    def _release_ip_slot(self, client_ip):
        with self._ip_conn_lock:
            cur = self._ip_conns.get(client_ip, 0)
            if cur <= 1:
                self._ip_conns.pop(client_ip, None)
            else:
                self._ip_conns[client_ip] = cur - 1

    def _allow_rate(self, rate_key):
        now = time.monotonic()
        cutoff = now - RATE_LIMIT_WINDOW_SEC
        with self._rate_lock:
            # Podar entradas expiradas si el diccionario crece
            if len(self._rate_buckets) >= RATE_LIMIT_MAX_KEYS:
                stale = [k for k, q in self._rate_buckets.items() if not q or q[-1] < cutoff]
                for k in stale:
                    self._rate_buckets.pop(k, None)

            bucket = self._rate_buckets.get(rate_key)
            if bucket is None:
                bucket = deque()
                self._rate_buckets[rate_key] = bucket
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= RATE_LIMIT_MAX_REQS:
                return False
            bucket.append(now)
            return True

    def start(self, port=8765, bind_host="127.0.0.1", auth_token=None):
        self.stop()
        self.last_error = ""
        try:
            self.port = int(port)
        except Exception:
            self.port = 8765
        if not (1024 <= self.port <= 65535):
            self.port = 8765

        self.bind_host = str(bind_host or "127.0.0.1").strip() or "127.0.0.1"
        if auth_token is not None and str(auth_token).strip():
            self.auth_token = str(auth_token).strip()
        elif not self.auth_token:
            self.auth_token = secrets.token_urlsafe(32)

        allowed_hosts = {
            f"127.0.0.1:{self.port}",
            f"localhost:{self.port}",
            f"[::1]:{self.port}",
        }
        allowed_origins = {
            f"http://127.0.0.1:{self.port}",
            f"http://localhost:{self.port}",
            f"http://[::1]:{self.port}",
        }
        if self.bind_host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
            allowed_hosts.add(f"{self.bind_host}:{self.port}")
            allowed_origins.add(f"http://{self.bind_host}:{self.port}")

        parent = self

        class AlertHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"
            timeout = 5

            def version_string(self):
                return "PNGTuberCoop"

            def log_message(self, format, *args):
                return

            def handle(self):
                client_ip = self.client_address[0] if self.client_address else "unknown"
                if not parent._conn_sem.acquire(blocking=False):
                    try:
                        self.send_error(503, "Servidor ocupado")
                    except Exception:
                        pass
                    return
                if not parent._acquire_ip_slot(client_ip):
                    parent._conn_sem.release()
                    try:
                        self.send_error(503, "Demasiadas conexiones por IP")
                    except Exception:
                        pass
                    return
                try:
                    self._req_start = time.monotonic()
                    super().handle()
                finally:
                    parent._release_ip_slot(client_ip)
                    parent._conn_sem.release()

            def _send_json(self, code, payload, origin=None):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                if origin and origin in allowed_origins:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                self.end_headers()
                self.wfile.write(body)

            def _check_origin_and_host(self):
                """Orden: Host -> Origin / Sec-Fetch-Site."""
                host_hdr = str(self.headers.get("Host") or "").strip().lower()
                if host_hdr not in allowed_hosts:
                    self._send_json(403, {"ok": False, "error": "Host no permitido"})
                    return False, None

                sfs = str(self.headers.get("Sec-Fetch-Site") or "").strip().lower()
                if sfs and sfs not in ("none", "same-origin"):
                    self._send_json(403, {"ok": False, "error": "Cross-site bloqueado"})
                    return False, None

                origin = self.headers.get("Origin")
                if origin is not None:
                    origin_clean = str(origin).strip()
                    if origin_clean == "null" or origin_clean not in allowed_origins:
                        self._send_json(403, {"ok": False, "error": "Origen no permitido"}, None)
                        return False, None
                    return True, origin_clean
                return True, None

            def _extract_token(self):
                tok = str(self.headers.get("X-Remote-Token") or "").strip()
                if not tok:
                    auth = str(self.headers.get("Authorization") or "").strip()
                    if auth.lower().startswith("bearer "):
                        tok = auth[7:].strip()
                return tok

            def _is_authorized(self):
                tok = self._extract_token()
                if not tok:
                    return False, ""
                try:
                    ok = hmac.compare_digest(tok.encode("utf-8"), parent.auth_token.encode("utf-8"))
                except Exception:
                    return False, ""
                if not ok:
                    return False, ""
                tok_hash = hashlib.sha256(tok.encode("utf-8")).hexdigest()[:16]
                return True, tok_hash

            def _check_rate_limit(self, key_suffix, origin=None):
                client_ip = self.client_address[0] if self.client_address else "unknown"
                if not parent._allow_rate(f"{client_ip}:{key_suffix}"):
                    self._send_json(429, {"ok": False, "error": "Demasiadas peticiones"}, origin)
                    return False
                return True

            def _read_json_body(self):
                te = str(self.headers.get("Transfer-Encoding") or "").strip().lower()
                if te:
                    return None, (501, "Transfer-Encoding no soportado")
                raw_len = self.headers.get("Content-Length")
                if raw_len is None:
                    return None, (411, "Falta Content-Length")
                try:
                    length = int(raw_len)
                except Exception:
                    return None, (400, "Content-Length inválido")
                if length < 0:
                    return None, (400, "Content-Length inválido")
                if length > MAX_BODY_BYTES:
                    return None, (413, "Cuerpo demasiado grande")
                if time.monotonic() - getattr(self, "_req_start", time.monotonic()) > REQUEST_DEADLINE_SEC:
                    return None, (408, "Tiempo de petición agotado")
                if length == 0:
                    return {}, None
                raw = self.rfile.read(length)
                if time.monotonic() - getattr(self, "_req_start", time.monotonic()) > REQUEST_DEADLINE_SEC:
                    return None, (408, "Tiempo de petición agotado")
                try:
                    data = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
                except Exception:
                    return None, (400, "JSON inválido")
                if not isinstance(data, dict):
                    return None, (400, "El cuerpo JSON debe ser un objeto")
                return data, None

            def do_OPTIONS(self):
                ok, origin = self._check_origin_and_host()
                if not ok:
                    return
                self.send_response(204)
                if origin and origin in allowed_origins:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Remote-Token, Authorization")
                self.end_headers()

            def do_GET(self):
                ok, origin = self._check_origin_and_host()
                if not ok:
                    return
                parsed = urlparse(self.path)

                if parsed.path in ("/", "/status", "/health"):
                    if not self._check_rate_limit("public", origin):
                        return
                    self._send_json(200, {"ok": True, "service": "pngtuber-coop-api", "api": "v1"}, origin)
                    return

                if parsed.path in ("/api/action", "/trigger", "/alert"):
                    self._send_json(405, {"ok": False, "error": "Usa POST con cabecera de autenticación"}, origin)
                    return

                if parsed.path == "/api/state":
                    auth_ok, tok_hash = self._is_authorized()
                    if not auth_ok:
                        self._send_json(401, {"ok": False, "error": "No autorizado"}, origin)
                        return
                    if not self._check_rate_limit(tok_hash, origin):
                        return
                    if not parent.on_state_callback:
                        self._send_json(501, {"ok": False, "error": "Estado remoto no configurado"}, origin)
                        return
                    res = parent.on_state_callback()
                    if isinstance(res, dict) and res.get("ok") is False:
                        self._send_json(500, {"ok": False, "error": "Error interno al leer estado"}, origin)
                    else:
                        self._send_json(200, {"ok": True, "state": res}, origin)
                    return

                self._send_json(404, {"ok": False, "error": "Ruta no encontrada"}, origin)

            def do_POST(self):
                ok, origin = self._check_origin_and_host()
                if not ok:
                    return
                parsed = urlparse(self.path)

                if parsed.path not in ("/api/action", "/trigger", "/alert"):
                    self._send_json(404, {"ok": False, "error": "Ruta no encontrada"}, origin)
                    return

                auth_ok, tok_hash = self._is_authorized()
                if not auth_ok:
                    self._send_json(401, {"ok": False, "error": "No autorizado"}, origin)
                    return

                if not self._check_rate_limit(tok_hash, origin):
                    return

                if parsed.path == "/api/action":
                    ctype = str(self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                    if ctype != "application/json":
                        self._send_json(415, {"ok": False, "error": "Content-Type debe ser application/json"}, origin)
                        return
                    if not parent.on_action_callback:
                        self._send_json(501, {"ok": False, "error": "Control remoto no configurado"}, origin)
                        return
                    payload, err = self._read_json_body()
                    if err is not None:
                        self._send_json(err[0], {"ok": False, "error": err[1]}, origin)
                        return
                    res = parent.on_action_callback(payload)
                    code = 200 if (isinstance(res, dict) and res.get("ok", False)) else 400
                    self._send_json(code, res if isinstance(res, dict) else {"ok": True}, origin)
                    return

                # /trigger y /alert: solo POST autenticado
                payload = {}
                qs = parse_qs(parsed.query)
                for k, v in qs.items():
                    if isinstance(v, list) and v:
                        payload[_sanitize_log(k, 40)] = _sanitize_log(v[0], 120)
                if self.headers.get("Content-Length") is not None:
                    body_data, err = self._read_json_body()
                    if err is not None:
                        self._send_json(err[0], {"ok": False, "error": err[1]}, origin)
                        return
                    payload.update(body_data)
                if not payload.get("event"):
                    self._send_json(400, {"ok": False, "error": "Falta el campo 'event'"}, origin)
                    return
                if parent.on_event_callback:
                    parent.on_event_callback(payload)
                self._send_json(200, {"ok": True, "queued": True, "event": payload.get("event")}, origin)

        try:
            self._server = _HardenedHTTPServer((self.bind_host, self.port), AlertHandler)
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
