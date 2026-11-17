"""Atajos de teclado globales (funcionan aunque el programa no tenga el foco, p. ej. jugando).

Se usa un hilo muy ligero que consulta GetAsyncKeyState SOLO de las teclas asignadas.
No instala hooks de teclado ni "roba" la tecla al juego: el juego sigue recibiéndola normal.
"""
import sys
import threading
import time

IS_WIN = sys.platform.startswith("win")

if IS_WIN:
    import ctypes
    _user32 = ctypes.windll.user32
    _user32.GetAsyncKeyState.restype = ctypes.c_short
else:
    _user32 = None

MOD_CTRL = 1
MOD_ALT = 2
MOD_SHIFT = 4

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt

MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x14, 0x90}


def is_key_down(vk):
    if not _user32:
        return False
    try:
        return bool(_user32.GetAsyncKeyState(int(vk)) & 0x8000)
    except Exception:
        return False


def current_modifiers():
    mods = 0
    if is_key_down(VK_CONTROL):
        mods |= MOD_CTRL
    if is_key_down(VK_MENU):
        mods |= MOD_ALT
    if is_key_down(VK_SHIFT):
        mods |= MOD_SHIFT
    return mods


def format_hotkey(mods, key_label):
    parts = []
    if mods & MOD_CTRL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    parts.append(key_label)
    return "+".join(parts)


def pretty_key_label(keysym, vk):
    ks = str(keysym or "")
    if ks.startswith("KP_"):
        return "Num " + ks[3:]
    if len(ks) == 1:
        return ks.upper()
    names = {
        "space": "Espacio", "Return": "Enter", "Tab": "Tab", "BackSpace": "Retroceso",
        "Prior": "RePág", "Next": "AvPág", "Home": "Inicio", "End": "Fin",
        "Insert": "Insert", "Delete": "Supr", "Up": "↑", "Down": "↓", "Left": "←", "Right": "→",
    }
    if ks in names:
        return names[ks]
    if ks:
        return ks.capitalize() if not ks[0].isupper() else ks
    return f"VK{vk}"


class GlobalHotkeyListener:
    """Hilo en segundo plano que detecta las teclas asignadas y llama a callback(binding_id)."""

    def __init__(self, callback, poll_interval=0.03):
        self.callback = callback
        self.poll_interval = poll_interval
        self._bindings = {}  # binding_id -> (vk, mods)
        self._lock = threading.Lock()
        self._prev = {}
        self.suspended = False
        self._running = False
        self._thread = None

    def set_bindings(self, bindings):
        """bindings: dict binding_id -> (vk, mods)."""
        with self._lock:
            self._bindings = {k: (int(v[0]), int(v[1])) for k, v in bindings.items() if v and int(v[0]) > 0}
            self._prev = {k: True for k in self._bindings}  # evita disparos al reasignar

    def start(self):
        if not IS_WIN or self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="GlobalHotkeys", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        while self._running:
            with self._lock:
                items = list(self._bindings.items())
            if not items or self.suspended:
                time.sleep(0.3)
                continue
            mods_now = current_modifiers()
            for bid, (vk, mods) in items:
                down = is_key_down(vk) and (mods_now == mods)
                was = self._prev.get(bid, False)
                if down and not was:
                    try:
                        self.callback(bid)
                    except Exception:
                        pass
                self._prev[bid] = down
            time.sleep(self.poll_interval)

