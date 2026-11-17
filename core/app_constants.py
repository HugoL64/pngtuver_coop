import tkinter as tk
from tkinter import ttk
import os
import sys
from datetime import datetime

PROFILES_FILE = "profiles.json"
CONFIG_FILE = "config.json"
CHARACTERS_DIR = "personajes"

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def log_debug(message):
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    try:
        print(f"[{now}] {message}", flush=True)
    except Exception:
        try:
            safe_msg = str(message).encode("ascii", errors="backslashreplace").decode("ascii")
            print(f"[{now}] {safe_msg}", flush=True)
        except Exception:
            pass

class ScrollableFrame(tk.Frame):
    _active_instances = []
    _wheel_bound = False

    def __init__(self, parent, bg="#FFFFFF", **kwargs):
        super().__init__(parent, bg=bg, **kwargs)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = tk.Frame(self.canvas, bg=bg)

        self.content.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")) if self.canvas.winfo_exists() else None
        )

        self.window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        ScrollableFrame._active_instances.append(self)
        if not ScrollableFrame._wheel_bound:
            ScrollableFrame._wheel_bound = True
            self.winfo_toplevel().bind_all("<MouseWheel>", ScrollableFrame._global_mousewheel)

    @classmethod
    def _global_mousewheel(cls, event):
        try:
            top = event.widget.winfo_toplevel()
            w = top.winfo_containing(event.x_root, event.y_root)
        except Exception:
            w = event.widget
        # Buscar el ScrollableFrame más cercano que contenga el widget bajo el ratón
        cur = w
        target_sf = None
        while cur is not None:
            if isinstance(cur, ScrollableFrame):
                target_sf = cur
                break
            cur = getattr(cur, "master", None)
        if target_sf is not None and target_sf.winfo_exists() and target_sf.canvas.winfo_exists():
            try:
                target_sf.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass

    def _on_canvas_configure(self, event):
        if self.canvas.winfo_exists():
            self.canvas.itemconfig(self.window_id, width=event.width)


# ============================================================================
# --- CATÁLOGO DE EXPRESIONES SITUACIONALES / DINÁMICAS (BOTÓN '+') ---
# ============================================================================
EXTRA_EXPRESSION_CATALOG = [
    {
        "category": "💤 Por Tiempo / Inactividad (Vida propia)",
        "color": "#0284C7",
        "bg": "#E0F2FE",
        "items": [
            {
                "trigger": "afk_sleep",
                "title": "💤 Dormido / AFK",
                "desc": "Se activa cuando llevas un rato en silencio total. Se despierta al hablar.",
                "default_motion": "Flotar",
                "param_label": "Espera:",
                "param_options": ["5s", "10s", "20s", "30s", "60s", "120s"],
                "default_param": "20s",
            },
            {
                "trigger": "idle_fidget",
                "title": "✨ Tic / Gesto espontáneo",
                "desc": "Hace un gesto corto aleatorio mientras estás callado (mirar a los lados, acomodarse, etc.).",
                "default_motion": "Saltitos",
                "param_label": "Frecuencia:",
                "param_options": ["Cada 8s", "Cada 15s", "Cada 25s", "Cada 40s"],
                "default_param": "Cada 15s",
                "allow_multiple": True,
                "is_variant": True,
            },
        ],
    },
    {
        "category": "🔄 Transiciones de Voz y Parpadeo (Fluidez)",
        "color": "#7C3AED",
        "bg": "#F3E8FF",
        "items": [
            {
                "trigger": "state_scream",
                "title": "💥 Grito / Susto (Volumen Alto)",
                "desc": "Se activa cuando tu voz supera la barra de grito. Al agregarlo se habilita la barra de umbral de grito.",
                "default_motion": "Sacudida",
                "param_label": "Umbral:",
                "param_options": ["Barra de Grito"],
                "default_param": "Barra de Grito",
            },
            {
                "trigger": "state_scream_alt",
                "title": "🔥 Variante de Grito (Alternar al gritar)",
                "desc": "Se intercala rápidamente con el fotograma de grito principal mientras gritas.",
                "default_motion": "Sacudida",
                "param_label": "Ritmo:",
                "param_options": ["80ms", "120ms", "180ms", "250ms"],
                "default_param": "120ms",
                "allow_multiple": True,
                "is_variant": True,
            },
            {
                "trigger": "trans_mouth_inbetween",
                "title": "👄 Boca Semi-Abierta (Entre Abierto y Cerrado)",
                "desc": "Fotograma transicional que se reproduce tanto al abrir como al cerrar la boca para que no salte de un estado a otro.",
                "default_motion": "Respiración",
                "param_label": "Duración:",
                "param_options": ["60ms", "90ms", "130ms", "180ms", "250ms"],
                "default_param": "90ms",
            },
            {
                "trigger": "trans_blink_inbetween",
                "title": "👁️ Ojos Semi-Cerrados (Boca cerrada / General)",
                "desc": "Fotograma intermedio que suaviza el pestañeo (Abiertos → Semi-cerrados → Cerrados → Semi-cerrados → Abiertos).",
                "default_motion": "Ninguna",
                "param_label": "Velocidad:",
                "param_options": ["Rápido (45ms)", "Normal (65ms)", "Suave (90ms)"],
                "default_param": "Normal (65ms)",
            },
            {
                "trigger": "trans_blink_talk_inbetween",
                "title": "👁️🗨️ Variante: Ojos Semi-Cerrados (Boca abierta)",
                "desc": "Fotograma intermedio de pestañeo cuando estás hablando con la boca abierta.",
                "default_motion": "Ninguna",
                "param_label": "Velocidad:",
                "param_options": ["Rápido (45ms)", "Normal (65ms)", "Suave (90ms)"],
                "default_param": "Normal (65ms)",
                "is_variant": True,
            },
            {
                "trigger": "trans_pre_talk",
                "title": "🗣️ Anticipación (Solo antes de hablar)",
                "desc": "Frame fugaz únicamente al empezar a hablar (inhalar o tomar aire).",
                "default_motion": "Respiración",
                "param_label": "Duración:",
                "param_options": ["80ms", "140ms", "220ms", "350ms"],
                "default_param": "140ms",
            },
            {
                "trigger": "trans_post_talk",
                "title": "🙂 Aterrizaje (Solo al dejar de hablar)",
                "desc": "Frame suave únicamente al terminar de hablar (cerrando la boca o sonriendo).",
                "default_motion": "Ninguna",
                "param_label": "Duración:",
                "param_options": ["120ms", "200ms", "350ms", "500ms"],
                "default_param": "200ms",
            },
            {
                "trigger": "trans_pre_scream",
                "title": "⚡ Sobresalto (Antes de gritar)",
                "desc": "Instante de susto o impacto justo al superar el umbral de grito.",
                "default_motion": "Sacudida",
                "param_label": "Duración:",
                "param_options": ["40ms", "60ms", "80ms", "100ms", "140ms", "180ms", "300ms"],
                "default_param": "80ms",
            },
        ],
    },
    {
        "category": "👥 Dinámica Dúo / Cooperativa (Reacción a 2P)",
        "color": "#EA580C",
        "bg": "#FFEDD5",
        "items": [
            {
                "trigger": "coop_listening",
                "title": "👂 Escuchando al compañero",
                "desc": "Se activa cuando tú estás en silencio pero tu compañero (2P) está hablando.",
                "default_motion": "Balanceo",
                "param_label": "Modo:",
                "param_options": ["Al hablar 2P"],
                "default_param": "Al hablar 2P",
            },
            {
                "trigger": "coop_both_talking",
                "title": "⚔️ Hablando a la vez (Debate)",
                "desc": "Se activa cuando ambos jugadores hablan simultáneamente.",
                "default_motion": "Saltitos",
                "param_label": "Modo:",
                "param_options": ["Ambos hablando"],
                "default_param": "Ambos hablando",
            },
            {
                "trigger": "coop_partner_scream",
                "title": "😱 Susto por grito de 2P",
                "desc": "Tu personaje reacciona o se tapa los oídos cuando el compañero grita.",
                "default_motion": "Sacudida",
                "param_label": "Modo:",
                "param_options": ["Al gritar 2P"],
                "default_param": "Al gritar 2P",
            },
        ],
    },
    {
        "category": "🔇 Estado de Dispositivos y Audio",
        "color": "#059669",
        "bg": "#D1FAE5",
        "items": [
            {
                "trigger": "state_muted",
                "title": "🔇 Micrófono Silenciado (Mute)",
                "desc": "Se muestra cuando tienes el micrófono muteado (ej. tomando café o cartel de Mute).",
                "default_motion": "Ninguna",
                "param_label": "Modo:",
                "param_options": ["En Mute"],
                "default_param": "En Mute",
            },
            {
                "trigger": "state_whisper",
                "title": "🤫 Susurro / Voz muy baja",
                "desc": "Se activa cuando hablas bajito, por debajo del umbral normal de voz.",
                "default_motion": "Flotar",
                "param_label": "Sensibilidad:",
                "param_options": ["Suave (30%)", "Media (45%)", "Alta (60%)"],
                "default_param": "Media (45%)",
            },
        ],
    },
]


