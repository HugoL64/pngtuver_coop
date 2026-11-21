import ctypes
from ctypes import wintypes
import sys
import numpy as np

IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_APPWINDOW = 0x00040000
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOZORDER = 0x0004
    SWP_FRAMECHANGED = 0x0020

    ULW_ALPHA = 0x00000002
    AC_SRC_OVER = 0x00
    AC_SRC_ALPHA = 0x01
    DIB_RGB_COLORS = 0
    BI_RGB = 0

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [
            ("BlendOp", ctypes.c_ubyte),
            ("BlendFlags", ctypes.c_ubyte),
            ("SourceConstantAlpha", ctypes.c_ubyte),
            ("AlphaFormat", ctypes.c_ubyte),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]


def get_tk_hwnd(tk_win):
    """Obtiene el HWND real de una ventana Tk (borderless o con marco)."""
    if not IS_WINDOWS:
        return 0
    try:
        frame_hex = tk_win.wm_frame()
        if frame_hex and frame_hex != "0x0":
            return int(frame_hex, 16)
    except Exception:
        pass
    try:
        return int(tk_win.winfo_id())
    except Exception:
        return 0


class Win32LayeredRenderer:
    """Renderizador de transparencia Alpha por píxel en Windows usando UpdateLayeredWindow."""

    def __init__(self):
        self.hwnd = 0
        self._mem_dc = 0
        self._hbitmap = 0
        self._old_bmp = 0
        self._bits_ptr = None
        self._w = 0
        self._h = 0

    def attach(self, tk_win, enabled=True):
        if not IS_WINDOWS:
            return False
        hwnd = get_tk_hwnd(tk_win)
        if not hwnd:
            return False
        self.hwnd = hwnd
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            ex_style = (ex_style | WS_EX_LAYERED | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        else:
            ex_style = ex_style & ~WS_EX_LAYERED
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
        return True

    def _ensure_dib(self, w, h):
        if self._hbitmap and self._w == w and self._h == h:
            return True
        self._free_dib()
        screen_dc = user32.GetDC(0)
        self._mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # Top-down DIB
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        self._hbitmap = gdi32.CreateDIBSection(
            self._mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0
        )
        user32.ReleaseDC(0, screen_dc)
        if not self._hbitmap or not bits.value:
            self._free_dib()
            return False
        self._old_bmp = gdi32.SelectObject(self._mem_dc, self._hbitmap)
        self._bits_ptr = bits.value
        self._w = w
        self._h = h
        return True

    def push_pil_rgba(self, pil_rgba, win_x, win_y):
        if not IS_WINDOWS or not self.hwnd or pil_rgba is None:
            return False
        w, h = pil_rgba.size
        if w <= 0 or h <= 0 or not self._ensure_dib(w, h):
            return False

        arr = np.asarray(pil_rgba, dtype=np.uint8)
        alpha = arr[:, :, 3:4].astype(np.uint16)
        premul_rgb = ((arr[:, :, :3].astype(np.uint16) * alpha + 127) // 255).astype(np.uint8)

        bgra = np.empty((h, w, 4), dtype=np.uint8)
        bgra[:, :, 0] = premul_rgb[:, :, 2]
        bgra[:, :, 1] = premul_rgb[:, :, 1]
        bgra[:, :, 2] = premul_rgb[:, :, 0]
        bgra[:, :, 3] = arr[:, :, 3]

        raw_bytes = bgra.tobytes()
        ctypes.memmove(self._bits_ptr, raw_bytes, len(raw_bytes))

        screen_dc = user32.GetDC(0)
        pt_dst = POINT(int(win_x), int(win_y))
        sz = SIZE(w, h)
        pt_src = POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        ok = user32.UpdateLayeredWindow(
            self.hwnd, screen_dc, ctypes.byref(pt_dst), ctypes.byref(sz),
            self._mem_dc, ctypes.byref(pt_src), 0, ctypes.byref(blend), ULW_ALPHA
        )
        user32.ReleaseDC(0, screen_dc)
        return bool(ok)

    def _free_dib(self):
        if not IS_WINDOWS:
            return
        if self._mem_dc and self._old_bmp:
            try:
                gdi32.SelectObject(self._mem_dc, self._old_bmp)
            except Exception:
                pass
        if self._hbitmap:
            try:
                gdi32.DeleteObject(self._hbitmap)
            except Exception:
                pass
        if self._mem_dc:
            try:
                gdi32.DeleteDC(self._mem_dc)
            except Exception:
                pass
        self._mem_dc = 0
        self._hbitmap = 0
        self._old_bmp = 0
        self._bits_ptr = None
        self._w = 0
        self._h = 0

    def dispose(self):
        self._free_dib()
        self.hwnd = 0
