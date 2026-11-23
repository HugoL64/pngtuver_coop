"""Gestor de servicios locales (Relay WebSocket, Web Invitado y túnel cloudflared) para Co-op Remoto."""

import asyncio
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
from urllib.parse import urlparse
import urllib.request

import websockets
from websockets.datastructures import Headers
from websockets.http11 import Response

from core.app_constants import APP_DIR, DATA_DIR, get_resource_path, log_debug
from relay_server import RelayServer

_TRYCLOUDFLARE_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

_CLOUDFLARED_URLS = {
    "win32": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    "linux": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
}


class _QuietHTTPHandler(SimpleHTTPRequestHandler):
    """Handler de archivos estáticos sin ruido en consola."""

    def log_message(self, format, *args):
        pass


def _make_static_http_hook(web_dir: str):
    """Devuelve `process_request` para servir `web_guest/` en el mismo puerto que el Relay WS."""
    base_real = os.path.realpath(web_dir)

    def _process_request(connection, request):
        # Si es upgrade WebSocket, dejar que `websockets` continúe el handshake.
        upgrade = (request.headers.get("Upgrade") or "").lower()
        if upgrade == "websocket":
            return None

        raw_path = (request.path or "/").split("?", 1)[0].split("#", 1)[0]
        rel = "index.html" if raw_path in ("", "/") else raw_path.lstrip("/")
        target = os.path.realpath(os.path.join(base_real, rel))

        try:
            in_base = os.path.commonpath([base_real, target]) == base_real
        except ValueError:
            in_base = False

        if not in_base or not os.path.isfile(target):
            return Response(404, "Not Found", Headers([("Content-Type", "text/plain; charset=utf-8")]), b"404 Not Found")

        ctype, _ = mimetypes.guess_type(target)
        if not ctype:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype = f"{ctype}; charset=utf-8"

        try:
            with open(target, "rb") as f:
                body = f.read()
        except OSError:
            return Response(500, "Internal Server Error", Headers([("Content-Type", "text/plain")]), b"Read error")

        headers = Headers(
            [
                ("Content-Type", ctype),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
            ]
        )
        return Response(200, "OK", headers, body)

    return _process_request


class LocalCoopHost:
    """Inicia y detiene bajo demanda el Relay local, Web Invitado y túnel `cloudflared`."""

    def __init__(self):
        self._relay_thread = None
        self._relay_loop = None
        self._relay_server = None
        self._relay_srv_obj = None
        self._relay_stop_event = None
        self._relay_lock = threading.Lock()

        self._web_thread = None
        self._web_server = None
        self._web_lock = threading.Lock()

        self._tunnel_proc = None
        self._tunnel_thread = None
        self._tunnel_lock = threading.Lock()
        self.tunnel_url = ""
        self.tunnel_state = "idle"  # idle | downloading | starting | ready | error
        self.tunnel_error = ""
        self.download_bytes = 0
        self.download_total = 0
        self.download_dest = ""

    def ensure_local_services(self, relay_url: str, web_url: str = ""):
        """Arranca Relay (+ HTTP integrado en el mismo puerto) y Web extra si usa otro puerto local."""
        r_parsed = urlparse(str(relay_url or "").strip())
        relay_port = r_parsed.port or 8766
        if r_parsed.scheme == "ws" and r_parsed.hostname in ("127.0.0.1", "localhost"):
            self.start_relay(host=r_parsed.hostname, port=relay_port)

        if web_url:
            w_parsed = urlparse(str(web_url or "").strip())
            web_port = w_parsed.port or 8000
            if w_parsed.scheme == "http" and w_parsed.hostname in ("127.0.0.1", "localhost") and web_port != relay_port:
                self.start_web_server(host=w_parsed.hostname, port=web_port)

    def start_relay(self, host: str = "127.0.0.1", port: int = 8766) -> bool:
        """Inicia `RelayServer` (con HTTP estático de `web_guest/` en el mismo puerto) en un hilo."""
        with self._relay_lock:
            if self._relay_thread is not None and self._relay_thread.is_alive():
                return True

            ready = threading.Event()
            state = {"ok": False, "err": None}
            web_dir = get_resource_path("web_guest")
            http_hook = _make_static_http_hook(web_dir) if os.path.isdir(web_dir) else None

            def _runner():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._relay_loop = loop
                stop_ev = asyncio.Event()
                self._relay_stop_event = stop_ev

                async def _serve():
                    srv = RelayServer()
                    self._relay_srv_obj = srv
                    if self.tunnel_url:
                        srv.allow_origin(self.tunnel_url)
                    try:
                        async with websockets.serve(
                            srv.handle_connection,
                            host,
                            int(port),
                            compression=None,
                            process_request=http_hook,
                        ) as ws_srv:
                            self._relay_server = ws_srv
                            state["ok"] = True
                            ready.set()
                            await stop_ev.wait()
                    except OSError as exc:
                        state["err"] = exc
                        ready.set()
                    except Exception as exc:
                        state["err"] = exc
                        ready.set()
                    finally:
                        self._relay_server = None
                        self._relay_srv_obj = None

                try:
                    loop.run_until_complete(_serve())
                finally:
                    loop.close()
                    self._relay_loop = None
                    self._relay_stop_event = None

            self._relay_thread = threading.Thread(target=_runner, name="LocalCoopRelay", daemon=True)
            self._relay_thread.start()

        ready.wait(timeout=5.0)
        if state["ok"]:
            log_debug(f"[RELAY-LOCAL] Relay + Web escuchando en http://{host}:{port}")
            return True
        if isinstance(state["err"], OSError):
            winerr = getattr(state["err"], "winerror", None)
            if winerr == 10048 or getattr(state["err"], "errno", None) in (48, 98, 10048):
                log_debug(f"[RELAY-LOCAL] Puerto {port} ya está en uso (usando instancia existente).")
            else:
                log_debug(f"[RELAY-LOCAL] No se pudo abrir ws://{host}:{port}: {state['err']}")
            return False
        if state["err"] is not None:
            log_debug(f"[RELAY-LOCAL] No se pudo iniciar Relay local: {state['err']}")
        return False

    def stop_relay(self):
        """Detiene el servidor Relay local si fue iniciado por esta instancia."""
        with self._relay_lock:
            loop = self._relay_loop
            stop_ev = self._relay_stop_event
            thread = self._relay_thread
            if loop and stop_ev:
                try:
                    loop.call_soon_threadsafe(stop_ev.set)
                except Exception:
                    pass
            if thread and thread.is_alive():
                thread.join(timeout=1.5)
            self._relay_thread = None

    def start_web_server(self, host: str = "127.0.0.1", port: int = 8000) -> bool:
        """Sirve la carpeta `web_guest/` en HTTP local si se usa un puerto separado."""
        with self._web_lock:
            if self._web_server is not None:
                return True

            web_dir = get_resource_path("web_guest")
            if not os.path.isdir(web_dir):
                log_debug(f"[WEB-LOCAL] No se encontró la carpeta web_guest en: {web_dir}")
                return False

            handler = functools.partial(_QuietHTTPHandler, directory=web_dir)
            try:
                httpd = ThreadingHTTPServer((host, int(port)), handler)
            except OSError:
                log_debug(f"[WEB-LOCAL] Puerto {port} ya está en uso (usando instancia existente).")
                return False
            except Exception as exc:
                log_debug(f"[WEB-LOCAL] No se pudo iniciar servidor web local: {exc}")
                return False

            self._web_server = httpd
            self._web_thread = threading.Thread(target=httpd.serve_forever, name="LocalCoopWeb", daemon=True)
            self._web_thread.start()
            log_debug(f"[WEB-LOCAL] Web de invitado disponible en http://{host}:{port}")
            return True

    def stop_web_server(self):
        """Detiene el servidor HTTP local de `web_guest/`."""
        with self._web_lock:
            httpd = self._web_server
            thread = self._web_thread
            self._web_server = None
            self._web_thread = None
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                pass
            try:
                httpd.server_close()
            except Exception:
                pass
        if thread and thread.is_alive():
            thread.join(timeout=1.5)

    # ── Túnel automático Cloudflare (Quick Tunnel) ─────────────────────────
    def find_cloudflared(self):
        """Busca `cloudflared` en PATH, APP_DIR o DATA_DIR/bin."""
        found = shutil.which("cloudflared")
        if found:
            return found
        exe_name = "cloudflared.exe" if sys.platform.startswith("win") else "cloudflared"
        for cand in (
            os.path.join(APP_DIR, exe_name),
            os.path.join(DATA_DIR, "bin", exe_name),
        ):
            if os.path.isfile(cand):
                return cand
        return None

    def _download_cloudflared(self) -> str:
        """Descarga el binario oficial de `cloudflared` a `DATA_DIR/bin/`."""
        plat = "win32" if sys.platform.startswith("win") else "linux"
        url = _CLOUDFLARED_URLS.get(plat)
        if not url:
            raise RuntimeError(f"Descarga automática de cloudflared no soportada en {sys.platform}")

        bin_dir = os.path.join(DATA_DIR, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        exe_name = "cloudflared.exe" if plat == "win32" else "cloudflared"
        dest = os.path.join(bin_dir, exe_name)
        tmp = dest + ".tmp"
        self.download_dest = dest
        self.download_bytes = 0
        self.download_total = 0

        log_debug(f"[TUNNEL] Descargando cloudflared desde GitHub oficial hacia {dest}...")
        req = urllib.request.Request(url, headers={"User-Agent": "PNGTuberCoop"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
            try:
                self.download_total = int(resp.headers.get("Content-Length") or 0)
            except Exception:
                self.download_total = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
                self.download_bytes += len(chunk)
        os.replace(tmp, dest)
        if not sys.platform.startswith("win"):
            os.chmod(dest, 0o755)
        log_debug(f"[TUNNEL] cloudflared guardado en {dest}")
        return dest

    def start_tunnel_async(self, local_port: int = 8766, auto_download: bool = True):
        """Inicia un Quick Tunnel (`trycloudflare.com`) en segundo plano hacia `127.0.0.1:local_port`."""
        with self._tunnel_lock:
            if self._tunnel_proc is not None and self._tunnel_proc.poll() is None:
                return
            self.tunnel_url = ""
            self.tunnel_error = ""
            self.tunnel_state = "starting"

        def _worker():
            try:
                exe = self.find_cloudflared()
                if not exe:
                    if not auto_download:
                        self.tunnel_state = "error"
                        self.tunnel_error = "No se encontró cloudflared"
                        return
                    self.tunnel_state = "downloading"
                    exe = self._download_cloudflared()

                self.tunnel_state = "starting"
                cflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
                proc = subprocess.Popen(
                    [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{int(local_port)}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=cflags,
                )
                with self._tunnel_lock:
                    self._tunnel_proc = proc

                log_debug(f"[TUNNEL] Iniciando túnel Cloudflare hacia http://127.0.0.1:{local_port}...")
                for line in proc.stdout:
                    m = _TRYCLOUDFLARE_RE.search(line)
                    if m and not self.tunnel_url:
                        url = m.group(0).rstrip("/")
                        self.tunnel_url = url
                        self.tunnel_state = "ready"
                        if self._relay_srv_obj is not None:
                            self._relay_srv_obj.allow_origin(url)
                        log_debug(f"[TUNNEL] Túnel público activo: {url}")

                rc = proc.wait()
                if self.tunnel_state != "idle" and not self.tunnel_url:
                    self.tunnel_state = "error"
                    self.tunnel_error = f"cloudflared terminó inesperadamente (código {rc})"
                    log_debug(f"[TUNNEL] {self.tunnel_error}")
            except Exception as exc:
                self.tunnel_state = "error"
                self.tunnel_error = str(exc)
                log_debug(f"[TUNNEL] Error en túnel: {exc}")

        self._tunnel_thread = threading.Thread(target=_worker, name="CloudflaredTunnel", daemon=True)
        self._tunnel_thread.start()

    def stop_tunnel(self):
        """Detiene el proceso `cloudflared` si está corriendo."""
        with self._tunnel_lock:
            proc = self._tunnel_proc
            self._tunnel_proc = None
            self.tunnel_url = ""
            self.tunnel_error = ""
            self.tunnel_state = "idle"
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def stop_all(self):
        """Detiene túnel, servidor web y Relay local."""
        self.stop_tunnel()
        self.stop_web_server()
        self.stop_relay()
