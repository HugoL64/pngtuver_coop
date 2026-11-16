import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import json
import os
import shutil
import sys
import time
import random
import math
from datetime import datetime

from audio_engine import AudioEngine
from avatar_window import AvatarWindow
from hotkeys import GlobalHotkeyListener, MODIFIER_VKS, current_modifiers, format_hotkey, pretty_key_label
from twitch_alerts import TwitchAlertServer

# Asegurar soporte de salida UTF-8 en consolas Windows para emojis y caracteres especiales
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

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


# ============================================================================
# --- COMPONENTE AVATAR EN VIVO (ESTILO RETRO PORTÁTIL A 60 FPS) ---
# ============================================================================
class LiveAvatarPreview(tk.Frame):
    def __init__(self, parent, size=(120, 120), bg="#F8FBFF", border_color="#242E3B", accent_color="#3671C6", **kwargs):
        super().__init__(parent, bg=border_color, highlightthickness=1, highlightbackground=border_color, padx=0, pady=0, **kwargs)
        self.size = size
        self.bg_color = bg
        self.accent_color = accent_color

        # Marco interno biselado estilo consola portátil
        self.inner_border = tk.Frame(self, bg="#94A3B8", padx=1, pady=1)
        self.inner_border.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.inner_border, width=size[0], height=size[1], bg=bg, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.char_data = {}
        self.prefix = "a1"
        # Formato raw: { role: [(PIL.Image, duration_sec), ...] }
        self.raw_images = {}
        # Formato base redimensionado: { role: [PIL.Image, ...] }
        self.base_resized_images = {}
        # Formato: { role: [(PhotoImage, duration_sec), ...] }
        self.images_cache = {}
        # Caché bajo demanda para Squash & Stretch: { (role, frame_idx, squash_state): (PhotoImage, dy_anchor) }
        self.squash_photo_cache = {}
        self.image_mode = "4_states"
        self.is_talking = False
        self.is_screaming = False
        self.is_blinking = False
        self.bounce_enabled = True
        self.squash_enabled = True
        self.flip_x = False
        self.squash_state = 0
        self.squash_anchor_dy = 0

        # Contexto para expresiones situacionales / extra
        self.extra_expressions = []
        self.is_muted = False
        self.audio_level = 0.0
        self.talk_threshold = 20.0
        self.partner_talking = False
        self.partner_screaming = False

        now_init = time.time()
        self.last_activity_time = now_init
        self.talk_start_time = 0.0
        self.talk_end_time = 0.0
        self.scream_start_time = 0.0
        self.blink_start_time = 0.0
        self.blink_end_time = 0.0
        self.whisper_until = 0.0
        self.next_fidget_time = now_init + random.uniform(8.0, 16.0)
        self.fidget_end_time = 0.0
        self.fidget_active_role = None
        self.active_emote_role = None
        self.active_emote_until = 0.0
        self.preview_override_role = None
        self.preview_override_until = 0.0

        # Accesorios independientes
        self.props = []
        self.raw_props = []
        self.photo_props = []
        self.prop_canvas_items = {}
        self._last_rebuild_size = None
        self.freeze_motion = False

        self.anim_frame_idx = 0
        self.next_frame_time = 0.0
        self._last_active_role = None

        self.current_offset_y = 0.0
        self.target_offset_y = 0.0
        self.jitter_x = 0
        self.jitter_y = 0

        self.image_item = None
        self._draw_background_grid()

        icon_sz = max(28, int(size[1] * 0.28))
        self.placeholder_item = self.canvas.create_text(
            size[0] // 2, size[1] // 2, text="👤", font=("Segoe UI", icon_sz), fill="#8A99AD"
        )

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self._schedule_blink()
        self._animate_loop()

    def _draw_background_grid(self):
        self.canvas.delete("grid_bg")
        w = max(self.size[0], self.canvas.winfo_width())
        h = max(self.size[1], self.canvas.winfo_height())
        step = 16

        # Líneas de cuadrícula estilo libreta retro
        for x in range(0, w + step, step):
            color = "#D3E2F2" if (x % 64 == 0) else "#E6EFF8"
            self.canvas.create_line(x, 0, x, h, fill=color, width=1, tags="grid_bg")
        for y in range(0, h + step, step):
            color = "#D3E2F2" if (y % 64 == 0) else "#E6EFF8"
            self.canvas.create_line(0, y, w, y, fill=color, width=1, tags="grid_bg")

        # Esquinas pixeladas retro
        c_len = 8
        for cx, cy, dx, dy in [(4, 4, 1, 1), (w - 4, 4, -1, 1), (4, h - 4, 1, -1), (w - 4, h - 4, -1, -1)]:
            self.canvas.create_line(cx, cy, cx + dx * c_len, cy, fill=self.accent_color, width=2, tags="grid_bg")
            self.canvas.create_line(cx, cy, cx, cy + dy * c_len, fill=self.accent_color, width=2, tags="grid_bg")

        self.canvas.tag_lower("grid_bg")

    def _on_canvas_resize(self, event=None):
        self._draw_background_grid()
        self._rebuild_photo_cache()
        self._update_position_only()
        self._render()

    def set_character(self, char_data, prefix="a1"):
        self.char_data = char_data or {}
        self.prefix = prefix
        self.image_mode = self.char_data.get("image_mode", "4_states")
        self.flip_x = bool(self.char_data.get("flip_x", False))
        self.raw_images.clear()
        self.raw_props.clear()
        self._last_rebuild_size = None
        self.anim_frame_idx = 0
        self._last_active_role = None
        self.talk_start_time = 0.0
        self.talk_end_time = 0.0
        self.scream_start_time = 0.0
        self.preview_override_role = None
        self.active_emote_role = None
        self._motion_role = None
        self._pending_role = None

        keys_map = {
            "idle": f"{prefix}_idle",
            "idle_blink": f"{prefix}_idle_blink",
            "talk": f"{prefix}_talk",
            "talk_blink": f"{prefix}_talk_blink",
            "scream": f"{prefix}_scream",
        }

        self.extra_expressions = self.char_data.get("extra_expressions", []) or []
        for ex in self.extra_expressions:
            r_id = ex.get("role")
            if r_id:
                keys_map[r_id] = f"{prefix}_{r_id}"
                if not self.char_data.get(f"{prefix}_{r_id}") and ex.get("file"):
                    self.char_data[f"{prefix}_{r_id}"] = ex["file"]
                if not self.char_data.get(f"{prefix}_{r_id}_motion") and ex.get("motion"):
                    self.char_data[f"{prefix}_{r_id}_motion"] = ex["motion"]

        for role, key in keys_map.items():
            path = self.char_data.get(key)
            if path and os.path.exists(path):
                try:
                    img = Image.open(path)
                    n_frames = min(getattr(img, "n_frames", 1), 60)
                    frames = []
                    if n_frames > 1 and getattr(img, "is_animated", False):
                        for f_idx in range(n_frames):
                            img.seek(f_idx)
                            dur_ms = img.info.get("duration", 80) or 80
                            dur_sec = max(0.02, min(2.0, dur_ms / 1000.0))
                            frames.append((img.convert("RGBA").copy(), dur_sec))
                    else:
                        frames.append((img.convert("RGBA"), 1.0))

                    if frames:
                        self.raw_images[role] = frames
                except Exception as e:
                    print(f"[LiveAvatar] Error cargando {path}: {e}")

        # Cargar accesorios en raw para escalar dinámicamente
        self.props = self.char_data.get("props", [])
        for p in self.props:
            f_path = p.get("file", "")
            if f_path and os.path.exists(f_path):
                try:
                    with Image.open(f_path) as p_img:
                        n_f = min(getattr(p_img, "n_frames", 1), 60)
                        p_frames = []
                        if n_f > 1 and getattr(p_img, "is_animated", False):
                            for f_idx in range(n_f):
                                p_img.seek(f_idx)
                                dur_ms = p_img.info.get("duration", 80) or 80
                                dur_sec = max(0.02, min(2.0, dur_ms / 1000.0))
                                frame_rgba = p_img.convert("RGBA").copy()
                                if max(frame_rgba.size) > 1024:
                                    frame_rgba.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                                p_frames.append((frame_rgba, dur_sec))
                        else:
                            frame_rgba = p_img.convert("RGBA")
                            if max(frame_rgba.size) > 1024:
                                frame_rgba.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                            p_frames.append((frame_rgba, 1.0))

                    self.raw_props.append({
                        "id": p.get("id", str(id(p))),
                        "_file": f_path,
                        "raw_frames": p_frames,
                        "layer": p.get("layer", "front"),
                        "follows_bounce": bool(p.get("follows_bounce", False)),
                        "offset_x": int(p.get("offset_x", 0)),
                        "offset_y": int(p.get("offset_y", 0)),
                        "scale": float(p.get("scale", 100)) / 100.0,
                        "rotation": float(p.get("rotation", 0)),
                        "enabled": bool(p.get("enabled", True)),
                        "visible_frames": p.get("visible_frames", "all"),
                    })
                except Exception as e:
                    print(f"[LiveAvatar] Error cargando accesorio {p.get('name')}: {e}")

        self._rebuild_photo_cache()
        self._render()

    def _rebuild_photo_cache(self):
        cw = max(self.size[0], self.canvas.winfo_width())
        ch = max(self.size[1], self.canvas.winfo_height())
        if cw <= 30 or ch <= 30:
            cw, ch = self.size[0], self.size[1]

        if getattr(self, "_last_rebuild_size", None) == (cw, ch):
            return
        self._last_rebuild_size = (cw, ch)

        padding = 8
        avail_w = max(20, cw - padding * 2)
        avail_h = max(20, ch - padding * 2)

        self.images_cache.clear()
        self.base_resized_images.clear()
        self.squash_photo_cache.clear()
        for role, frame_list in self.raw_images.items():
            if not frame_list:
                continue
            scaled_frames = []
            pil_frames = []
            for raw_img, dur_sec in frame_list:
                img_w, img_h = raw_img.size
                if img_w <= 0 or img_h <= 0:
                    continue
                ratio = min(avail_w / img_w, avail_h / img_h)
                nw = max(1, int(img_w * ratio))
                nh = max(1, int(img_h * ratio))
                resized = raw_img.resize((nw, nh), Image.Resampling.LANCZOS)
                if getattr(self, "flip_x", False):
                    resized = resized.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                pil_frames.append(resized)
                scaled_frames.append((ImageTk.PhotoImage(resized), dur_sec))
            if scaled_frames:
                self.images_cache[role] = scaled_frames
                self.base_resized_images[role] = pil_frames

        if "idle" in self.images_cache:
            self.images_cache.setdefault("idle_blink", self.images_cache["idle"])
            self.images_cache.setdefault("talk", self.images_cache["idle"])
            self.images_cache.setdefault("talk_blink", self.images_cache["talk"])
            self.images_cache.setdefault("scream", self.images_cache["talk"])
        if "idle" in self.base_resized_images:
            self.base_resized_images.setdefault("idle_blink", self.base_resized_images["idle"])
            self.base_resized_images.setdefault("talk", self.base_resized_images["idle"])
            self.base_resized_images.setdefault("talk_blink", self.base_resized_images["talk"])
            self.base_resized_images.setdefault("scream", self.base_resized_images["talk"])

        for old_id in list(self.prop_canvas_items.values()):
            try:
                self.canvas.delete(old_id)
            except Exception:
                pass
        self.prop_canvas_items.clear()
        self.photo_props.clear()
        for cp in self.raw_props:
            prop_scaled_frames = []
            scale_factor = cp.get("scale", 1.0)
            rot_deg = float(cp.get("rotation", 0))
            for raw_img, dur_sec in cp["raw_frames"]:
                img_w, img_h = raw_img.size
                if img_w <= 0 or img_h <= 0:
                    continue
                ratio = min(avail_w / img_w, avail_h / img_h) * scale_factor
                nw = max(1, int(img_w * ratio))
                nh = max(1, int(img_h * ratio))
                resized = raw_img.resize((nw, nh), Image.Resampling.LANCZOS)
                if rot_deg != 0:
                    resized = resized.rotate(-rot_deg, resample=Image.Resampling.BICUBIC, expand=True)
                prop_scaled_frames.append((ImageTk.PhotoImage(resized), dur_sec))

            self.photo_props.append({
                "id": cp["id"],
                "_file": cp.get("_file", ""),
                "_scale": scale_factor,
                "_rotation": rot_deg,
                "frames": prop_scaled_frames,
                "layer": cp.get("layer", "front"),
                "follows_bounce": cp.get("follows_bounce", False),
                "offset_x": cp.get("offset_x", 0),
                "offset_y": cp.get("offset_y", 0),
                "enabled": cp.get("enabled", True),
                "visible_frames": cp.get("visible_frames", "all"),
            })

    def update_props_fast(self, props_list):
        """Actualiza solo los accesorios en memoria sin recargar imágenes del personaje."""
        self.props = props_list or []
        self.char_data["props"] = self.props
        old_raw_by_id = {cp["id"]: cp for cp in self.raw_props}
        old_photo_by_id = {pp["id"]: pp for pp in self.photo_props}

        cw = max(self.size[0], self.canvas.winfo_width())
        ch = max(self.size[1], self.canvas.winfo_height())
        if cw <= 30 or ch <= 30:
            cw, ch = self.size[0], self.size[1]
        avail_w = max(20, cw - 16)
        avail_h = max(20, ch - 16)

        new_raw = []
        new_photos = []
        for p in self.props:
            pid = p.get("id", str(id(p)))
            f_path = p.get("file", "")
            old_cp = old_raw_by_id.get(pid)
            if old_cp and old_cp.get("_file") == f_path:
                p_frames = old_cp["raw_frames"]
            elif f_path and os.path.exists(f_path):
                try:
                    with Image.open(f_path) as p_img:
                        n_f = min(getattr(p_img, "n_frames", 1), 60)
                        p_frames = []
                        if n_f > 1 and getattr(p_img, "is_animated", False):
                            for f_idx in range(n_f):
                                p_img.seek(f_idx)
                                dur_ms = p_img.info.get("duration", 80) or 80
                                dur_sec = max(0.02, min(2.0, dur_ms / 1000.0))
                                frame_rgba = p_img.convert("RGBA").copy()
                                if max(frame_rgba.size) > 1024:
                                    frame_rgba.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                                p_frames.append((frame_rgba, dur_sec))
                        else:
                            frame_rgba = p_img.convert("RGBA")
                            if max(frame_rgba.size) > 1024:
                                frame_rgba.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                            p_frames.append((frame_rgba, 1.0))
                except Exception:
                    continue
            else:
                continue

            sc_factor = float(p.get("scale", 100)) / 100.0
            rot_deg = float(p.get("rotation", 0))
            new_raw.append({
                "id": pid,
                "_file": f_path,
                "raw_frames": p_frames,
                "layer": p.get("layer", "front"),
                "follows_bounce": bool(p.get("follows_bounce", False)),
                "offset_x": int(p.get("offset_x", 0)),
                "offset_y": int(p.get("offset_y", 0)),
                "scale": sc_factor,
                "rotation": rot_deg,
                "enabled": bool(p.get("enabled", True)),
                "visible_frames": p.get("visible_frames", "all"),
            })

            old_pp = old_photo_by_id.get(pid)
            if old_pp and old_pp.get("_file") == f_path and old_pp.get("_scale") == sc_factor and old_pp.get("_rotation") == rot_deg:
                prop_scaled_frames = old_pp["frames"]
            else:
                prop_scaled_frames = []
                for raw_img, dur_sec in p_frames:
                    img_w, img_h = raw_img.size
                    if img_w <= 0 or img_h <= 0:
                        continue
                    ratio = min(avail_w / img_w, avail_h / img_h) * sc_factor
                    nw = max(1, int(img_w * ratio))
                    nh = max(1, int(img_h * ratio))
                    resized = raw_img.resize((nw, nh), Image.Resampling.BILINEAR)
                    if rot_deg != 0:
                        resized = resized.rotate(-rot_deg, resample=Image.Resampling.BILINEAR, expand=True)
                    prop_scaled_frames.append((ImageTk.PhotoImage(resized), dur_sec))

            new_photos.append({
                "id": pid,
                "_file": f_path,
                "_scale": sc_factor,
                "_rotation": rot_deg,
                "frames": prop_scaled_frames,
                "layer": p.get("layer", "front"),
                "follows_bounce": bool(p.get("follows_bounce", False)),
                "offset_x": int(p.get("offset_x", 0)),
                "offset_y": int(p.get("offset_y", 0)),
                "enabled": bool(p.get("enabled", True)),
                "visible_frames": p.get("visible_frames", "all"),
            })

        self.raw_props = new_raw
        self.photo_props = new_photos
        self._render()

    @staticmethod
    def _parse_ms_param(val, default=150):
        try:
            digits = "".join(c for c in str(val) if c.isdigit())
            return float(digits) if digits else float(default)
        except Exception:
            return float(default)

    @staticmethod
    def _parse_sec_param(val, default=20):
        try:
            digits = "".join(c for c in str(val) if c.isdigit())
            return float(digits) if digits else float(default)
        except Exception:
            return float(default)

    @staticmethod
    def _parse_whisper_ratio(val):
        s = str(val)
        if "30" in s:
            return 0.30
        if "60" in s:
            return 0.60
        return 0.45

    def trigger_preview_role(self, role_id, duration=2.5):
        self.preview_override_role = role_id
        self.preview_override_until = time.time() + duration
        self._render()

    def trigger_hotkey_emote(self, key_pressed):
        key_upper = str(key_pressed).upper()
        if key_upper in ("0", "ESCAPE"):
            if self.active_emote_role is not None:
                self.active_emote_role = None
                self.active_emote_until = 0.0
                self._render()
                return True
            return False

        extras = getattr(self, "extra_expressions", []) or []
        now = time.time()
        for ex in extras:
            if ex.get("trigger") == "hotkey_emote":
                param = str(ex.get("param", "1 (Toggle)"))
                parts = param.split(" ", 1)
                configured_key = parts[0].strip().upper()
                if configured_key == key_upper:
                    r_id = ex.get("role")
                    is_timed = "3" in (parts[1] if len(parts) > 1 else "")
                    if is_timed:
                        self.active_emote_role = r_id
                        self.active_emote_until = now + 3.0
                    else:
                        if self.active_emote_role == r_id:
                            self.active_emote_role = None
                            self.active_emote_until = 0.0
                        else:
                            self.active_emote_role = r_id
                            self.active_emote_until = 0.0
                    self._render()
                    return True
        return False

    def _get_current_role(self):
        now = time.time()
        talking = self.is_talking and not self.is_muted
        screaming = self.is_screaming and (talking or getattr(self, "_manual_scream", False))

        if talking or screaming:
            self.last_activity_time = now

        # 1. Prueba manual desde el Taller (botón "▶ Probar")
        if self.preview_override_role and now < self.preview_override_until:
            if self.preview_override_role in self.images_cache:
                return self.preview_override_role
        elif self.preview_override_role and now >= self.preview_override_until:
            self.preview_override_role = None

        extras = getattr(self, "extra_expressions", []) or []

        def find_extra(trig_type):
            for ex in extras:
                r_id = ex.get("role")
                if ex.get("trigger") == trig_type and r_id in self.images_cache:
                    return ex
            return None

        # 2. Estado Muteado (state_muted) o quieto sin movimiento si no tiene frame de mute
        if self.is_muted:
            ex_mute = find_extra("state_muted")
            if ex_mute:
                return ex_mute["role"]
            if self.is_blinking and self.image_mode == "4_states" and "idle_blink" in self.images_cache:
                return "idle_blink"
            return "idle"

        # 3. Emoción activada por Tecla Rápida (hotkey_emote)
        if self.active_emote_role:
            if self.active_emote_until > 0 and now >= self.active_emote_until:
                self.active_emote_role = None
                self.active_emote_until = 0.0
            elif self.active_emote_role in self.images_cache:
                return self.active_emote_role

        # 4. Grito y Transición Pre-Grito (state_scream / state_scream_alt / trans_pre_scream)
        ex_scream = find_extra("state_scream")
        if screaming and ex_scream:
            ex_pre_scream = find_extra("trans_pre_scream")
            if ex_pre_scream and self.scream_start_time > 0:
                dur_ms = self._parse_ms_param(ex_pre_scream.get("param", "80ms"), 80)
                if (now - self.scream_start_time) < (dur_ms / 1000.0):
                    return ex_pre_scream["role"]
            scream_alts = [ex for ex in extras if ex.get("trigger") == "state_scream_alt" and ex.get("role") in self.images_cache]
            if scream_alts:
                scream_roles = [ex_scream["role"]] + [ex["role"] for ex in scream_alts]
                alt_ms = self._parse_ms_param(scream_alts[0].get("param", "120ms"), 120)
                base_t = self.scream_start_time if self.scream_start_time > 0 else now
                idx = int(max(0.0, now - base_t) / max(0.04, alt_ms / 1000.0)) % len(scream_roles)
                return scream_roles[idx]
            return ex_scream["role"]

        # 5. Cooperativo: Ambos hablando a la vez (coop_both_talking)
        if talking and self.partner_talking:
            ex_both = find_extra("coop_both_talking")
            if ex_both:
                return ex_both["role"]

        # 6. Hablando y Transición de Boca / Pre-Habla (trans_mouth_inbetween / trans_pre_talk)
        if talking:
            ex_mouth_mid = find_extra("trans_mouth_inbetween")
            if ex_mouth_mid and self.talk_start_time > 0:
                dur_ms = self._parse_ms_param(ex_mouth_mid.get("param", "90ms"), 90)
                if (now - self.talk_start_time) < (dur_ms / 1000.0):
                    return ex_mouth_mid["role"]

            ex_pre_talk = find_extra("trans_pre_talk")
            if ex_pre_talk and self.talk_start_time > 0:
                dur_ms = self._parse_ms_param(ex_pre_talk.get("param", "140ms"), 140)
                if (now - self.talk_start_time) < (dur_ms / 1000.0):
                    return ex_pre_talk["role"]

            if self.is_blinking:
                ex_blink_talk = find_extra("trans_blink_talk_inbetween")
                ex_blink_mid = ex_blink_talk or find_extra("trans_blink_inbetween")
                if ex_blink_mid:
                    half_ms = self._parse_ms_param(ex_blink_mid.get("param", "Normal (65ms)"), 65)
                    half_s = half_ms / 1000.0
                    if (now - self.blink_start_time) < half_s or (self.blink_end_time - now) < half_s:
                        return ex_blink_mid["role"]
                if self.image_mode == "4_states" and "talk_blink" in self.images_cache:
                    return "talk_blink"

            if getattr(self, "mouth_flutter_enabled", False) and ex_mouth_mid and self.talk_start_time > 0:
                elapsed_talk = now - self.talk_start_time
                if elapsed_talk >= 0.28:
                    if int((elapsed_talk - 0.28) / 0.11) % 2 == 1:
                        return ex_mouth_mid["role"]
            return "talk"

        # --- EN SILENCIO ---

        # 7. Transición de Boca al cerrar / Post-Habla (trans_mouth_inbetween / trans_post_talk)
        ex_mouth_mid = find_extra("trans_mouth_inbetween")
        if ex_mouth_mid and self.talk_end_time > 0:
            dur_ms = self._parse_ms_param(ex_mouth_mid.get("param", "90ms"), 90)
            if (now - self.talk_end_time) < (dur_ms / 1000.0):
                return ex_mouth_mid["role"]

        ex_post_talk = find_extra("trans_post_talk")
        if ex_post_talk and self.talk_end_time > 0:
            dur_ms = self._parse_ms_param(ex_post_talk.get("param", "200ms"), 200)
            if (now - self.talk_end_time) < (dur_ms / 1000.0):
                return ex_post_talk["role"]

        # 8. Cooperativo en silencio: Reacción al grito del compañero (coop_partner_scream)
        if self.partner_screaming:
            ex_pscream = find_extra("coop_partner_scream")
            if ex_pscream:
                self.last_activity_time = now
                return ex_pscream["role"]

        # 9. Cooperativo en silencio: Escuchando al compañero (coop_listening)
        if self.partner_talking:
            ex_listen = find_extra("coop_listening")
            if ex_listen:
                self.last_activity_time = now
                return ex_listen["role"]

        # 10. Susurro / Voz muy baja (state_whisper)
        if not self.is_muted:
            ex_whisper = find_extra("state_whisper")
            if ex_whisper:
                ratio = self._parse_whisper_ratio(ex_whisper.get("param", "Media (45%)"))
                min_lvl = max(3.5, self.talk_threshold * ratio)
                if self.audio_level >= min_lvl:
                    self.whisper_until = now + 0.25
                    self.last_activity_time = now
                if now < self.whisper_until:
                    return ex_whisper["role"]

        # 11. Inactividad prolongada: Dormido / AFK (afk_sleep)
        ex_afk = find_extra("afk_sleep")
        if ex_afk:
            afk_sec = self._parse_sec_param(ex_afk.get("param", "20s"), 20)
            if (now - self.last_activity_time) >= afk_sec:
                return ex_afk["role"]

        # 12. Tic / Gesto espontáneo en reposo (idle_fidget)
        ex_fidget = find_extra("idle_fidget")
        if ex_fidget:
            interval_sec = self._parse_sec_param(ex_fidget.get("param", "Cada 15s"), 15)
            if now < self.fidget_end_time and self.fidget_active_role in self.images_cache:
                return self.fidget_active_role
            elif now >= self.next_fidget_time:
                fidget_list = [e for e in extras if e.get("trigger") == "idle_fidget" and e.get("role") in self.images_cache]
                if fidget_list:
                    chosen = random.choice(fidget_list)
                    self.fidget_active_role = chosen["role"]
                    self.fidget_end_time = now + 1.5
                    self.next_fidget_time = now + 1.5 + max(4.0, interval_sec + random.uniform(-2.0, 2.0))
                    return self.fidget_active_role

        # 13. Reposo normal (con o sin pestañeo y transición de pestañeo)
        if self.is_blinking:
            ex_blink_mid = find_extra("trans_blink_inbetween")
            if ex_blink_mid:
                half_ms = self._parse_ms_param(ex_blink_mid.get("param", "Normal (65ms)"), 65)
                half_s = half_ms / 1000.0
                if (now - self.blink_start_time) < half_s or (self.blink_end_time - now) < half_s:
                    return ex_blink_mid["role"]
            if self.image_mode == "4_states" and "idle_blink" in self.images_cache:
                return "idle_blink"
        return "idle"

    def update_state(self, talking, screaming, muted=None, audio_level=None, talk_threshold=None, partner_talking=None, partner_screaming=None):
        now = time.time()
        mute_changed = False
        if muted is not None:
            new_m = bool(muted)
            if self.is_muted != new_m:
                mute_changed = True
            self.is_muted = new_m
        if audio_level is not None:
            self.audio_level = float(audio_level)
        if talk_threshold is not None:
            self.talk_threshold = float(talk_threshold)
        if partner_talking is not None:
            self.partner_talking = bool(partner_talking)
        if partner_screaming is not None:
            self.partner_screaming = bool(partner_screaming)

        if self.is_talking != talking:
            self.last_activity_time = now
            if talking:
                self.talk_start_time = now
                self.fidget_end_time = 0.0
            else:
                self.talk_end_time = now
        if self.is_screaming != screaming and screaming:
            self.scream_start_time = now
            self.last_activity_time = now

        state_changed = (self.is_talking != talking or self.is_screaming != screaming or mute_changed)
        self.is_talking = talking
        self.is_screaming = screaming

        if state_changed:
            self._render()

    def _is_scream_role(self, r):
        if r == "scream":
            return True
        for ex in (getattr(self, "extra_expressions", []) or []):
            if ex.get("role") == r and ex.get("trigger") in ("state_scream", "state_scream_alt", "trans_pre_scream"):
                return True
        return False

    def _congruent_motion_role(self, role, now):
        """Congruencia: un fotograma fugaz (p. ej. un pestañeo) conserva la animación del anterior.
        Solo si el nuevo fotograma se mantiene un instante adopta su propia animación."""
        if not getattr(self, "congruence_enabled", True):
            self._motion_role = role
            self._pending_role = None
            return role
        cur = getattr(self, "_motion_role", None)
        if cur is None or cur == role:
            self._motion_role = role
            self._pending_role = None
            return role
        if getattr(self, "_pending_role", None) != role:
            self._pending_role = role
            self._pending_since = now
        hold = 0.0 if (self.is_screaming or self._is_scream_role(role) or self._is_scream_role(cur)) else 0.25
        if now - self._pending_since >= hold:
            self._motion_role = role
            self._pending_role = None
        return self._motion_role

    def _get_active_motion_type(self, role=None):
        if not getattr(self, "bounce_enabled", True):
            return "Ninguna"
        if role is None:
            role = self._get_current_role()
        if getattr(self, "is_muted", False):
            for ex in getattr(self, "extra_expressions", []) or []:
                if ex.get("trigger") == "state_muted" and ex.get("role") == role:
                    m = ex.get("motion", "Ninguna")
                    return "Respiración" if m == "Rebote" else m
            return "Ninguna"
        pref = getattr(self, "prefix", "a1")
        motion = self.char_data.get(f"{pref}_{role}_motion")
        if not motion:
            motion = self.char_data.get(f"a1_{role}_motion") or self.char_data.get(f"a2_{role}_motion")
        if not motion:
            for ex in getattr(self, "extra_expressions", []) or []:
                if ex.get("role") == role and ex.get("motion"):
                    motion = ex["motion"]
                    break
        if not motion:
            if role in ("idle", "talk"):
                motion = "Respiración"
            elif role == "scream":
                motion = "Sacudida"
            else:
                motion = "Ninguna"
        if motion == "Rebote":
            motion = "Respiración"
        return motion

    def _get_active_motion_speed(self, role=None):
        if role is None:
            role = self._get_current_role()
        pref = getattr(self, "prefix", "a1")
        spd = self.char_data.get(f"{pref}_{role}_speed")
        if spd is None:
            spd = self.char_data.get(f"a1_{role}_speed") or self.char_data.get(f"a2_{role}_speed")
        if spd is None:
            for ex in getattr(self, "extra_expressions", []) or []:
                if ex.get("role") == role and ex.get("speed") is not None:
                    spd = ex["speed"]
                    break
        try:
            return max(0.25, min(3.5, float(spd))) if spd is not None else 1.0
        except Exception:
            return 1.0

    def _animate_loop(self):
        if not self.winfo_exists():
            return

        # Modo ahorro: si la vista previa está pausada (OBS activo y el programa en segundo plano), no dibujar nada
        if getattr(self, "paused", False):
            self.after(250, self._animate_loop)
            return

        if getattr(self, "freeze_motion", False):
            need_render = (self._last_active_role != "idle" or self.is_blinking or self.is_talking or self.is_screaming)
            self.is_blinking = False
            self.is_talking = False
            self.is_screaming = False
            self.current_offset_y = 0.0
            self.target_offset_y = 0.0
            self.jitter_x = 0
            self.jitter_y = 0
            if need_render:
                self._last_active_role = "idle"
                self._render()
            else:
                self._update_position_only()
            self.after(120, self._animate_loop)
            return

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw > 30 and ch > 30 and getattr(self, "_last_rebuild_size", None) != (cw, ch):
            self._rebuild_photo_cache()
            self._render()

        now = time.time()
        pos_changed = False

        # 0. Avance de fotograma para expresiones animadas (GIF / APNG / WEBP)
        role = self._get_current_role()
        if role != self._last_active_role:
            self._last_active_role = role
            self.anim_frame_idx = 0
            frames_list = self.images_cache.get(role) or self.images_cache.get("idle", [])
            if len(frames_list) > 1:
                self.next_frame_time = now + frames_list[0][1]
            self._render()
        else:
            frames_list = self.images_cache.get(role) or self.images_cache.get("idle", [])
            if len(frames_list) > 1 and now >= self.next_frame_time:
                self.anim_frame_idx = (self.anim_frame_idx + 1) % len(frames_list)
                self.next_frame_time = now + frames_list[self.anim_frame_idx][1]
                self._render()

        # 1. Movimientos dinámicos según el tipo seleccionado y su velocidad individual (fase continua)
        motion_role = self._congruent_motion_role(role, now)
        motion_type = self._get_active_motion_type(motion_role)
        motion_speed = self._get_active_motion_speed(motion_role)
        dt = min(0.1, max(0.0, now - getattr(self, "_last_anim_tick", now)))
        self._last_anim_tick = now
        self._anim_phase = getattr(self, "_anim_phase", 0.0) + dt * motion_speed
        p = self._anim_phase
        prev_offset_y = self.current_offset_y
        congruence_on = getattr(self, "congruence_enabled", True)
        if motion_type != getattr(self, "_last_motion_type", None):
            self._last_motion_type = motion_type
            self._blend_from_y = self.current_offset_y
            self._blend_from_x = self.jitter_x
            self._blend_from_squash = self.squash_state
            self._blend_start = now if congruence_on else 0.0

        # Sacudida (únicamente si esa pose tiene asignada Sacudida)
        if motion_type == "Sacudida":
            step_period = max(0.015, 0.04 / motion_speed)
            if not hasattr(self, "_last_shake_t") or (now - self._last_shake_t) >= step_period:
                self._last_shake_t = now
                self.jitter_x = random.choice([-3, -1, 1, 3])
                self.jitter_y = random.choice([-3, -1, 1, 3])
            pos_changed = True
        elif motion_type != "Balanceo":
            if self.jitter_x != 0 or self.jitter_y != 0:
                self.jitter_x = 0
                self.jitter_y = 0
                pos_changed = True

        if motion_type == "Respiración":
            # Respiración pura y continua: sube y baja suavemente (inhalar / exhalar), sin deformar la imagen
            target_y = -((math.sin(p * 2.2) + 1.0) * 0.5) * 3.5
            self.current_offset_y += (target_y - self.current_offset_y) * 0.25
            pos_changed = True

        elif motion_type == "Saltitos":
            # Saltitos continuos y rítmicos
            self.current_offset_y = -abs(math.sin(p * 12.0)) * 8.0
            pos_changed = True

        elif motion_type == "Elástico":
            # Rebote elástico suave y continuo (mismo ritmo sin acelerarse frenéticamente entre poses)
            self.current_offset_y = -max(0.0, math.sin(p * 4.5)) * 6.0
            pos_changed = True

        elif motion_type == "Balanceo":
            # Vaivén lateral continuo
            self.jitter_x = int(math.sin(p * 7.0) * 5.0)
            self.jitter_y = 0
            diff_y = 0.0 - self.current_offset_y
            if abs(diff_y) > 0.25:
                self.current_offset_y += diff_y * 0.35
            else:
                self.current_offset_y = 0.0
            pos_changed = True

        elif motion_type == "Flotar":
            # Suave vaivén vertical
            self.current_offset_y = math.sin(p * 3.5) * 6.0
            pos_changed = True

        else: # Ninguna
            if self.current_offset_y != 0.0:
                diff_y = 0.0 - self.current_offset_y
                if abs(diff_y) > 0.25:
                    self.current_offset_y += diff_y * 0.35
                else:
                    self.current_offset_y = 0.0
                pos_changed = True

        # 2. Efecto "Squash & Stretch" (Estirar y Aplastar elástico)
        vel_y = self.current_offset_y - prev_offset_y
        new_squash = 0
        if not self.is_muted and (getattr(self, "squash_enabled", True) or motion_type == "Elástico"):
            if motion_type == "Elástico":
                s_wave = math.sin(p * 4.5)
                if s_wave > 0.45:
                    new_squash = 1
                elif s_wave < -0.45:
                    new_squash = -1
            elif motion_type == "Saltitos":
                if vel_y < -1.1:
                    new_squash = 2 if vel_y < -2.2 else 1
                elif vel_y > 1.0:
                    new_squash = -2 if vel_y > 2.0 else -1
                elif self.current_offset_y < -6.5:
                    new_squash = 1

        # 3. Congruencia: el nuevo fotograma arranca en la posición y tamaño del anterior y se transforma suavemente
        blend_t = now - getattr(self, "_blend_start", 0.0)
        if congruence_on and 0.0 <= blend_t < 0.22:
            k = blend_t / 0.22
            k = k * k * (3.0 - 2.0 * k)
            self.current_offset_y = self._blend_from_y + (self.current_offset_y - self._blend_from_y) * k
            self.jitter_x = int(round(self._blend_from_x + (self.jitter_x - self._blend_from_x) * k))
            if k < 0.5:
                new_squash = self._blend_from_squash
            pos_changed = True

        if new_squash != self.squash_state:
            self.squash_state = new_squash
            self._render()
        elif pos_changed:
            self._update_position_only()

        self.after(16, self._animate_loop)

    def _get_squash_photo(self, role, frame_idx):
        frames_list = self.images_cache.get(role) or self.images_cache.get("idle")
        if not frames_list:
            return None, 0
        idx = frame_idx % len(frames_list)
        if self.squash_state == 0:
            return frames_list[idx][0], 0

        cache_key = (role, idx, self.squash_state)
        cached = self.squash_photo_cache.get(cache_key)
        if cached is not None:
            return cached

        pil_list = self.base_resized_images.get(role) or self.base_resized_images.get("idle")
        if not pil_list:
            return frames_list[idx][0], 0

        base_img = pil_list[idx % len(pil_list)]
        bw, bh = base_img.size
        scale_map = {
            -2: (1.07, 0.93),
            -1: (1.04, 0.96),
            1: (0.96, 1.04),
            2: (0.93, 1.07),
        }
        sx, sy = scale_map.get(self.squash_state, (1.0, 1.0))
        nw = max(1, int(round(bw * sx)))
        nh = max(1, int(round(bh * sy)))
        deformed = base_img.resize((nw, nh), Image.Resampling.BILINEAR)
        # Mantener la base inferior del personaje plantada en su sitio al estirar o aplastar
        dy_anchor = (bh - nh) // 2
        res = (ImageTk.PhotoImage(deformed), dy_anchor)
        self.squash_photo_cache[cache_key] = res
        return res

    @staticmethod
    def _is_prop_visible_for_role(prop, role):
        vf = prop.get("visible_frames", "all")
        if vf == "all" or not vf:
            return True
        if isinstance(vf, list):
            return role in vf
        return True

    def _update_position_only(self):
        w = max(self.size[0], self.canvas.winfo_width())
        h = max(self.size[1], self.canvas.winfo_height())
        base_x = (w // 2)
        base_y = (h // 2)
        pos_scale = max(20, h - 16) / 384.0
        role = self._get_current_role()

        if self.image_item is not None:
            x = base_x + self.jitter_x
            y = base_y + int(self.current_offset_y) + self.jitter_y + getattr(self, "squash_anchor_dy", 0)
            self.canvas.coords(self.image_item, x, y)

        for p in self.photo_props:
            item_id = self.prop_canvas_items.get(p["id"])
            if item_id:
                try:
                    if p["enabled"] and self._is_prop_visible_for_role(p, role):
                        dx = int(p["offset_x"] * pos_scale)
                        dy = int(p["offset_y"] * pos_scale)
                        if p["follows_bounce"]:
                            px = base_x + dx + self.jitter_x
                            py = base_y + dy + int(self.current_offset_y) + self.jitter_y
                        else:
                            px = base_x + dx
                            py = base_y + dy
                        self.canvas.coords(item_id, px, py)
                        self.canvas.itemconfig(item_id, state="normal")
                    else:
                        self.canvas.itemconfig(item_id, state="hidden")
                except tk.TclError:
                    self.prop_canvas_items.pop(p["id"], None)

    def _schedule_blink(self):
        delay = random.randint(2600, 5200)
        self.after(delay, self._start_blink)

    def _start_blink(self):
        if not self.winfo_exists():
            return
        has_blink_mid = any(
            ex.get("trigger") == "trans_blink_inbetween" and ex.get("role") in self.images_cache
            for ex in (getattr(self, "extra_expressions", []) or [])
        )
        if (self.image_mode == "4_states" or has_blink_mid) and not self.is_screaming:
            now = time.time()
            self.is_blinking = True
            self.blink_start_time = now
            dur_ms = 210 if has_blink_mid else 135
            self.blink_end_time = now + (dur_ms / 1000.0)
            self._render()
            self.after(dur_ms, self._end_blink)
        else:
            self._schedule_blink()

    def _end_blink(self):
        if not self.winfo_exists():
            return
        self.is_blinking = False
        self._render()
        self._schedule_blink()

    def _render(self):
        w = max(self.size[0], self.canvas.winfo_width())
        h = max(self.size[1], self.canvas.winfo_height())
        base_x = (w // 2)
        base_y = (h // 2)
        pos_scale = max(20, h - 16) / 384.0

        # Limpiar items de accesorios eliminados
        valid_pids = {p["id"] for p in self.photo_props}
        for old_pid in list(self.prop_canvas_items.keys()):
            if old_pid not in valid_pids:
                try:
                    self.canvas.delete(self.prop_canvas_items.pop(old_pid))
                except Exception:
                    pass

        if not self.images_cache:
            self.canvas.itemconfig(self.placeholder_item, state="normal")
            if self.image_item is not None:
                self.canvas.itemconfig(self.image_item, state="hidden")
            return

        self.canvas.itemconfig(self.placeholder_item, state="hidden")
        role = self._get_current_role()

        # 1. DIBUJAR ACCESORIOS DE FONDO (BACK)
        back_items = []
        for p in self.photo_props:
            if p["layer"] != "back":
                continue
            item_id = self._render_preview_prop_item(p, base_x, base_y, pos_scale, role)
            if item_id:
                back_items.append(item_id)

        # 2. DIBUJAR AVATAR PRINCIPAL (con soporte para Squash & Stretch)
        photo, dy_anchor = self._get_squash_photo(role, self.anim_frame_idx)
        self.squash_anchor_dy = dy_anchor

        if photo:
            x = base_x + self.jitter_x
            y = base_y + int(self.current_offset_y) + self.jitter_y + dy_anchor
            if self.image_item is None:
                self.image_item = self.canvas.create_image(x, y, anchor="center", image=photo)
            else:
                self.canvas.coords(self.image_item, x, y)
                self.canvas.itemconfig(self.image_item, image=photo, state="normal")
            self.canvas.current_photo = photo

        # 3. DIBUJAR ACCESORIOS DE FRENTE (FRONT)
        front_items = []
        for p in self.photo_props:
            if p["layer"] == "back":
                continue
            item_id = self._render_preview_prop_item(p, base_x, base_y, pos_scale, role)
            if item_id:
                front_items.append(item_id)

        # Asegurar orden Z (preservando orden exacto de capas)
        if self.image_item is not None:
            for b_it in back_items:
                self.canvas.tag_lower(b_it, self.image_item)
            prev_it = self.image_item
            for f_it in front_items:
                self.canvas.tag_raise(f_it, prev_it)
                prev_it = f_it

    def _render_preview_prop_item(self, prop, base_x, base_y, pos_scale, role):
        pid = prop["id"]
        if not prop["enabled"] or not prop["frames"] or not self._is_prop_visible_for_role(prop, role):
            if pid in self.prop_canvas_items:
                try:
                    self.canvas.itemconfig(self.prop_canvas_items[pid], state="hidden")
                except tk.TclError:
                    self.prop_canvas_items.pop(pid, None)
            return None

        f_idx = self.anim_frame_idx % len(prop["frames"])
        p_photo = prop["frames"][f_idx][0]

        dx = int(prop["offset_x"] * pos_scale)
        dy = int(prop["offset_y"] * pos_scale)
        if prop["follows_bounce"]:
            px = base_x + dx + self.jitter_x
            py = base_y + dy + int(self.current_offset_y) + self.jitter_y
        else:
            px = base_x + dx
            py = base_y + dy

        item_id = self.prop_canvas_items.get(pid)
        if item_id is None:
            item_id = self.canvas.create_image(px, py, anchor="center", image=p_photo)
            self.prop_canvas_items[pid] = item_id
        else:
            try:
                self.canvas.itemconfig(item_id, image=p_photo, state="normal")
                self.canvas.coords(item_id, px, py)
            except tk.TclError:
                item_id = self.canvas.create_image(px, py, anchor="center", image=p_photo)
                self.prop_canvas_items[pid] = item_id

        return item_id


# ============================================================================
# --- APLICACIÓN PRINCIPAL (PNGTUBER DUO CO-OP) ---
# ============================================================================
class PNGTuberCoopApp:
    def __init__(self, root):
        log_debug("🚀 [SISTEMA] Iniciando PNGTuber Duo Co-op...")
        self.root = root
        self.root.title("PNGTuber Duo Co-op")
        self.root.geometry("980x820")
        self.root.minsize(920, 720)
        self.root.configure(bg="#DFE5EE")

        self.audio_engine = AudioEngine(
            on_mic_level=self._on_mic_level_thread,
            on_discord_level=self._on_discord_level_thread,
            on_mic_state=self._on_mic_state_thread,
            on_discord_state=self._on_discord_state_thread,
            on_mic_scream=self._on_mic_scream_thread,
            on_discord_scream=self._on_discord_scream_thread
        )

        self.avatar1_window = None
        self.avatar2_window = None
        self.btn_open = None

        self.mic_level = 0.0
        self.discord_level = 0.0
        self.mic_talking = False
        self.discord_talking = False

        self.p1_is_screaming = False
        self.p2_is_screaming = False

        self.thumbnails = {}
        self.current_screen = "lobby"
        self.workshop_player = 1

        self.default_assets = {
            "a1_idle": get_resource_path(os.path.join("assets", "avatar1_idle.png")),
            "a1_idle_blink": get_resource_path(os.path.join("assets", "avatar1_idle_blink.png")),
            "a1_talk": get_resource_path(os.path.join("assets", "avatar1_talk.png")),
            "a1_talk_blink": get_resource_path(os.path.join("assets", "avatar1_talk_blink.png")),
            "a1_scream": get_resource_path(os.path.join("assets", "avatar1_scream.png")),

            "a2_idle": get_resource_path(os.path.join("assets", "avatar2_idle.png")),
            "a2_idle_blink": get_resource_path(os.path.join("assets", "avatar2_idle_blink.png")),
            "a2_talk": get_resource_path(os.path.join("assets", "avatar2_talk.png")),
            "a2_talk_blink": get_resource_path(os.path.join("assets", "avatar2_talk_blink.png")),
            "a2_scream": get_resource_path(os.path.join("assets", "avatar2_scream.png")),
        }

        # Segundo jugador sale desactivado por defecto
        self.global_config = {
            "game_mode": "single",
            "current_p1_profile": "Gatito Azul",
            "current_p2_profile": "Osito Discord",
            "bg_color": "#00FF00",
            "bounce_enabled": True,
            "squash_enabled": True,
            "hysteresis_enabled": False,
            "congruence_enabled": True,
            "mouth_flutter_enabled": False,
            "experimental_enabled": False,
            "twitch_alerts": {
                "enabled": False,
                "port": 8765,
                "rules": [
                    {"id": "rule_follow", "enabled": True, "event": "follow", "player": 1, "action": "character", "character": "", "duration": 8.0},
                    {"id": "rule_sub", "enabled": True, "event": "sub", "player": 1, "action": "scream", "character": "", "duration": 5.0},
                    {"id": "rule_raid", "enabled": True, "event": "raid", "player": 1, "action": "scream", "character": "", "duration": 7.0},
                ]
            },
            "hotkeys": {"1": [], "2": []},
            "character_layout": []
        }

        self.profiles = {"player1": {}, "player2": {}}

        self.p1_data = {
            "mic_device_name": "",
            "mic_threshold": 20,
            "scream_threshold": 55,
            "image_mode": "4_states",
            "props": [],
            "extra_expressions": [],
            "a1_idle": self.default_assets["a1_idle"],
            "a1_idle_blink": self.default_assets["a1_idle_blink"],
            "a1_talk": self.default_assets["a1_talk"],
            "a1_talk_blink": self.default_assets["a1_talk_blink"],
            "a1_scream": self.default_assets["a1_scream"]
        }

        self.p2_data = {
            "discord_source_id": "app:discord",
            "discord_threshold": 25,
            "scream_threshold": 55,
            "image_mode": "4_states",
            "props": [],
            "extra_expressions": [],
            "a2_idle": self.default_assets["a2_idle"],
            "a2_idle_blink": self.default_assets["a2_idle_blink"],
            "a2_talk": self.default_assets["a2_talk"],
            "a2_talk_blink": self.default_assets["a2_talk_blink"],
            "a2_scream": self.default_assets["a2_scream"]
        }

        self.load_all_data()
        self.audio_engine.hysteresis_ratio = 0.70 if self.global_config.get("hysteresis_enabled", False) else 1.0
        log_debug(f"[CONFIG] Perfil 1P activo: '{self.global_config.get('current_p1_profile')}', 2P activo: '{self.global_config.get('current_p2_profile')}', Modo: '{self.global_config.get('game_mode')}'")

        self._setup_styles()
        self._build_ui()
        self._refresh_audio_devices()

        # Iniciar en modo single con las dos tarjetas en blanco listas para elegir personaje
        self._set_game_mode("single")

        self._start_audio_engine()
        log_debug("[SISTEMA] Motor de audio iniciado y listo para capturar.")
        self._update_ui_loop()

        self.root.bind("<KeyPress>", self._on_global_key_press)
        self.root.bind("<FocusOut>", lambda e: self._refresh_eco_mode())
        self.root.bind("<FocusIn>", lambda e: self._refresh_eco_mode())
        self.root.bind("<Unmap>", lambda e: self._refresh_eco_mode() if e.widget == self.root else None)
        self.root.bind("<Map>", lambda e: self._refresh_eco_mode() if e.widget == self.root else None)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Congruencia entre fotogramas (activada por defecto) y alternado de boca (desactivado por defecto)
        self._apply_congruence_to_all()
        self._apply_mouth_flutter_to_all()

        # Atajos globales para cambiar de personaje (1P / 2P), funcionan aunque estés jugando
        self._hotkey_base = {1: None, 2: None}
        self.hotkey_listener = GlobalHotkeyListener(
            lambda bid: self.root.after(0, lambda b=bid: self._on_hotkey_triggered(b))
        )
        self._refresh_hotkey_bindings()
        self.hotkey_listener.start()

        # Modo ahorro de recursos mientras se transmite a OBS
        self._eco_mode = False

        # Receptor local de alertas de Twitch (cola por jugador)
        self._alert_queues = {1: [], 2: []}
        self._alert_active = {1: False, 2: False}
        self._alert_restore = {1: None, 2: None}
        self._alert_timer = {1: None, 2: None}
        self.twitch_alert_server = TwitchAlertServer(
            lambda payload: self.root.after(0, lambda p=payload: self._handle_twitch_alert(p))
        )
        self._sync_twitch_alert_server()
        self._refresh_experimental_buttons()

    def _setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.style.configure(".", background="#DFE5EE", foreground="#1A222C", font=("Segoe UI", 9))
        self.style.configure("TLabel", background="#DFE5EE", foreground="#1A222C")
        self.style.configure("White.TLabel", background="#FFFFFF", foreground="#1A222C")
        self.style.configure("WhiteTip.TLabel", background="#FFFFFF", foreground="#5D6D82", font=("Segoe UI", 8))

        self.style.configure(
            "DSButton.TButton",
            font=("Segoe UI", 9, "bold"),
            background="#FFFFFF",
            foreground="#1A222C",
            borderwidth=1,
            relief="solid"
        )
        self.style.map(
            "DSButton.TButton",
            background=[("active", "#EBF2FA"), ("pressed", "#D3E0F0")],
            foreground=[("active", "#101620")]
        )

        self.style.configure(
            "DSBlue.TButton",
            font=("Segoe UI", 9, "bold"),
            background="#3671C6",
            foreground="#FFFFFF",
            borderwidth=1,
            relief="solid"
        )
        self.style.map(
            "DSBlue.TButton",
            background=[("active", "#4885DB"), ("pressed", "#285FA8")]
        )

        self.style.configure(
            "DSSend.TButton",
            font=("Segoe UI", 11, "bold"),
            background="#E45B47",
            foreground="#FFFFFF",
            borderwidth=2,
            relief="solid"
        )
        self.style.map(
            "DSSend.TButton",
            background=[("active", "#F06E5C"), ("pressed", "#C74230")]
        )

        self.style.configure(
            "DSRedMini.TButton",
            font=("Segoe UI", 8, "bold"),
            background="#E45B47",
            foreground="#FFFFFF",
            borderwidth=1,
            relief="solid"
        )
        self.style.map(
            "DSRedMini.TButton",
            background=[("active", "#F06E5C"), ("pressed", "#C74230")]
        )

        self.style.configure(
            "DSArrow.TButton",
            font=("Segoe UI", 12, "bold"),
            background="#FFFFFF",
            foreground="#1E293B",
            borderwidth=1,
            relief="solid"
        )
        self.style.map(
            "DSArrow.TButton",
            background=[("active", "#E0F2FE"), ("pressed", "#BAE6FD")],
            foreground=[("active", "#0284C7")]
        )

        self.style.configure(
            "DSGearBlue.TButton",
            font=("Segoe UI", 10, "bold"),
            background="#3671C6",
            foreground="#FFFFFF",
            borderwidth=2,
            relief="solid",
            padding=(8, 8)
        )
        self.style.map(
            "DSGearBlue.TButton",
            background=[("active", "#2563EB"), ("pressed", "#1D4ED8")]
        )

        self.style.configure(
            "DSGearRed.TButton",
            font=("Segoe UI", 10, "bold"),
            background="#E45B47",
            foreground="#FFFFFF",
            borderwidth=2,
            relief="solid",
            padding=(8, 8)
        )
        self.style.map(
            "DSGearRed.TButton",
            background=[("active", "#DC2626"), ("pressed", "#B91C1C")]
        )

        self.style.configure(
            "DSBack.TButton",
            font=("Segoe UI", 10, "bold"),
            background="#059669",
            foreground="#FFFFFF",
            borderwidth=2,
            relief="solid",
            padding=(8, 6)
        )
        self.style.map(
            "DSBack.TButton",
            background=[("active", "#10B981"), ("pressed", "#047857")]
        )

        self.style.configure(
            "ModeActive.TButton",
            font=("Segoe UI", 9, "bold"),
            background="#3671C6",
            foreground="#FFFFFF"
        )
        self.style.configure(
            "ModeInactive.TButton",
            font=("Segoe UI", 9),
            background="#FFFFFF",
            foreground="#4A5868"
        )

        self.style.configure("TScale", background="#FFFFFF", troughcolor="#E2E7EE")
        self.style.configure("TCombobox", fieldbackground="#FFFFFF", background="#D4DCE8", foreground="#1A222C")
        self.style.map("TCombobox", fieldbackground=[("readonly", "#FFFFFF")], foreground=[("readonly", "#1A222C")])

    def _build_ui(self):
        # 1. BARRA SUPERIOR DS
        ds_header = tk.Frame(self.root, bg="#3671C6", height=42, padx=14)
        ds_header.pack(fill=tk.X)
        ds_header.pack_propagate(False)

        left_h = tk.Frame(ds_header, bg="#3671C6")
        left_h.pack(side=tk.LEFT, fill=tk.Y)

        tk.Label(
            left_h, text="PNGTUBER DUO", font=("Segoe UI", 11, "bold"),
            bg="#3671C6", fg="#FFFFFF"
        ).pack(side=tk.LEFT, pady=8)

        right_h = tk.Frame(ds_header, bg="#3671C6")
        right_h.pack(side=tk.RIGHT, fill=tk.Y)

        self.clock_lbl = tk.Label(right_h, text="🕒 12:00", font=("Segoe UI", 9, "bold"), bg="#3671C6", fg="#FFFFFF")
        self.clock_lbl.pack(side=tk.RIGHT, pady=8, padx=(6, 0))

        # 2. CONTENEDOR PRINCIPAL: LOBBY (CON TARJETAS WORKSHOP ESTILO RIVALS OF AETHER) Y TALLER
        self.screen_container = tk.Frame(self.root, bg="#DFE5EE")
        self.screen_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        self._build_lobby_screen()
        self._build_workshop_screen()

        # 3. CONSOLA INFERIOR DS
        ds_bottom = tk.Frame(self.root, bg="#CBD5E1", height=54, padx=14, pady=6, relief="solid", bd=1)
        ds_bottom.pack(fill=tk.X)

        self.opts_f = tk.Frame(ds_bottom, bg="#CBD5E1")
        self.opts_f.pack(side=tk.LEFT)

        tk.Label(self.opts_f, text="🟩 Fondo OBS (Croma):", font=("Segoe UI", 8, "bold"), bg="#CBD5E1", fg="#1E293B").pack(side=tk.LEFT, padx=(4, 4))
        self.bg_combo = ttk.Combobox(self.opts_f, values=["Verde (#00FF00)", "Azul (#0000FF)", "Magenta (#FF00FF)", "Negro (#000000)"], state="readonly", width=13)
        bg_map = {"#00FF00": 0, "#0000FF": 1, "#FF00FF": 2, "#000000": 3}
        self.bg_combo.current(bg_map.get(self.global_config.get("bg_color"), 0))
        self.bg_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.bg_combo.bind("<<ComboboxSelected>>", self._on_bg_color_changed)

        self.bounce_var = tk.BooleanVar(value=self.global_config.get("bounce_enabled", True))
        self.squash_var = tk.BooleanVar(value=self.global_config.get("squash_enabled", True))
        self.hysteresis_var = tk.BooleanVar(value=self.global_config.get("hysteresis_enabled", False))
        if hasattr(self, "p1_live_avatar"):
            self.p1_live_avatar.squash_enabled = self.squash_var.get()
        if hasattr(self, "p2_live_avatar"):
            self.p2_live_avatar.squash_enabled = self.squash_var.get()
        if hasattr(self, "w_live_avatar"):
            self.w_live_avatar.squash_enabled = self.squash_var.get()

        self.btn_open = ttk.Button(
            ds_bottom, text="Abrir avatares",
            style="DSSend.TButton", command=self.toggle_avatar_windows
        )
        self.btn_open.pack(side=tk.RIGHT, padx=4)

        self.btn_workshop_accept = tk.Button(
            ds_bottom, text="✅ Aceptar",
            font=("Segoe UI", 10, "bold"),
            bg="#16A34A", fg="#FFFFFF",
            activebackground="#15803D", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=18, pady=2, cursor="hand2",
            command=lambda: self._switch_screen("lobby")
        )

        # Iniciar directamente en el Lobby con las 2 tarjetas en blanco listas para elegir personaje
        self._switch_screen("lobby")

        self._update_clock()

    # =========================================================================
    # --- PANTALLA PRINCIPAL: LOBBY CON TARJETAS ESTILO RIVALS OF AETHER ---
    # =========================================================================
    def _build_lobby_screen(self):
        self.lobby_frame = tk.Frame(self.screen_container, bg="#DFE5EE")
        self.roster_thumbs_p1 = []
        self.roster_thumbs_p2 = []
        self.card_list_thumbs = {1: [], 2: []}
        self._dragging_meter_target = {1: "voice", 2: "voice"}

        # Estados independientes por tarjeta: "blank" (en blanco), "list" (selector Workshop en la tarjeta), "active" (personaje elegido)
        self.card_view_state = {1: "blank", 2: "blank"}
        self.card_has_selected = {1: False, 2: False}
        self.card_list_page = {1: 0, 2: 0}
        self.card_search_vars = {1: tk.StringVar(value=""), 2: tk.StringVar(value="")}
        self.ITEMS_PER_CARD_PAGE = 4  # 4 personajes por página + fila ALEATORIO (igual que Rivals of Aether)

        # Barra superior del Lobby con botón de Menú estilo videojuego
        sub_banner = tk.Frame(self.lobby_frame, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", pady=5, padx=12)
        sub_banner.pack(fill=tk.X, pady=(0, 8))

        self.btn_lobby_menu = tk.Button(
            sub_banner,
            text="⚙️  MENÚ",
            font=("Segoe UI", 9, "bold"),
            bg="#3671C6", fg="#FFFFFF",
            activebackground="#25559C", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=14, pady=2, cursor="hand2",
            command=self._open_settings_menu
        )
        self.btn_lobby_menu.pack(side=tk.LEFT)

        self.btn_lobby_hotkeys = tk.Button(
            sub_banner,
            text="⌨️  ATAJOS",
            font=("Segoe UI", 9, "bold"),
            bg="#F59E0B", fg="#1E293B",
            activebackground="#D97706", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=14, pady=2, cursor="hand2",
            command=self._open_hotkeys_dialog
        )
        self.btn_lobby_hotkeys.pack(side=tk.LEFT, padx=(8, 0))

        self.btn_lobby_twitch = tk.Button(
            sub_banner,
            text="🟣  ALERTAS TWITCH",
            font=("Segoe UI", 9, "bold"),
            bg="#9146FF", fg="#FFFFFF",
            activebackground="#772CE8", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=12, pady=2, cursor="hand2",
            command=self._open_twitch_alerts_dialog
        )
        self.btn_lobby_remote = tk.Button(
            sub_banner,
            text="📱  CONTROL REMOTO",
            font=("Segoe UI", 9, "bold"),
            bg="#0EA5E9", fg="#FFFFFF",
            activebackground="#0284C7", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=12, pady=2, cursor="hand2",
            command=self._open_remote_control_placeholder
        )
        self.btn_lobby_4p = tk.Button(
            sub_banner,
            text="👥  4 PLAYERS MODE",
            font=("Segoe UI", 9, "bold"),
            bg="#6366F1", fg="#FFFFFF",
            activebackground="#4F46E5", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=12, pady=2, cursor="hand2",
            command=self._open_4p_mode_placeholder
        )

        self.eco_status_lbl = tk.Label(
            sub_banner,
            text="",
            font=("Segoe UI", 8, "bold"),
            bg="#FFFFFF", fg="#15803D"
        )
        self.eco_status_lbl.pack(side=tk.RIGHT)

        booths_f = tk.Frame(self.lobby_frame, bg="#DFE5EE")
        booths_f.pack(fill=tk.BOTH, expand=True)

        # =====================================================================
        # ------------------- TARJETA JUGADOR 1 (IZQUIERDA) -------------------
        # =====================================================================
        self.p1_booth = tk.Frame(booths_f, bg="#FFFFFF", highlightthickness=3, highlightbackground="#242E3B")
        self.p1_booth.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        self.p1_h = tk.Frame(self.p1_booth, bg="#3671C6", height=36, padx=10)
        self.p1_h.pack(fill=tk.X)
        self.p1_h.pack_propagate(False)

        # Badge estilo [ HMN / 1P ] de Rivals of Aether
        self.p1_tag_badge = tk.Label(
            self.p1_h, text=" 1P MIC ", font=("Segoe UI", 9, "bold"),
            bg="#FACC15", fg="#1E293B", relief="solid", bd=1, padx=4, pady=1
        )
        self.p1_tag_badge.pack(side=tk.LEFT, pady=5, padx=(0, 8))

        self.p1_title_lbl = tk.Label(
            self.p1_h, text="JUGADOR 1 (Sin personaje)",
            font=("Segoe UI", 9, "bold"), bg="#3671C6", fg="#FFFFFF"
        )
        self.p1_title_lbl.pack(side=tk.LEFT, pady=6)

        self.p1_clear_btn = ttk.Button(
            self.p1_h, text="✖ Quitar", style="DSRedMini.TButton",
            command=lambda: self._set_card_view(1, "blank")
        )

        self.p1_mute_btn = tk.Button(
            self.p1_h, text="🔇 Silenciar", font=("Segoe UI", 8, "bold"),
            bg="#1E293B", fg="#F8FAFC", activebackground="#334155", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=6, pady=1, cursor="hand2",
            command=lambda: self._toggle_player_mute(1)
        )

        self.p1_voice_badge = tk.Label(
            self.p1_h, text="🤫 En silencio", font=("Segoe UI", 8, "bold"),
            bg="#25559C", fg="#E2E8F0", padx=8, pady=2
        )

        # --- 1A. CUERPO EN BLANCO (TARJETA EN BLANCO 1P AL INICIAR) ---
        self.p1_blank_body = tk.Frame(self.p1_booth, bg="#F8FAFC", padx=20, pady=24, cursor="hand2")

        p1_blank_card = tk.Frame(
            self.p1_blank_body, bg="#FFFFFF", highlightthickness=2,
            highlightbackground="#94A3B8", padx=20, pady=28, cursor="hand2"
        )
        p1_blank_card.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        p1_b_icon = tk.Label(p1_blank_card, text="👤❔", font=("Segoe UI", 46), bg="#FFFFFF", fg="#3671C6", cursor="hand2")
        p1_b_icon.pack(pady=(24, 10))

        p1_b_title = tk.Label(
            p1_blank_card, text="TARJETA 1P EN BLANCO",
            font=("Segoe UI", 13, "bold"), bg="#FFFFFF", fg="#1E293B", cursor="hand2"
        )
        p1_b_title.pack(pady=(0, 6))

        p1_b_desc = tk.Label(
            p1_blank_card,
            text="Haz clic en el botón para abrir la lista de tus carpetas\nde personajes aquí mismo dentro de esta tarjeta.",
            font=("Segoe UI", 9), bg="#FFFFFF", fg="#64748B", justify=tk.CENTER, cursor="hand2"
        )
        p1_b_desc.pack(pady=(0, 18))

        p1_b_btn = ttk.Button(
            p1_blank_card, text="📁 ELEGIR PERSONAJE (ABRIR LISTA AQUÍ)",
            style="DSGearBlue.TButton", command=lambda: self._open_card_character_list(1)
        )
        p1_b_btn.pack(ipadx=12, ipady=4)

        for w in (self.p1_blank_body, p1_blank_card, p1_b_icon, p1_b_title, p1_b_desc):
            w.bind("<Button-1>", lambda e: self._open_card_character_list(1))

        # --- 1B. CUERPO LISTA WORKSHOP DENTRO DE LA TARJETA 1P (ESTILO RIVALS OF AETHER) ---
        self.p1_list_body = tk.Frame(self.p1_booth, bg="#334155", padx=10, pady=8)
        self._build_in_card_workshop_list_ui(player_num=1, parent_frame=self.p1_list_body, accent_hex="#3671C6")

        # --- 1C. CUERPO ACTIVO (PERSONAJE SELECCIONADO EN TARJETA 1P) ---
        self.p1_active_body = tk.Frame(self.p1_booth, bg="#FFFFFF", padx=12, pady=8)

        # Marco de Retrato estilo Rivals of Aether (Avatar + Barra oscura de Nombre con botón [+])
        p1_portrait_card = tk.Frame(self.p1_active_body, bg="#1E293B", highlightthickness=2, highlightbackground="#0F172A")
        p1_portrait_card.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        p1_avatar_box = tk.Frame(p1_portrait_card, bg="#F8FBFF", padx=0, pady=0)
        p1_avatar_box.pack(fill=tk.BOTH, expand=True)

        self.p1_live_avatar = LiveAvatarPreview(
            p1_avatar_box, size=(280, 280), bg="#F8FBFF", border_color="#1E293B", accent_color="#3671C6"
        )
        self.p1_live_avatar.bounce_enabled = self.global_config.get("bounce_enabled", True)
        self.p1_live_avatar.pack(fill=tk.BOTH, expand=True)

        # Franja oscura inferior con el NOMBRE DEL PERSONAJE
        p1_name_bar = tk.Frame(p1_portrait_card, bg="#0F172A", height=38, padx=10, pady=4)
        p1_name_bar.pack(fill=tk.X, side=tk.BOTTOM)
        p1_name_bar.pack_propagate(False)

        curr_p1 = self.global_config.get("current_p1_profile", "Gatito Azul")
        self.p1_name_lbl = tk.Label(
            p1_name_bar, text=curr_p1.upper(), font=("Consolas", 13, "bold"),
            bg="#0F172A", fg="#FFFFFF"
        )
        self.p1_name_lbl.pack(fill=tk.BOTH, expand=True)

        # Vúmetro INTERACTIVO en el Lobby (Clic / Arrastrar para umbrales de Voz y Grito + Auto-Calibración)
        meter_f1 = tk.Frame(self.p1_active_body, bg="#FFFFFF")
        meter_f1.pack(fill=tk.X, pady=(2, 4))

        m1_top = tk.Frame(meter_f1, bg="#FFFFFF")
        m1_top.pack(fill=tk.X)
        tk.Label(
            m1_top, text="🎤 Nivel y Umbral:",
            font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#475569", anchor=tk.W
        ).pack(side=tk.LEFT)

        self.p1_auto_cal_btn = tk.Button(
            m1_top, text="🪄 Auto (3s)", font=("Segoe UI", 7, "bold"),
            bg="#E0F2FE", fg="#0369A1", activebackground="#3671C6", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=5, pady=0, cursor="hand2",
            command=lambda: self._start_auto_calibration(1)
        )
        self.p1_auto_cal_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.p1_meter_info_lbl = tk.Label(
            m1_top,
            text=f"🤫 Voz: {int(self.p1_data.get('mic_threshold', 20))}%  |  💥 Grito: {int(self.p1_data.get('scream_threshold', 55))}%",
            font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#0369A1", anchor=tk.E
        )
        self.p1_meter_info_lbl.pack(side=tk.RIGHT)

        self.p1_mini_meter = tk.Canvas(
            meter_f1, height=22, bg="#E2E8F0", highlightthickness=1, highlightbackground="#64748B", cursor="hand2"
        )
        self.p1_mini_meter.pack(fill=tk.X, pady=(2, 2))
        self.p1_mini_meter.bind("<Button-1>", lambda e: self._on_lobby_meter_press(1, e, force_mode=None))
        self.p1_mini_meter.bind("<B1-Motion>", lambda e: self._on_lobby_meter_drag(1, e))
        self.p1_mini_meter.bind("<ButtonRelease-1>", lambda e: self._on_lobby_meter_release(1, e))
        self.p1_mini_meter.bind("<Button-3>", lambda e: self._on_lobby_meter_press(1, e, force_mode="scream"))
        self.p1_mini_meter.bind("<B3-Motion>", lambda e: self._on_lobby_meter_drag(1, e))
        self.p1_mini_meter.bind("<ButtonRelease-3>", lambda e: self._on_lobby_meter_release(1, e))

        # Selector rápido de Micrófono en el Lobby + Botón Refrescar 🔄
        dev_f1 = tk.Frame(self.p1_active_body, bg="#FFFFFF")
        dev_f1.pack(fill=tk.X, pady=(2, 6))
        tk.Label(dev_f1, text="🎙️ Mic:", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#475569").pack(side=tk.LEFT, padx=(0, 4))
        self.p1_lobby_dev_combo = ttk.Combobox(dev_f1, state="readonly", font=("Segoe UI", 8))
        self.p1_lobby_dev_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.p1_lobby_dev_combo.bind("<<ComboboxSelected>>", self._on_p1_lobby_device_changed)
        ttk.Button(
            dev_f1, text="🔄", width=3, style="DSButton.TButton",
            command=self._manual_refresh_devices
        ).pack(side=tk.RIGHT)

        # Fila inferior de botones estilo Rivals of Aether (Verde: Cambiar Personaje | Morado: Elementos | Amarillo: Expresiones)
        p1_rivals_btns = tk.Frame(self.p1_active_body, bg="#FFFFFF")
        p1_rivals_btns.pack(fill=tk.X, pady=(2, 0))

        tk.Button(
            p1_rivals_btns, text="👤 Cambiar personaje", font=("Segoe UI", 9, "bold"),
            bg="#16A34A", fg="#FFFFFF", activebackground="#15803D", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=8, pady=5, cursor="hand2",
            command=lambda: self._open_card_character_list(1)
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))

        tk.Button(
            p1_rivals_btns, text="🎒 Accesorios", font=("Segoe UI", 9, "bold"),
            bg="#8B5CF6", fg="#FFFFFF", activebackground="#7C3AED", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=8, pady=5, cursor="hand2",
            command=lambda: self._open_props_manager_dialog(1)
        ).pack(side=tk.LEFT, padx=3)

        tk.Button(
            p1_rivals_btns, text="🎞️ Fotogramas", font=("Segoe UI", 9, "bold"),
            bg="#EAB308", fg="#1E293B", activebackground="#CA8A04", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=8, pady=5, cursor="hand2",
            command=lambda: self._open_workshop(1)
        ).pack(side=tk.RIGHT, padx=(3, 0))

        # =====================================================================
        # ------------------- TARJETA JUGADOR 2 (DERECHA) ---------------------
        # =====================================================================
        self.p2_booth = tk.Frame(booths_f, bg="#FFFFFF", highlightthickness=3, highlightbackground="#242E3B")
        self.p2_booth.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(6, 0))

        self.p2_h = tk.Frame(self.p2_booth, bg="#E45B47", height=36, padx=10)
        self.p2_h.pack(fill=tk.X)
        self.p2_h.pack_propagate(False)

        self.p2_tag_badge = tk.Label(
            self.p2_h, text=" 2P DISC ", font=("Segoe UI", 9, "bold"),
            bg="#FACC15", fg="#1E293B", relief="solid", bd=1, padx=4, pady=1
        )
        self.p2_tag_badge.pack(side=tk.LEFT, pady=5, padx=(0, 8))

        self.p2_title_lbl = tk.Label(
            self.p2_h, text="JUGADOR 2 (Sin personaje)",
            font=("Segoe UI", 9, "bold"), bg="#E45B47", fg="#FFFFFF"
        )
        self.p2_title_lbl.pack(side=tk.LEFT, pady=6)

        self.p2_remove_btn = ttk.Button(
            self.p2_h, text="✖ Quitar", style="DSRedMini.TButton",
            command=lambda: self._set_card_view(2, "blank")
        )

        self.p2_mute_btn = tk.Button(
            self.p2_h, text="🔇 Silenciar", font=("Segoe UI", 8, "bold"),
            bg="#1E293B", fg="#F8FAFC", activebackground="#334155", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=6, pady=1, cursor="hand2",
            command=lambda: self._toggle_player_mute(2)
        )

        self.p2_voice_badge = tk.Label(
            self.p2_h, text="🤫 En silencio", font=("Segoe UI", 8, "bold"),
            bg="#B83F2E", fg="#E2E8F0", padx=8, pady=2
        )

        # --- 2A. CUERPO EN BLANCO (TARJETA EN BLANCO 2P AL INICIAR O DESACTIVAR) ---
        self.p2_empty_body = tk.Frame(self.p2_booth, bg="#F8FAFC", padx=20, pady=24, cursor="hand2")

        p2_blank_card = tk.Frame(
            self.p2_empty_body, bg="#FFFFFF", highlightthickness=2,
            highlightbackground="#94A3B8", padx=20, pady=28, cursor="hand2"
        )
        p2_blank_card.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        p2_b_icon = tk.Label(p2_blank_card, text="🎧❔", font=("Segoe UI", 46), bg="#FFFFFF", fg="#E45B47", cursor="hand2")
        p2_b_icon.pack(pady=(24, 10))

        p2_b_title = tk.Label(
            p2_blank_card, text="TARJETA 2P EN BLANCO",
            font=("Segoe UI", 13, "bold"), bg="#FFFFFF", fg="#1E293B", cursor="hand2"
        )
        p2_b_title.pack(pady=(0, 6))

        p2_b_desc = tk.Label(
            p2_blank_card,
            text="Haz clic en el botón para activar a tu amigo de Discord\ny elegir su personaje aquí mismo dentro de su tarjeta.",
            font=("Segoe UI", 9), bg="#FFFFFF", fg="#64748B", justify=tk.CENTER, cursor="hand2"
        )
        p2_b_desc.pack(pady=(0, 18))

        p2_b_btn = ttk.Button(
            p2_blank_card, text="📁 ELEGIR PERSONAJE 2P (ABRIR LISTA AQUÍ)",
            style="DSGearRed.TButton", command=lambda: self._open_card_character_list(2)
        )
        p2_b_btn.pack(ipadx=12, ipady=4)

        for widget in (self.p2_empty_body, p2_blank_card, p2_b_icon, p2_b_title, p2_b_desc):
            widget.bind("<Button-1>", lambda e: self._open_card_character_list(2))

        # --- 2B. CUERPO LISTA WORKSHOP DENTRO DE LA TARJETA 2P (ESTILO RIVALS OF AETHER) ---
        self.p2_list_body = tk.Frame(self.p2_booth, bg="#334155", padx=10, pady=8)
        self._build_in_card_workshop_list_ui(player_num=2, parent_frame=self.p2_list_body, accent_hex="#E45B47")

        # --- 2C. CUERPO ACTIVO JUGADOR 2 (CUANDO TIENE PERSONAJE ELEGIDO) ---
        self.p2_active_body = tk.Frame(self.p2_booth, bg="#FFFFFF", padx=12, pady=8)

        p2_portrait_card = tk.Frame(self.p2_active_body, bg="#1E293B", highlightthickness=2, highlightbackground="#0F172A")
        p2_portrait_card.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        p2_avatar_box = tk.Frame(p2_portrait_card, bg="#FFFDF9", padx=0, pady=0)
        p2_avatar_box.pack(fill=tk.BOTH, expand=True)

        self.p2_live_avatar = LiveAvatarPreview(
            p2_avatar_box, size=(280, 280), bg="#FFFDF9", border_color="#1E293B", accent_color="#E45B47"
        )
        self.p2_live_avatar.bounce_enabled = self.global_config.get("bounce_enabled", True)
        self.p2_live_avatar.pack(fill=tk.BOTH, expand=True)

        # Franja oscura inferior con el NOMBRE DEL PERSONAJE 2P
        p2_name_bar = tk.Frame(p2_portrait_card, bg="#0F172A", height=38, padx=10, pady=4)
        p2_name_bar.pack(fill=tk.X, side=tk.BOTTOM)
        p2_name_bar.pack_propagate(False)

        curr_p2 = self.global_config.get("current_p2_profile", "Osito Discord")
        self.p2_name_lbl = tk.Label(
            p2_name_bar, text=curr_p2.upper(), font=("Consolas", 13, "bold"),
            bg="#0F172A", fg="#FFFFFF"
        )
        self.p2_name_lbl.pack(fill=tk.BOTH, expand=True)

        # Vúmetro INTERACTIVO de Discord + Auto-Calibración
        meter_f2 = tk.Frame(self.p2_active_body, bg="#FFFFFF")
        meter_f2.pack(fill=tk.X, pady=(2, 4))

        m2_top = tk.Frame(meter_f2, bg="#FFFFFF")
        m2_top.pack(fill=tk.X)
        tk.Label(
            m2_top, text="🎧 Nivel y Umbral:",
            font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#475569", anchor=tk.W
        ).pack(side=tk.LEFT)

        self.p2_auto_cal_btn = tk.Button(
            m2_top, text="🪄 Auto (3s)", font=("Segoe UI", 7, "bold"),
            bg="#FFEDD5", fg="#C2410C", activebackground="#E45B47", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=5, pady=0, cursor="hand2",
            command=lambda: self._start_auto_calibration(2)
        )
        self.p2_auto_cal_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.p2_meter_info_lbl = tk.Label(
            m2_top,
            text=f"🤫 Voz: {int(self.p2_data.get('discord_threshold', 25))}%  |  💥 Grito: {int(self.p2_data.get('scream_threshold', 55))}%",
            font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#C2410C", anchor=tk.E
        )
        self.p2_meter_info_lbl.pack(side=tk.RIGHT)

        self.p2_mini_meter = tk.Canvas(
            meter_f2, height=22, bg="#E2E8F0", highlightthickness=1, highlightbackground="#64748B", cursor="hand2"
        )
        self.p2_mini_meter.pack(fill=tk.X, pady=(2, 2))
        self.p2_mini_meter.bind("<Button-1>", lambda e: self._on_lobby_meter_press(2, e, force_mode=None))
        self.p2_mini_meter.bind("<B1-Motion>", lambda e: self._on_lobby_meter_drag(2, e))
        self.p2_mini_meter.bind("<ButtonRelease-1>", lambda e: self._on_lobby_meter_release(2, e))
        self.p2_mini_meter.bind("<Button-3>", lambda e: self._on_lobby_meter_press(2, e, force_mode="scream"))
        self.p2_mini_meter.bind("<B3-Motion>", lambda e: self._on_lobby_meter_drag(2, e))
        self.p2_mini_meter.bind("<ButtonRelease-3>", lambda e: self._on_lobby_meter_release(2, e))

        # Selector rápido de Fuente Discord en el Lobby + Botón Refrescar 🔄
        dev_f2 = tk.Frame(self.p2_active_body, bg="#FFFFFF")
        dev_f2.pack(fill=tk.X, pady=(2, 6))
        tk.Label(dev_f2, text="🔊 Fuente:", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#475569").pack(side=tk.LEFT, padx=(0, 4))
        self.p2_lobby_dev_combo = ttk.Combobox(dev_f2, state="readonly", font=("Segoe UI", 8))
        self.p2_lobby_dev_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.p2_lobby_dev_combo.bind("<<ComboboxSelected>>", self._on_p2_lobby_device_changed)
        ttk.Button(
            dev_f2, text="🔄", width=3, style="DSButton.TButton",
            command=self._manual_refresh_devices
        ).pack(side=tk.RIGHT)

        # Fila inferior de botones estilo Rivals of Aether para 2P
        p2_rivals_btns = tk.Frame(self.p2_active_body, bg="#FFFFFF")
        p2_rivals_btns.pack(fill=tk.X, pady=(2, 0))

        tk.Button(
            p2_rivals_btns, text="👤 Cambiar personaje", font=("Segoe UI", 9, "bold"),
            bg="#16A34A", fg="#FFFFFF", activebackground="#15803D", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=8, pady=5, cursor="hand2",
            command=lambda: self._open_card_character_list(2)
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))

        tk.Button(
            p2_rivals_btns, text="🎒 Accesorios", font=("Segoe UI", 9, "bold"),
            bg="#8B5CF6", fg="#FFFFFF", activebackground="#7C3AED", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=8, pady=5, cursor="hand2",
            command=lambda: self._open_props_manager_dialog(2)
        ).pack(side=tk.LEFT, padx=3)

        tk.Button(
            p2_rivals_btns, text="🎞️ Fotogramas", font=("Segoe UI", 9, "bold"),
            bg="#EAB308", fg="#1E293B", activebackground="#CA8A04", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=8, pady=5, cursor="hand2",
            command=lambda: self._open_workshop(2)
        ).pack(side=tk.RIGHT, padx=(3, 0))

        self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
        self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
        self._set_card_view(1, "blank")
        self._set_card_view(2, "blank")

    # =========================================================================
    # --- LISTA WORKSHOP DENTRO DE CADA TARJETA (ESTILO RIVALS OF AETHER) ---
    # =========================================================================
    def _build_in_card_workshop_list_ui(self, player_num, parent_frame, accent_hex):
        # 1. Pestaña superior de Búsqueda (como [🔍 BACKSPACE] en Rivals of Aether)
        top_tab_row = tk.Frame(parent_frame, bg="#334155")
        top_tab_row.pack(fill=tk.X, pady=(0, 4))

        search_tab = tk.Frame(top_tab_row, bg="#0F172A", highlightthickness=2, highlightbackground="#64748B", padx=8, pady=4)
        search_tab.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(search_tab, text="🔍", font=("Segoe UI", 9, "bold"), bg="#0F172A", fg="#F8FAFC").pack(side=tk.LEFT, padx=(0, 4))

        sv = self.card_search_vars[player_num]
        search_entry = tk.Entry(
            search_tab, textvariable=sv, font=("Consolas", 10, "bold"),
            bg="#1E293B", fg="#FFFFFF", insertbackground="#FFFFFF", relief="flat"
        )
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        search_entry.bind("<KeyRelease>", lambda e, p=player_num: self._on_card_search_changed(p))

        clear_s_btn = tk.Button(
            search_tab, text="⌫", font=("Segoe UI", 8, "bold"),
            bg="#1E293B", fg="#94A3B8", activebackground="#334155", activeforeground="#FFFFFF",
            relief="flat", bd=0, cursor="hand2",
            command=lambda p=player_num: self._clear_card_search(p)
        )
        clear_s_btn.pack(side=tk.RIGHT, padx=(2, 0))

        close_list_btn = tk.Button(
            top_tab_row, text="✖ Volver", font=("Segoe UI", 8, "bold"),
            bg="#1E293B", fg="#E2E8F0", activebackground="#EF4444", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=8, pady=4, cursor="hand2",
            command=lambda p=player_num: self._close_card_character_list(p)
        )
        close_list_btn.pack(side=tk.RIGHT, padx=(6, 0))

        # 2. Contenedor negro desplazable de filas de personajes y carpetas (estilo capas Procreate)
        rows_outer = tk.Frame(parent_frame, bg="#090D16", highlightthickness=2, highlightbackground="#64748B", padx=6, pady=6)
        rows_outer.pack(fill=tk.BOTH, expand=True)

        rows_sf = ScrollableFrame(rows_outer, bg="#090D16")
        rows_sf.pack(fill=tk.BOTH, expand=True)
        setattr(self, f"p{player_num}_rows_sf", rows_sf)
        setattr(self, f"p{player_num}_rows_container", rows_sf.content)

        # 3. Barra inferior de la tarjeta: [➕ Nuevo Personaje]  y ayuda de capas
        footer_bar = tk.Frame(parent_frame, bg="#334155", pady=4)
        footer_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(6, 0))

        create_cmd = self._create_p1_profile_dialog if player_num == 1 else self._create_p2_profile_dialog
        tk.Button(
            footer_bar, text="➕ Nuevo Personaje", font=("Segoe UI", 8, "bold"),
            bg="#FACC15", fg="#0F172A", activebackground="#EAB308",
            relief="solid", bd=1, padx=8, pady=3, cursor="hand2",
            command=create_cmd
        ).pack(side=tk.LEFT)

        tk.Label(
            footer_bar,
            text="💡 Arrastra para ordenar • Mantén sobre otro = Carpeta",
            font=("Segoe UI", 7, "bold"), bg="#334155", fg="#CBD5E1"
        ).pack(side=tk.RIGHT, padx=(6, 2))

    def _set_card_view(self, player_num, view_state):
        """Cambia la vista ÚNICAMENTE dentro de la tarjeta del jugador indicado ('blank', 'list', 'active')."""
        self.card_view_state[player_num] = view_state

        if player_num == 1:
            self.p1_blank_body.pack_forget()
            self.p1_list_body.pack_forget()
            self.p1_active_body.pack_forget()

            if view_state == "blank":
                self.card_has_selected[1] = False
                self.p1_title_lbl.config(text="JUGADOR 1 (Tarjeta en blanco)")
                self.p1_clear_btn.pack_forget()
                self.p1_mute_btn.pack_forget()
                self.p1_voice_badge.pack_forget()
                self.p1_blank_body.pack(fill=tk.BOTH, expand=True)

                if self.avatar1_window and self.avatar1_window.winfo_exists():
                    try:
                        self.avatar1_window.destroy()
                    except Exception:
                        pass
                    self.avatar1_window = None
                if not (self.avatar2_window and self.avatar2_window.winfo_exists()):
                    if hasattr(self, "btn_open") and self.btn_open:
                        self.btn_open.config(text="🚀 ENVIAR A OBS (Abrir Avatares)", style="DSSend.TButton")
            elif view_state == "list":
                self._scan_disk_character_folders()
                self.p1_title_lbl.config(text="ELIGE PERSONAJE 1P")
                self.p1_voice_badge.pack_forget()
                self.p1_mute_btn.pack_forget()
                self.p1_clear_btn.pack_forget()
                self.p1_list_body.pack(fill=tk.BOTH, expand=True)
                self._render_in_card_workshop_rows(1)
            elif view_state == "active":
                self.card_has_selected[1] = True
                curr_p1 = self.global_config.get("current_p1_profile", "Gatito Azul")
                self.p1_title_lbl.config(text=f"1P: {curr_p1}")
                self.p1_clear_btn.pack(side=tk.RIGHT, pady=4, padx=2)
                self.p1_mute_btn.pack(side=tk.RIGHT, pady=4, padx=2)
                self.p1_voice_badge.pack(side=tk.RIGHT, pady=4, padx=(0, 4))
                self.p1_active_body.pack(fill=tk.BOTH, expand=True)
                self._refresh_p1_card_roster()
                self._sync_mute_buttons()

                # Si OBS ya está abierto para 2P, abrir también 1P
                if self.avatar2_window and self.avatar2_window.winfo_exists():
                    if not (self.avatar1_window and self.avatar1_window.winfo_exists()):
                        self._open_avatar1_window_only()
        else:
            self.p2_empty_body.pack_forget()
            self.p2_list_body.pack_forget()
            self.p2_active_body.pack_forget()

            if view_state == "blank":
                self.card_has_selected[2] = False
                self.p2_title_lbl.config(text="JUGADOR 2 (Tarjeta en blanco)")
                self.p2_remove_btn.pack_forget()
                self.p2_mute_btn.pack_forget()
                self.p2_voice_badge.pack_forget()
                self.p2_empty_body.pack(fill=tk.BOTH, expand=True)

                if self.global_config.get("game_mode") != "single":
                    self.global_config["game_mode"] = "single"
                    self.discord_talking = False
                    self.discord_level = 0.0
                    self.p2_is_screaming = False
                    if getattr(self, "_mode_initialized", False):
                        self._start_audio_engine()
                        self.save_global_config()

                if self.avatar2_window and self.avatar2_window.winfo_exists():
                    try:
                        self.avatar2_window.destroy()
                    except Exception:
                        pass
                    self.avatar2_window = None
                if not (self.avatar1_window and self.avatar1_window.winfo_exists()):
                    if hasattr(self, "btn_open") and self.btn_open:
                        self.btn_open.config(text="🚀 ENVIAR A OBS (Abrir Avatares)", style="DSSend.TButton")
            elif view_state == "list":
                self._scan_disk_character_folders()
                if self.global_config.get("game_mode") == "single":
                    self.global_config["game_mode"] = "coop"
                    self._start_audio_engine()
                self.p2_title_lbl.config(text="ELIGE PERSONAJE 2P")
                self.p2_voice_badge.pack_forget()
                self.p2_mute_btn.pack_forget()
                self.p2_remove_btn.pack(side=tk.RIGHT, pady=4, padx=2)
                self.p2_list_body.pack(fill=tk.BOTH, expand=True)
                self._render_in_card_workshop_rows(2)
            elif view_state == "active":
                self.card_has_selected[2] = True
                if self.global_config.get("game_mode") == "single":
                    self.global_config["game_mode"] = "coop"
                    self._start_audio_engine()
                    self.save_global_config()
                curr_p2 = self.global_config.get("current_p2_profile", "Osito Discord")
                self.p2_title_lbl.config(text=f"2P: {curr_p2}")
                self.p2_remove_btn.pack(side=tk.RIGHT, pady=4, padx=2)
                self.p2_mute_btn.pack(side=tk.RIGHT, pady=4, padx=2)
                self.p2_voice_badge.pack(side=tk.RIGHT, pady=4, padx=(0, 4))
                self.p2_active_body.pack(fill=tk.BOTH, expand=True)
                self._refresh_p2_card_roster()
                self._sync_mute_buttons()

                # Si OBS ya está abierto para 1P, abrir también 2P
                if self.avatar1_window and self.avatar1_window.winfo_exists():
                    if not (self.avatar2_window and self.avatar2_window.winfo_exists()):
                        self._open_avatar2_window_only()

        self._refresh_eco_mode()

    def _open_card_character_list(self, player_num):
        log_debug(f"[WORKSHOP CARD] 📋 Abriendo lista de personajes dentro de la Tarjeta {player_num}P")
        self._set_card_view(player_num, "list")

    def _close_card_character_list(self, player_num):
        if self.card_has_selected.get(player_num, False):
            self._set_card_view(player_num, "active")
        else:
            self._set_card_view(player_num, "blank")

    def _on_card_search_changed(self, player_num):
        self.card_list_page[player_num] = 0
        self._render_in_card_workshop_rows(player_num)

    def _clear_card_search(self, player_num):
        self.card_search_vars[player_num].set("")
        self.card_list_page[player_num] = 0
        self._render_in_card_workshop_rows(player_num)

    def _change_card_list_page(self, player_num, delta):
        keys = self._get_filtered_characters_for_card(player_num)
        total_pages = max(1, (len(keys) + self.ITEMS_PER_CARD_PAGE - 1) // self.ITEMS_PER_CARD_PAGE)
        self.card_list_page[player_num] = (self.card_list_page[player_num] + delta) % total_pages
        self._render_in_card_workshop_rows(player_num)

    def _get_filtered_characters_for_card(self, player_num):
        profile_key = "player1" if player_num == 1 else "player2"
        all_keys = list(self.profiles.get(profile_key, {}).keys())
        q = self.card_search_vars[player_num].get().strip().lower()
        if not q:
            return all_keys
        return [k for k in all_keys if q in k.lower()]

    def _pick_random_character_in_card(self, player_num):
        profile_key = "player1" if player_num == 1 else "player2"
        all_keys = list(self.profiles.get(profile_key, {}).keys())
        if not all_keys:
            return
        chosen = random.choice(all_keys)
        log_debug(f"[WORKSHOP CARD] 🎲 {player_num}P eligió ALEATORIO -> '{chosen}'")
        self._choose_character_from_card_list(player_num, chosen)

    def _choose_character_from_card_list(self, player_num, name):
        if player_num == 1:
            self._select_p1_character(name)
            self._set_card_view(1, "active")
        else:
            if self.global_config.get("game_mode") == "single":
                self._set_game_mode("coop")
            self._select_p2_character(name)
            self._set_card_view(2, "active")

    def _sync_character_layout(self):
        """Sincroniza global_config['character_layout'] con los personajes existentes en profiles['player1']."""
        all_names = list(self.profiles.get("player1", {}).keys())
        all_set = set(all_names)
        raw = self.global_config.get("character_layout") or []
        clean = []
        seen = set()

        for entry in raw:
            if not isinstance(entry, dict):
                continue
            etype = entry.get("type")
            if etype == "char":
                n = entry.get("name")
                if n in all_set and n not in seen:
                    clean.append({"type": "char", "name": n})
                    seen.add(n)
            elif etype == "folder":
                f_items = []
                for n in entry.get("items", []) or []:
                    if n in all_set and n not in seen:
                        f_items.append(n)
                        seen.add(n)
                if f_items:
                    clean.append({
                        "type": "folder",
                        "id": entry.get("id") or f"fld_{int(time.time()*1000)}_{len(clean)}",
                        "name": entry.get("name") or "Carpeta",
                        "expanded": bool(entry.get("expanded", True)),
                        "items": f_items,
                    })

        for n in all_names:
            if n not in seen:
                clean.append({"type": "char", "name": n})
                seen.add(n)

        self.global_config["character_layout"] = clean
        return clean

    def _remove_char_from_layout(self, char_name):
        layout = self._sync_character_layout()
        new_layout = []
        for entry in layout:
            if entry["type"] == "char":
                if entry["name"] != char_name:
                    new_layout.append(entry)
            elif entry["type"] == "folder":
                entry["items"] = [x for x in entry["items"] if x != char_name]
                if len(entry["items"]) > 1:
                    new_layout.append(entry)
                elif len(entry["items"]) == 1:
                    # Si queda 1 solo personaje en la carpeta, se disuelve a capa normal
                    new_layout.append({"type": "char", "name": entry["items"][0]})
        self.global_config["character_layout"] = new_layout

    def _refresh_both_card_lists(self):
        for p in (1, 2):
            if self.card_view_state.get(p) == "list":
                self._render_in_card_workshop_rows(p)

    def _toggle_folder_expanded(self, folder_id):
        layout = self._sync_character_layout()
        for entry in layout:
            if entry["type"] == "folder" and entry["id"] == folder_id:
                entry["expanded"] = not entry.get("expanded", True)
                break
        self.save_global_config()
        self._refresh_both_card_lists()

    def _pull_char_out_of_folder(self, char_name):
        layout = self._sync_character_layout()
        # Localizar posición de la carpeta para colocarlo justo debajo
        folder_idx = None
        for idx, entry in enumerate(layout):
            if entry["type"] == "folder" and char_name in entry["items"]:
                folder_idx = idx
                break
        self._remove_char_from_layout(char_name)
        layout = self.global_config["character_layout"]
        insert_at = min(len(layout), (folder_idx + 1) if folder_idx is not None else len(layout))
        layout.insert(insert_at, {"type": "char", "name": char_name})
        self.save_global_config()
        self._refresh_both_card_lists()

    def _on_folder_right_click(self, event, folder_id):
        layout = self._sync_character_layout()
        folder = next((e for e in layout if e["type"] == "folder" and e["id"] == folder_id), None)
        if not folder:
            return
        menu = tk.Menu(
            self.root, tearoff=0,
            bg="#0F172A", fg="#F8FAFC",
            activebackground="#F59E0B", activeforeground="#0F172A",
            font=("Segoe UI", 9, "bold"), bd=1, relief="solid"
        )
        menu.add_command(
            label="✏️ Renombrar carpeta",
            command=lambda: self._rename_layout_folder(folder_id)
        )
        menu.add_command(
            label="📤 Desagrupar carpeta",
            command=lambda: self._ungroup_layout_folder(folder_id)
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _rename_layout_folder(self, folder_id):
        layout = self._sync_character_layout()
        folder = next((e for e in layout if e["type"] == "folder" and e["id"] == folder_id), None)
        if not folder:
            return
        new_name = simpledialog.askstring("Renombrar Carpeta", "Nombre de la carpeta:", initialvalue=folder["name"], parent=self.root)
        if new_name and new_name.strip():
            folder["name"] = new_name.strip()
            self.save_global_config()
            self._refresh_both_card_lists()

    def _ungroup_layout_folder(self, folder_id):
        layout = self._sync_character_layout()
        new_layout = []
        for entry in layout:
            if entry["type"] == "folder" and entry["id"] == folder_id:
                for n in entry["items"]:
                    new_layout.append({"type": "char", "name": n})
            else:
                new_layout.append(entry)
        self.global_config["character_layout"] = new_layout
        self.save_global_config()
        self._refresh_both_card_lists()

    def _render_in_card_workshop_rows(self, player_num):
        container = getattr(self, f"p{player_num}_rows_container", None)
        if not container:
            return

        old_thumbs = list(self.card_list_thumbs.get(player_num, []))
        new_thumbs = []
        for w in container.winfo_children():
            w.destroy()

        layout = self._sync_character_layout()
        q = self.card_search_vars[player_num].get().strip().lower()
        curr_active = self.global_config.get("current_p1_profile" if player_num == 1 else "current_p2_profile", "")
        accent_border = "#38BDF8" if player_num == 1 else "#FB7185"

        # 1. FILA ESPECIAL: [ ? ] ALEATORIO
        rand_row = tk.Frame(
            container, bg="#111827", highlightthickness=2, highlightbackground="#475569",
            padx=8, pady=5, cursor="hand2"
        )
        rand_row.pack(fill=tk.X, pady=(0, 6))

        rand_icon_box = tk.Frame(rand_row, bg="#374151", width=40, height=40, highlightthickness=1, highlightbackground="#64748B", cursor="hand2")
        rand_icon_box.pack(side=tk.LEFT, padx=(0, 10))
        rand_icon_box.pack_propagate(False)

        rand_ic_lbl = tk.Label(rand_icon_box, text="?", font=("Consolas", 18, "bold"), bg="#374151", fg="#FFFFFF", cursor="hand2")
        rand_ic_lbl.pack(fill=tk.BOTH, expand=True)

        rand_txt_lbl = tk.Label(
            rand_row, text="ALEATORIO", font=("Consolas", 12, "bold"),
            bg="#111827", fg="#FFFFFF", anchor=tk.W, cursor="hand2"
        )
        rand_txt_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def on_rand_enter(e):
            rand_row.configure(highlightbackground="#FFFFFF", bg="#1E293B")
            rand_txt_lbl.configure(bg="#1E293B", fg="#FACC15")

        def on_rand_leave(e):
            rand_row.configure(highlightbackground="#475569", bg="#111827")
            rand_txt_lbl.configure(bg="#111827", fg="#FFFFFF")

        for w_r in (rand_row, rand_icon_box, rand_ic_lbl, rand_txt_lbl):
            w_r.bind("<Enter>", on_rand_enter)
            w_r.bind("<Leave>", on_rand_leave)
            w_r.bind("<Button-1>", lambda e, p=player_num: self._pick_random_character_in_card(p))

        # Estado de arrastrar y soltar estilo Procreate
        drop_targets = []  # lista de dicts: {"kind": "char"|"folder", "id": name_or_fid, "folder_id": fid_or_None, "widget": frame, "base_bg": ..., "base_bd": ..., "label": ...}
        drag_state = {
            "active": False, "source_name": None, "start_x": 0, "start_y": 0,
            "pill": None, "hover_key": None, "hold_timer": None, "mode": "reorder",
            "target_info": None
        }

        def reset_highlights():
            for dt in drop_targets:
                dt["widget"].configure(highlightbackground=dt["base_bd"], bg=dt["base_bg"])
                if dt.get("hint_lbl"):
                    dt["hint_lbl"].config(text="")

        def cancel_hold_timer():
            if drag_state["hold_timer"] is not None:
                try:
                    self.root.after_cancel(drag_state["hold_timer"])
                except Exception:
                    pass
                drag_state["hold_timer"] = None

        def find_target_at(x_root, y_root):
            for dt in drop_targets:
                w = dt["widget"]
                if not w.winfo_exists():
                    continue
                wx = w.winfo_rootx()
                wy = w.winfo_rooty()
                ww = w.winfo_width()
                wh = w.winfo_height()
                if wx <= x_root <= wx + ww and wy <= y_root <= wy + wh:
                    rel_y = (y_root - wy) / max(1, wh)
                    return dt, rel_y
            return None, 0.5

        def make_char_row(parent_w, name, folder_id=None):
            char_dict = self.profiles["player1"].get(name, {})
            is_sel = (name == curr_active and self.card_has_selected.get(player_num, False))
            base_bd = accent_border if is_sel else "#334155"
            base_bg = "#172554" if (is_sel and player_num == 1) else ("#450A0A" if (is_sel and player_num == 2) else "#0F172A")

            row_f = tk.Frame(
                parent_w, bg=base_bg, highlightthickness=2, highlightbackground=base_bd,
                padx=8, pady=5, cursor="hand2"
            )
            row_f.pack(fill=tk.X, pady=(0, 5))

            drag_grip = tk.Label(row_f, text="⠿", font=("Segoe UI", 11, "bold"), bg=base_bg, fg="#64748B", cursor="fleur")
            drag_grip.pack(side=tk.LEFT, padx=(0, 6))

            icon_box = tk.Frame(row_f, bg="#374151", width=40, height=40, highlightthickness=1, highlightbackground="#64748B", cursor="hand2")
            icon_box.pack(side=tk.LEFT, padx=(0, 10))
            icon_box.pack_propagate(False)

            thumb = self._get_character_thumbnail(char_dict.get("a1_idle"), size=(36, 36))
            if thumb:
                new_thumbs.append(thumb)
                ic_lbl = tk.Label(icon_box, image=thumb, bg="#374151", cursor="hand2")
            else:
                ic_lbl = tk.Label(icon_box, text="👤", font=("Segoe UI", 15), bg="#374151", fg="#CBD5E1", cursor="hand2")
            ic_lbl.pack(fill=tk.BOTH, expand=True)

            name_lbl = tk.Label(
                row_f, text=name.upper(), font=("Consolas", 11, "bold"),
                bg=base_bg, fg="#FFFFFF", anchor=tk.W, cursor="hand2"
            )
            name_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

            hint_lbl = tk.Label(row_f, text="", font=("Segoe UI", 8, "bold"), bg=base_bg, fg="#FACC15")
            hint_lbl.pack(side=tk.LEFT, padx=(4, 4))

            if folder_id is not None:
                out_btn = tk.Button(
                    row_f, text="📤", font=("Segoe UI", 8, "bold"),
                    bg="#1E293B", fg="#93C5FD", activebackground="#334155",
                    relief="solid", bd=1, padx=4, pady=2, cursor="hand2",
                    command=lambda n=name: self._pull_char_out_of_folder(n)
                )
                out_btn.pack(side=tk.RIGHT, padx=(4, 0))

            wrench_btn = tk.Button(
                row_f, text="🔧", font=("Segoe UI", 8, "bold"),
                bg="#1E293B", fg="#FACC15", activebackground="#EAB308", activeforeground="#0F172A",
                relief="solid", bd=1, padx=5, pady=2, cursor="hand2",
                command=lambda n=name, p=player_num: self._open_character_folder_workshop(n, p)
            )
            wrench_btn.pack(side=tk.RIGHT, padx=(4, 0))

            drop_targets.append({
                "kind": "char", "id": name, "folder_id": folder_id,
                "widget": row_f, "base_bg": base_bg, "base_bd": base_bd, "hint_lbl": hint_lbl
            })

            def on_e(e):
                if not drag_state["active"]:
                    row_f.configure(highlightbackground="#FFFFFF", bg="#1E293B")
                    name_lbl.configure(bg="#1E293B", fg="#38BDF8" if player_num == 1 else "#FCA5A5")
                    drag_grip.configure(bg="#1E293B")
                    hint_lbl.configure(bg="#1E293B")

            def on_l(e):
                if not drag_state["active"]:
                    row_f.configure(highlightbackground=base_bd, bg=base_bg)
                    name_lbl.configure(bg=base_bg, fg="#FFFFFF")
                    drag_grip.configure(bg=base_bg)
                    hint_lbl.configure(bg=base_bg)

            def on_press(e):
                drag_state["active"] = False
                drag_state["source_name"] = name
                drag_state["start_x"] = e.x_root
                drag_state["start_y"] = e.y_root
                drag_state["mode"] = "reorder"
                drag_state["hover_key"] = None
                drag_state["target_info"] = None

            def on_motion(e):
                if drag_state["source_name"] != name:
                    return
                if not drag_state["active"]:
                    if abs(e.x_root - drag_state["start_x"]) + abs(e.y_root - drag_state["start_y"]) < 7:
                        return
                    drag_state["active"] = True
                    pill = tk.Toplevel(self.root)
                    pill.overrideredirect(True)
                    pill.attributes("-topmost", True)
                    pill.configure(bg="#FACC15", padx=2, pady=2)
                    tk.Label(
                        pill, text=f"⠿  {name}", font=("Consolas", 10, "bold"),
                        bg="#0F172A", fg="#FACC15", padx=10, pady=4
                    ).pack()
                    drag_state["pill"] = pill

                if drag_state["pill"]:
                    drag_state["pill"].geometry(f"+{e.x_root + 12}+{e.y_root + 12}")

                dt, rel_y = find_target_at(e.x_root, e.y_root)
                reset_highlights()

                if not dt or (dt["kind"] == "char" and dt["id"] == name):
                    cancel_hold_timer()
                    drag_state["hover_key"] = None
                    drag_state["target_info"] = None
                    return

                hkey = (dt["kind"], dt["id"])
                if dt["kind"] == "folder":
                    cancel_hold_timer()
                    drag_state["hover_key"] = hkey
                    drag_state["mode"] = "into_folder"
                    drag_state["target_info"] = (dt, rel_y)
                    dt["widget"].configure(highlightbackground="#F59E0B", bg="#451A03")
                    if dt.get("hint_lbl"):
                        dt["hint_lbl"].config(text="📥 Soltar en carpeta")
                else:
                    # Sobre otro personaje: borde = reordenar; centro mantenido 550ms = crear carpeta
                    is_center = (0.22 <= rel_y <= 0.78) and (dt["folder_id"] is None)
                    drag_state["target_info"] = (dt, rel_y)
                    if is_center:
                        if drag_state["hover_key"] != hkey:
                            cancel_hold_timer()
                            drag_state["hover_key"] = hkey
                            drag_state["mode"] = "reorder"
                            def promote_to_folder(target_dt=dt, key_chk=hkey):
                                if drag_state["active"] and drag_state["hover_key"] == key_chk:
                                    drag_state["mode"] = "make_folder"
                                    target_dt["widget"].configure(highlightbackground="#F59E0B", bg="#451A03")
                                    if target_dt.get("hint_lbl"):
                                        target_dt["hint_lbl"].config(text="📁 Crear carpeta")
                            drag_state["hold_timer"] = self.root.after(550, promote_to_folder)
                        if drag_state["mode"] == "make_folder":
                            dt["widget"].configure(highlightbackground="#F59E0B", bg="#451A03")
                            if dt.get("hint_lbl"):
                                dt["hint_lbl"].config(text="📁 Crear carpeta")
                        else:
                            dt["widget"].configure(highlightbackground="#38BDF8", bg="#1E293B")
                            if dt.get("hint_lbl"):
                                dt["hint_lbl"].config(text="⏳ Mantén = carpeta")
                    else:
                        cancel_hold_timer()
                        drag_state["hover_key"] = hkey
                        drag_state["mode"] = "reorder"
                        dt["widget"].configure(highlightbackground="#38BDF8", bg="#1E293B")
                        if dt.get("hint_lbl"):
                            dt["hint_lbl"].config(text="⬆️ Mover arriba" if rel_y < 0.5 else "⬇️ Mover abajo")

            def on_release(e):
                cancel_hold_timer()
                if drag_state["pill"]:
                    try:
                        drag_state["pill"].destroy()
                    except Exception:
                        pass
                    drag_state["pill"] = None

                was_dragging = drag_state["active"]
                src = drag_state["source_name"]
                mode = drag_state["mode"]
                tinfo = drag_state["target_info"]
                drag_state["active"] = False
                drag_state["source_name"] = None
                reset_highlights()

                if not was_dragging:
                    self._choose_character_from_card_list(player_num, name)
                    return

                if not src or not tinfo:
                    return
                dt, rel_y = tinfo
                self._apply_character_drag_drop(src, dt, mode, rel_y)

            for w_item in (row_f, drag_grip, icon_box, ic_lbl, name_lbl, hint_lbl):
                w_item.bind("<Enter>", on_e)
                w_item.bind("<Leave>", on_l)
                w_item.bind("<ButtonPress-1>", on_press)
                w_item.bind("<B1-Motion>", on_motion)
                w_item.bind("<ButtonRelease-1>", on_release)
                w_item.bind("<Button-3>", lambda e, p=player_num, n=name: self._on_card_character_right_click(e, p, n))

        rendered_any = False
        for entry in layout:
            if entry["type"] == "char":
                n = entry["name"]
                if q and q not in n.lower():
                    continue
                rendered_any = True
                make_char_row(container, n, folder_id=None)
            elif entry["type"] == "folder":
                f_items = [x for x in entry["items"] if (not q or q in x.lower() or q in entry["name"].lower())]
                if not f_items:
                    continue
                rendered_any = True
                fid = entry["id"]
                expanded = bool(entry.get("expanded", True)) or bool(q)
                f_bg = "#1E1B4B"
                f_bd = "#F59E0B"

                f_box = tk.Frame(container, bg="#0F172A", highlightthickness=2, highlightbackground=f_bd)
                f_box.pack(fill=tk.X, pady=(0, 6))

                f_hdr = tk.Frame(f_box, bg=f_bg, padx=8, pady=5, cursor="hand2")
                f_hdr.pack(fill=tk.X)

                f_ic = tk.Label(f_hdr, text="📂" if expanded else "📁", font=("Segoe UI", 12), bg=f_bg, fg="#FACC15", cursor="hand2")
                f_ic.pack(side=tk.LEFT, padx=(0, 6))

                f_title = tk.Label(
                    f_hdr, text=f"{entry['name']} ({len(entry['items'])})",
                    font=("Consolas", 11, "bold"), bg=f_bg, fg="#FDE68A", anchor=tk.W, cursor="hand2"
                )
                f_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

                f_hint = tk.Label(f_hdr, text="", font=("Segoe UI", 8, "bold"), bg=f_bg, fg="#FACC15")
                f_hint.pack(side=tk.RIGHT)

                drop_targets.append({
                    "kind": "folder", "id": fid, "folder_id": fid,
                    "widget": f_hdr, "base_bg": f_bg, "base_bd": f_bd, "hint_lbl": f_hint
                })

                for fw in (f_hdr, f_ic, f_title, f_hint):
                    fw.bind("<Button-1>", lambda e, id_=fid: self._toggle_folder_expanded(id_))
                    fw.bind("<Button-3>", lambda e, id_=fid: self._on_folder_right_click(e, id_))

                if expanded:
                    f_inner = tk.Frame(f_box, bg="#090D16", padx=8, pady=5)
                    f_inner.pack(fill=tk.X)
                    for child_name in f_items:
                        make_char_row(f_inner, child_name, folder_id=fid)

        if not rendered_any:
            tk.Label(
                container, text="No se encontraron personajes con ese nombre.",
                font=("Segoe UI", 9, "italic"), bg="#090D16", fg="#94A3B8", pady=20
            ).pack(fill=tk.X)

        self.card_list_thumbs[player_num] = new_thumbs
        del old_thumbs

    def _apply_character_drag_drop(self, src_name, target_dt, mode, rel_y):
        tkind = target_dt["kind"]
        tid = target_dt["id"]
        tfolder = target_dt.get("folder_id")

        if tkind == "char" and tid == src_name:
            return

        if mode == "make_folder" and tkind == "char" and tfolder is None:
            # Crear una nueva carpeta donde estaba el personaje destino con ambos dentro
            layout = self._sync_character_layout()
            pos = next((i for i, e in enumerate(layout) if e["type"] == "char" and e["name"] == tid), len(layout))
            self._remove_char_from_layout(src_name)
            layout = self.global_config["character_layout"]
            # Re-localizar destino
            pos = next((i for i, e in enumerate(layout) if e["type"] == "char" and e["name"] == tid), None)
            if pos is not None:
                folder_count = sum(1 for e in layout if e["type"] == "folder") + 1
                layout[pos] = {
                    "type": "folder",
                    "id": f"fld_{int(time.time()*1000)}_{folder_count}",
                    "name": f"Carpeta {folder_count}",
                    "expanded": True,
                    "items": [tid, src_name],
                }
        elif mode == "into_folder" or (tkind == "folder"):
            fid = tid if tkind == "folder" else tfolder
            self._remove_char_from_layout(src_name)
            for e in self.global_config["character_layout"]:
                if e["type"] == "folder" and e["id"] == fid:
                    if src_name not in e["items"]:
                        e["items"].append(src_name)
                    e["expanded"] = True
                    break
        else:
            # Reordenar (ya sea en nivel raíz o dentro de una carpeta)
            self._remove_char_from_layout(src_name)
            layout = self.global_config["character_layout"]
            if tfolder is not None:
                for e in layout:
                    if e["type"] == "folder" and e["id"] == tfolder:
                        if tid in e["items"]:
                            idx = e["items"].index(tid) + (0 if rel_y < 0.5 else 1)
                            e["items"].insert(idx, src_name)
                        else:
                            e["items"].append(src_name)
                        break
            else:
                pos = next((i for i, e in enumerate(layout) if e["type"] == "char" and e["name"] == tid), None)
                if pos is None:
                    layout.append({"type": "char", "name": src_name})
                else:
                    layout.insert(pos + (0 if rel_y < 0.5 else 1), {"type": "char", "name": src_name})

        self.save_global_config()
        self._refresh_both_card_lists()

    def _on_card_character_right_click(self, event, player_num, name):
        menu = tk.Menu(
            self.root, tearoff=0,
            bg="#0F172A", fg="#F8FAFC",
            activebackground="#EF4444", activeforeground="#FFFFFF",
            font=("Segoe UI", 9, "bold"), bd=1, relief="solid"
        )
        menu.add_command(
            label=f"🗑️ Borrar personaje '{name}'",
            command=lambda: self._delete_character_by_name(name, player_num)
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _delete_character_by_name(self, name, player_num=1):
        if len(self.profiles.get("player1", {})) <= 1:
            messagebox.showwarning("Atención", "Debes tener al menos un personaje guardado.")
            return

        if not messagebox.askyesno("Eliminar Personaje", f"¿Eliminar el personaje '{name}' y sus imágenes?"):
            return

        log_debug(f"[CARPETA] 🗑️ Eliminando personaje '{name}' por clic derecho")
        folder_path = os.path.abspath(os.path.join(CHARACTERS_DIR, self._sanitize_folder_name(name)))
        self.profiles["player1"].pop(name, None)
        self.profiles["player2"].pop(name, None)
        try:
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path, ignore_errors=True)
        except Exception:
            pass

        first = list(self.profiles["player1"].keys())[0]
        self.save_profiles_to_disk()

        if self.global_config.get("current_p1_profile") == name:
            self.global_config["current_p1_profile"] = first
            if self.card_has_selected.get(1, False):
                self._select_p1_character(first)
        if self.global_config.get("current_p2_profile") == name:
            self.global_config["current_p2_profile"] = first
            if self.card_has_selected.get(2, False):
                self._select_p2_character(first)

        if self.card_view_state.get(1) == "list":
            self._render_in_card_workshop_rows(1)
        if self.card_view_state.get(2) == "list":
            self._render_in_card_workshop_rows(2)

    def _open_character_folder_workshop(self, name, player_num=1):
        log_debug(f"[CARPETA] ⚙️ Abriendo expresiones de la carpeta '{name}'")
        if player_num == 1:
            self._select_p1_character(name)
            self._set_card_view(1, "active")
        else:
            if self.global_config.get("game_mode") == "single":
                self._set_game_mode("coop")
            self._select_p2_character(name)
            self._set_card_view(2, "active")
        self._open_workshop(player_num)

    # =========================================================================
    # --- CICLADO Y ACTUALIZACIÓN DE ETIQUETAS DE TARJETA ---
    # =========================================================================
    def _cycle_p1_character(self, direction):
        keys = list(self.profiles.get("player1", {}).keys())
        if not keys:
            return
        curr = self.global_config.get("current_p1_profile", "")
        idx = keys.index(curr) if curr in keys else 0
        new_idx = (idx + direction) % len(keys)
        new_name = keys[new_idx]
        log_debug(f"[ACCION] 🎮 1P Cambió a personaje: '{new_name}'")
        self._select_p1_character(new_name)

    def _cycle_p2_character(self, direction):
        keys = list(self.profiles.get("player2", {}).keys())
        if not keys:
            return
        curr = self.global_config.get("current_p2_profile", "")
        idx = keys.index(curr) if curr in keys else 0
        new_idx = (idx + direction) % len(keys)
        new_name = keys[new_idx]
        log_debug(f"[ACCION] 🎧 2P Cambió a personaje: '{new_name}'")
        self._select_p2_character(new_name)

    def _character_has_scream(self, target_dict):
        if not isinstance(target_dict, dict):
            return False
        for ex in target_dict.get("extra_expressions", []) or []:
            if ex.get("trigger") == "state_scream":
                return True
        return False

    def _refresh_p1_card_roster(self):
        curr_name = self.global_config.get("current_p1_profile", "")
        if hasattr(self, "p1_name_lbl"):
            self.p1_name_lbl.config(text=curr_name.upper())
        if hasattr(self, "p1_title_lbl") and self.card_view_state.get(1) == "active":
            self.p1_title_lbl.config(text=f"1P: {curr_name}")
        if hasattr(self, "p1_meter_info_lbl"):
            if self._character_has_scream(self.p1_data):
                self.p1_meter_info_lbl.config(
                    text=f"🤫 Voz: {int(self.p1_data.get('mic_threshold', 20))}%  |  💥 Grito: {int(self.p1_data.get('scream_threshold', 55))}%"
                )
            else:
                self.p1_meter_info_lbl.config(
                    text=f"🤫 Voz: {int(self.p1_data.get('mic_threshold', 20))}%"
                )
        if self.card_view_state.get(1) == "list":
            self._render_in_card_workshop_rows(1)

    def _refresh_p2_card_roster(self):
        curr_name = self.global_config.get("current_p2_profile", "")
        if hasattr(self, "p2_name_lbl"):
            self.p2_name_lbl.config(text=curr_name.upper())
        if hasattr(self, "p2_title_lbl") and self.card_view_state.get(2) == "active":
            self.p2_title_lbl.config(text=f"2P: {curr_name}")
        if hasattr(self, "p2_meter_info_lbl"):
            if self._character_has_scream(self.p2_data):
                self.p2_meter_info_lbl.config(
                    text=f"🤫 Voz: {int(self.p2_data.get('discord_threshold', 25))}%  |  💥 Grito: {int(self.p2_data.get('scream_threshold', 55))}%"
                )
            else:
                self.p2_meter_info_lbl.config(
                    text=f"🤫 Voz: {int(self.p2_data.get('discord_threshold', 25))}%"
                )
        if self.card_view_state.get(2) == "list":
            self._render_in_card_workshop_rows(2)

    # =========================================================================
    # --- PANTALLA 2: TALLER / AJUSTES Y TARJETAS DE POSES DE LA CARPETA ---
    # =========================================================================
    def _build_workshop_screen(self):
        self.workshop_frame = tk.Frame(self.screen_container, bg="#DFE5EE")

        top_w = tk.Frame(self.workshop_frame, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", pady=6, padx=10)
        top_w.pack(fill=tk.X, pady=(0, 8))

        ttk.Button(
            top_w, text="◀ Volver", style="DSBack.TButton",
            command=lambda: self._switch_screen("lobby")
        ).pack(side=tk.LEFT, padx=(0, 10))

        self.w_char_title = tk.Label(top_w, text="📁 Gatito Azul", font=("Segoe UI", 11, "bold"), bg="#FFFFFF", fg="#1E293B")
        self.w_char_title.pack(side=tk.LEFT)

        self.w_mode_badge = tk.Label(
            top_w, text="✨ Modo Pro (4 poses)",
            font=("Segoe UI", 8, "bold"), bg="#E0F2FE", fg="#0369A1", padx=8, pady=2
        )
        self.w_mode_badge.pack(side=tk.LEFT, padx=(10, 0))

        w_body = tk.Frame(self.workshop_frame, bg="#DFE5EE")
        w_body.pack(fill=tk.BOTH, expand=True)

        col_audio = tk.Frame(w_body, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", padx=14, pady=10)
        col_audio.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 6))

        tk.Label(
            col_audio, text="🎙️ CABINA DE PRUEBA DE VOZ",
            font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#3671C6"
        ).pack(anchor=tk.W, pady=(0, 6))

        self.w_live_avatar = LiveAvatarPreview(
            col_audio, size=(240, 240), bg="#F8FBFF", border_color="#242E3B", accent_color="#3671C6"
        )
        self.w_live_avatar.bounce_enabled = self.global_config.get("bounce_enabled", True)
        self.w_live_avatar.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        self.w_flip_x_var = tk.BooleanVar(value=False)
        self.w_flip_x_check = tk.Checkbutton(
            col_audio, text="↔️ Espejo en X (Voltear horizontalmente)",
            variable=self.w_flip_x_var, command=self._on_workshop_flip_x_toggle,
            bg="#FFFFFF", fg="#1E293B", activebackground="#FFFFFF", activeforeground="#0F172A",
            selectcolor="#FFFFFF", font=("Segoe UI", 9, "bold"), cursor="hand2"
        )
        self.w_flip_x_check.pack(anchor=tk.W, pady=(0, 8))

        meter_hdr = tk.Frame(col_audio, bg="#FFFFFF")
        meter_hdr.pack(fill=tk.X)
        ttk.Label(meter_hdr, text="Volumen en vivo:", style="White.TLabel", font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
        self.w_auto_cal_btn = tk.Button(
            meter_hdr, text="🪄 Auto-Calibrar (3s)", font=("Segoe UI", 8, "bold"),
            bg="#E0F2FE", fg="#0369A1", activebackground="#3671C6", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=6, pady=1, cursor="hand2",
            command=lambda: self._start_auto_calibration(self.workshop_player)
        )
        self.w_auto_cal_btn.pack(side=tk.RIGHT)

        self.w_audio_meter = tk.Canvas(col_audio, height=18, bg="#E2E8F0", highlightthickness=1, highlightbackground="#94A3B8")
        self.w_audio_meter.pack(fill=tk.X, pady=(2, 8))

        s_lbl_f = tk.Frame(col_audio, bg="#FFFFFF")
        s_lbl_f.pack(fill=tk.X)
        tk.Label(s_lbl_f, text="🤫 Sensibilidad de Voz:", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#1E293B").pack(side=tk.LEFT)
        self.w_thresh_val_lbl = tk.Label(s_lbl_f, text="20%", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#3671C6")
        self.w_thresh_val_lbl.pack(side=tk.RIGHT)

        self.w_thresh_scale = ttk.Scale(col_audio, from_=1, to=80, command=self._on_workshop_thresh_slider)
        self.w_thresh_scale.pack(fill=tk.X, pady=(2, 6))

        self.w_scream_container = tk.Frame(col_audio, bg="#FFFFFF")
        sc_lbl_f = tk.Frame(self.w_scream_container, bg="#FFFFFF")
        sc_lbl_f.pack(fill=tk.X)
        tk.Label(sc_lbl_f, text="💥 Umbral de Grito / Susto:", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#1E293B").pack(side=tk.LEFT)
        self.w_scream_val_lbl = tk.Label(sc_lbl_f, text="55%", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#E45B47")
        self.w_scream_val_lbl.pack(side=tk.RIGHT)

        self.w_scream_scale = ttk.Scale(self.w_scream_container, from_=20, to=95, command=self._on_workshop_scream_slider)
        self.w_scream_scale.pack(fill=tk.X, pady=(2, 8))

        self.w_audio_dev_lbl = tk.Label(col_audio, text="Dispositivo de Audio:", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#1E293B")
        self.w_audio_dev_lbl.pack(anchor=tk.W)
        self.w_audio_combo = ttk.Combobox(col_audio, state="readonly", width=34)
        self.w_audio_combo.pack(fill=tk.X, pady=(2, 4))
        self.w_audio_combo.bind("<<ComboboxSelected>>", self._on_workshop_device_changed)

        self.w_audio_tip = tk.Label(
            col_audio, text="💡 '🎯 Discord' captura solo la llamada sin el juego.",
            font=("Segoe UI", 8, "italic"), bg="#FFFFFF", fg="#10B981"
        )
        self.w_audio_tip.pack(anchor=tk.W)

        col_sprites = tk.Frame(w_body, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", padx=14, pady=10)
        col_sprites.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(6, 0))

        char_h = tk.Frame(col_sprites, bg="#FFFFFF")
        char_h.pack(fill=tk.X, pady=(0, 2))

        tk.Label(
            char_h, text="🎞️ FOTOGRAMAS Y ANIMACIONES DEL PERSONAJE",
            font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#1E293B"
        ).pack(side=tk.LEFT)

        self.w_folder_path_lbl = tk.Label(
            col_sprites, text="💡 Pasa el ratón sobre cualquier tarjeta para cambiar su imagen, o elige su animación abajo.",
            font=("Segoe UI", 8, "bold"), bg="#F1F5F9", fg="#0369A1", padx=8, pady=3, anchor=tk.W
        )
        self.w_folder_path_lbl.pack(fill=tk.X, pady=(2, 6))

        self.w_sprites_scroll = ScrollableFrame(col_sprites, bg="#FFFFFF")
        self.w_sprites_scroll.pack(fill=tk.BOTH, expand=True)
        self.w_sprites_content = self.w_sprites_scroll.content

    def _on_workshop_flip_x_toggle(self):
        val = bool(self.w_flip_x_var.get())
        is_p1 = (self.workshop_player == 1)
        curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
        log_debug(f"[TALLER] ↔️ Espejo en X para '{curr_name}' cambiado a: {val}")

        for p_key, rt_dict in (
            ("player1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
            ("player2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
        ):
            prof = self.profiles.get(p_key, {}).get(curr_name)
            for d in (prof, rt_dict):
                if isinstance(d, dict):
                    d["flip_x"] = val

        self._save_character_folder_meta(curr_name)
        self.save_profiles_to_disk()

        self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
        self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
        target_dict = self.p1_data if is_p1 else self.p2_data
        self.w_live_avatar.set_character(target_dict, prefix="a1" if is_p1 else "a2")
        self._sync_windows_images()

    def _update_workshop_scream_bar_visibility(self, target_dict):
        if not hasattr(self, "w_scream_container"):
            return
        if self._character_has_scream(target_dict):
            self.w_scream_container.pack(fill=tk.X, before=self.w_audio_dev_lbl)
        else:
            self.w_scream_container.pack_forget()

    # =========================================================================
    # --- NAVEGACIÓN ENTRE LOBBY Y TALLER ---
    # =========================================================================
    def _switch_screen(self, screen_name):
        log_debug(f"[ACCION] 📺 Cambiando a pantalla: '{screen_name.upper()}'")
        self.current_screen = screen_name
        self._refresh_eco_mode()
        self.lobby_frame.pack_forget()
        self.workshop_frame.pack_forget()

        if screen_name == "lobby":
            self.lobby_frame.pack(fill=tk.BOTH, expand=True)

            if hasattr(self, "btn_workshop_accept"):
                self.btn_workshop_accept.pack_forget()
            if hasattr(self, "opts_f"):
                self.opts_f.pack(side=tk.LEFT)
            if hasattr(self, "btn_open"):
                self.btn_open.pack(side=tk.RIGHT, padx=4)

            self._refresh_p1_card_roster()
            self._refresh_p2_card_roster()

            self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
            self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
        elif screen_name == "workshop":
            self.workshop_frame.pack(fill=tk.BOTH, expand=True)

            if hasattr(self, "opts_f"):
                self.opts_f.pack_forget()
            if hasattr(self, "btn_open"):
                self.btn_open.pack_forget()
            if hasattr(self, "btn_workshop_accept"):
                self.btn_workshop_accept.pack(side=tk.RIGHT, padx=4)

            self._refresh_workshop_ui()

    def _open_workshop(self, player_num):
        log_debug(f"[ACCION] 🛠️ Abriendo Taller de edición para Jugador {player_num}")
        self.workshop_player = player_num
        self._switch_screen("workshop")

    def _set_workshop_player(self, player_num):
        log_debug(f"[ACCION] 🛠️ Taller: Cambiando a pestaña de Jugador {player_num}")
        self.workshop_player = player_num
        self._refresh_workshop_ui()

    def _refresh_workshop_ui(self):
        p_num = self.workshop_player
        is_p1 = (p_num == 1)

        if is_p1:
            target_data = self.p1_data
            curr_name = self.global_config.get("current_p1_profile", "Gatito Azul")
            prefix = "a1"
            thresh_val = target_data["mic_threshold"]
            scream_val = target_data.get("scream_threshold", 55)
            self.w_audio_tip.pack_forget()
        else:
            target_data = self.p2_data
            curr_name = self.global_config.get("current_p2_profile", "Osito Discord")
            prefix = "a2"
            thresh_val = target_data["discord_threshold"]
            scream_val = target_data.get("scream_threshold", 55)
            self.w_audio_tip.pack(anchor=tk.W)

        self.w_char_title.config(text=f"📁 {curr_name}")
        if hasattr(self, "w_folder_path_lbl"):
            self.w_folder_path_lbl.config(
                text=f"💡 Personaje: '{curr_name}' | Pasa el ratón sobre cualquier tarjeta para cambiar su imagen, o elige su animación abajo."
            )
        if hasattr(self, "w_flip_x_var"):
            self.w_flip_x_var.set(bool(target_data.get("flip_x", False)))
        self.w_live_avatar.set_character(target_data, prefix=prefix)

        mode = target_data.get("image_mode", "4_states")
        if mode == "4_states":
            self.w_mode_badge.config(text="✨ Modo Pro (4 poses)", bg="#E0F2FE", fg="#0369A1")
        else:
            self.w_mode_badge.config(text="⚡ Modo Simple (2 poses)", bg="#FEF3C7", fg="#92400E")

        self.w_thresh_scale.set(thresh_val)
        self.w_thresh_val_lbl.config(text=f"{int(thresh_val)}%")

        self.w_scream_scale.set(scream_val)
        self.w_scream_val_lbl.config(text=f"{int(scream_val)}%")

        self._update_workshop_scream_bar_visibility(target_data)
        self._sync_audio_combos_selection()
        self._rebuild_workshop_sprite_slots(target_data, prefix)

    def _rebuild_workshop_sprite_slots(self, target_dict, prefix):
        for w in self.w_sprites_content.winfo_children():
            w.destroy()

        self._update_workshop_scream_bar_visibility(target_dict)

        mode_4 = (target_dict.get("image_mode") == "4_states")

        if mode_4:
            slots = [
                (f"{prefix}_idle", "Quieto ojos abiertos", "idle"),
                (f"{prefix}_idle_blink", "Quieto (pestañeo)", "idle_blink"),
                (f"{prefix}_talk", "Hablando ojos abiertos", "talk"),
                (f"{prefix}_talk_blink", "Hablando (pestañeo)", "talk_blink"),
            ]
        else:
            slots = [
                (f"{prefix}_idle", "Quieto (Boca cerrada)", "idle"),
                (f"{prefix}_talk", "Hablando (Boca abierta)", "talk"),
            ]

        self.w_sprites_content.grid_columnconfigure(0, weight=1, uniform="pose_card")
        self.w_sprites_content.grid_columnconfigure(1, weight=1, uniform="pose_card")

        idx = 0
        for key, title_text, role_id in slots:
            r = idx // 2
            c = idx % 2
            self._build_pose_card(self.w_sprites_content, key, title_text, role_id, target_dict, r, c)
            idx += 1

        # Renderizar tarjetas de expresiones situacionales / extra añadidas con '+'
        extra_list = target_dict.get("extra_expressions", []) or []
        for ex_item in extra_list:
            r = idx // 2
            c = idx % 2
            self._build_extra_pose_card(self.w_sprites_content, ex_item, prefix, target_dict, r, c)
            idx += 1

        # La última celda siempre muestra el botón '+' para agregar nuevas expresiones situacionales
        self._build_add_slot_card(self.w_sprites_content, row_idx=idx // 2, col_idx=idx % 2)

    def _build_add_slot_card(self, parent, row_idx, col_idx):
        card = tk.Frame(
            parent, bg="#F8FAFC", highlightthickness=2, highlightbackground="#94A3B8",
            padx=12, pady=12, cursor="hand2"
        )
        card.grid(row=row_idx, column=col_idx, padx=6, pady=6, sticky="nsew")

        center_lbl = tk.Label(
            card,
            text="➕\n\nAgregar fotograma\n(Grito, Dormido, Transición, Coop...)",
            font=("Segoe UI", 10, "bold"),
            bg="#F8FAFC", fg="#334155", justify=tk.CENTER, cursor="hand2"
        )
        center_lbl.pack(expand=True, fill=tk.BOTH, pady=18)

        def on_enter(e=None):
            card.configure(highlightbackground="#2563EB", bg="#EFF6FF")
            center_lbl.configure(bg="#EFF6FF", fg="#1D4ED8")

        def on_leave(e=None):
            card.configure(highlightbackground="#94A3B8", bg="#F8FAFC")
            center_lbl.configure(bg="#F8FAFC", fg="#334155")

        def on_click(e=None):
            self._open_add_expression_dialog()

        for w in (card, center_lbl):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)

    def _find_catalog_meta(self, trigger_type, title_hint=""):
        for cat in EXTRA_EXPRESSION_CATALOG:
            for it in cat["items"]:
                if it["trigger"] == trigger_type:
                    if not title_hint or it["title"] == title_hint:
                        return it
        for cat in EXTRA_EXPRESSION_CATALOG:
            for it in cat["items"]:
                if it["trigger"] == trigger_type:
                    return it
        return {
            "trigger": trigger_type,
            "title": title_hint or "Fotograma extra",
            "default_motion": "Ninguna",
            "param_label": "Modo:",
            "param_options": ["Activo"],
            "default_param": "Activo",
        }

    def _open_add_expression_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("➕ Agregar fotograma")
        dlg.geometry("680x580")
        dlg.configure(bg="#DFE5EE")
        dlg.transient(self.root)
        dlg.grab_set()

        hdr = tk.Frame(dlg, bg="#242E3B", padx=14, pady=10)
        hdr.pack(fill=tk.X)
        tk.Label(
            hdr, text="➕ ¿EN QUÉ MOMENTO SE REPRODUCIRÁ ESTE NUEVO FRAME?",
            font=("Segoe UI", 11, "bold"), bg="#242E3B", fg="#FFFFFF"
        ).pack(anchor=tk.W)
        tk.Label(
            hdr,
            text="Elige una situación para añadir su tarjeta al personaje (dormido, transiciones, reacción al compañero, mute o tecla):",
            font=("Segoe UI", 8), bg="#242E3B", fg="#CBD5E1"
        ).pack(anchor=tk.W, pady=(2, 0))

        scroll_area = ScrollableFrame(dlg, bg="#DFE5EE")
        scroll_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        container = scroll_area.content

        is_p1 = (self.workshop_player == 1)
        target_dict = self.p1_data if is_p1 else self.p2_data
        existing_triggers = {ex.get("trigger") for ex in (target_dict.get("extra_expressions", []) or [])}

        any_available = False
        for cat in EXTRA_EXPRESSION_CATALOG:
            avail_items = [
                it for it in cat["items"]
                if (it["trigger"] not in existing_triggers) or it.get("allow_multiple", False)
            ]
            if not avail_items:
                continue
            any_available = True

            cat_box = tk.Frame(
                container, bg="#FFFFFF", highlightthickness=2,
                highlightbackground="#242E3B", padx=10, pady=8
            )
            cat_box.pack(fill=tk.X, pady=5, padx=4)

            cat_hdr = tk.Frame(cat_box, bg=cat["bg"], padx=8, pady=4)
            cat_hdr.pack(fill=tk.X, pady=(0, 6))
            tk.Label(
                cat_hdr, text=cat["category"],
                font=("Segoe UI", 9, "bold"), bg=cat["bg"], fg=cat["color"]
            ).pack(anchor=tk.W)

            for item in avail_items:
                row = tk.Frame(
                    cat_box, bg="#F8FAFC", highlightthickness=1,
                    highlightbackground="#CBD5E1", padx=10, pady=6
                )
                row.pack(fill=tk.X, pady=3)

                info_f = tk.Frame(row, bg="#F8FAFC")
                info_f.pack(side=tk.LEFT, fill=tk.X, expand=True)

                title_txt = item["title"]
                if item.get("allow_multiple") and item["trigger"] in existing_triggers:
                    title_txt = f"{title_txt} (Agregar otra)"

                tk.Label(
                    info_f, text=title_txt,
                    font=("Segoe UI", 9, "bold"), bg="#F8FAFC", fg="#1E293B", anchor=tk.W
                ).pack(fill=tk.X)
                tk.Label(
                    info_f, text=item["desc"],
                    font=("Segoe UI", 8), bg="#F8FAFC", fg="#475569", anchor=tk.W, justify=tk.LEFT, wraplength=460
                ).pack(fill=tk.X)

                btn_add = tk.Button(
                    row, text="➕ Agregar", font=("Segoe UI", 9, "bold"),
                    bg="#2563EB", fg="#FFFFFF", activebackground="#1D4ED8", activeforeground="#FFFFFF",
                    relief="flat", padx=12, pady=4, cursor="hand2",
                    command=lambda it=item: self._confirm_add_extra_expression(dlg, it)
                )
                btn_add.pack(side=tk.RIGHT, padx=(8, 0))

        if not any_available:
            tk.Label(
                container,
                text="✅ Ya agregaste todos los fotogramas únicos disponibles para este personaje.",
                font=("Segoe UI", 10, "bold"), bg="#DFE5EE", fg="#475569", pady=40
            ).pack(fill=tk.X)

        ftr = tk.Frame(dlg, bg="#DFE5EE", padx=12, pady=8)
        ftr.pack(fill=tk.X)
        ttk.Button(ftr, text="Cancelar", style="DSButton.TButton", command=dlg.destroy).pack(side=tk.RIGHT)

    def _confirm_add_extra_expression(self, dlg, catalog_item):
        try:
            dlg.destroy()
        except Exception:
            pass

        is_p1 = (self.workshop_player == 1)
        target_dict = self.p1_data if is_p1 else self.p2_data
        prefix = "a1" if is_p1 else "a2"
        curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
        char_folder = self._get_character_folder(curr_name)

        trig = catalog_item["trigger"]
        unique_suffix = int(time.time() * 1000) % 100000
        role_id = f"ext_{trig}_{unique_suffix}"
        key = f"{prefix}_{role_id}"

        # Pedir imagen para la nueva expresión (o usar idle por defecto si cancela para que pueda cambiarla luego)
        file_path = filedialog.askopenfilename(
            title=f"Selecciona imagen o GIF para: {catalog_item['title']}",
            filetypes=[
                ("Imágenes y GIFs Animados", "*.png;*.gif;*.webp;*.jpg;*.jpeg"),
                ("Todos los archivos", "*.*"),
            ]
        )

        if file_path and os.path.exists(file_path):
            ext = os.path.splitext(file_path)[1].lower()
            save_ext = ext if ext in (".gif", ".webp", ".png") else ".png"
            dest_path = os.path.join(char_folder, f"{role_id}{save_ext}")
            try:
                if os.path.abspath(file_path) != os.path.abspath(dest_path):
                    if ext in (".jpg", ".jpeg"):
                        Image.open(file_path).convert("RGBA").save(dest_path, "PNG")
                    else:
                        shutil.copy2(file_path, dest_path)
            except Exception:
                dest_path = file_path
        else:
            # Usar copia del sprite base como imagen inicial para que la tarjeta sea visible de inmediato
            base_key = f"{prefix}_scream" if trig == "state_scream" else f"{prefix}_idle"
            idle_src = target_dict.get(base_key) or self.default_assets.get(base_key) or target_dict.get(f"{prefix}_idle") or self.default_assets.get(f"{prefix}_idle")
            ext = os.path.splitext(idle_src)[1].lower() if idle_src else ".png"
            save_ext = ext if ext in (".gif", ".webp", ".png") else ".png"
            dest_path = os.path.join(char_folder, f"{role_id}{save_ext}")
            if idle_src and os.path.exists(idle_src):
                try:
                    shutil.copy2(idle_src, dest_path)
                except Exception:
                    dest_path = idle_src

        default_motion = catalog_item.get("default_motion", "Ninguna")
        default_param = catalog_item.get("default_param", "Activo")

        new_entry = {
            "role": role_id,
            "trigger": trig,
            "title": catalog_item["title"],
            "file": dest_path,
            "motion": default_motion,
            "param": default_param,
        }

        self._append_extra_expression_to_character(curr_name, new_entry)
        self._rebuild_workshop_sprite_slots(target_dict, prefix)
        self._trigger_preview_on_all(role_id, is_p1)

    def _append_extra_expression_to_character(self, char_name, new_entry):
        role_id = new_entry["role"]
        dest_path = new_entry["file"]
        motion = new_entry["motion"]

        for p_key, pref, runtime_dict in (
            ("player1", "a1", self.p1_data if self.global_config.get("current_p1_profile") == char_name else None),
            ("player2", "a2", self.p2_data if self.global_config.get("current_p2_profile") == char_name else None),
        ):
            prof = self.profiles.get(p_key, {}).get(char_name)
            for d in (prof, runtime_dict):
                if isinstance(d, dict):
                    if "extra_expressions" not in d or not isinstance(d["extra_expressions"], list):
                        d["extra_expressions"] = []
                    # Evitar duplicar el mismo role_id
                    d["extra_expressions"] = [x for x in d["extra_expressions"] if x.get("role") != role_id]
                    d["extra_expressions"].append(dict(new_entry))
                    d[f"{pref}_{role_id}"] = dest_path
                    d[f"{pref}_{role_id}_motion"] = motion

        self._save_character_folder_meta(char_name)
        self.save_profiles_to_disk()
        self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
        self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
        if self.current_screen == "workshop":
            is_p1 = (self.workshop_player == 1)
            self.w_live_avatar.set_character(self.p1_data if is_p1 else self.p2_data, prefix="a1" if is_p1 else "a2")
        self._sync_windows_images()

    def _remove_extra_expression(self, role_id, target_dict, prefix):
        is_p1 = (target_dict is self.p1_data)
        curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
        char_folder = self._get_character_folder(curr_name)

        # Eliminar archivo en carpeta si es un extra
        for ext in (".png", ".gif", ".webp"):
            cand = os.path.join(char_folder, f"{role_id}{ext}")
            if os.path.exists(cand):
                try:
                    os.remove(cand)
                except Exception:
                    pass

        for p_key, pref, runtime_dict in (
            ("player1", "a1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
            ("player2", "a2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
        ):
            prof = self.profiles.get(p_key, {}).get(curr_name)
            for d in (prof, runtime_dict):
                if isinstance(d, dict):
                    if "extra_expressions" in d and isinstance(d["extra_expressions"], list):
                        d["extra_expressions"] = [x for x in d["extra_expressions"] if x.get("role") != role_id]
                    d.pop(f"{pref}_{role_id}", None)
                    d.pop(f"{pref}_{role_id}_motion", None)

        self._save_character_folder_meta(curr_name)
        self.save_profiles_to_disk()
        self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
        self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
        self.w_live_avatar.set_character(target_dict, prefix=prefix)
        self._sync_windows_images()
        self._rebuild_workshop_sprite_slots(target_dict, prefix)

    def _trigger_preview_on_all(self, role_id, is_p1):
        self.w_live_avatar.trigger_preview_role(role_id, 2.5)
        if is_p1:
            self.p1_live_avatar.trigger_preview_role(role_id, 2.5)
            if self.avatar1_window and self.avatar1_window.winfo_exists():
                self.avatar1_window.trigger_preview_role(role_id, 2.5)
        else:
            self.p2_live_avatar.trigger_preview_role(role_id, 2.5)
            if self.avatar2_window and self.avatar2_window.winfo_exists():
                self.avatar2_window.trigger_preview_role(role_id, 2.5)

    def _build_extra_pose_card(self, parent, ex_item, prefix, target_dict, row_idx, col_idx):
        role_id = ex_item.get("role", "ext_custom")
        trig_type = ex_item.get("trigger", "afk_sleep")
        title_text = ex_item.get("title", "Fotograma extra")
        key = f"{prefix}_{role_id}"
        is_p1 = (target_dict is self.p1_data)

        if not target_dict.get(key) and ex_item.get("file"):
            target_dict[key] = ex_item["file"]

        meta_info = self._find_catalog_meta(trig_type, title_text)

        card = tk.Frame(
            parent, bg="#FFFFFF", highlightthickness=2, highlightbackground="#0284C7",
            padx=10, pady=8, cursor="hand2"
        )
        card.grid(row=row_idx, column=col_idx, padx=6, pady=6, sticky="nsew")

        # Cabecera con título + botón Probar + botón Eliminar
        hdr_f = tk.Frame(card, bg="#FFFFFF")
        hdr_f.pack(fill=tk.X, pady=(0, 4))

        title_lbl = tk.Label(
            hdr_f, text=title_text, font=("Segoe UI", 9, "bold"),
            bg="#FFFFFF", fg="#0369A1", cursor="hand2"
        )
        title_lbl.pack(side=tk.LEFT)

        del_btn = tk.Button(
            hdr_f, text="✕", font=("Segoe UI", 8, "bold"),
            bg="#FEE2E2", fg="#DC2626", activebackground="#DC2626", activeforeground="#FFFFFF",
            relief="flat", padx=5, pady=0, cursor="hand2",
            command=lambda: self._remove_extra_expression(role_id, target_dict, prefix)
        )
        del_btn.pack(side=tk.RIGHT, padx=(3, 0))

        test_btn = tk.Button(
            hdr_f, text="▶ Probar", font=("Segoe UI", 8, "bold"),
            bg="#E0F2FE", fg="#0284C7", activebackground="#0284C7", activeforeground="#FFFFFF",
            relief="flat", padx=6, pady=0, cursor="hand2",
            command=lambda: self._trigger_preview_on_all(role_id, is_p1)
        )
        test_btn.pack(side=tk.RIGHT)

        # Contenedor central de la imagen con overlay interactivo
        img_box = tk.Frame(
            card, bg="#F8FAFC", width=140, height=115,
            highlightthickness=1, highlightbackground="#CBD5E1", cursor="hand2"
        )
        img_box.pack(pady=3, fill=tk.BOTH, expand=True)
        img_box.pack_propagate(False)

        thumb_lbl = tk.Label(img_box, bg="#F8FAFC", cursor="hand2")
        thumb_lbl.pack(fill=tk.BOTH, expand=True)

        self.thumbnails[key] = (thumb_lbl, target_dict)
        self._update_thumbnail(key)

        overlay_banner = tk.Label(
            img_box, text="🔄 Cambiar imagen", font=("Segoe UI", 9, "bold"),
            bg="#2563EB", fg="#FFFFFF", cursor="hand2", pady=4
        )

        def show_overlay(event=None):
            card.configure(highlightbackground="#2563EB", bg="#F0F9FF")
            hdr_f.configure(bg="#F0F9FF")
            title_lbl.configure(bg="#F0F9FF", fg="#1D4ED8")
            overlay_banner.place(relx=0.0, rely=1.0, relwidth=1.0, anchor="sw")

        def hide_overlay(event=None):
            card.configure(highlightbackground="#0284C7", bg="#FFFFFF")
            hdr_f.configure(bg="#FFFFFF")
            title_lbl.configure(bg="#FFFFFF", fg="#0369A1")
            overlay_banner.place_forget()

        def on_change_click(event=None):
            self._choose_image(key, target_dict)

        def on_extra_right_click(event):
            menu = tk.Menu(
                self.root, tearoff=0,
                bg="#0F172A", fg="#F8FAFC",
                activebackground="#EF4444", activeforeground="#FFFFFF",
                font=("Segoe UI", 9, "bold"), bd=1, relief="solid"
            )
            menu.add_command(
                label=f"🗑️ Borrar fotograma",
                command=lambda: self._remove_extra_expression(role_id, target_dict, prefix)
            )
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        for w in (card, hdr_f, title_lbl, img_box, thumb_lbl, overlay_banner):
            w.bind("<Button-3>", on_extra_right_click)
        for w in (card, title_lbl, img_box, thumb_lbl, overlay_banner):
            w.bind("<Enter>", show_overlay)
            w.bind("<Leave>", hide_overlay)
            w.bind("<Button-1>", on_change_click)

        # Selector de parámetro situacional (Tiempo AFK, Duración ms, Tecla, etc.)
        param_options = meta_info.get("param_options", ["Activo"])
        curr_param = ex_item.get("param") or meta_info.get("default_param", param_options[0])
        param_var = tk.StringVar(value=curr_param)

        param_f = tk.Frame(card, bg="#FFFFFF")
        param_f.pack(fill=tk.X, pady=(3, 1))
        tk.Label(
            param_f, text=meta_info.get("param_label", "Cuando:"),
            font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#475569"
        ).pack(side=tk.LEFT, padx=(0, 4))

        param_combo = ttk.Combobox(
            param_f, textvariable=param_var, values=param_options,
            state="readonly" if len(param_options) > 1 else "disabled",
            font=("Segoe UI", 8, "bold"), width=14, justify=tk.CENTER
        )
        param_combo.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        # Selector de movimiento (Respiración, Saltitos, Elástico, Balanceo, Sacudida, Flotar)
        motion_options = ["Ninguna", "Respiración", "Saltitos", "Elástico", "Balanceo", "Sacudida", "Flotar"]
        current_motion = target_dict.get(f"{key}_motion") or ex_item.get("motion") or meta_info.get("default_motion", "Ninguna")
        if current_motion == "Rebote":
            current_motion = "Respiración"
        target_dict[f"{key}_motion"] = current_motion
        motion_var = tk.StringVar(value=current_motion)

        motion_f = tk.Frame(card, bg="#FFFFFF", pady=1)
        motion_f.pack(fill=tk.X, pady=(2, 0))
        motion_menu = ttk.Combobox(
            motion_f, textvariable=motion_var, values=motion_options,
            state="readonly", font=("Segoe UI", 9, "bold"), justify=tk.CENTER
        )
        motion_menu.pack(fill=tk.X)

        # Control de velocidad individual de la animación
        curr_speed = target_dict.get(f"{key}_speed")
        if curr_speed is None:
            curr_speed = ex_item.get("speed", 1.0)
        try:
            curr_speed = max(0.3, min(3.0, float(curr_speed)))
        except Exception:
            curr_speed = 1.0
        target_dict[f"{key}_speed"] = curr_speed

        speed_f = tk.Frame(card, bg="#FFFFFF")
        speed_f.pack(fill=tk.X, pady=(3, 0))
        tk.Label(speed_f, text="⚡ Vel:", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#475569").pack(side=tk.LEFT)
        speed_val_lbl = tk.Label(speed_f, text=f"{curr_speed:.1f}x", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#0369A1", width=4, anchor=tk.E)
        speed_val_lbl.pack(side=tk.RIGHT)
        speed_scale = ttk.Scale(speed_f, from_=0.3, to=3.0, value=curr_speed)
        speed_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        def sync_extra_settings(event=None):
            new_m = motion_var.get()
            new_p = param_var.get()
            new_spd = round(float(speed_scale.get()), 2)
            speed_val_lbl.config(text=f"{new_spd:.1f}x")
            target_dict[f"{key}_motion"] = new_m
            target_dict[f"{key}_speed"] = new_spd
            ex_item["motion"] = new_m
            ex_item["param"] = new_p
            ex_item["speed"] = new_spd

            curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
            for p_key, pref, rt_dict in (
                ("player1", "a1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
                ("player2", "a2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
            ):
                prof = self.profiles.get(p_key, {}).get(curr_name)
                for d in (prof, rt_dict):
                    if isinstance(d, dict):
                        d[f"{pref}_{role_id}_motion"] = new_m
                        d[f"{pref}_{role_id}_speed"] = new_spd
                        for item in d.get("extra_expressions", []) or []:
                            if item.get("role") == role_id:
                                item["motion"] = new_m
                                item["param"] = new_p
                                item["speed"] = new_spd

            self._save_character_folder_meta(curr_name)
            self.save_profiles_to_disk()
            self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
            self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
            self.w_live_avatar.set_character(target_dict, prefix=prefix)
            self._sync_windows_images()

        def on_extra_speed_move(val):
            speed_val_lbl.config(text=f"{float(val):.1f}x")

        speed_scale.config(command=on_extra_speed_move)
        speed_scale.bind("<ButtonRelease-1>", sync_extra_settings)
        param_combo.bind("<<ComboboxSelected>>", sync_extra_settings)
        motion_menu.bind("<<ComboboxSelected>>", sync_extra_settings)

    def _build_pose_card(self, parent, key, title_text, role_id, target_dict, row_idx, col_idx):
        card = tk.Frame(
            parent, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B",
            padx=10, pady=8, cursor="hand2"
        )
        card.grid(row=row_idx, column=col_idx, padx=6, pady=6, sticky="nsew")

        # Título arriba
        title_lbl = tk.Label(
            card, text=title_text, font=("Segoe UI", 9, "bold"),
            bg="#FFFFFF", fg="#1E293B", cursor="hand2"
        )
        title_lbl.pack(anchor=tk.W, pady=(0, 4))

        # Contenedor central de la imagen con overlay interactivo
        img_box = tk.Frame(
            card, bg="#F8FAFC", width=140, height=130,
            highlightthickness=1, highlightbackground="#CBD5E1", cursor="hand2"
        )
        img_box.pack(pady=4, fill=tk.BOTH, expand=True)
        img_box.pack_propagate(False)

        thumb_lbl = tk.Label(img_box, bg="#F8FAFC", cursor="hand2")
        thumb_lbl.pack(fill=tk.BOTH, expand=True)

        self.thumbnails[key] = (thumb_lbl, target_dict)
        self._update_thumbnail(key)

        # Banner interactivo flotante "🔄 Cambiar imagen" que aparece al pasar el ratón (hover)
        overlay_banner = tk.Label(
            img_box, text="🔄 Cambiar imagen", font=("Segoe UI", 9, "bold"),
            bg="#2563EB", fg="#FFFFFF", cursor="hand2", pady=4
        )

        def show_overlay(event=None):
            card.configure(highlightbackground="#2563EB", bg="#F0F9FF")
            title_lbl.configure(bg="#F0F9FF", fg="#0284C7")
            overlay_banner.place(relx=0.0, rely=1.0, relwidth=1.0, anchor="sw")

        def hide_overlay(event=None):
            card.configure(highlightbackground="#242E3B", bg="#FFFFFF")
            title_lbl.configure(bg="#FFFFFF", fg="#1E293B")
            overlay_banner.place_forget()

        def on_change_click(event=None):
            self._choose_image(key, target_dict)

        def on_base_right_click(event):
            menu = tk.Menu(
                self.root, tearoff=0,
                bg="#0F172A", fg="#F8FAFC",
                activebackground="#EF4444", activeforeground="#FFFFFF",
                font=("Segoe UI", 9, "bold"), bd=1, relief="solid"
            )
            menu.add_command(
                label=f"🗑️ Borrar imagen de '{title_text}'",
                command=lambda: self._clear_base_pose_image(key, role_id, target_dict)
            )
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        for w in (card, title_lbl, img_box, thumb_lbl, overlay_banner):
            w.bind("<Enter>", show_overlay)
            w.bind("<Leave>", hide_overlay)
            w.bind("<Button-1>", on_change_click)
            w.bind("<Button-3>", on_base_right_click)

        # Selector de animación inferior
        motion_options = ["Ninguna", "Respiración", "Saltitos", "Elástico", "Balanceo", "Sacudida", "Flotar"]
        current_motion = target_dict.get(f"{key}_motion")
        if current_motion == "Rebote":
            current_motion = "Respiración"
        if not current_motion:
            if role_id in ("idle", "talk"):
                current_motion = "Respiración"
            elif role_id == "scream":
                current_motion = "Sacudida"
            else:
                current_motion = "Ninguna"
        target_dict[f"{key}_motion"] = current_motion

        motion_var = tk.StringVar(value=current_motion)

        motion_f = tk.Frame(card, bg="#FFFFFF", pady=2)
        motion_f.pack(fill=tk.X, pady=(4, 0))

        motion_menu = ttk.Combobox(
            motion_f, textvariable=motion_var, values=motion_options,
            state="readonly", font=("Segoe UI", 9, "bold"), justify=tk.CENTER
        )
        motion_menu.pack(fill=tk.X)

        # Control de velocidad individual de la animación
        curr_speed = target_dict.get(f"{key}_speed", 1.0)
        try:
            curr_speed = max(0.3, min(3.0, float(curr_speed)))
        except Exception:
            curr_speed = 1.0
        target_dict[f"{key}_speed"] = curr_speed

        speed_f = tk.Frame(card, bg="#FFFFFF")
        speed_f.pack(fill=tk.X, pady=(3, 0))
        tk.Label(speed_f, text="⚡ Vel:", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#475569").pack(side=tk.LEFT)
        speed_val_lbl = tk.Label(speed_f, text=f"{curr_speed:.1f}x", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#0369A1", width=4, anchor=tk.E)
        speed_val_lbl.pack(side=tk.RIGHT)
        speed_scale = ttk.Scale(speed_f, from_=0.3, to=3.0, value=curr_speed)
        speed_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        def save_pose_motion_and_speed(event=None):
            val = motion_var.get()
            spd = round(float(speed_scale.get()), 2)
            speed_val_lbl.config(text=f"{spd:.1f}x")
            target_dict[f"{key}_motion"] = val
            target_dict[f"{key}_speed"] = spd
            is_p1 = (target_dict is self.p1_data)
            curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
            for p_key, pref, rt_dict in (
                ("player1", "a1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
                ("player2", "a2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
            ):
                prof = self.profiles.get(p_key, {}).get(curr_name)
                for d in (prof, rt_dict):
                    if isinstance(d, dict):
                        d[f"{pref}_{role_id}_motion"] = val
                        d[f"{pref}_{role_id}_speed"] = spd
            self._save_character_folder_meta(curr_name)
            if is_p1:
                self._save_p1_profile()
                self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
                self.w_live_avatar.set_character(self.p1_data, prefix="a1")
            else:
                self._save_p2_profile()
                self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
                self.w_live_avatar.set_character(self.p2_data, prefix="a2")
            self._sync_windows_images()

        def on_pose_speed_move(val):
            speed_val_lbl.config(text=f"{float(val):.1f}x")

        speed_scale.config(command=on_pose_speed_move)
        speed_scale.bind("<ButtonRelease-1>", save_pose_motion_and_speed)
        motion_menu.bind("<<ComboboxSelected>>", save_pose_motion_and_speed)

    def _clear_base_pose_image(self, key, role_id, target_dict):
        is_p1 = (target_dict is self.p1_data)
        curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
        target_dict[key] = ""
        for p_key, pref, rt_dict in (
            ("player1", "a1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
            ("player2", "a2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
        ):
            prof = self.profiles.get(p_key, {}).get(curr_name)
            for d in (prof, rt_dict):
                if isinstance(d, dict):
                    d[f"{pref}_{role_id}"] = ""
        self._update_thumbnail(key)
        self._save_character_folder_meta(curr_name)
        self.save_profiles_to_disk()
        self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
        self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
        self.w_live_avatar.set_character(target_dict, prefix="a1" if is_p1 else "a2")
        self._sync_windows_images()

    def _get_expression_display_label(self, path):
        if not path or not os.path.exists(path):
            return "Sin imagen"
        base = os.path.basename(path)
        try:
            img = Image.open(path)
            n_f = getattr(img, "n_frames", 1)
            if n_f > 1 and getattr(img, "is_animated", False):
                return f"🎞️ {base} ({n_f} frames)"
        except Exception:
            pass
        return base

    def _choose_image(self, key, target_dict):
        file_path = filedialog.askopenfilename(
            title="Seleccionar imagen o GIF animado del fotograma (se guardará en la carpeta del personaje)",
            filetypes=[
                ("Imágenes y GIFs Animados", "*.png;*.gif;*.webp;*.jpg;*.jpeg"),
                ("GIF / APNG / WEBP Animado", "*.gif;*.png;*.webp"),
                ("Todos los archivos", "*.*"),
            ]
        )
        if file_path:
            is_p1 = (target_dict is self.p1_data)
            curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
            role = key.split("_", 1)[1] if "_" in key else key  # ej. 'idle', 'talk', 'scream'

            char_folder = self._get_character_folder(curr_name)
            ext = os.path.splitext(file_path)[1].lower()
            save_ext = ext if ext in (".gif", ".webp", ".png") else ".png"
            dest_path = os.path.join(char_folder, f"{role}{save_ext}")

            # Limpiar versiones anteriores de esta expresión con distinta extensión dentro de la carpeta
            for old_ext in (".png", ".gif", ".webp"):
                old_candidate = os.path.join(char_folder, f"{role}{old_ext}")
                if old_ext != save_ext and os.path.exists(old_candidate):
                    try:
                        os.remove(old_candidate)
                    except Exception:
                        pass

            try:
                if os.path.abspath(file_path) != os.path.abspath(dest_path):
                    if ext in (".jpg", ".jpeg"):
                        Image.open(file_path).convert("RGBA").save(dest_path, "PNG")
                    else:
                        shutil.copy2(file_path, dest_path)
            except Exception as e:
                print(f"[Carpeta] Error copiando {file_path} a {dest_path}: {e}")
                dest_path = file_path

            log_debug(f"[CARPETA] 🖼️ Guardada expresión '{os.path.basename(dest_path)}' en carpeta de '{curr_name}'")
            target_dict[key] = dest_path
            if hasattr(self, f"{key}_path_var"):
                getattr(self, f"{key}_path_var").set(self._get_expression_display_label(dest_path))
            self._update_thumbnail(key)

            # Sincronizar esta expresión en ambos perfiles (1P y 2P) para esta misma carpeta de personaje
            for p_key, pref_k, rt_d in (
                ("player1", "a1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
                ("player2", "a2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
            ):
                prof_d = self.profiles.get(p_key, {}).get(curr_name)
                for d_obj in (prof_d, rt_d):
                    if isinstance(d_obj, dict):
                        d_obj[f"{pref_k}_{role}"] = dest_path
                        for ex_it in d_obj.get("extra_expressions", []) or []:
                            if ex_it.get("role") == role:
                                ex_it["file"] = dest_path

            if is_p1:
                self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
                self.w_live_avatar.set_character(self.p1_data, prefix="a1")
                self._save_p1_profile()
                self._refresh_p1_card_roster()
                if self.global_config.get("current_p2_profile") == curr_name:
                    self.p2_data[f"a2_{role}"] = dest_path
                    self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
            else:
                self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
                self.w_live_avatar.set_character(self.p2_data, prefix="a2")
                self._save_p2_profile()
                self._refresh_p2_card_roster()
                if self.global_config.get("current_p1_profile") == curr_name:
                    self.p1_data[f"a1_{role}"] = dest_path
                    self.p1_live_avatar.set_character(self.p1_data, prefix="a1")

            self._save_character_folder_meta(curr_name)
            self._sync_windows_images()

    def _update_thumbnail(self, key):
        entry = self.thumbnails.get(key)
        if not entry:
            return
        lbl, target_dict = entry
        path = target_dict.get(key)
        if hasattr(self, f"{key}_path_var"):
            getattr(self, f"{key}_path_var").set(self._get_expression_display_label(path))
        if lbl and path and os.path.exists(path):
            try:
                img = Image.open(path)
                img.seek(0)
                rgba = img.convert("RGBA")
                rgba.thumbnail((72, 72), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(rgba)
                lbl.configure(image=photo, text="")
                lbl.image = photo
            except Exception:
                lbl.configure(image="", text="❌", fg="#EF4444")
        elif lbl:
            lbl.configure(image="", text="❌ Sin imagen", fg="#94A3B8")

    # =========================================================================
    # --- GESTOR DE ACCESORIOS ESTILO PHOTOSHOP (CAPAS, ARRASTRE Y FRAMES) ---
    # =========================================================================
    def _open_props_manager_dialog(self, player_num):
        curr_name = self.global_config.get(
            "current_p1_profile" if player_num == 1 else "current_p2_profile",
            "Gatito Azul" if player_num == 1 else "Osito Discord"
        )
        target_dict = self.p1_data if player_num == 1 else self.p2_data
        prefix = "a1" if player_num == 1 else "a2"
        char_folder = self._get_character_folder(curr_name)
        props_dir = os.path.join(char_folder, "props")
        os.makedirs(props_dir, exist_ok=True)

        # Reconciliar accesorios desde target_dict, character.json y carpeta props/
        if "props" not in target_dict or not isinstance(target_dict["props"], list):
            target_dict["props"] = []

        meta_path = os.path.join(char_folder, "character.json")
        if not target_dict["props"] and os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta_disk = json.load(f)
                for p in meta_disk.get("props", []):
                    p_loaded = dict(p)
                    if p_loaded.get("file_rel"):
                        cand_rel = os.path.abspath(os.path.join(char_folder, p_loaded["file_rel"]))
                        if os.path.exists(cand_rel):
                            p_loaded["file"] = cand_rel
                    if not p_loaded.get("file") or not os.path.exists(p_loaded.get("file", "")):
                        cand = os.path.join(props_dir, os.path.basename(p_loaded.get("file", "")))
                        if os.path.exists(cand):
                            p_loaded["file"] = cand
                    target_dict["props"].append(p_loaded)
            except Exception as e:
                log_debug(f"[ACCESORIOS] Error leyendo character.json: {e}")

        # Detectar archivos sueltos en props/ que no estén en la lista
        known_files = {os.path.abspath(p.get("file", "")).lower() for p in target_dict["props"] if p.get("file")}
        try:
            for fname in sorted(os.listdir(props_dir)):
                if fname.lower().endswith((".png", ".gif", ".webp")):
                    fpath = os.path.abspath(os.path.join(props_dir, fname))
                    if fpath.lower() not in known_files:
                        bname = os.path.splitext(fname)[0].replace("_", " ").replace("-", " ").title()
                        target_dict["props"].append({
                            "id": f"prop_{int(time.time() * 1000)}_{len(target_dict['props'])+1}",
                            "name": bname,
                            "file": fpath,
                            "layer": "front",
                            "follows_bounce": False,
                            "offset_x": 0,
                            "offset_y": 0,
                            "scale": 100,
                            "enabled": True,
                            "visible_frames": "all",
                        })
                        known_files.add(fpath.lower())
        except Exception:
            pass

        # Normalizar estructura de todos los accesorios existentes para seguimiento confiable
        for idx, p in enumerate(target_dict["props"]):
            if not p.get("id"):
                p["id"] = f"prop_{int(time.time() * 1000)}_{idx}"
            p.setdefault("name", f"Accesorio {idx+1}")
            p.setdefault("layer", "front")
            p.setdefault("follows_bounce", False)
            p.setdefault("offset_x", 0)
            p.setdefault("offset_y", 0)
            p.setdefault("scale", 100)
            p.setdefault("rotation", 0)
            p.setdefault("enabled", True)
            p.setdefault("visible_frames", "all")

        log_debug(f"[ACCESORIOS] 🎒 Abriendo Gestor de Accesorios para {player_num}P: '{curr_name}' ({len(target_dict['props'])} accesorios)")

        # Pausar movimiento del personaje principal mientras se colocan accesorios
        self._props_editor_open_for = player_num
        live_av = self.p1_live_avatar if player_num == 1 else self.p2_live_avatar
        live_av.freeze_motion = True
        if self.current_screen == "workshop" and self.workshop_player == player_num:
            self.w_live_avatar.freeze_motion = True

        dlg = tk.Toplevel(self.root)
        dlg.title(f"🎒 Accesorios - {curr_name} ({'1P: Tú' if player_num == 1 else '2P: Amigo Discord'})")
        dlg.geometry("1000x690")
        dlg.minsize(880, 580)
        dlg.configure(bg="#E2E8F0")
        dlg.transient(self.root)

        self.root.update_idletasks()
        rx = self.root.winfo_x() + max(0, (self.root.winfo_width() - 1000) // 2)
        ry = self.root.winfo_y() + max(0, (self.root.winfo_height() - 690) // 2)
        dlg.geometry(f"+{max(10, rx)}+{max(10, ry)}")

        # Catálogo de frames disponibles del personaje
        frame_options = [
            ("idle", "Reposo (idle)"),
            ("idle_blink", "Parpadeo Reposo (idle_blink)"),
            ("talk", "Hablando (talk)"),
            ("talk_blink", "Parpadeo Hablando (talk_blink)"),
            ("scream", "Gritando (scream)"),
        ]
        for ex in target_dict.get("extra_expressions", []) or []:
            r_id = ex.get("role")
            if r_id:
                ex_label = ex.get("name") or ex.get("label") or r_id
                frame_options.append((r_id, f"Extra: {ex_label}"))
        role_to_label = dict(frame_options)
        label_to_role = {lbl: r for r, lbl in frame_options}

        # Estado del editor
        state = {
            "selected_id": target_dict["props"][0]["id"] if target_dict["props"] else None,
            "preview_role": "idle",
            "drag_pid": None,
            "drag_start_x": 0,
            "drag_start_y": 0,
            "drag_orig_ox": 0,
            "drag_orig_oy": 0,
            "sync_job": None,
        }

        # Cache de imágenes PIL ya cargadas (evita reabrir archivos del disco al arrastrar/escalar)
        char_pil_cache = {}   # role -> PIL.Image (RGBA, ya escalada para canvas 400x400)
        char_tk_cache = {}    # role -> ImageTk.PhotoImage
        prop_pil_cache = {}   # pid -> PIL.Image (RGBA, max 1024px)
        prop_tk_cache = {}    # (pid, scale) -> ImageTk.PhotoImage
        layer_thumbs_cache = {}
        canvas_prop_items = {}  # pid -> canvas item id
        prop_bboxes = {}        # pid -> (x1, y1, x2, y2)

        CANVAS_W, CANVAS_H = 400, 400
        AVAIL_W, AVAIL_H = 384, 384

        def load_char_preview_image(role):
            if role in char_tk_cache:
                return char_tk_cache[role]
            img_path = target_dict.get(f"{prefix}_{role}") or target_dict.get(f"{prefix}_idle")
            if not img_path or not os.path.exists(img_path):
                return None
            try:
                with Image.open(img_path) as im:
                    im.seek(0)
                    rgba = im.convert("RGBA")
                    iw, ih = rgba.size
                    if iw <= 0 or ih <= 0:
                        return None
                    ratio = min(AVAIL_W / iw, AVAIL_H / ih)
                    nw, nh = max(1, int(iw * ratio)), max(1, int(ih * ratio))
                    resized = rgba.resize((nw, nh), Image.Resampling.LANCZOS)
                    if target_dict.get("flip_x", False):
                        resized = resized.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    char_pil_cache[role] = resized
                    tk_im = ImageTk.PhotoImage(resized)
                    char_tk_cache[role] = tk_im
                    return tk_im
            except Exception as e:
                log_debug(f"[ACCESORIOS] Error cargando frame '{role}': {e}")
                return None

        def get_prop_raw_pil(prop):
            pid = prop["id"]
            if pid in prop_pil_cache:
                return prop_pil_cache[pid]
            f_path = prop.get("file", "")
            if not f_path or not os.path.exists(f_path):
                return None
            try:
                with Image.open(f_path) as im:
                    im.seek(0)
                    rgba = im.convert("RGBA").copy()
                    if max(rgba.size) > 420:
                        rgba.thumbnail((420, 420), Image.Resampling.LANCZOS)
                    prop_pil_cache[pid] = rgba
                    return rgba
            except Exception as e:
                log_debug(f"[ACCESORIOS] Error cargando imagen de accesorio '{prop.get('name')}': {e}")
                return None

        def get_prop_tk(prop):
            pid = prop["id"]
            sc = max(10, min(250, int(prop.get("scale", 100))))
            rot = int(float(prop.get("rotation", 0)))
            key = (pid, sc, rot)
            if key in prop_tk_cache:
                return prop_tk_cache[key]
            raw = get_prop_raw_pil(prop)
            if raw is None:
                return None
            iw, ih = raw.size
            if iw <= 0 or ih <= 0:
                return None
            ratio = min(AVAIL_W / iw, AVAIL_H / ih) * (sc / 100.0)
            nw, nh = max(1, int(iw * ratio)), max(1, int(ih * ratio))
            resized = raw.resize((nw, nh), Image.Resampling.BILINEAR)
            if rot != 0:
                resized = resized.rotate(-rot, resample=Image.Resampling.BILINEAR, expand=True)
            tk_im = ImageTk.PhotoImage(resized)
            # Mantener caché acotado por prop para no consumir RAM en exceso
            for old_k in [k for k in prop_tk_cache if k[0] == pid and k != key]:
                del prop_tk_cache[old_k]
            prop_tk_cache[key] = tk_im
            return tk_im

        def save_and_sync_all():
            props_snapshot = [dict(x) for x in target_dict["props"]]
            if curr_name in self.profiles.get("player1", {}):
                self.profiles["player1"][curr_name]["props"] = [dict(x) for x in props_snapshot]
            if curr_name in self.profiles.get("player2", {}):
                self.profiles["player2"][curr_name]["props"] = [dict(x) for x in props_snapshot]

            if player_num == 1:
                self.p1_live_avatar.update_props_fast(props_snapshot)
                if self.current_screen == "workshop" and self.workshop_player == 1:
                    self.w_live_avatar.update_props_fast(props_snapshot)
                if self.global_config.get("current_p2_profile") == curr_name:
                    self.p2_data["props"] = [dict(x) for x in props_snapshot]
                    self.p2_live_avatar.update_props_fast(props_snapshot)
                if self.avatar1_window and self.avatar1_window.winfo_exists():
                    self.avatar1_window.update_props_fast(props_snapshot)
                self._save_p1_profile()
            else:
                self.p2_live_avatar.update_props_fast(props_snapshot)
                if self.current_screen == "workshop" and self.workshop_player == 2:
                    self.w_live_avatar.update_props_fast(props_snapshot)
                if self.global_config.get("current_p1_profile") == curr_name:
                    self.p1_data["props"] = [dict(x) for x in props_snapshot]
                    self.p1_live_avatar.update_props_fast(props_snapshot)
                if self.avatar2_window and self.avatar2_window.winfo_exists():
                    self.avatar2_window.update_props_fast(props_snapshot)
                self._save_p2_profile()

            self._save_character_folder_meta(curr_name, explicit_props=props_snapshot)

        def schedule_sync(delay_ms=320):
            if state["sync_job"] is not None:
                try:
                    dlg.after_cancel(state["sync_job"])
                except Exception:
                    pass
            state["sync_job"] = dlg.after(delay_ms, lambda: (state.__setitem__("sync_job", None), save_and_sync_all()))

        def get_selected_prop():
            sid = state["selected_id"]
            if not sid:
                return None
            for p in target_dict["props"]:
                if p["id"] == sid:
                    return p
            return None

        def is_prop_visible_in_role(prop, role):
            vf = prop.get("visible_frames", "all")
            if vf == "all" or not vf:
                return True
            if isinstance(vf, list):
                return role in vf
            return True

        # --- ENCABEZADO ---
        top_f = tk.Frame(dlg, bg="#1E293B", padx=16, pady=10, highlightthickness=2, highlightbackground="#0F172A")
        top_f.pack(fill=tk.X, padx=12, pady=(10, 8))

        h_left = tk.Frame(top_f, bg="#1E293B")
        h_left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        accent_p = "#60A5FA" if player_num == 1 else "#FB7185"
        tk.Label(
            h_left, text=f"🎒 Accesorios — {curr_name}",
            font=("Segoe UI", 12, "bold"), fg=accent_p, bg="#1E293B"
        ).pack(anchor=tk.W)

        btn_bar = tk.Frame(top_f, bg="#1E293B")
        btn_bar.pack(side=tk.RIGHT)

        # --- CUERPO PRINCIPAL (2 COLUMNAS) ---
        body_f = tk.Frame(dlg, bg="#E2E8F0")
        body_f.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        # COLUMNA IZQUIERDA: LIENZO INTERACTIVO (PHOTOSHOP VIEWPORT)
        left_col = tk.Frame(body_f, bg="#FFFFFF", highlightthickness=2, highlightbackground="#334155", padx=12, pady=10)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 10))

        canvas_toolbar = tk.Frame(left_col, bg="#FFFFFF")
        canvas_toolbar.pack(fill=tk.X, pady=(0, 6))

        tk.Label(canvas_toolbar, text="Frame:", font=("Segoe UI", 8, "bold"), fg="#475569", bg="#FFFFFF").pack(side=tk.LEFT, padx=(0, 4))
        preview_frame_var = tk.StringVar(value=role_to_label.get("idle", "Reposo (idle)"))
        frame_combo = ttk.Combobox(
            canvas_toolbar, textvariable=preview_frame_var, state="readonly",
            values=[lbl for _, lbl in frame_options], width=24, font=("Segoe UI", 8)
        )
        frame_combo.pack(side=tk.LEFT)

        tk.Label(
            canvas_toolbar, text="⏸️ Personaje quieto", font=("Segoe UI", 8, "bold"),
            fg="#0369A1", bg="#E0F2FE", padx=8, pady=2
        ).pack(side=tk.RIGHT)

        editor_canvas = tk.Canvas(
            left_col, width=CANVAS_W, height=CANVAS_H, bg="#F8FAFC",
            highlightthickness=2, highlightbackground="#94A3B8", cursor="crosshair"
        )
        editor_canvas.pack()

        # Fondo tipo tablero de ajedrez sutil (estilo Photoshop transparencia)
        sq = 20
        for gy in range(0, CANVAS_H, sq):
            for gx in range(0, CANVAS_W, sq):
                col = "#FFFFFF" if ((gx // sq + gy // sq) % 2 == 0) else "#EEF2F7"
                editor_canvas.create_rectangle(gx, gy, gx + sq, gy + sq, fill=col, outline="", tags="checker_bg")

        char_canvas_item = editor_canvas.create_image(CANVAS_W // 2, CANVAS_H // 2, anchor="center")
        sel_rect_item = editor_canvas.create_rectangle(0, 0, 0, 0, outline="#0284C7", width=2, dash=(5, 3), state="hidden")
        sel_rot_stem = editor_canvas.create_line(0, 0, 0, 0, fill="#7C3AED", width=2, state="hidden")
        sel_rot_handle = editor_canvas.create_oval(0, 0, 0, 0, fill="#7C3AED", outline="#FFFFFF", width=2, state="hidden")
        sel_corner_handles = {
            "nw": editor_canvas.create_rectangle(0, 0, 0, 0, fill="#FFFFFF", outline="#0284C7", width=2, state="hidden"),
            "ne": editor_canvas.create_rectangle(0, 0, 0, 0, fill="#FFFFFF", outline="#0284C7", width=2, state="hidden"),
            "sw": editor_canvas.create_rectangle(0, 0, 0, 0, fill="#FFFFFF", outline="#0284C7", width=2, state="hidden"),
            "se": editor_canvas.create_rectangle(0, 0, 0, 0, fill="#FFFFFF", outline="#0284C7", width=2, state="hidden"),
        }
        sel_label_item = editor_canvas.create_text(0, 0, text="", fill="#0284C7", font=("Segoe UI", 8, "bold"), anchor=tk.SW, state="hidden")

        canvas_hint = tk.Label(
            left_col,
            text="💡 Clic izq: mover  |  Esquinas: escalar  |  Círculo superior: rotar  |  Rueda: zoom  |  Clic der: opciones",
            font=("Segoe UI", 8), fg="#64748B", bg="#FFFFFF"
        )
        canvas_hint.pack(pady=(6, 0))

        # COLUMNA DERECHA: CAPAS + PROPIEDADES
        right_col = tk.Frame(body_f, bg="#E2E8F0")
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Panel Capas (Layers)
        layers_panel = tk.Frame(right_col, bg="#FFFFFF", highlightthickness=2, highlightbackground="#334155", padx=10, pady=8)
        layers_panel.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        layers_hdr = tk.Frame(layers_panel, bg="#FFFFFF")
        layers_hdr.pack(fill=tk.X, pady=(0, 6))
        tk.Label(layers_hdr, text="📚 Capas", font=("Segoe UI", 9, "bold"), fg="#1E293B", bg="#FFFFFF").pack(side=tk.LEFT)
        drop_status_lbl = tk.Label(
            layers_hdr, text="Arrastra para reordenar • Clic der: menú",
            font=("Segoe UI", 8), fg="#64748B", bg="#FFFFFF"
        )
        drop_status_lbl.pack(side=tk.RIGHT)

        scroll_layers = ScrollableFrame(layers_panel, bg="#F1F5F9")
        scroll_layers.pack(fill=tk.BOTH, expand=True)
        layers_list_f = scroll_layers.content

        # Línea guía de Drag & Drop en tiempo real sobre la lista de capas
        drop_guide_line = tk.Frame(layers_list_f, bg="#2563EB", height=3)

        # Panel Propiedades de la Capa Seleccionada
        props_panel = tk.Frame(right_col, bg="#FFFFFF", highlightthickness=2, highlightbackground="#334155", padx=10, pady=8)
        props_panel.pack(fill=tk.X)

        props_hdr = tk.Label(props_panel, text="⚙️ Propiedades de la Capa", font=("Segoe UI", 9, "bold"), fg="#1E293B", bg="#FFFFFF")
        props_hdr.pack(anchor=tk.W, pady=(0, 6))
        props_form_f = tk.Frame(props_panel, bg="#FFFFFF")
        props_form_f.pack(fill=tk.X)

        # --- FUNCIONES DE RENDERIZADO DEL LIENZO ---
        sel_handle_coords = {}  # handle_name -> (x1, y1, x2, y2)

        def hide_selection_overlay():
            editor_canvas.itemconfig(sel_rect_item, state="hidden")
            editor_canvas.itemconfig(sel_label_item, state="hidden")
            editor_canvas.itemconfig(sel_rot_stem, state="hidden")
            editor_canvas.itemconfig(sel_rot_handle, state="hidden")
            for h_it in sel_corner_handles.values():
                editor_canvas.itemconfig(h_it, state="hidden")
            sel_handle_coords.clear()

        def update_selection_overlay():
            sel = get_selected_prop()
            if not sel or not sel.get("enabled", True) or not is_prop_visible_in_role(sel, state["preview_role"]):
                hide_selection_overlay()
                return
            bbox = prop_bboxes.get(sel["id"])
            if not bbox:
                hide_selection_overlay()
                return
            x1, y1, x2, y2 = bbox
            bx1, by1, bx2, by2 = x1 - 2, y1 - 2, x2 + 2, y2 + 2
            editor_canvas.coords(sel_rect_item, bx1, by1, bx2, by2)
            editor_canvas.itemconfig(sel_rect_item, state="normal")
            editor_canvas.tag_raise(sel_rect_item)

            # Tiradores de escala en las 4 esquinas
            hs = 5
            corners = {
                "nw": (bx1, by1),
                "ne": (bx2, by1),
                "sw": (bx1, by2),
                "se": (bx2, by2),
            }
            for cname, (hx, hy) in corners.items():
                h_it = sel_corner_handles[cname]
                editor_canvas.coords(h_it, hx - hs, hy - hs, hx + hs, hy + hs)
                editor_canvas.itemconfig(h_it, state="normal")
                editor_canvas.tag_raise(h_it)
                sel_handle_coords[cname] = (hx - hs - 3, hy - hs - 3, hx + hs + 3, hy + hs + 3)

            # Tirador superior de rotación
            mid_x = (bx1 + bx2) // 2
            rot_y = max(14, by1 - 22)
            editor_canvas.coords(sel_rot_stem, mid_x, by1, mid_x, rot_y)
            editor_canvas.itemconfig(sel_rot_stem, state="normal")
            editor_canvas.tag_raise(sel_rot_stem)

            rs = 6
            editor_canvas.coords(sel_rot_handle, mid_x - rs, rot_y - rs, mid_x + rs, rot_y + rs)
            editor_canvas.itemconfig(sel_rot_handle, state="normal")
            editor_canvas.tag_raise(sel_rot_handle)
            sel_handle_coords["rot"] = (mid_x - rs - 4, rot_y - rs - 4, mid_x + rs + 4, rot_y + rs + 4)

            editor_canvas.coords(sel_label_item, bx1, max(14, by1 - 4))
            editor_canvas.itemconfig(
                sel_label_item,
                text=f"{sel.get('name', 'Accesorio')} ({int(sel.get('scale', 100))}% | {int(float(sel.get('rotation', 0)))}°)",
                state="normal"
            )
            editor_canvas.tag_raise(sel_label_item)

        def render_editor_canvas():
            role = state["preview_role"]
            char_tk = load_char_preview_image(role)
            if char_tk:
                editor_canvas.itemconfig(char_canvas_item, image=char_tk, state="normal")
            else:
                editor_canvas.itemconfig(char_canvas_item, state="hidden")

            valid_pids = {p["id"] for p in target_dict["props"]}
            for old_pid in list(canvas_prop_items.keys()):
                if old_pid not in valid_pids:
                    try:
                        editor_canvas.delete(canvas_prop_items.pop(old_pid))
                    except Exception:
                        pass
                    prop_bboxes.pop(old_pid, None)

            back_items = []
            front_items = []
            prop_bboxes.clear()

            for p in target_dict["props"]:
                pid = p["id"]
                visible = bool(p.get("enabled", True)) and is_prop_visible_in_role(p, role)
                tk_im = get_prop_tk(p) if visible else None
                if not visible or tk_im is None:
                    if pid in canvas_prop_items:
                        editor_canvas.itemconfig(canvas_prop_items[pid], state="hidden")
                    continue

                px = (CANVAS_W // 2) + int(p.get("offset_x", 0))
                py = (CANVAS_H // 2) + int(p.get("offset_y", 0))
                item_id = canvas_prop_items.get(pid)
                if item_id is None:
                    item_id = editor_canvas.create_image(px, py, anchor="center", image=tk_im)
                    canvas_prop_items[pid] = item_id
                else:
                    editor_canvas.itemconfig(item_id, image=tk_im, state="normal")
                    editor_canvas.coords(item_id, px, py)

                pw, ph = tk_im.width(), tk_im.height()
                prop_bboxes[pid] = (px - pw // 2, py - ph // 2, px + pw // 2, py + ph // 2)

                if p.get("layer", "front") == "back":
                    back_items.append(item_id)
                else:
                    front_items.append(item_id)

            # Z-order exacto: checker_bg -> back_items -> char -> front_items -> selection
            editor_canvas.tag_lower("checker_bg")
            for b_it in back_items:
                editor_canvas.tag_lower(b_it, char_canvas_item)
            prev_it = char_canvas_item
            for f_it in front_items:
                editor_canvas.tag_raise(f_it, prev_it)
                prev_it = f_it

            update_selection_overlay()

        # --- ACCIONES DE CAPA (BORRAR, MOVER, VISIBILIDAD, CONTEXT MENU) ---
        def delete_prop_by_id(pid, confirm=True):
            prop_ref = next((p for p in target_dict["props"] if p["id"] == pid), None)
            if not prop_ref:
                return
            if confirm and not messagebox.askyesno("Quitar Accesorio", f"¿Quitar el accesorio '{prop_ref.get('name')}'?", parent=dlg):
                return
            f_path = prop_ref.get("file", "")
            target_dict["props"].remove(prop_ref)
            # Limpiar archivo en props/ si no lo usa otro accesorio
            if f_path and os.path.exists(f_path):
                try:
                    in_props_dir = os.path.abspath(f_path).lower().startswith(os.path.abspath(props_dir).lower())
                    still_used = any(os.path.abspath(x.get("file", "")).lower() == os.path.abspath(f_path).lower() for x in target_dict["props"])
                    if in_props_dir and not still_used:
                        os.remove(f_path)
                except Exception:
                    pass
            prop_pil_cache.pop(pid, None)
            for k in [k for k in prop_tk_cache if k[0] == pid]:
                del prop_tk_cache[k]
            if state["selected_id"] == pid:
                state["selected_id"] = target_dict["props"][0]["id"] if target_dict["props"] else None
            save_and_sync_all()
            refresh_all_ui()

        def move_layer(pid, direction):
            # En la lista de capas (Photoshop), el índice más alto está arriba (más al frente)
            props = target_dict["props"]
            idx = next((i for i, p in enumerate(props) if p["id"] == pid), -1)
            if idx < 0:
                return
            new_idx = idx + direction  # +1 = subir capa, -1 = bajar capa
            if 0 <= new_idx < len(props):
                props[idx], props[new_idx] = props[new_idx], props[idx]
                save_and_sync_all()
                refresh_all_ui()

        def show_prop_context_menu(event, pid):
            prop_ref = next((p for p in target_dict["props"] if p["id"] == pid), None)
            if not prop_ref:
                return
            state["selected_id"] = pid
            refresh_layers_list()
            refresh_properties_panel()
            update_selection_overlay()

            menu = tk.Menu(dlg, tearoff=0)
            menu.add_command(
                label=f"🗑️ Quitar '{prop_ref.get('name', 'Accesorio')}'",
                command=lambda: delete_prop_by_id(pid, confirm=False)
            )
            menu.add_separator()
            vis_lbl = "👁️ Ocultar capa" if prop_ref.get("enabled", True) else "👁️ Mostrar capa"
            def toggle_vis():
                prop_ref["enabled"] = not prop_ref.get("enabled", True)
                save_and_sync_all()
                refresh_all_ui()
            menu.add_command(label=vis_lbl, command=toggle_vis)

            if prop_ref.get("layer", "front") == "front":
                def send_back():
                    prop_ref["layer"] = "back"
                    save_and_sync_all()
                    refresh_all_ui()
                menu.add_command(label="🔄 Enviar detrás del personaje", command=send_back)
            else:
                def send_front():
                    prop_ref["layer"] = "front"
                    save_and_sync_all()
                    refresh_all_ui()
                menu.add_command(label="🔄 Traer delante del personaje", command=send_front)

            menu.add_command(label="⬆️ Subir capa", command=lambda: move_layer(pid, 1))
            menu.add_command(label="⬇️ Bajar capa", command=lambda: move_layer(pid, -1))
            menu.add_separator()
            def center_pos():
                prop_ref["offset_x"] = 0
                prop_ref["offset_y"] = 0
                save_and_sync_all()
                refresh_all_ui()
            menu.add_command(label="⌖ Centrar posición (0, 0)", command=center_pos)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        # --- PANEL DE CAPAS CON DRAG & DROP EN TIEMPO REAL ---
        layer_drag_state = {"pid": None, "start_y": 0, "dragging": False, "drop_target": None}
        layer_row_widgets = []  # lista de dicts: {"pid", "layer", "widget", "idx_in_layer"}
        char_div_holder = {"widget": None}

        def compute_drop_target(y_root):
            """Determina en qué capa (front/back) e índice se soltará el elemento arrastrado, y la Y de la línea guía."""
            div_w = char_div_holder.get("widget")
            list_top_y = layers_list_f.winfo_rooty()
            if not layer_row_widgets:
                return ("front", 0, 4, "Delante del personaje")

            # Verificar posición respecto al divisor del personaje
            div_cy = (div_w.winfo_rooty() + div_w.winfo_height() // 2) if (div_w and div_w.winfo_exists()) else 999999
            target_layer = "front" if y_root < div_cy else "back"
            same_layer_rows = [r for r in layer_row_widgets if r["layer"] == target_layer]

            if not same_layer_rows:
                if target_layer == "front":
                    guide_y = max(2, (div_w.winfo_rooty() - list_top_y - 3) if div_w else 2)
                    return ("front", 0, guide_y, "Delante del personaje")
                else:
                    guide_y = ((div_w.winfo_rooty() + div_w.winfo_height() - list_top_y + 2) if div_w else 2)
                    return ("back", 0, guide_y, "Detrás del personaje")

            for pos_idx, r_info in enumerate(same_layer_rows):
                rw = r_info["widget"]
                ry = rw.winfo_rooty()
                rh = rw.winfo_height()
                if y_root < ry + rh // 2:
                    guide_y = max(2, ry - list_top_y - 2)
                    txt = "Al frente (arriba)" if (target_layer == "front" and pos_idx == 0) else (
                        "Delante del personaje" if target_layer == "front" else "Detrás del personaje"
                    )
                    return (target_layer, pos_idx, guide_y, txt)

            last_rw = same_layer_rows[-1]["widget"]
            guide_y = (last_rw.winfo_rooty() + last_rw.winfo_height() - list_top_y + 1)
            txt = "Delante del personaje" if target_layer == "front" else "Al fondo (detrás)"
            return (target_layer, len(same_layer_rows), guide_y, txt)

        def apply_layer_drop(pid, target_layer, visual_pos_idx):
            props = target_dict["props"]
            dragged = next((p for p in props if p["id"] == pid), None)
            if not dragged:
                return
            props.remove(dragged)
            dragged["layer"] = target_layer

            # Reconstruir orden: en target_dict["props"], índice menor = más atrás, índice mayor = más al frente.
            # En la UI visual (de arriba a abajo), visual_pos_idx=0 es el más al frente (último en la sublista).
            front_rev = [p for p in reversed(props) if p.get("layer", "front") != "back"]
            back_rev = [p for p in reversed(props) if p.get("layer", "front") == "back"]

            if target_layer == "front":
                ins = max(0, min(len(front_rev), visual_pos_idx))
                front_rev.insert(ins, dragged)
            else:
                ins = max(0, min(len(back_rev), visual_pos_idx))
                back_rev.insert(ins, dragged)

            target_dict["props"] = list(reversed(back_rev)) + list(reversed(front_rev))
            save_and_sync_all()
            refresh_all_ui()

        def render_layer_row(p):
            pid = p["id"]
            is_sel = (pid == state["selected_id"])
            row_bg = "#DBEAFE" if is_sel else "#FFFFFF"
            border_col = "#2563EB" if is_sel else "#CBD5E1"

            row = tk.Frame(layers_list_f, bg=row_bg, highlightthickness=2 if is_sel else 1, highlightbackground=border_col, padx=6, pady=4, cursor="hand2")
            row.pack(fill=tk.X, padx=4, pady=2)
            layer_row_widgets.append({"pid": pid, "layer": p.get("layer", "front"), "widget": row})

            # Grip de arrastre sutil
            grip_lbl = tk.Label(row, text="⋮⋮", font=("Segoe UI", 9, "bold"), fg="#94A3B8", bg=row_bg, cursor="fleur")
            grip_lbl.pack(side=tk.LEFT, padx=(0, 4))

            # Botón Ojo (Visibilidad)
            en = p.get("enabled", True)
            eye_btn = tk.Button(
                row, text="👁️" if en else "🚫", font=("Segoe UI", 9),
                bg="#ECFDF5" if en else "#F1F5F9", fg="#15803D" if en else "#94A3B8",
                relief="flat", bd=0, padx=4, cursor="hand2",
                command=lambda _p=p: (_p.__setitem__("enabled", not _p.get("enabled", True)), save_and_sync_all(), refresh_all_ui())
            )
            eye_btn.pack(side=tk.LEFT, padx=(0, 6))

            # Miniatura 32x32
            f_path = p.get("file", "")
            if pid not in layer_thumbs_cache:
                layer_thumbs_cache[pid] = self._get_character_thumbnail(f_path, size=(32, 32))
            th = layer_thumbs_cache.get(pid)
            if th:
                th_lbl = tk.Label(row, image=th, bg=row_bg)
            else:
                th_lbl = tk.Label(row, text="📦", font=("Segoe UI", 12), bg=row_bg)
            th_lbl.pack(side=tk.LEFT, padx=(0, 8))

            # Info de capa (Nombre + Badges)
            info_f = tk.Frame(row, bg=row_bg)
            info_f.pack(side=tk.LEFT, fill=tk.X, expand=True)

            name_lbl = tk.Label(
                info_f, text=p.get("name", "Accesorio"),
                font=("Segoe UI", 9, "bold"), fg="#0F172A" if en else "#94A3B8", bg=row_bg, anchor=tk.W
            )
            name_lbl.pack(fill=tk.X)

            badges_f = tk.Frame(info_f, bg=row_bg)
            badges_f.pack(fill=tk.X)
            is_front = (p.get("layer", "front") != "back")
            b1 = tk.Label(
                badges_f, text="🎭 Delante" if is_front else "🪑 Detrás",
                font=("Segoe UI", 7, "bold"),
                bg="#E0F2FE" if is_front else "#FEF3C7",
                fg="#0369A1" if is_front else "#B45309", padx=4
            )
            b1.pack(side=tk.LEFT, padx=(0, 4))

            vf = p.get("visible_frames", "all")
            if vf == "all" or not vf:
                vf_txt, vf_bg, vf_fg = "Todos", "#DCFCE7", "#15803D"
            else:
                first_lbl = role_to_label.get(vf[0], vf[0]).split(" (")[0]
                vf_txt = f"Solo: {first_lbl}" if len(vf) == 1 else f"{len(vf)} frames"
                vf_bg, vf_fg = "#F3E8FF", "#7E22CE"
            b2 = tk.Label(badges_f, text=vf_txt, font=("Segoe UI", 7, "bold"), bg=vf_bg, fg=vf_fg, padx=4)
            b2.pack(side=tk.LEFT)

            # Acción rápida sutil para quitar
            del_ico = tk.Button(
                row, text="✕", font=("Segoe UI", 8, "bold"),
                bg=row_bg, fg="#94A3B8", activeforeground="#DC2626", activebackground="#FEE2E2",
                relief="flat", bd=0, padx=5, cursor="hand2",
                command=lambda _pid=pid: delete_prop_by_id(_pid, confirm=True)
            )
            del_ico.pack(side=tk.RIGHT, padx=(4, 0))

            def on_layer_press(e, _pid=pid):
                layer_drag_state["pid"] = _pid
                layer_drag_state["start_y"] = e.y_root
                layer_drag_state["dragging"] = False
                layer_drag_state["drop_target"] = None

            def on_layer_motion(e):
                if not layer_drag_state["pid"]:
                    return
                if not layer_drag_state["dragging"] and abs(e.y_root - layer_drag_state["start_y"]) > 5:
                    layer_drag_state["dragging"] = True
                    row.config(bg="#EFF6FF")
                if layer_drag_state["dragging"]:
                    t_layer, t_idx, guide_y, hint_txt = compute_drop_target(e.y_root)
                    layer_drag_state["drop_target"] = (t_layer, t_idx)
                    line_col = "#2563EB" if t_layer == "front" else "#D97706"
                    drop_guide_line.config(bg=line_col)
                    drop_guide_line.place(in_=layers_list_f, x=4, y=guide_y, relwidth=0.96, height=3)
                    drop_guide_line.lift()
                    drop_status_lbl.config(text=f"↳ {hint_txt}", fg=line_col, font=("Segoe UI", 8, "bold"))

            def on_layer_release(_e, _pid=pid):
                drop_guide_line.place_forget()
                drop_status_lbl.config(text="Arrastra para reordenar • Clic der: menú", fg="#64748B", font=("Segoe UI", 8))
                was_dragging = layer_drag_state["dragging"]
                target = layer_drag_state["drop_target"]
                drag_pid = layer_drag_state["pid"]
                layer_drag_state["pid"] = None
                layer_drag_state["dragging"] = False
                layer_drag_state["drop_target"] = None

                if was_dragging and target and drag_pid:
                    apply_layer_drop(drag_pid, target[0], target[1])
                else:
                    state["selected_id"] = _pid
                    refresh_layers_list()
                    refresh_properties_panel()
                    update_selection_overlay()

            for w_bind in (row, grip_lbl, th_lbl, info_f, name_lbl, badges_f, b1, b2):
                w_bind.bind("<ButtonPress-1>", on_layer_press)
                w_bind.bind("<B1-Motion>", on_layer_motion)
                w_bind.bind("<ButtonRelease-1>", on_layer_release)
                w_bind.bind("<Button-3>", lambda e, _pid=pid: show_prop_context_menu(e, _pid))

        def refresh_layers_list():
            drop_guide_line.place_forget()
            layer_row_widgets.clear()
            for w in layers_list_f.winfo_children():
                if w is drop_guide_line:
                    continue
                w.destroy()

            props = target_dict["props"]
            if not props:
                char_div_holder["widget"] = None
                empty_l = tk.Frame(layers_list_f, bg="#F1F5F9", pady=28)
                empty_l.pack(fill=tk.BOTH, expand=True)
                tk.Label(empty_l, text="🎒 Sin accesorios", font=("Segoe UI", 10, "bold"), fg="#475569", bg="#F1F5F9").pack()
                tk.Label(
                    empty_l, text="Haz clic en '➕ Añadir Accesorio' arriba\npara agregar sombreros, lentes, sillas, etc.",
                    font=("Segoe UI", 8), fg="#64748B", bg="#F1F5F9", justify=tk.CENTER
                ).pack(pady=(4, 0))
                return

            front_list = [p for p in reversed(props) if p.get("layer", "front") != "back"]
            back_list = [p for p in reversed(props) if p.get("layer", "front") == "back"]

            for p in front_list:
                render_layer_row(p)

            # Separador visual del personaje para distinguir Delante vs Detrás
            char_div = tk.Frame(layers_list_f, bg="#CBD5E1", padx=8, pady=4)
            char_div.pack(fill=tk.X, padx=4, pady=4)
            char_div_holder["widget"] = char_div
            tk.Label(
                char_div, text="👤 PERSONAJE  (arrastra arriba = delante | abajo = detrás)",
                font=("Segoe UI", 7, "bold"), fg="#334155", bg="#CBD5E1"
            ).pack()

            for p in back_list:
                render_layer_row(p)

        # --- PANEL DE PROPIEDADES DE LA CAPA SELECCIONADA ---
        def refresh_properties_panel():
            for w in props_form_f.winfo_children():
                w.destroy()

            prop = get_selected_prop()
            if not prop:
                tk.Label(
                    props_form_f, text="Selecciona una capa o haz clic en un accesorio en el lienzo para editarlo.",
                    font=("Segoe UI", 8), fg="#64748B", bg="#FFFFFF", pady=14
                ).pack()
                return

            # 1. TRANSFORMACIÓN (Escala + Rotación)
            sec_trans = tk.LabelFrame(
                props_form_f, text=" 🔧 Transformación ", font=("Segoe UI", 8, "bold"),
                fg="#334155", bg="#F8FAFC", padx=8, pady=6, bd=1, relief="solid"
            )
            sec_trans.pack(fill=tk.X, pady=(0, 6))

            r_sc = tk.Frame(sec_trans, bg="#F8FAFC")
            r_sc.pack(fill=tk.X, pady=(0, 4))
            sc_lbl = tk.Label(r_sc, text=f"Escala: {int(prop.get('scale', 100))}%", font=("Segoe UI", 8, "bold"), fg="#0284C7", bg="#F8FAFC", width=13, anchor=tk.W)
            sc_lbl.pack(side=tk.LEFT)

            def on_scale_drag(val):
                vi = int(float(val))
                prop["scale"] = vi
                sc_lbl.config(text=f"Escala: {vi}%")
                render_editor_canvas()
                schedule_sync(180)

            sc_slider = ttk.Scale(r_sc, from_=10, to=250, value=prop.get("scale", 100), command=on_scale_drag)
            sc_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

            r_rot = tk.Frame(sec_trans, bg="#F8FAFC")
            r_rot.pack(fill=tk.X)
            rot_lbl = tk.Label(r_rot, text=f"Rotación: {int(float(prop.get('rotation', 0)))}°", font=("Segoe UI", 8, "bold"), fg="#7C3AED", bg="#F8FAFC", width=13, anchor=tk.W)
            rot_lbl.pack(side=tk.LEFT)

            def on_rot_drag(val):
                vi = int(float(val))
                prop["rotation"] = vi
                rot_lbl.config(text=f"Rotación: {vi}°")
                render_editor_canvas()
                schedule_sync(180)

            rot_slider = ttk.Scale(r_rot, from_=-180, to=180, value=float(prop.get("rotation", 0)), command=on_rot_drag)
            rot_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

            def reset_rot():
                prop["rotation"] = 0
                rot_slider.set(0)
                rot_lbl.config(text="Rotación: 0°")
                render_editor_canvas()
                schedule_sync(80)

            tk.Button(
                r_rot, text="↺ 0°", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#475569",
                relief="solid", bd=1, padx=5, cursor="hand2", command=reset_rot
            ).pack(side=tk.LEFT, padx=(2, 0))

            # 2. POSICIONAMIENTO (X, Y + Centrar)
            sec_pos = tk.LabelFrame(
                props_form_f, text=" 📍 Posicionamiento ", font=("Segoe UI", 8, "bold"),
                fg="#334155", bg="#F8FAFC", padx=8, pady=6, bd=1, relief="solid"
            )
            sec_pos.pack(fill=tk.X, pady=(0, 6))

            r_pos = tk.Frame(sec_pos, bg="#F8FAFC")
            r_pos.pack(fill=tk.X)

            x_var = tk.IntVar(value=int(prop.get("offset_x", 0)))
            y_var = tk.IntVar(value=int(prop.get("offset_y", 0)))

            def apply_xy(*_args):
                try:
                    prop["offset_x"] = int(x_var.get())
                    prop["offset_y"] = int(y_var.get())
                    render_editor_canvas()
                    schedule_sync(180)
                except Exception:
                    pass

            tk.Label(r_pos, text="X:", font=("Segoe UI", 8, "bold"), fg="#475569", bg="#F8FAFC").pack(side=tk.LEFT)
            sp_x = tk.Spinbox(r_pos, from_=-400, to=400, textvariable=x_var, width=6, font=("Segoe UI", 8), command=apply_xy)
            sp_x.pack(side=tk.LEFT, padx=(3, 10))
            sp_x.bind("<Return>", apply_xy)

            tk.Label(r_pos, text="Y:", font=("Segoe UI", 8, "bold"), fg="#475569", bg="#F8FAFC").pack(side=tk.LEFT)
            sp_y = tk.Spinbox(r_pos, from_=-400, to=400, textvariable=y_var, width=6, font=("Segoe UI", 8), command=apply_xy)
            sp_y.pack(side=tk.LEFT, padx=(3, 12))
            sp_y.bind("<Return>", apply_xy)

            def reset_center():
                x_var.set(0)
                y_var.set(0)
                prop["offset_x"] = 0
                prop["offset_y"] = 0
                render_editor_canvas()
                schedule_sync(80)

            tk.Button(
                r_pos, text="+ Centrar", font=("Segoe UI", 8, "bold"), bg="#E0F2FE", fg="#0369A1",
                activebackground="#BAE6FD", relief="solid", bd=1, padx=8, cursor="hand2", command=reset_center
            ).pack(side=tk.RIGHT)

            # 3. CONFIGURACIÓN Y VISIBILIDAD (Nombre, Delante/Detrás, Seguir movimiento, Visibilidad compacta)
            sec_cfg = tk.LabelFrame(
                props_form_f, text=" 🎛️ Configuración y Visibilidad ", font=("Segoe UI", 8, "bold"),
                fg="#334155", bg="#F8FAFC", padx=8, pady=6, bd=1, relief="solid"
            )
            sec_cfg.pack(fill=tk.X)

            r_cfg1 = tk.Frame(sec_cfg, bg="#F8FAFC")
            r_cfg1.pack(fill=tk.X, pady=(0, 5))

            tk.Label(r_cfg1, text="Nombre:", font=("Segoe UI", 8, "bold"), fg="#475569", bg="#F8FAFC").pack(side=tk.LEFT, padx=(0, 4))
            n_var = tk.StringVar(value=prop.get("name", "Accesorio"))
            def on_name_write(*_args):
                prop["name"] = n_var.get()
                schedule_sync(250)
            n_var.trace_add("write", on_name_write)
            ttk.Entry(r_cfg1, textvariable=n_var, font=("Segoe UI", 8, "bold"), width=16).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

            layer_var = tk.StringVar(value=prop.get("layer", "front"))
            def on_layer_chg():
                prop["layer"] = layer_var.get()
                render_editor_canvas()
                refresh_layers_list()
                schedule_sync(80)
            tk.Radiobutton(r_cfg1, text="🎭 Delante", variable=layer_var, value="front", bg="#F8FAFC", font=("Segoe UI", 8), command=on_layer_chg).pack(side=tk.LEFT)
            tk.Radiobutton(r_cfg1, text="🪑 Detrás", variable=layer_var, value="back", bg="#F8FAFC", font=("Segoe UI", 8), command=on_layer_chg).pack(side=tk.LEFT)

            r_cfg2 = tk.Frame(sec_cfg, bg="#F8FAFC")
            r_cfg2.pack(fill=tk.X)

            vf_curr = prop.get("visible_frames", "all")
            is_all = (vf_curr == "all" or not vf_curr)
            vis_opt_all = "🌐 Todos los frames"
            vis_opt_spec = "🎯 Solo frames específicos..."
            vis_combo_var = tk.StringVar(value=vis_opt_all if is_all else vis_opt_spec)

            tk.Label(r_cfg2, text="Mostrar:", font=("Segoe UI", 8, "bold"), fg="#475569", bg="#F8FAFC").pack(side=tk.LEFT, padx=(0, 4))
            vis_combo = ttk.Combobox(
                r_cfg2, textvariable=vis_combo_var, state="readonly",
                values=[vis_opt_all, vis_opt_spec], width=22, font=("Segoe UI", 8)
            )
            vis_combo.pack(side=tk.LEFT)

            bounce_var = tk.BooleanVar(value=bool(prop.get("follows_bounce", False)))
            tk.Checkbutton(
                r_cfg2, text="Seguir movimiento", variable=bounce_var, bg="#F8FAFC", font=("Segoe UI", 8, "bold"), fg="#334155",
                command=lambda: (prop.__setitem__("follows_bounce", bounce_var.get()), schedule_sync(80))
            ).pack(side=tk.RIGHT)

            frames_box = tk.Frame(sec_cfg, bg="#F8FAFC")
            frame_chk_vars = {}

            def sync_vf_from_checks():
                chosen = [r for r, v in frame_chk_vars.items() if v.get()]
                if not chosen:
                    chosen = [state["preview_role"]]
                    if state["preview_role"] in frame_chk_vars:
                        frame_chk_vars[state["preview_role"]].set(True)
                prop["visible_frames"] = chosen
                render_editor_canvas()
                refresh_layers_list()
                schedule_sync(100)

            def on_vis_combo_changed(_e=None):
                if vis_combo_var.get() == vis_opt_all:
                    prop["visible_frames"] = "all"
                    frames_box.pack_forget()
                else:
                    if prop.get("visible_frames") == "all" or not isinstance(prop.get("visible_frames"), list):
                        prop["visible_frames"] = [state["preview_role"]]
                    frames_box.pack(fill=tk.X, pady=(5, 0))
                    for r, v in frame_chk_vars.items():
                        v.set(r in prop["visible_frames"])
                render_editor_canvas()
                refresh_layers_list()
                schedule_sync(100)

            vis_combo.bind("<<ComboboxSelected>>", on_vis_combo_changed)

            col_i = 0
            for r_id, r_lbl in frame_options:
                short_lbl = r_lbl.split(" (")[0]
                v = tk.BooleanVar(value=(isinstance(vf_curr, list) and r_id in vf_curr))
                frame_chk_vars[r_id] = v
                cb = tk.Checkbutton(frames_box, text=short_lbl, variable=v, bg="#F8FAFC", font=("Segoe UI", 8), command=sync_vf_from_checks)
                cb.grid(row=col_i // 3, column=col_i % 3, sticky=tk.W, padx=(0, 6))
                col_i += 1

            if not is_all:
                frames_box.pack(fill=tk.X, pady=(5, 0))

        def refresh_all_ui():
            render_editor_canvas()
            refresh_layers_list()
            refresh_properties_panel()

        # --- EVENTOS DE RATÓN EN EL LIENZO (MOVER, TIRADORES ESCALA/ROTACIÓN, RUEDA, CLIC DER) ---
        def hit_test_handle(cx, cy):
            for hname, (hx1, hy1, hx2, hy2) in sel_handle_coords.items():
                if hx1 <= cx <= hx2 and hy1 <= cy <= hy2:
                    return hname
            return None

        def hit_test_prop(cx, cy):
            role = state["preview_role"]
            # Buscar de arriba hacia abajo en orden visual (front top->bottom, luego back top->bottom)
            front_props = [p for p in target_dict["props"] if p.get("layer", "front") != "back"]
            back_props = [p for p in target_dict["props"] if p.get("layer", "front") == "back"]
            for p in reversed(front_props):
                if not p.get("enabled", True) or not is_prop_visible_in_role(p, role):
                    continue
                bb = prop_bboxes.get(p["id"])
                if bb and bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]:
                    return p
            for p in reversed(back_props):
                if not p.get("enabled", True) or not is_prop_visible_in_role(p, role):
                    continue
                bb = prop_bboxes.get(p["id"])
                if bb and bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]:
                    return p
            return None

        def on_canvas_motion(event):
            if state.get("drag_pid"):
                return
            h_hit = hit_test_handle(event.x, event.y)
            if h_hit == "rot":
                editor_canvas.config(cursor="exchange")
            elif h_hit in ("nw", "se"):
                editor_canvas.config(cursor="size_nw_se")
            elif h_hit in ("ne", "sw"):
                editor_canvas.config(cursor="size_ne_sw")
            elif hit_test_prop(event.x, event.y):
                editor_canvas.config(cursor="fleur")
            else:
                editor_canvas.config(cursor="crosshair")

        def on_canvas_lclick(event):
            h_hit = hit_test_handle(event.x, event.y)
            sel = get_selected_prop()
            if h_hit and sel:
                state["drag_pid"] = sel["id"]
                state["drag_mode"] = "rotate" if h_hit == "rot" else "scale"
                state["drag_start_x"] = event.x
                state["drag_start_y"] = event.y
                state["drag_orig_scale"] = int(sel.get("scale", 100))
                px = (CANVAS_W // 2) + int(sel.get("offset_x", 0))
                py = (CANVAS_H // 2) + int(sel.get("offset_y", 0))
                state["drag_start_dist"] = max(8.0, math.hypot(event.x - px, event.y - py))
                return

            hit = hit_test_prop(event.x, event.y)
            if hit:
                state["selected_id"] = hit["id"]
                state["drag_pid"] = hit["id"]
                state["drag_mode"] = "move"
                state["drag_start_x"] = event.x
                state["drag_start_y"] = event.y
                state["drag_orig_ox"] = int(hit.get("offset_x", 0))
                state["drag_orig_oy"] = int(hit.get("offset_y", 0))
                refresh_layers_list()
                refresh_properties_panel()
                update_selection_overlay()
            else:
                state["drag_pid"] = None
                state["drag_mode"] = None

        def on_canvas_ldrag(event):
            pid = state["drag_pid"]
            if not pid:
                return
            prop = next((p for p in target_dict["props"] if p["id"] == pid), None)
            if not prop:
                return

            mode = state.get("drag_mode", "move")
            px = (CANVAS_W // 2) + int(prop.get("offset_x", 0))
            py = (CANVAS_H // 2) + int(prop.get("offset_y", 0))

            if mode == "rotate":
                ang = math.degrees(math.atan2(event.y - py, event.x - px)) + 90.0
                if ang > 180.0:
                    ang -= 360.0
                elif ang < -180.0:
                    ang += 360.0
                prop["rotation"] = int(round(ang))
                render_editor_canvas()
                return

            if mode == "scale":
                cur_dist = max(4.0, math.hypot(event.x - px, event.y - py))
                ratio = cur_dist / max(8.0, state.get("drag_start_dist", 20.0))
                new_sc = max(10, min(250, int(round(state.get("drag_orig_scale", 100) * ratio))))
                if new_sc != prop.get("scale"):
                    prop["scale"] = new_sc
                    render_editor_canvas()
                return

            dx = event.x - state["drag_start_x"]
            dy = event.y - state["drag_start_y"]
            new_ox = max(-400, min(400, state["drag_orig_ox"] + dx))
            new_oy = max(-400, min(400, state["drag_orig_oy"] + dy))
            prop["offset_x"] = new_ox
            prop["offset_y"] = new_oy

            item_id = canvas_prop_items.get(pid)
            tk_im = get_prop_tk(prop)
            if item_id and tk_im:
                npx = (CANVAS_W // 2) + new_ox
                npy = (CANVAS_H // 2) + new_oy
                editor_canvas.coords(item_id, npx, npy)
                pw, ph = tk_im.width(), tk_im.height()
                prop_bboxes[pid] = (npx - pw // 2, npy - ph // 2, npx + pw // 2, npy + ph // 2)
                update_selection_overlay()

        def on_canvas_lrelease(_event):
            if state["drag_pid"]:
                state["drag_pid"] = None
                state["drag_mode"] = None
                refresh_properties_panel()
                schedule_sync(120)

        def on_canvas_wheel(event):
            prop = get_selected_prop()
            if not prop:
                return
            step = 5 if event.delta > 0 else -5
            new_sc = max(10, min(250, int(prop.get("scale", 100)) + step))
            if new_sc != prop.get("scale"):
                prop["scale"] = new_sc
                render_editor_canvas()
                refresh_properties_panel()
                schedule_sync(180)

        def on_canvas_rclick(event):
            hit = hit_test_prop(event.x, event.y)
            if hit:
                show_prop_context_menu(event, hit["id"])

        editor_canvas.bind("<Motion>", on_canvas_motion)
        editor_canvas.bind("<Button-1>", on_canvas_lclick)
        editor_canvas.bind("<B1-Motion>", on_canvas_ldrag)
        editor_canvas.bind("<ButtonRelease-1>", on_canvas_lrelease)
        editor_canvas.bind("<MouseWheel>", on_canvas_wheel)
        editor_canvas.bind("<Button-3>", on_canvas_rclick)

        def on_preview_frame_changed(_e=None):
            state["preview_role"] = label_to_role.get(preview_frame_var.get(), "idle")
            render_editor_canvas()

        frame_combo.bind("<<ComboboxSelected>>", on_preview_frame_changed)

        # --- PREGUNTAR SI VA EN TODOS LADOS O SOLO EN UN FRAME AL AÑADIR ---
        def ask_visibility_scope(prop_name):
            scope_res = {"confirmed": False, "visible_frames": "all"}
            q_dlg = tk.Toplevel(dlg)
            q_dlg.title("Visibilidad del Accesorio")
            q_dlg.geometry("420x230")
            q_dlg.resizable(False, False)
            q_dlg.configure(bg="#FFFFFF")
            q_dlg.transient(dlg)
            q_dlg.grab_set()

            dlg.update_idletasks()
            qx = dlg.winfo_x() + (dlg.winfo_width() - 420) // 2
            qy = dlg.winfo_y() + (dlg.winfo_height() - 230) // 2
            q_dlg.geometry(f"+{max(10, qx)}+{max(10, qy)}")

            tk.Label(
                q_dlg, text=f"¿Dónde quieres mostrar '{prop_name}'?",
                font=("Segoe UI", 10, "bold"), fg="#1E293B", bg="#FFFFFF", wraplength=380
            ).pack(pady=(14, 10), padx=14, anchor=tk.W)

            mode_v = tk.StringVar(value="all")
            picked_lbl = tk.StringVar(value=role_to_label.get(state["preview_role"], "Reposo (idle)"))

            tk.Radiobutton(
                q_dlg, text="🌐 En todos lados (Todos los frames / estados)",
                variable=mode_v, value="all", bg="#FFFFFF", font=("Segoe UI", 9, "bold"), fg="#15803D"
            ).pack(anchor=tk.W, padx=18, pady=2)

            tk.Radiobutton(
                q_dlg, text="🎯 Solo en un frame en particular:",
                variable=mode_v, value="one", bg="#FFFFFF", font=("Segoe UI", 9, "bold"), fg="#7E22CE"
            ).pack(anchor=tk.W, padx=18, pady=(6, 2))

            f_pick = ttk.Combobox(
                q_dlg, textvariable=picked_lbl, state="readonly",
                values=[lbl for _, lbl in frame_options], width=32, font=("Segoe UI", 9)
            )
            f_pick.pack(anchor=tk.W, padx=38, pady=(2, 12))

            btns_q = tk.Frame(q_dlg, bg="#FFFFFF")
            btns_q.pack(fill=tk.X, padx=14, pady=(4, 12))

            def on_ok():
                scope_res["confirmed"] = True
                if mode_v.get() == "all":
                    scope_res["visible_frames"] = "all"
                else:
                    r_sel = label_to_role.get(picked_lbl.get(), state["preview_role"])
                    scope_res["visible_frames"] = [r_sel]
                q_dlg.destroy()

            ttk.Button(btns_q, text="✅ Añadir Accesorio", style="DSBlue.TButton", command=on_ok).pack(side=tk.RIGHT, padx=(6, 0))
            ttk.Button(btns_q, text="Cancelar", style="DSButton.TButton", command=q_dlg.destroy).pack(side=tk.RIGHT)

            dlg.wait_window(q_dlg)
            return scope_res

        def add_prop_action():
            file_path = filedialog.askopenfilename(
                parent=dlg,
                title="Seleccionar accesorio (PNG transparente o GIF animado)",
                filetypes=[
                    ("Imágenes y Animaciones", "*.png;*.gif;*.webp"),
                    ("PNG con transparencia", "*.png"),
                    ("GIF / WEBP Animado", "*.gif;*.webp"),
                    ("Todos los archivos", "*.*")
                ]
            )
            if not file_path:
                return

            base_name = os.path.splitext(os.path.basename(file_path))[0]
            pretty_name = base_name.replace("_", " ").replace("-", " ").title()

            scope = ask_visibility_scope(pretty_name)
            if not scope["confirmed"]:
                return

            ext = os.path.splitext(file_path)[1].lower()
            save_ext = ext if ext in (".gif", ".webp", ".png") else ".png"

            dest_filename = f"{self._sanitize_folder_name(base_name)}{save_ext}"
            dest_path = os.path.join(props_dir, dest_filename)

            c = 1
            while os.path.exists(dest_path) and os.path.abspath(dest_path) != os.path.abspath(file_path):
                dest_filename = f"{self._sanitize_folder_name(base_name)}_{c}{save_ext}"
                dest_path = os.path.join(props_dir, dest_filename)
                c += 1

            try:
                if os.path.abspath(file_path) != os.path.abspath(dest_path):
                    shutil.copy2(file_path, dest_path)
            except Exception as e:
                log_debug(f"[ACCESORIOS] Error copiando {file_path} a {dest_path}: {e}")
                dest_path = file_path

            # Si es solo para un frame y está viendo otro, cambiar vista previa a ese frame
            vf = scope["visible_frames"]
            if isinstance(vf, list) and vf and state["preview_role"] not in vf:
                state["preview_role"] = vf[0]
                preview_frame_var.set(role_to_label.get(vf[0], vf[0]))

            new_prop = {
                "id": f"prop_{int(time.time() * 1000)}",
                "name": pretty_name,
                "file": dest_path,
                "layer": "front",
                "follows_bounce": False,
                "offset_x": 0,
                "offset_y": 0,
                "scale": 50,
                "rotation": 0,
                "enabled": True,
                "visible_frames": vf,
            }

            target_dict["props"].append(new_prop)
            state["selected_id"] = new_prop["id"]
            log_debug(f"[ACCESORIOS] ✅ Añadido accesorio '{new_prop['name']}' para '{curr_name}' (visible_frames={vf})")
            save_and_sync_all()
            refresh_all_ui()

        def on_close_dialog():
            if state["sync_job"] is not None:
                try:
                    dlg.after_cancel(state["sync_job"])
                except Exception:
                    pass
                save_and_sync_all()
            self._props_editor_open_for = None
            self._refresh_eco_mode()
            dlg.destroy()

        dlg.protocol("WM_DELETE_WINDOW", on_close_dialog)

        tk.Button(
            btn_bar, text="➕ Añadir Accesorio", font=("Segoe UI", 9, "bold"),
            bg="#2563EB", fg="#FFFFFF", activebackground="#1D4ED8", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=12, pady=5, cursor="hand2", command=add_prop_action
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            btn_bar, text="✅ Listo", font=("Segoe UI", 9, "bold"),
            bg="#16A34A", fg="#FFFFFF", activebackground="#15803D", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=16, pady=5, cursor="hand2", command=on_close_dialog
        ).pack(side=tk.LEFT)

        refresh_all_ui()

    # =========================================================================
    # --- CREACIÓN, DUPLICACIÓN, RENOMBRADO Y BORRADO DE CARPETAS ---
    # =========================================================================
    def _prompt_create_character(self, player_num):
        log_debug(f"[ACCION] ➕ Abriendo diálogo para crear carpeta de personaje (Jugador {player_num})")
        dlg = tk.Toplevel(self.root)
        player_label = "1P: Tú" if player_num == 1 else "2P: Amigo Discord"
        dlg.title(f"Nueva Carpeta de Personaje - {player_label}")
        dlg.geometry("430x340")
        dlg.resizable(False, False)
        dlg.configure(bg="#DFE5EE")
        dlg.transient(self.root)
        dlg.grab_set()

        self.root.update_idletasks()
        rx = self.root.winfo_x() + (self.root.winfo_width() - 430) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - 340) // 2
        dlg.geometry(f"+{max(10, rx)}+{max(10, ry)}")

        f = tk.Frame(dlg, bg="#FFFFFF", padx=20, pady=16, highlightthickness=2, highlightbackground="#242E3B")
        f.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(
            f, text=f"📁 Crear Carpeta de Personaje ({player_label})",
            font=("Segoe UI", 11, "bold"), fg="#3671C6" if player_num == 1 else "#E45B47", bg="#FFFFFF"
        ).pack(anchor=tk.W, pady=(0, 8))

        tk.Label(f, text="Nombre del personaje (se creará su carpeta en 'personajes/'):", font=("Segoe UI", 9, "bold"), fg="#1E293B", bg="#FFFFFF").pack(anchor=tk.W, pady=(0, 3))
        name_entry = ttk.Entry(f, width=32, font=("Segoe UI", 10))
        name_entry.pack(fill=tk.X, pady=(0, 12))
        name_entry.focus_set()

        tk.Label(f, text="Elige cuántos fotogramas tendrá su carpeta:", font=("Segoe UI", 9, "bold"), fg="#1E293B", bg="#FFFFFF").pack(anchor=tk.W, pady=(0, 6))
        mode_var = tk.StringVar(value="4_states")

        card_modes = tk.Frame(f, bg="#F1F5F9", padx=10, pady=8, highlightthickness=1, highlightbackground="#CBD5E1")
        card_modes.pack(fill=tk.X, pady=(0, 12))

        rb_pro = tk.Radiobutton(
            card_modes, text="✨ Modo Pro (4 poses + Grito)", variable=mode_var, value="4_states",
            bg="#F1F5F9", fg="#1E293B", selectcolor="#FFFFFF", font=("Segoe UI", 9, "bold")
        )
        rb_pro.pack(anchor=tk.W)
        tk.Label(card_modes, text="   idle.png, idle_blink.png, talk.png, talk_blink.png, scream.png", font=("Segoe UI", 8), fg="#64748B", bg="#F1F5F9").pack(anchor=tk.W, pady=(0, 6))

        rb_simple = tk.Radiobutton(
            card_modes, text="⚡ Modo Simple (2 poses + Grito)", variable=mode_var, value="2_states",
            bg="#F1F5F9", fg="#1E293B", selectcolor="#FFFFFF", font=("Segoe UI", 9, "bold")
        )
        rb_simple.pack(anchor=tk.W)
        tk.Label(card_modes, text="   idle.png, talk.png (+ scream.png opcional)", font=("Segoe UI", 8), fg="#64748B", bg="#F1F5F9").pack(anchor=tk.W)

        btn_row = tk.Frame(f, bg="#FFFFFF")
        btn_row.pack(fill=tk.X, side=tk.BOTTOM)

        result = [None]

        def on_confirm(event=None):
            name = name_entry.get().strip()
            if not name:
                messagebox.showwarning("Atención", "Por favor ingresa un nombre para el personaje.", parent=dlg)
                return
            if name in self.profiles.get("player1", {}) or name in self.profiles.get("player2", {}):
                messagebox.showwarning("Atención", f"Ya existe una carpeta de personaje llamada '{name}'.", parent=dlg)
                return
            result[0] = (name, mode_var.get())
            dlg.destroy()

        def on_cancel(event=None):
            dlg.destroy()

        ttk.Button(btn_row, text="Cancelar", style="DSButton.TButton", command=on_cancel).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_row, text="✅ Crear Carpeta", style="DSBlue.TButton", command=on_confirm).pack(side=tk.RIGHT, padx=4)

        dlg.bind("<Return>", on_confirm)
        dlg.bind("<Escape>", on_cancel)

        dlg.wait_window()
        return result[0]

    def _create_p1_profile_dialog(self):
        res = self._prompt_create_character(1)
        if not res:
            log_debug("[ACCION] Creación de personaje 1P cancelada")
            return
        name, mode = res
        log_debug(f"[CARPETA] ✅ Creando carpeta de personaje '{name}' (Modo: {mode})")
        self._register_new_character_folder(name, mode, default_prefix="a1")
        self._select_p1_character(name)
        self._set_card_view(1, "active")

    def _create_p2_profile_dialog(self):
        res = self._prompt_create_character(2)
        if not res:
            log_debug("[ACCION] Creación de personaje 2P cancelada")
            return
        name, mode = res
        log_debug(f"[CARPETA] ✅ Creando carpeta de personaje '{name}' (Modo: {mode})")
        self._register_new_character_folder(name, mode, default_prefix="a2")
        if self.global_config.get("game_mode") == "single":
            self._set_game_mode("coop")
        self._select_p2_character(name)
        self._set_card_view(2, "active")

    def _duplicate_workshop_profile(self):
        is_p1 = (self.workshop_player == 1)
        curr = self.global_config.get(f"current_p{self.workshop_player}_profile")
        name = simpledialog.askstring("Copiar Carpeta de Personaje", f"Nombre para la nueva carpeta copia de '{curr}':")
        if name:
            name = name.strip()
            if not name or name in self.profiles["player1"]:
                return
            log_debug(f"[CARPETA] 📋 Duplicando carpeta '{curr}' -> '{name}'")
            src_folder = self._get_character_folder(curr)
            dst_folder = self._get_character_folder(name)
            p1_copy = dict(self.profiles["player1"].get(curr, self.p1_data))
            p2_copy = dict(self.profiles["player2"].get(curr, self.p2_data))

            for role in ("idle", "idle_blink", "talk", "talk_blink", "scream"):
                s_file = self._find_role_file_in_folder(src_folder, role)
                ext = os.path.splitext(s_file)[1] if os.path.exists(s_file) else ".png"
                d_file = os.path.join(dst_folder, f"{role}{ext}")
                if os.path.exists(s_file):
                    try:
                        shutil.copy2(s_file, d_file)
                    except Exception:
                        pass
                p1_copy[f"a1_{role}"] = d_file
                p2_copy[f"a2_{role}"] = d_file

            # Duplicar carpeta de props/accesorios si existe
            src_props = os.path.join(src_folder, "props")
            dst_props = os.path.join(dst_folder, "props")
            os.makedirs(dst_props, exist_ok=True)
            if os.path.exists(src_props):
                for pf in os.listdir(src_props):
                    s_pf = os.path.join(src_props, pf)
                    if os.path.isfile(s_pf):
                        try:
                            shutil.copy2(s_pf, os.path.join(dst_props, pf))
                        except Exception:
                            pass

            copied_props = []
            for p_item in p1_copy.get("props", []):
                p_dup = dict(p_item)
                if p_dup.get("file"):
                    p_dup["file"] = os.path.join(dst_props, os.path.basename(p_dup["file"]))
                copied_props.append(p_dup)
            p1_copy["props"] = copied_props
            p2_copy["props"] = [dict(x) for x in copied_props]

            self.profiles["player1"][name] = p1_copy
            self.profiles["player2"][name] = p2_copy
            self._save_character_folder_meta(name)
            self.save_profiles_to_disk()
            if is_p1:
                self._select_p1_character(name)
            else:
                self._select_p2_character(name)

    def _rename_workshop_profile(self):
        is_p1 = (self.workshop_player == 1)
        curr = self.global_config.get(f"current_p{self.workshop_player}_profile")
        name = simpledialog.askstring("Renombrar Carpeta de Personaje", f"Nuevo nombre para la carpeta '{curr}':", initialvalue=curr)
        if name:
            name = name.strip()
            if not name or name == curr or name in self.profiles["player1"]:
                return
            log_debug(f"[CARPETA] ✏️ Renombrando carpeta '{curr}' -> '{name}'")
            old_folder = self._get_character_folder(curr)
            new_folder = os.path.abspath(os.path.join(CHARACTERS_DIR, self._sanitize_folder_name(name)))
            try:
                if os.path.exists(old_folder) and not os.path.exists(new_folder):
                    os.rename(old_folder, new_folder)
                else:
                    os.makedirs(new_folder, exist_ok=True)
            except Exception as e:
                print(f"[Carpeta] Error renombrando carpeta: {e}")
                os.makedirs(new_folder, exist_ok=True)

            p1_entry = self.profiles["player1"].pop(curr, dict(self.p1_data))
            p2_entry = self.profiles["player2"].pop(curr, dict(self.p2_data))
            for role in ("idle", "idle_blink", "talk", "talk_blink", "scream"):
                n_file = self._find_role_file_in_folder(new_folder, role)
                p1_entry[f"a1_{role}"] = n_file
                p2_entry[f"a2_{role}"] = n_file

            new_props = os.path.join(new_folder, "props")
            for p_dict in (p1_entry, p2_entry):
                for p_item in p_dict.get("props", []):
                    if p_item.get("file"):
                        p_item["file"] = os.path.join(new_props, os.path.basename(p_item["file"]))

            self.profiles["player1"][name] = p1_entry
            self.profiles["player2"][name] = p2_entry

            if self.global_config.get("current_p1_profile") == curr:
                self.global_config["current_p1_profile"] = name
            if self.global_config.get("current_p2_profile") == curr:
                self.global_config["current_p2_profile"] = name

            self._save_character_folder_meta(name)
            self.save_profiles_to_disk()
            if is_p1:
                self._select_p1_character(name)
            else:
                self._select_p2_character(name)

    def _delete_workshop_profile(self):
        is_p1 = (self.workshop_player == 1)
        curr = self.global_config.get(f"current_p{self.workshop_player}_profile")
        if len(self.profiles["player1"]) <= 1:
            messagebox.showwarning("Atención", "Debes tener al menos una carpeta de personaje guardada.")
            return

        if messagebox.askyesno("Confirmar", f"¿Eliminar el personaje '{curr}' y sus fotogramas?"):
            log_debug(f"[CARPETA] 🗑️ Eliminando personaje '{curr}' y su carpeta")
            folder_path = os.path.abspath(os.path.join(CHARACTERS_DIR, self._sanitize_folder_name(curr)))
            self.profiles["player1"].pop(curr, None)
            self.profiles["player2"].pop(curr, None)
            try:
                if os.path.exists(folder_path):
                    shutil.rmtree(folder_path, ignore_errors=True)
            except Exception:
                pass

            first = list(self.profiles["player1"].keys())[0]
            self.save_profiles_to_disk()
            if self.global_config.get("current_p1_profile") == curr:
                self._select_p1_character(first)
            if self.global_config.get("current_p2_profile") == curr:
                self._select_p2_character(first)
            if is_p1:
                self._select_p1_character(self.global_config.get("current_p1_profile", first))
            else:
                self._select_p2_character(self.global_config.get("current_p2_profile", first))

    # =========================================================================
    # --- SELECCIÓN Y ACTIVACIÓN DE PERSONAJE ---
    # =========================================================================
    def _select_p1_character(self, name):
        if name not in self.profiles.get("player1", {}):
            return

        is_already_active = (self.global_config.get("current_p1_profile") == name)
        log_debug(f"[ACCION] 🎮 1P seleccionó personaje: '{name}' {'(ya en uso)' if is_already_active else ''}")

        self.global_config["current_p1_profile"] = name
        prof_p1 = self.profiles["player1"][name]
        self.p1_data.update(prof_p1)
        self.p1_data["flip_x"] = bool(prof_p1.get("flip_x", False))
        self.p1_data["props"] = [dict(x) for x in (prof_p1.get("props") or [])]
        self.p1_data["extra_expressions"] = [dict(x) for x in (prof_p1.get("extra_expressions") or [])]

        self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
        self._refresh_p1_card_roster()
        self._sync_audio_combos_selection()

        if self.current_screen == "workshop" and self.workshop_player == 1:
            self.w_live_avatar.set_character(self.p1_data, prefix="a1")
            self._refresh_workshop_ui()

        # Actualizar umbrales dinámicamente en el motor de audio SIN reiniciar streams
        if hasattr(self, "audio_engine") and self.audio_engine:
            self.audio_engine.mic_threshold = float(self.p1_data.get("mic_threshold", 20))
            self.audio_engine.mic_scream_threshold = float(self.p1_data.get("scream_threshold", 55))

        self._sync_windows_images()
        self.save_global_config()
        self.save_profiles_to_disk()

    def _select_p2_character(self, name):
        if name not in self.profiles.get("player2", {}):
            return

        is_already_active = (self.global_config.get("current_p2_profile") == name)
        log_debug(f"[ACCION] 🎧 2P seleccionó personaje: '{name}' {'(ya en uso)' if is_already_active else ''}")

        self.global_config["current_p2_profile"] = name
        prof_p2 = self.profiles["player2"][name]
        self.p2_data.update(prof_p2)
        self.p2_data["flip_x"] = bool(prof_p2.get("flip_x", False))
        self.p2_data["props"] = [dict(x) for x in (prof_p2.get("props") or [])]
        self.p2_data["extra_expressions"] = [dict(x) for x in (prof_p2.get("extra_expressions") or [])]

        self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
        self._refresh_p2_card_roster()
        self._sync_audio_combos_selection()

        if self.current_screen == "workshop" and self.workshop_player == 2:
            self.w_live_avatar.set_character(self.p2_data, prefix="a2")
            self._refresh_workshop_ui()

        # Actualizar umbrales dinámicamente en el motor de audio SIN reiniciar streams
        if hasattr(self, "audio_engine") and self.audio_engine:
            self.audio_engine.discord_threshold = float(self.p2_data.get("discord_threshold", 25))
            self.audio_engine.discord_scream_threshold = float(self.p2_data.get("scream_threshold", 55))

        self._sync_windows_images()
        self.save_global_config()
        self.save_profiles_to_disk()

    # =========================================================================
    # --- EVENTOS DE CALIBRACIÓN Y AUDIO (LOBBY Y TALLER) ---
    # =========================================================================
    def _on_lobby_meter_press(self, player_num, event, force_mode=None):
        canvas = self.p1_mini_meter if player_num == 1 else self.p2_mini_meter
        w = max(10, canvas.winfo_width())
        pct = max(1, min(95, int(round((event.x / w) * 100.0))))

        data = self.p1_data if player_num == 1 else self.p2_data
        has_scream = self._character_has_scream(data)
        v_key = "mic_threshold" if player_num == 1 else "discord_threshold"
        voice_t = int(data.get(v_key, 20 if player_num == 1 else 25))
        scream_t = int(data.get("scream_threshold", 55))

        if not has_scream:
            self._dragging_meter_target[player_num] = "voice"
        elif force_mode in ("voice", "scream"):
            self._dragging_meter_target[player_num] = force_mode
        else:
            # Si hace clic más cerca de la línea de grito, arrastra grito; si no, arrastra voz
            dist_voice = abs(pct - voice_t)
            dist_scream = abs(pct - scream_t)
            self._dragging_meter_target[player_num] = "scream" if dist_scream < dist_voice else "voice"

        self._apply_lobby_meter_value(player_num, pct)

    def _on_lobby_meter_drag(self, player_num, event):
        canvas = self.p1_mini_meter if player_num == 1 else self.p2_mini_meter
        w = max(10, canvas.winfo_width())
        pct = max(1, min(95, int(round((event.x / w) * 100.0))))
        self._apply_lobby_meter_value(player_num, pct)

    def _on_lobby_meter_release(self, player_num, event):
        target = self._dragging_meter_target.get(player_num, "voice")
        if player_num == 1:
            self._save_p1_profile()
            val = self.p1_data["scream_threshold"] if target == "scream" else self.p1_data["mic_threshold"]
            log_debug(f"[CALIBRACION LOBBY] P1 Umbral ({target}) guardado en {val}%")
        else:
            self._save_p2_profile()
            val = self.p2_data["scream_threshold"] if target == "scream" else self.p2_data["discord_threshold"]
            log_debug(f"[CALIBRACION LOBBY] P2 Umbral ({target}) guardado en {val}%")

    def _apply_lobby_meter_value(self, player_num, pct):
        target = self._dragging_meter_target.get(player_num, "voice")
        if player_num == 1:
            has_scream = self._character_has_scream(self.p1_data)
            if target == "scream" and has_scream:
                min_s = max(20, int(self.p1_data.get("mic_threshold", 20)) + 5)
                val = max(min_s, min(95, pct))
                self.p1_data["scream_threshold"] = val
                self.audio_engine.mic_scream_threshold = float(val)
            else:
                max_v = min(80, int(self.p1_data.get("scream_threshold", 55)) - 5) if has_scream else 80
                val = max(1, min(max_v, pct))
                self.p1_data["mic_threshold"] = val
                self.audio_engine.mic_threshold = float(val)

            if hasattr(self, "p1_meter_info_lbl"):
                if has_scream:
                    self.p1_meter_info_lbl.config(
                        text=f"🤫 Voz: {int(self.p1_data['mic_threshold'])}%  |  💥 Grito: {int(self.p1_data.get('scream_threshold', 55))}%"
                    )
                else:
                    self.p1_meter_info_lbl.config(
                        text=f"🤫 Voz: {int(self.p1_data['mic_threshold'])}%"
                    )
        else:
            has_scream = self._character_has_scream(self.p2_data)
            if target == "scream" and has_scream:
                min_s = max(20, int(self.p2_data.get("discord_threshold", 25)) + 5)
                val = max(min_s, min(95, pct))
                self.p2_data["scream_threshold"] = val
                self.audio_engine.discord_scream_threshold = float(val)
            else:
                max_v = min(80, int(self.p2_data.get("scream_threshold", 55)) - 5) if has_scream else 80
                val = max(1, min(max_v, pct))
                self.p2_data["discord_threshold"] = val
                self.audio_engine.discord_threshold = float(val)

            if hasattr(self, "p2_meter_info_lbl"):
                if has_scream:
                    self.p2_meter_info_lbl.config(
                        text=f"🤫 Voz: {int(self.p2_data['discord_threshold'])}%  |  💥 Grito: {int(self.p2_data.get('scream_threshold', 55))}%"
                    )
                else:
                    self.p2_meter_info_lbl.config(
                        text=f"🤫 Voz: {int(self.p2_data['discord_threshold'])}%"
                    )

    def _on_p1_lobby_device_changed(self, event=None):
        if not hasattr(self, "p1_lobby_dev_combo"):
            return
        idx = self.p1_lobby_dev_combo.current()
        if 0 <= idx < len(self.mic_devices):
            dev = self.mic_devices[idx]
            self.p1_data["mic_device_name"] = dev["name"]
            log_debug(f"[AUDIO LOBBY] P1 Cambió micrófono a: '{dev['name']}'")
            self._start_audio_engine()
            self._save_p1_profile()
            self._sync_audio_combos_selection()

    def _on_p2_lobby_device_changed(self, event=None):
        if not hasattr(self, "p2_lobby_dev_combo"):
            return
        idx = self.p2_lobby_dev_combo.current()
        if 0 <= idx < len(self.discord_sources):
            src = self.discord_sources[idx]
            self.p2_data["discord_source_id"] = src["id"]
            log_debug(f"[AUDIO LOBBY] P2 Cambió fuente Discord a: '{src['name']}'")
            self._start_audio_engine()
            self._save_p2_profile()
            self._sync_audio_combos_selection()

    def _manual_refresh_devices(self):
        log_debug("[AUDIO] 🔄 Refrescando lista de micrófonos y fuentes de Discord...")
        self._refresh_audio_devices()
        self._start_audio_engine()

    # =========================================================================
    # --- AUTO-CALIBRACIÓN INTELIGENTE EN 3 SEGUNDOS (🪄 AUTO) ---
    # =========================================================================
    def _start_auto_calibration(self, player_num):
        if getattr(self, "_auto_cal_running", False):
            return
        self._auto_cal_running = True
        self._auto_cal_samples = []
        log_debug(f"[AUTO-CALIBRACION] 🪄 Iniciando medición de 3 segundos para Jugador {player_num}...")
        self._sample_auto_calibration(player_num, remaining_ticks=50)

    def _sample_auto_calibration(self, player_num, remaining_ticks):
        if not getattr(self, "_auto_cal_running", False):
            return

        lvl = float(self.mic_level if player_num == 1 else self.discord_level)
        self._auto_cal_samples.append(lvl)

        secs_left = max(1, (remaining_ticks * 50 + 999) // 1000)
        btn_lobby = getattr(self, "p1_auto_cal_btn" if player_num == 1 else "p2_auto_cal_btn", None)
        if btn_lobby and btn_lobby.winfo_exists():
            btn_lobby.config(text=f"⏳ {secs_left}s...", bg="#FDE047", fg="#0F172A")

        if hasattr(self, "w_auto_cal_btn") and self.w_auto_cal_btn.winfo_exists() and self.workshop_player == player_num:
            self.w_auto_cal_btn.config(text=f"⏳ Midiendo ({secs_left}s)...", bg="#FDE047", fg="#0F172A")

        if remaining_ticks > 0:
            self.root.after(50, lambda: self._sample_auto_calibration(player_num, remaining_ticks - 1))
        else:
            self._finish_auto_calibration(player_num)

    def _finish_auto_calibration(self, player_num):
        self._auto_cal_running = False
        samples = sorted(self._auto_cal_samples) if self._auto_cal_samples else [0.0]
        n = len(samples)

        # Percentil 30 = piso de ruido ambiental; Percentil 85 = voz media; Máximo = pico
        noise_floor = samples[min(n - 1, int(n * 0.30))]
        high_level = samples[min(n - 1, int(n * 0.85))]
        peak_level = samples[-1]

        # Si hubo voz clara durante la prueba (diferencia > 12% entre ruido y voz alta), calibrar entre ambos
        if (high_level - noise_floor) > 12.0:
            new_voice = int(round(noise_floor + (high_level - noise_floor) * 0.42))
            new_Voice_clamped = max(5, min(68, new_voice))
            new_scream = max(new_Voice_clamped + 24, min(92, int(round(max(high_level + 22, peak_level + 12)))))
        else:
            # Solo ruido ambiental de fondo: colocar el umbral justo por encima del ruido del cuarto
            new_Voice_clamped = max(6, min(65, int(round(noise_floor + 8.0))))
            new_scream = max(45, min(90, new_Voice_clamped + 36))

        if player_num == 1:
            self.p1_data["mic_threshold"] = new_Voice_clamped
            self.p1_data["scream_threshold"] = new_scream
            self.audio_engine.mic_threshold = float(new_Voice_clamped)
            self.audio_engine.mic_scream_threshold = float(new_scream)
            self._save_p1_profile()
            self._refresh_p1_card_roster()
            if hasattr(self, "p1_auto_cal_btn") and self.p1_auto_cal_btn.winfo_exists():
                self.p1_auto_cal_btn.config(text="✅ ¡Listo!", bg="#DCFCE7", fg="#15803D")
                self.root.after(
                    2000,
                    lambda: self.p1_auto_cal_btn.config(text="🪄 Auto (3s)", bg="#E0F2FE", fg="#0369A1")
                    if hasattr(self, "p1_auto_cal_btn") and self.p1_auto_cal_btn.winfo_exists() else None
                )
        else:
            self.p2_data["discord_threshold"] = new_Voice_clamped
            self.p2_data["scream_threshold"] = new_scream
            self.audio_engine.discord_threshold = float(new_Voice_clamped)
            self.audio_engine.discord_scream_threshold = float(new_scream)
            self._save_p2_profile()
            self._refresh_p2_card_roster()
            if hasattr(self, "p2_auto_cal_btn") and self.p2_auto_cal_btn.winfo_exists():
                self.p2_auto_cal_btn.config(text="✅ ¡Listo!", bg="#DCFCE7", fg="#15803D")
                self.root.after(
                    2000,
                    lambda: self.p2_auto_cal_btn.config(text="🪄 Auto (3s)", bg="#FFEDD5", fg="#C2410C")
                    if hasattr(self, "p2_auto_cal_btn") and self.p2_auto_cal_btn.winfo_exists() else None
                )

        if self.current_screen == "workshop" and self.workshop_player == player_num:
            self.w_thresh_scale.set(new_Voice_clamped)
            self.w_thresh_val_lbl.config(text=f"{new_Voice_clamped}%")
            self.w_scream_scale.set(new_scream)
            self.w_scream_val_lbl.config(text=f"{new_scream}%")
            if hasattr(self, "w_auto_cal_btn") and self.w_auto_cal_btn.winfo_exists():
                self.w_auto_cal_btn.config(text="✅ ¡Auto-Calibrado!", bg="#DCFCE7", fg="#15803D")
                self.root.after(
                    2000,
                    lambda: self.w_auto_cal_btn.config(text="🪄 Auto-Calibrar (3s)", bg="#E0F2FE", fg="#0369A1")
                    if hasattr(self, "w_auto_cal_btn") and self.w_auto_cal_btn.winfo_exists() else None
                )

        log_debug(
            f"[AUTO-CALIBRACION] ✅ {player_num}P completado -> Ruido base: {noise_floor:.1f}%, "
            f"Voz fijada en: {new_Voice_clamped}%, Grito fijado en: {new_scream}%"
        )

    def _on_workshop_thresh_slider(self, val):
        val_int = int(float(val))
        self.w_thresh_val_lbl.config(text=f"{val_int}%")
        if self.workshop_player == 1:
            self.p1_data["mic_threshold"] = val_int
            self.audio_engine.mic_threshold = float(val_int)
            self._save_p1_profile()
            log_debug(f"[CALIBRACION] P1 Sensibilidad de voz ajustada a {val_int}%")
        else:
            self.p2_data["discord_threshold"] = val_int
            self.audio_engine.discord_threshold = float(val_int)
            self._save_p2_profile()
            log_debug(f"[CALIBRACION] P2 Sensibilidad Discord ajustada a {val_int}%")

    def _on_workshop_scream_slider(self, val):
        val_int = int(float(val))
        self.w_scream_val_lbl.config(text=f"{val_int}%")
        if self.workshop_player == 1:
            self.p1_data["scream_threshold"] = val_int
            self.audio_engine.mic_scream_threshold = float(val_int)
            self._save_p1_profile()
            log_debug(f"[CALIBRACION] P1 Umbral de grito ajustado a {val_int}%")
        else:
            self.p2_data["scream_threshold"] = val_int
            self.audio_engine.discord_scream_threshold = float(val_int)
            self._save_p2_profile()
            log_debug(f"[CALIBRACION] P2 Umbral de grito ajustado a {val_int}%")

    def _on_workshop_device_changed(self, event=None):
        idx = self.w_audio_combo.current()
        if idx < 0:
            return

        if self.workshop_player == 1:
            if idx < len(self.mic_devices):
                dev = self.mic_devices[idx]
                self.p1_data["mic_device_name"] = dev["name"]
                log_debug(f"[AUDIO] P1 Cambió dispositivo de micrófono a: '{dev['name']}'")
                self._start_audio_engine()
                self._save_p1_profile()
                self._sync_audio_combos_selection()
        else:
            if idx < len(self.discord_sources):
                src = self.discord_sources[idx]
                self.p2_data["discord_source_id"] = src["id"]
                log_debug(f"[AUDIO] P2 Cambió fuente de Discord a: '{src['name']}'")
                self._start_audio_engine()
                self._save_p2_profile()
                self._sync_audio_combos_selection()

    # =========================================================================
    # --- GESTIÓN ROBUSTA DE MODO SINGLE / CO-OP (AÑADIR Y QUITAR JUGADOR 2) ---
    # =========================================================================
    def _set_game_mode(self, mode):
        if getattr(self, "_mode_initialized", False) and self.global_config.get("game_mode") == mode and mode == "coop":
            return
        self._mode_initialized = True
        self.global_config["game_mode"] = mode
        log_debug(f"[ACCION] 👥 Modo de juego cambiado a: {'Co-op (2 Jugadores - 2P Activo)' if mode == 'coop' else 'Solo (1 Jugador - 2P Desactivado)'}")

        if mode == "single":
            self._set_card_view(2, "blank")

            if self.avatar2_window and self.avatar2_window.winfo_exists():
                try:
                    self.avatar2_window.destroy()
                except Exception:
                    pass
            self.avatar2_window = None

            self.discord_talking = False
            self.discord_level = 0.0
            self.p2_is_screaming = False
        else:
            if self.card_has_selected.get(2, False):
                self._set_card_view(2, "active")
            else:
                self._set_card_view(2, "list")

            # Si las ventanas OBS ya están abiertas, abrir la ventana del avatar 2 de inmediato
            if self.avatar1_window and self.avatar1_window.winfo_exists():
                if not (self.avatar2_window and self.avatar2_window.winfo_exists()):
                    self._open_avatar2_window_only()

        self._start_audio_engine()
        self.save_global_config()

    def _toggle_player_mute(self, player_num):
        if player_num == 1:
            muted = self.audio_engine.toggle_mic_mute()
            log_debug(f"[AUDIO] 🔇 1P Micrófono {'silenciado' if muted else 'activado'}")
            if self.avatar1_window and self.avatar1_window.winfo_exists():
                self.avatar1_window.is_muted = muted
                if muted:
                    self.avatar1_window.set_talking(False)
                    self.avatar1_window.set_screaming(False)
                self.avatar1_window._update_display()
        else:
            muted = self.audio_engine.toggle_discord_mute()
            log_debug(f"[AUDIO] 🔇 2P Discord {'silenciado' if muted else 'activado'}")
            if self.avatar2_window and self.avatar2_window.winfo_exists():
                self.avatar2_window.is_muted = muted
                if muted:
                    self.avatar2_window.set_talking(False)
                    self.avatar2_window.set_screaming(False)
                self.avatar2_window._update_display()
        self._sync_mute_buttons()

    def _sync_mute_buttons(self):
        p1_muted = getattr(self.audio_engine, "mic_muted", False)
        p2_muted = getattr(self.audio_engine, "discord_muted", False)
        if hasattr(self, "p1_mute_btn") and self.p1_mute_btn.winfo_exists():
            if p1_muted:
                self.p1_mute_btn.config(text="🔊 Activar", bg="#EF4444", fg="#FFFFFF")
            else:
                self.p1_mute_btn.config(text="🔇 Silenciar", bg="#1E293B", fg="#F8FAFC")
        if hasattr(self, "p2_mute_btn") and self.p2_mute_btn.winfo_exists():
            if p2_muted:
                self.p2_mute_btn.config(text="🔊 Activar", bg="#EF4444", fg="#FFFFFF")
            else:
                self.p2_mute_btn.config(text="🔇 Silenciar", bg="#1E293B", fg="#F8FAFC")

    def _on_bg_color_changed(self, event=None):
        colors = ["#00FF00", "#0000FF", "#FF00FF", "#000000"]
        c = colors[self.bg_combo.current()]
        self.global_config["bg_color"] = c
        log_debug(f"[CONFIG] Color de fondo croma cambiado a: '{c}'")
        if self.avatar1_window and self.avatar1_window.winfo_exists():
            self.avatar1_window.update_bg_color(c)
        if self.avatar2_window and self.avatar2_window.winfo_exists():
            self.avatar2_window.update_bg_color(c)
        self.save_global_config()

    def _on_bounce_toggle(self):
        b = self.bounce_var.get()
        self.global_config["bounce_enabled"] = b
        log_debug(f"[CONFIG] Rebote de voz: {'Activado' if b else 'Desactivado'}")
        if hasattr(self, "p1_live_avatar"):
            self.p1_live_avatar.bounce_enabled = b
        if hasattr(self, "p2_live_avatar"):
            self.p2_live_avatar.bounce_enabled = b
        if hasattr(self, "w_live_avatar"):
            self.w_live_avatar.bounce_enabled = b
        if self.avatar1_window and self.avatar1_window.winfo_exists():
            self.avatar1_window.bounce_enabled = b
        if self.avatar2_window and self.avatar2_window.winfo_exists():
            self.avatar2_window.bounce_enabled = b
        self.save_global_config()

    def _on_squash_toggle(self):
        sq = self.squash_var.get()
        self.global_config["squash_enabled"] = sq
        log_debug(f"[CONFIG] Efecto elástico (Squash & Stretch): {'Activado' if sq else 'Desactivado'}")
        if hasattr(self, "p1_live_avatar"):
            self.p1_live_avatar.squash_enabled = sq
            self.p1_live_avatar.squash_state = 0
            self.p1_live_avatar._render()
        if hasattr(self, "p2_live_avatar"):
            self.p2_live_avatar.squash_enabled = sq
            self.p2_live_avatar.squash_state = 0
            self.p2_live_avatar._render()
        if hasattr(self, "w_live_avatar"):
            self.w_live_avatar.squash_enabled = sq
            self.w_live_avatar.squash_state = 0
            self.w_live_avatar._render()
        if self.avatar1_window and self.avatar1_window.winfo_exists():
            self.avatar1_window.squash_enabled = sq
            self.avatar1_window.squash_state = 0
            self.avatar1_window._update_display()
        if self.avatar2_window and self.avatar2_window.winfo_exists():
            self.avatar2_window.squash_enabled = sq
            self.avatar2_window.squash_state = 0
            self.avatar2_window._update_display()
        self.save_global_config()

    def _on_hysteresis_toggle(self):
        enabled = bool(self.hysteresis_var.get())
        self.global_config["hysteresis_enabled"] = enabled
        self.audio_engine.hysteresis_ratio = 0.70 if enabled else 1.0
        log_debug(f"[CONFIG] Línea de retención de voz (histéresis): {'Activada' if enabled else 'Desactivada'}")
        self.save_global_config()

    def _apply_congruence_to_all(self):
        c = bool(self.global_config.get("congruence_enabled", True))
        for attr in ("p1_live_avatar", "p2_live_avatar", "w_live_avatar", "avatar1_window", "avatar2_window"):
            w = getattr(self, attr, None)
            if w and getattr(w, "winfo_exists", lambda: False)():
                w.congruence_enabled = c

    def _on_congruence_toggle(self):
        c = bool(self.congruence_var.get())
        self.global_config["congruence_enabled"] = c
        self._apply_congruence_to_all()
        log_debug(f"[CONFIG] Congruencia entre fotogramas: {'Activada' if c else 'Desactivada'}")
        self.save_global_config()

    def _apply_mouth_flutter_to_all(self):
        mf = bool(self.global_config.get("mouth_flutter_enabled", False))
        for attr in ("p1_live_avatar", "p2_live_avatar", "w_live_avatar", "avatar1_window", "avatar2_window"):
            w = getattr(self, attr, None)
            if w and getattr(w, "winfo_exists", lambda: False)():
                w.mouth_flutter_enabled = mf

    def _on_mouth_flutter_toggle(self):
        mf = bool(self.mouth_flutter_var.get())
        self.global_config["mouth_flutter_enabled"] = mf
        self._apply_mouth_flutter_to_all()
        log_debug(f"[CONFIG] Alternar boca al hablar continuo: {'Activado' if mf else 'Desactivado'}")
        self.save_global_config()

    def _refresh_experimental_buttons(self):
        show = bool(self.global_config.get("experimental_enabled", False))
        for btn in (
            getattr(self, "btn_lobby_twitch", None),
            getattr(self, "btn_lobby_remote", None),
            getattr(self, "btn_lobby_4p", None),
        ):
            if btn is None:
                continue
            try:
                btn.pack_forget()
                if show:
                    btn.pack(side=tk.LEFT, padx=(6, 0))
            except Exception:
                pass

    def _on_experimental_toggle(self):
        exp = bool(self.experimental_var.get())
        self.global_config["experimental_enabled"] = exp
        self._refresh_experimental_buttons()
        log_debug(f"[CONFIG] Opciones experimentales: {'Activadas' if exp else 'Desactivadas'}")
        self.save_global_config()

    def _refresh_eco_mode(self):
        try:
            a1_open = bool(self.avatar1_window and self.avatar1_window.winfo_exists())
            a2_open = bool(self.avatar2_window and self.avatar2_window.winfo_exists())
            obs_open = a1_open or a2_open
            is_iconic = (self.root.state() == "iconic")
            has_focus = (self.root.focus_displayof() is not None)
            freeze_for_obs = obs_open and (is_iconic or not has_focus)
        except Exception:
            obs_open = False
            freeze_for_obs = False

        self._eco_mode = False
        ed_player = getattr(self, "_props_editor_open_for", None)
        is_coop = (self.global_config.get("game_mode") != "single")

        if hasattr(self, "p1_live_avatar"):
            self.p1_live_avatar.paused = (self.current_screen != "lobby") or (self.card_view_state.get(1) != "active")
            self.p1_live_avatar.freeze_motion = freeze_for_obs or (ed_player == 1)
        if hasattr(self, "p2_live_avatar"):
            self.p2_live_avatar.paused = (not is_coop) or (self.current_screen != "lobby") or (self.card_view_state.get(2) != "active")
            self.p2_live_avatar.freeze_motion = freeze_for_obs or (ed_player == 2)
        if hasattr(self, "w_live_avatar"):
            self.w_live_avatar.paused = (self.current_screen != "workshop")
            self.w_live_avatar.freeze_motion = freeze_for_obs or (ed_player == getattr(self, "workshop_player", None))

        if hasattr(self, "eco_status_lbl"):
            if freeze_for_obs:
                self.eco_status_lbl.config(text="🎬 OBS activo (vista previa en reposo)", fg="#0284C7")
            elif obs_open:
                self.eco_status_lbl.config(text="🎬 OBS activo", fg="#0284C7")
            else:
                self.eco_status_lbl.config(text="")

    def _refresh_hotkey_bindings(self):
        hk_cfg = self.global_config.get("hotkeys", {"1": [], "2": []})
        bindings = {}
        for p_str in ("1", "2"):
            for idx, item in enumerate(hk_cfg.get(p_str, []) or []):
                vk = item.get("vk", 0)
                mods = item.get("mods", 0)
                if vk:
                    bindings[f"{p_str}:{idx}"] = (vk, mods)
        if hasattr(self, "hotkey_listener"):
            self.hotkey_listener.set_bindings(bindings)

    def _on_hotkey_triggered(self, binding_id):
        try:
            p_str, idx_str = binding_id.split(":", 1)
            pnum = int(p_str)
            idx = int(idx_str)
        except Exception:
            return
        slots = self.global_config.get("hotkeys", {}).get(p_str, [])
        if idx < 0 or idx >= len(slots):
            return
        slot = slots[idx]
        target = slot.get("character", "")
        prof_key = "player1" if pnum == 1 else "player2"
        if not target or target not in self.profiles.get(prof_key, {}):
            return

        curr_key = "current_p1_profile" if pnum == 1 else "current_p2_profile"
        curr = self.global_config.get(curr_key, "")
        mode = slot.get("mode", "toggle")

        if mode == "toggle":
            base = self._hotkey_base.get(pnum)
            if curr == target and base and base in self.profiles.get(prof_key, {}) and base != target:
                next_char = base
                self._hotkey_base[pnum] = None
            else:
                if curr != target:
                    self._hotkey_base[pnum] = curr
                next_char = target
        else:
            self._hotkey_base[pnum] = None
            next_char = target

        log_debug(f"[ATAJO] ⌨️ {pnum}P -> '{next_char}'")
        self._choose_character_from_card_list(pnum, next_char)

    def _open_hotkeys_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("⌨️ Atajos - PNGTuber Duo Co-op")
        dlg.geometry("760x560")
        dlg.resizable(False, False)
        dlg.configure(bg="#DFE5EE")
        dlg.transient(self.root)
        dlg.grab_set()

        self.root.update_idletasks()
        rx = self.root.winfo_x() + (self.root.winfo_width() - 760) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - 560) // 2
        dlg.geometry(f"+{max(10, rx)}+{max(10, ry)}")

        hk_cfg = self.global_config.setdefault("hotkeys", {"1": [], "2": []})
        hk_cfg.setdefault("1", [])
        hk_cfg.setdefault("2", [])
        thumb_refs = []

        hdr = tk.Frame(dlg, bg="#1E293B", padx=16, pady=12)
        hdr.pack(fill=tk.X)
        tk.Label(
            hdr, text="⌨️  ATAJOS",
            font=("Segoe UI", 13, "bold"), bg="#1E293B", fg="#FACC15"
        ).pack(anchor=tk.W)
        tk.Label(
            hdr, text="Asigna teclas globales para cambiar de personaje al instante (incluso mientras juegas).",
            font=("Segoe UI", 9), bg="#1E293B", fg="#E2E8F0"
        ).pack(anchor=tk.W, pady=(2, 0))

        cards_row = tk.Frame(dlg, bg="#DFE5EE", padx=14, pady=12)
        cards_row.pack(fill=tk.BOTH, expand=True)

        capturing = {"slot": None, "btn": None}

        def finish_capture():
            capturing["slot"] = None
            capturing["btn"] = None
            if hasattr(self, "hotkey_listener"):
                self.hotkey_listener.suspended = False

        def on_dlg_key(event):
            if capturing["slot"] is None:
                return
            vk = getattr(event, "keycode", 0)
            keysym = str(getattr(event, "keysym", ""))
            if not vk or vk in MODIFIER_VKS:
                return "break"
            if keysym == "Escape":
                finish_capture()
                render_both()
                return "break"
            mods = current_modifiers()
            lbl = format_hotkey(mods, pretty_key_label(keysym, vk))
            capturing["slot"]["vk"] = int(vk)
            capturing["slot"]["mods"] = int(mods)
            capturing["slot"]["label"] = lbl
            finish_capture()
            self._refresh_hotkey_bindings()
            self.save_global_config()
            render_both()
            return "break"

        dlg.bind("<KeyPress>", on_dlg_key)

        def build_player_equip_card(parent, pnum, title_txt, accent_bg, card_bg):
            outer = tk.Frame(parent, bg=card_bg, highlightthickness=3, highlightbackground="#242E3B")
            outer.pack(side=tk.LEFT if pnum == 1 else tk.RIGHT, fill=tk.BOTH, expand=True, padx=(0, 6) if pnum == 1 else (6, 0))

            c_hdr = tk.Frame(outer, bg=accent_bg, padx=12, pady=8)
            c_hdr.pack(fill=tk.X)
            tk.Label(
                c_hdr, text=title_txt,
                font=("Segoe UI", 10, "bold"), bg=accent_bg, fg="#FFFFFF"
            ).pack(side=tk.LEFT)
            tk.Label(
                c_hdr, text="EQUIPAR",
                font=("Consolas", 9, "bold"), bg="#FACC15", fg="#0F172A", padx=6, pady=1
            ).pack(side=tk.RIGHT)

            list_sf = ScrollableFrame(outer, bg=card_bg)
            list_sf.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

            def add_slot():
                prof_key = "player1" if pnum == 1 else "player2"
                chars = list(self.profiles.get(prof_key, {}).keys())
                default_char = chars[0] if chars else ""
                hk_cfg[str(pnum)].append({
                    "vk": 0, "mods": 0, "label": "Sin tecla",
                    "character": default_char, "mode": "toggle"
                })
                self.save_global_config()
                render_card()

            ftr_c = tk.Frame(outer, bg=card_bg, padx=10, pady=8)
            ftr_c.pack(fill=tk.X)
            tk.Button(
                ftr_c, text="➕  Añadir atajo",
                font=("Segoe UI", 9, "bold"),
                bg="#FACC15", fg="#0F172A", activebackground="#EAB308",
                relief="solid", bd=2, padx=10, pady=4, cursor="hand2",
                command=add_slot
            ).pack(fill=tk.X)

            def render_card():
                for w in list_sf.content.winfo_children():
                    w.destroy()
                slots = hk_cfg[str(pnum)]
                prof_key = "player1" if pnum == 1 else "player2"
                char_names = list(self.profiles.get(prof_key, {}).keys())

                if not slots:
                    tk.Label(
                        list_sf.content,
                        text="Sin atajos todavía.\nPulsa '+ Añadir atajo' para equipar\nun personaje en una tecla rápida.",
                        font=("Segoe UI", 9, "italic"), bg=card_bg, fg="#64748B", pady=28
                    ).pack(fill=tk.X)
                    return

                for idx, slot in enumerate(slots):
                    scard = tk.Frame(
                        list_sf.content, bg="#FFFFFF",
                        highlightthickness=2, highlightbackground="#242E3B",
                        padx=8, pady=7
                    )
                    scard.pack(fill=tk.X, pady=(0, 8))

                    top_r = tk.Frame(scard, bg="#FFFFFF")
                    top_r.pack(fill=tk.X)

                    ch_name = slot.get("character", "")
                    ch_dict = self.profiles.get(prof_key, {}).get(ch_name, {})
                    th = self._get_character_thumbnail(ch_dict.get("a1_idle" if pnum == 1 else "a2_idle"), size=(34, 34))
                    if th:
                        thumb_refs.append(th)
                        tk.Label(top_r, image=th, bg="#F1F5F9", highlightthickness=1, highlightbackground="#94A3B8").pack(side=tk.LEFT, padx=(0, 8))
                    else:
                        tk.Label(top_r, text="👤", font=("Segoe UI", 13), bg="#F1F5F9", width=3).pack(side=tk.LEFT, padx=(0, 8))

                    cvar = tk.StringVar(value=ch_name)
                    cmb = ttk.Combobox(top_r, textvariable=cvar, values=char_names, state="readonly", width=18)
                    cmb.pack(side=tk.LEFT, fill=tk.X, expand=True)

                    def make_char_cb(s_ref, v_ref):
                        def on_ch(e=None):
                            s_ref["character"] = v_ref.get()
                            self.save_global_config()
                            render_card()
                        return on_ch
                    cmb.bind("<<ComboboxSelected>>", make_char_cb(slot, cvar))

                    def make_del_cb(i_del):
                        def on_del():
                            slots.pop(i_del)
                            self._refresh_hotkey_bindings()
                            self.save_global_config()
                            render_card()
                        return on_del

                    tk.Button(
                        top_r, text="✕", font=("Segoe UI", 8, "bold"),
                        bg="#FEE2E2", fg="#DC2626", activebackground="#FCA5A5",
                        relief="solid", bd=1, padx=5, pady=1, cursor="hand2",
                        command=make_del_cb(idx)
                    ).pack(side=tk.RIGHT, padx=(6, 0))

                    bot_r = tk.Frame(scard, bg="#FFFFFF")
                    bot_r.pack(fill=tk.X, pady=(6, 0))

                    key_txt = slot.get("label") or "Sin tecla"
                    is_cap = (capturing["slot"] is slot)
                    key_btn = tk.Button(
                        bot_r,
                        text="⏺ Pulsa tecla..." if is_cap else f"⌨️ {key_txt}",
                        font=("Consolas", 9, "bold"),
                        bg="#FEF08A" if is_cap else "#0F172A",
                        fg="#0F172A" if is_cap else "#FACC15",
                        activebackground="#1E293B", activeforeground="#FFFFFF",
                        relief="solid", bd=1, padx=8, pady=2, cursor="hand2"
                    )
                    key_btn.pack(side=tk.LEFT)

                    def make_cap_cb(s_ref, b_ref):
                        def on_cap():
                            if hasattr(self, "hotkey_listener"):
                                self.hotkey_listener.suspended = True
                            capturing["slot"] = s_ref
                            capturing["btn"] = b_ref
                            b_ref.config(text="⏺ Pulsa tecla...", bg="#FEF08A", fg="#0F172A")
                            dlg.focus_set()
                        return on_cap
                    key_btn.config(command=make_cap_cb(slot, key_btn))

                    is_toggle = (slot.get("mode", "toggle") == "toggle")
                    mode_btn = tk.Button(
                        bot_r,
                        text="🔁 Alternar" if is_toggle else "⚡ Directo",
                        font=("Segoe UI", 8, "bold"),
                        bg="#DBEAFE" if is_toggle else "#DCFCE7",
                        fg="#1E40AF" if is_toggle else "#166534",
                        relief="solid", bd=1, padx=7, pady=2, cursor="hand2"
                    )
                    mode_btn.pack(side=tk.RIGHT)

                    def make_mode_cb(s_ref):
                        def on_m():
                            s_ref["mode"] = "direct" if s_ref.get("mode", "toggle") == "toggle" else "toggle"
                            self.save_global_config()
                            render_card()
                        return on_m
                    mode_btn.config(command=make_mode_cb(slot))

            return render_card

        r1 = build_player_equip_card(cards_row, 1, "🎮 JUGADOR 1 (1P)", "#3671C6", "#FFFBEB")
        r2 = build_player_equip_card(cards_row, 2, "🎧 JUGADOR 2 (2P)", "#E45B47", "#FFFBEB")

        def render_both():
            thumb_refs.clear()
            r1()
            r2()

        render_both()

        ftr = tk.Frame(dlg, bg="#CBD5E1", padx=14, pady=10, relief="solid", bd=1)
        ftr.pack(fill=tk.X)
        tk.Label(
            ftr, text="💡 Alternar: vuelve al personaje base al pulsar otra vez.",
            font=("Segoe UI", 8), bg="#CBD5E1", fg="#334155"
        ).pack(side=tk.LEFT)

        def close_dlg():
            finish_capture()
            dlg.destroy()

        dlg.protocol("WM_DELETE_WINDOW", close_dlg)
        tk.Button(
            ftr, text="✅  Listo",
            font=("Segoe UI", 10, "bold"),
            bg="#16A34A", fg="#FFFFFF", activebackground="#15803D", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=18, pady=4, cursor="hand2",
            command=close_dlg
        ).pack(side=tk.RIGHT)

    def _open_settings_menu(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("⚙️ Menú de Opciones - PNGTuber Duo Co-op")
        dlg.geometry("580x720")
        dlg.resizable(False, False)
        dlg.configure(bg="#DFE5EE")
        dlg.transient(self.root)
        dlg.grab_set()

        self.root.update_idletasks()
        rx = self.root.winfo_x() + (self.root.winfo_width() - 580) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - 720) // 2
        dlg.geometry(f"+{max(10, rx)}+{max(10, ry)}")

        # Encabezado estilo consola/videojuego
        hdr = tk.Frame(dlg, bg="#3671C6", padx=16, pady=12)
        hdr.pack(fill=tk.X)
        tk.Label(
            hdr, text="⚙️  MENÚ DE OPCIONES",
            font=("Segoe UI", 12, "bold"), bg="#3671C6", fg="#FFFFFF"
        ).pack(anchor=tk.W)
        tk.Label(
            hdr, text="Ajusta cómo se mueven y reaccionan tus personajes en directo.",
            font=("Segoe UI", 9), bg="#3671C6", fg="#DBEAFE"
        ).pack(anchor=tk.W, pady=(2, 0))

        body_sf = ScrollableFrame(dlg, bg="#DFE5EE")
        body_sf.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        body = body_sf.content

        def build_option_card(icon, title, description, var, command, accent="#3671C6"):
            card = tk.Frame(
                body, bg="#FFFFFF", highlightthickness=2,
                highlightbackground="#242E3B", padx=14, pady=10
            )
            card.pack(fill=tk.X, pady=(0, 10))

            top_row = tk.Frame(card, bg="#FFFFFF")
            top_row.pack(fill=tk.X)

            tk.Label(
                top_row, text=f"{icon}  {title}",
                font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#1E293B"
            ).pack(side=tk.LEFT)

            state_btn = tk.Button(
                top_row, font=("Segoe UI", 9, "bold"),
                relief="solid", bd=2, padx=12, pady=2, cursor="hand2"
            )
            state_btn.pack(side=tk.RIGHT)

            def refresh_btn():
                if var.get():
                    state_btn.config(
                        text="✔  ACTIVADO", bg="#16A34A", fg="#FFFFFF",
                        activebackground="#15803D", activeforeground="#FFFFFF"
                    )
                    card.configure(highlightbackground=accent)
                else:
                    state_btn.config(
                        text="✖  DESACTIVADO", bg="#E2E8F0", fg="#475569",
                        activebackground="#CBD5E1", activeforeground="#1E293B"
                    )
                    card.configure(highlightbackground="#64748B")

            def on_toggle():
                var.set(not var.get())
                command()
                refresh_btn()

            state_btn.config(command=on_toggle)
            refresh_btn()

            tk.Label(
                card, text=description,
                font=("Segoe UI", 8), bg="#FFFFFF", fg="#475569",
                justify=tk.LEFT, anchor=tk.W, wraplength=480
            ).pack(fill=tk.X, pady=(6, 0))

        build_option_card(
            "🎤",
            "Mover al hablar (Animaciones de estado)",
            "Activa las animaciones asignadas a cada pose (Respiración, Saltitos, Elástico, Balanceo, Sacudida o Flotar). Si lo desactivas, los avatares permanecerán totalmente quietos.",
            self.bounce_var,
            self._on_bounce_toggle,
            accent="#3671C6"
        )

        build_option_card(
            "🍮",
            "Efecto Gelatina (Estirar y Aplastar)",
            "Aplica una deformación elástica (Squash & Stretch) cuando el personaje sube, respira o aterriza, dándole una sensación más viva estilo dibujo animado.",
            self.squash_var,
            self._on_squash_toggle,
            accent="#7C3AED"
        )

        build_option_card(
            "〰️",
            "Línea de retención de voz (Línea punteada)",
            "Muestra una línea punteada debajo del umbral de voz. Evita que el avatar cierre la boca de golpe entre palabras: no vuelve a silencio hasta que el volumen baje de esa línea.",
            self.hysteresis_var,
            self._on_hysteresis_toggle,
            accent="#0284C7"
        )

        if not hasattr(self, "congruence_var"):
            self.congruence_var = tk.BooleanVar(value=self.global_config.get("congruence_enabled", True))
        build_option_card(
            "🔗",
            "Congruencia (Continuidad entre fotogramas)",
            "Si un fotograma dura muy poco (como un pestañeo), el personaje sigue con la animación que ya traía en vez de dar un tirón. "
            "Si el nuevo fotograma se mantiene (por ejemplo un grito), arranca en la misma posición y tamaño del anterior y luego se transforma suavemente.",
            self.congruence_var,
            self._on_congruence_toggle,
            accent="#D97706"
        )

        if not hasattr(self, "mouth_flutter_var"):
            self.mouth_flutter_var = tk.BooleanVar(value=self.global_config.get("mouth_flutter_enabled", False))
        build_option_card(
            "🗣️",
            "Alternar boca al hablar continuo",
            "Si el micrófono lleva tiempo sin bajar del umbral de voz, el personaje intercala entre la boca abierta y la boca semi-abierta para dar más vida al hablar. (Solo aplica si el personaje tiene asignada una Boca Semi-Abierta).",
            self.mouth_flutter_var,
            self._on_mouth_flutter_toggle,
            accent="#16A34A"
        )

        if not hasattr(self, "experimental_var"):
            self.experimental_var = tk.BooleanVar(value=self.global_config.get("experimental_enabled", False))
        build_option_card(
            "🧪",
            "Opciones experimentales",
            "Muestra en la barra superior junto a Atajos los botones en desarrollo: Alertas Twitch (receptor local), Control remoto y 4 Players mode.",
            self.experimental_var,
            self._on_experimental_toggle,
            accent="#9146FF"
        )

        # Panel inferior de controles rápidos estilo pantalla de ayuda de videojuego
        ctrl_card = tk.Frame(
            body, bg="#F8FAFC", highlightthickness=2,
            highlightbackground="#94A3B8", padx=12, pady=8
        )
        ctrl_card.pack(fill=tk.X, pady=(2, 0))
        tk.Label(
            ctrl_card, text="🎮 CONTROLES RÁPIDOS",
            font=("Segoe UI", 9, "bold"), bg="#F8FAFC", fg="#334155"
        ).pack(anchor=tk.W)
        tk.Label(
            ctrl_card,
            text="• Tecla [M]: Silenciar / activar micrófono rápidamente.\n"
                 "• Botón [⌨️ ATAJOS]: Asigna teclas globales para cambiar de personaje (emociones).\n"
                 "• Arrastra personajes en la lista para ordenarlos; mantén uno encima de otro para crear una carpeta.\n"
                 "• Clic derecho en un personaje de la lista: Borrar personaje.",
            font=("Segoe UI", 8), bg="#F8FAFC", fg="#475569", justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(3, 0))

        ftr = tk.Frame(dlg, bg="#CBD5E1", padx=14, pady=10, relief="solid", bd=1)
        ftr.pack(fill=tk.X)
        tk.Button(
            ftr, text="✅  Aceptar y Volver",
            font=("Segoe UI", 10, "bold"),
            bg="#16A34A", fg="#FFFFFF",
            activebackground="#15803D", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=18, pady=4, cursor="hand2",
            command=dlg.destroy
        ).pack(side=tk.RIGHT)

    # =========================================================================
    # --- ALERTAS TWITCH (RECEPTOR LOCAL) Y OPCIONES EXPERIMENTALES ---
    # =========================================================================
    def _get_twitch_cfg(self):
        cfg = self.global_config.setdefault("twitch_alerts", {})
        cfg.setdefault("enabled", False)
        cfg.setdefault("port", 8765)
        cfg.setdefault("rules", [])
        return cfg

    def _sync_twitch_alert_server(self):
        cfg = self._get_twitch_cfg()
        if cfg.get("enabled", False):
            ok = self.twitch_alert_server.start(cfg.get("port", 8765))
            if ok:
                log_debug(f"[TWITCH] Receptor local escuchando en http://127.0.0.1:{self.twitch_alert_server.port}")
            else:
                log_debug(f"[TWITCH] Error al iniciar receptor local: {self.twitch_alert_server.last_error}")
        else:
            self.twitch_alert_server.stop()

    def _handle_twitch_alert(self, payload):
        ev = str(payload.get("event", "")).strip().lower()
        reward = str(payload.get("reward", "")).strip().lower()
        log_debug(f"[TWITCH] Alerta recibida -> event='{ev}' reward='{reward}' payload={payload}")
        if not ev and not reward:
            return
        cfg = self._get_twitch_cfg()
        matched = False
        for rule in cfg.get("rules", []):
            if not rule.get("enabled", True):
                continue
            r_ev = str(rule.get("event", "")).strip().lower()
            if not r_ev:
                continue
            if r_ev == ev or (reward and r_ev == reward):
                matched = True
                self._trigger_twitch_rule(rule, payload)
        if not matched:
            log_debug(f"[TWITCH] Ninguna regla activa coincidió con event='{ev}' / reward='{reward}'")

    def _trigger_twitch_rule(self, rule, payload=None):
        target_p = rule.get("player", 1)
        players = [1, 2] if str(target_p) == "both" else ([2] if int(target_p) == 2 else [1])
        for pnum in players:
            self._alert_queues[pnum].append(dict(rule))
            if not self._alert_active[pnum]:
                self._run_next_twitch_alert(pnum)

    def _set_player_forced_scream(self, pnum, active):
        if not hasattr(self, "_forced_scream"):
            self._forced_scream = {1: False, 2: False}
        self._forced_scream[pnum] = bool(active)
        if pnum == 1:
            self.p1_is_screaming = bool(active)
            win = self.avatar1_window
            prev = getattr(self, "p1_live_avatar", None)
        else:
            self.p2_is_screaming = bool(active)
            win = self.avatar2_window
            prev = getattr(self, "p2_live_avatar", None)
        if win and win.winfo_exists():
            win._manual_scream = bool(active)
            win.set_screaming(bool(active))
        if prev and prev.winfo_exists():
            prev._manual_scream = bool(active)
            prev.update_state(prev.is_talking, bool(active))

    def _set_player_forced_flip_x(self, pnum, flip_val):
        target_data = self.p1_data if pnum == 1 else self.p2_data
        target_data["flip_x"] = bool(flip_val)
        prev = getattr(self, "p1_live_avatar" if pnum == 1 else "p2_live_avatar", None)
        if prev and prev.winfo_exists():
            prev.flip_x = bool(flip_val)
            prev._rebuild_photo_cache()
            prev._render()
        self._sync_windows_images()

    def _set_player_forced_mute(self, pnum, muted):
        if pnum == 1:
            if bool(self.audio_engine.mic_muted) != bool(muted):
                self.audio_engine.toggle_mic_mute()
        else:
            if bool(self.audio_engine.discord_muted) != bool(muted):
                self.audio_engine.toggle_discord_mute()

    def _run_next_twitch_alert(self, pnum):
        if not self._alert_queues[pnum]:
            self._alert_active[pnum] = False
            base = self._alert_restore.get(pnum)
            self._alert_restore[pnum] = None
            prof_key = f"player{pnum}"
            if base and base in self.profiles.get(prof_key, {}):
                curr_key = "current_p1_profile" if pnum == 1 else "current_p2_profile"
                if self.global_config.get(curr_key) != base:
                    self._choose_character_from_card_list(pnum, base)
            return

        self._alert_active[pnum] = True
        rule = self._alert_queues[pnum].pop(0)
        curr_key = "current_p1_profile" if pnum == 1 else "current_p2_profile"
        prof_key = f"player{pnum}"
        if self._alert_restore.get(pnum) is None:
            self._alert_restore[pnum] = self.global_config.get(curr_key, "")

        action = rule.get("action", "character")
        try:
            dur = max(0.0, float(rule.get("duration", 8.0)))
        except Exception:
            dur = 8.0

        restore_info = {"scream": False, "mute_prev": None, "flip_prev": None}
        log_debug(f"[TWITCH] Ejecutando alerta en {pnum}P: action={action}, char='{rule.get('character', '')}', dur={dur}s")
        if action == "character":
            target_char = rule.get("character", "")
            if target_char and target_char in self.profiles.get(prof_key, {}):
                self._choose_character_from_card_list(pnum, target_char)
        elif action == "random_character":
            names = list(self.profiles.get(prof_key, {}).keys())
            curr_name = self.global_config.get(curr_key, "")
            choices = [n for n in names if n != curr_name] or names
            if choices:
                self._choose_character_from_card_list(pnum, random.choice(choices))
        elif action == "scream":
            self._set_player_forced_scream(pnum, True)
            restore_info["scream"] = True
        elif action == "mute":
            prev_m = bool(self.audio_engine.mic_muted if pnum == 1 else self.audio_engine.discord_muted)
            restore_info["mute_prev"] = prev_m
            self._set_player_forced_mute(pnum, True)
        elif action == "flip_x":
            target_data = self.p1_data if pnum == 1 else self.p2_data
            prev_f = bool(target_data.get("flip_x", False))
            restore_info["flip_prev"] = prev_f
            self._set_player_forced_flip_x(pnum, not prev_f)

        if dur <= 0.0:
            # Cambio permanente (sin restaurar al anterior)
            if action in ("character", "random_character"):
                self._alert_restore[pnum] = None
            self._run_next_twitch_alert(pnum)
            return

        old_tid = self._alert_timer.get(pnum)
        if old_tid:
            try:
                self.root.after_cancel(old_tid)
            except Exception:
                pass
        self._alert_timer[pnum] = self.root.after(
            int(dur * 1000),
            lambda p=pnum, ri=restore_info: self._finish_twitch_alert(p, ri)
        )

    def _finish_twitch_alert(self, pnum, restore_info):
        self._alert_timer[pnum] = None
        if restore_info.get("scream"):
            self._set_player_forced_scream(pnum, False)
        if restore_info.get("mute_prev") is not None:
            self._set_player_forced_mute(pnum, restore_info["mute_prev"])
        if restore_info.get("flip_prev") is not None:
            self._set_player_forced_flip_x(pnum, restore_info["flip_prev"])
        self._run_next_twitch_alert(pnum)

    def _open_twitch_alerts_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("🟣 Alertas de Twitch - PNGTuber Duo Co-op")
        dlg.geometry("860x690")
        dlg.resizable(False, False)
        dlg.configure(bg="#DFE5EE")
        dlg.transient(self.root)
        dlg.grab_set()

        self.root.update_idletasks()
        rx = self.root.winfo_x() + (self.root.winfo_width() - 860) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - 690) // 2
        dlg.geometry(f"+{max(10, rx)}+{max(10, ry)}")

        cfg = self._get_twitch_cfg()
        EVENT_PLACEHOLDER = "Selecciona o escribe un evento..."

        hdr = tk.Frame(dlg, bg="#1E293B", padx=18, pady=12)
        hdr.pack(fill=tk.X)
        hdr_top = tk.Frame(hdr, bg="#1E293B")
        hdr_top.pack(fill=tk.X)
        tk.Label(
            hdr_top, text="🟣  ALERTAS DE TWITCH",
            font=("Segoe UI", 13, "bold"), bg="#1E293B", fg="#C084FC"
        ).pack(side=tk.LEFT)

        def open_help_guide():
            help_win = tk.Toplevel(dlg)
            help_win.title("❓ Cómo conectar Twitch paso a paso")
            help_win.geometry("560x440")
            help_win.resizable(False, False)
            help_win.configure(bg="#FFFFFF")
            help_win.transient(dlg)
            help_win.grab_set()

            tk.Label(
                help_win, text="❓ GUÍA RÁPIDA (SIN SABER DE REDES)",
                font=("Segoe UI", 11, "bold"), bg="#9146FF", fg="#FFFFFF", pady=10
            ).pack(fill=tk.X)

            guide_txt = (
                "No necesitas abrir puertos del router ni saber de redes. Todo funciona dentro de tu propia PC:\n\n"
                "1️⃣ ACTIVA EL INTERRUPTOR\n"
                "   Marca 'Activar alertas de Twitch' hasta que diga 🟢 Listo para recibir alertas.\n\n"
                "2️⃣ CREA O EDITA UNA REGLA\n"
                "   Elige qué evento quieres (ej. follow, sub, bits, raid o el nombre de un canje)\n"
                "   y qué hará tu personaje (cambiar a otra emoción/personaje o gritar unos segundos).\n"
                "   Usa '▶ Probar' para ver cómo se ve sin esperar una alerta real.\n\n"
                "3️⃣ COPIA EL ENLACE Y PÉGALO EN TU PROGRAMA DE ALERTAS\n"
                "   Cada regla tiene su botón '📋 Copiar enlace'. Cópialo y pégalo según uses:\n"
                "   • Streamer.bot: En tu acción → Add Sub-Action → Core → Network → Fetch URL → pega el enlace.\n"
                "   • Mix It Up: En tu comando/evento → Action: Web Request → pega el enlace.\n"
                "   • SAMMI: En tu botón → HTTP Request (GET) → pega el enlace.\n\n"
                "💡 TRUCO: Si pegas ese enlace en Chrome/Edge y presionas Enter, ¡también dispara la alerta!"
            )
            tk.Label(
                help_win, text=guide_txt, font=("Segoe UI", 9),
                bg="#FFFFFF", fg="#1E293B", justify=tk.LEFT, wraplength=520, padx=18, pady=14
            ).pack(fill=tk.BOTH, expand=True)
            tk.Button(
                help_win, text="Entendido", font=("Segoe UI", 9, "bold"),
                bg="#16A34A", fg="#FFFFFF", relief="solid", bd=1, padx=18, pady=4,
                cursor="hand2", command=help_win.destroy
            ).pack(pady=(0, 14))

        tk.Button(
            hdr_top, text="❓ Guía detallada", font=("Segoe UI", 8, "bold"),
            bg="#334155", fg="#F8FAFC", activebackground="#475569", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=10, pady=2, cursor="hand2", command=open_help_guide
        ).pack(side=tk.RIGHT)

        tk.Label(
            hdr,
            text="Haz que tu personaje cambie o reaccione automáticamente cuando recibas follows, subs, raids o canjes.",
            font=("Segoe UI", 9), bg="#1E293B", fg="#E2E8F0"
        ).pack(anchor=tk.W, pady=(2, 0))

        # 1. Panel superior de conexión + acordeón colapsable con 3 tarjetas de pasos
        srv_card = tk.Frame(dlg, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", padx=14, pady=10)
        srv_card.pack(fill=tk.X, padx=16, pady=(10, 6))

        top_row = tk.Frame(srv_card, bg="#FFFFFF")
        top_row.pack(fill=tk.X)

        enabled_var = tk.BooleanVar(value=bool(cfg.get("enabled", False)))
        port_var = tk.StringVar(value=str(cfg.get("port", 8765)))
        status_lbl = tk.Label(top_row, text="", font=("Segoe UI", 9, "bold"), bg="#FFFFFF")

        def update_status_label():
            if self.twitch_alert_server.running:
                status_lbl.config(text="🟢 Listo para recibir alertas", fg="#15803D")
            elif self.twitch_alert_server.last_error:
                status_lbl.config(
                    text="🔴 Puerto ocupado (abre ⚙️ Avanzado y cambia el número)",
                    fg="#DC2626"
                )
            else:
                status_lbl.config(text="⚪ Apagado (marca la casilla para encender)", fg="#64748B")

        def apply_server():
            cfg["enabled"] = bool(enabled_var.get())
            try:
                cfg["port"] = max(1024, min(65535, int(port_var.get().strip())))
            except Exception:
                cfg["port"] = 8765
            port_var.set(str(cfg["port"]))
            self._sync_twitch_alert_server()
            self.save_global_config()
            update_status_label()

        tk.Checkbutton(
            top_row, text="Activar alertas de Twitch", variable=enabled_var,
            font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#1E293B",
            activebackground="#FFFFFF", cursor="hand2", command=apply_server
        ).pack(side=tk.LEFT)
        status_lbl.pack(side=tk.LEFT, padx=(14, 0))

        adv_frame = tk.Frame(srv_card, bg="#F8FAFC", padx=10, pady=6, highlightthickness=1, highlightbackground="#CBD5E1")
        adv_frame.pack(fill=tk.X, pady=(8, 0))
        tk.Label(
            adv_frame, text="Puerto local (cámbialo si otro programa ya usa el 8765):",
            font=("Segoe UI", 8), bg="#F8FAFC", fg="#475569"
        ).pack(side=tk.LEFT)
        tk.Entry(adv_frame, textvariable=port_var, width=7, font=("Segoe UI", 8), relief="solid", bd=1).pack(side=tk.LEFT, padx=6)
        tk.Button(
            adv_frame, text="Guardar puerto", font=("Segoe UI", 8, "bold"),
            bg="#3671C6", fg="#FFFFFF", relief="solid", bd=1, padx=8, pady=1,
            cursor="hand2", command=apply_server
        ).pack(side=tk.LEFT)

        update_status_label()

        # Lista de reglas
        rules_sf = ScrollableFrame(dlg, bg="#DFE5EE")
        rules_sf.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)
        rules_body = rules_sf.content

        def get_char_names(p_val):
            if str(p_val) == "2":
                return sorted(self.profiles.get("player2", {}).keys())
            return sorted(self.profiles.get("player1", {}).keys())

        def render_rules():
            for w in rules_body.winfo_children():
                w.destroy()
            rules = cfg.get("rules", [])
            if not rules:
                tk.Label(
                    rules_body,
                    text="No hay reglas todavía. Pulsa '+ Añadir regla' para crear tu primera alerta.",
                    font=("Segoe UI", 9), bg="#DFE5EE", fg="#475569", pady=24
                ).pack()
                return

            ACTION_LABELS = {
                "character": "Cambiar personaje",
                "random_character": "Personaje aleatorio",
                "scream": "Grito temporal",
                "mute": "Silenciar (Mute)",
                "flip_x": "Voltear (Espejo X)",
            }
            LABEL_TO_ACTION = {v: k for k, v in ACTION_LABELS.items()}

            for idx, rule in enumerate(rules):
                is_active = bool(rule.get("enabled", True))
                card = tk.Frame(
                    rules_body,
                    bg="#FFFFFF" if is_active else "#F1F5F9",
                    highlightthickness=2 if is_active else 1,
                    highlightbackground="#94A3B8" if is_active else "#CBD5E1",
                    padx=14, pady=10
                )
                card.pack(fill=tk.X, pady=(0, 10))

                r_enabled = tk.BooleanVar(value=is_active)
                raw_ev = str(rule.get("event", "")).strip()
                r_event = tk.StringVar(value=raw_ev if raw_ev else EVENT_PLACEHOLDER)
                r_player = tk.StringVar(value="Ambos" if str(rule.get("player")) == "both" else ("2P" if str(rule.get("player")) == "2" else "1P"))
                r_action = tk.StringVar(value=ACTION_LABELS.get(rule.get("action", "character"), "Cambiar personaje"))
                r_char = tk.StringVar(value=str(rule.get("character", "")))
                r_dur = tk.StringVar(value=str(rule.get("duration", 8.0)))

                def save_rule(r=rule, ev_v=r_enabled, e_v=r_event, p_v=r_player, a_v=r_action, c_v=r_char, d_v=r_dur):
                    r["enabled"] = bool(ev_v.get())
                    ev_txt = e_v.get().strip()
                    if not ev_txt or ev_txt == EVENT_PLACEHOLDER:
                        r["event"] = ""
                    else:
                        r["event"] = ev_txt.lower()
                    pv = p_v.get()
                    r["player"] = "both" if pv == "Ambos" else (2 if pv == "2P" else 1)
                    r["action"] = LABEL_TO_ACTION.get(a_v.get(), "character")
                    r["character"] = c_v.get()
                    try:
                        r["duration"] = max(0.0, float(d_v.get().strip()))
                    except Exception:
                        r["duration"] = 8.0
                    self.save_global_config()

                # --- FILA 1: Checkbox + Cuando pase + Jugador + Que haga + Eliminar separado ---
                row1 = tk.Frame(card, bg=card["bg"])
                row1.pack(fill=tk.X)

                chk = tk.Checkbutton(row1, variable=r_enabled, bg=card["bg"], activebackground=card["bg"], cursor="hand2")
                chk.pack(side=tk.LEFT, padx=(0, 6))

                lbl_ev = tk.Label(row1, text="Cuando pase:", font=("Segoe UI", 8, "bold"), bg=card["bg"])
                lbl_ev.pack(side=tk.LEFT, padx=(0, 6))

                ev_cb = ttk.Combobox(
                    row1, textvariable=r_event,
                    values=["follow", "sub", "bits", "raid", "canje"],
                    width=24, font=("Segoe UI", 8)
                )
                ev_cb.pack(side=tk.LEFT, padx=(0, 14))
                if not raw_ev:
                    ev_cb.configure(foreground="#94A3B8")

                def on_ev_focus_in(_e, cb=ev_cb, v=r_event):
                    if v.get() == EVENT_PLACEHOLDER:
                        v.set("")
                    cb.configure(foreground="#1E293B")

                def on_ev_focus_out(_e, cb=ev_cb, v=r_event, fn=save_rule):
                    if not v.get().strip():
                        v.set(EVENT_PLACEHOLDER)
                        cb.configure(foreground="#94A3B8")
                    else:
                        cb.configure(foreground="#1E293B")
                    fn()

                ev_cb.bind("<FocusIn>", on_ev_focus_in)
                ev_cb.bind("<FocusOut>", on_ev_focus_out)
                ev_cb.bind("<<ComboboxSelected>>", lambda _e, cb=ev_cb, fn=save_rule: (cb.configure(foreground="#1E293B"), fn()))

                lbl_pl = tk.Label(row1, text="Jugador:", font=("Segoe UI", 8, "bold"), bg=card["bg"])
                lbl_pl.pack(side=tk.LEFT, padx=(0, 6))
                pl_cb = ttk.Combobox(row1, textvariable=r_player, values=["1P", "2P", "Ambos"], width=7, state="readonly", font=("Segoe UI", 8))
                pl_cb.pack(side=tk.LEFT, padx=(0, 14))

                lbl_ac = tk.Label(row1, text="Que haga:", font=("Segoe UI", 8, "bold"), bg=card["bg"])
                lbl_ac.pack(side=tk.LEFT, padx=(0, 6))
                ac_cb = ttk.Combobox(row1, textvariable=r_action, values=list(ACTION_LABELS.values()), width=19, state="readonly", font=("Segoe UI", 8))
                ac_cb.pack(side=tk.LEFT, padx=(0, 10))

                def del_rule(i=idx):
                    cfg["rules"].pop(i)
                    self.save_global_config()
                    render_rules()

                del_btn = tk.Button(
                    row1, text="🗑️", font=("Segoe UI", 9),
                    bg="#FEF2F2", fg="#B91C1C", activebackground="#FEE2E2",
                    relief="solid", bd=1, width=3, cursor="hand2",
                    command=del_rule
                )
                del_btn.pack(side=tk.RIGHT, padx=(18, 0))

                state_badge = tk.Button(
                    row1, text="PAUSADA" if not is_active else "ACTIVA",
                    font=("Segoe UI", 7, "bold"), relief="solid", bd=1,
                    padx=8, pady=1, cursor="hand2"
                )
                state_badge.pack(side=tk.RIGHT, padx=(8, 0))

                # --- FILA 2: Parámetros dependientes (Personaje + Duración) + Acciones (Probar + Copiar enlace) ---
                row2 = tk.Frame(card, bg=card["bg"])
                row2.pack(fill=tk.X, pady=(10, 0))

                lbl_ch = tk.Label(row2, text="Personaje al que cambia:", font=("Segoe UI", 8), bg=card["bg"])
                lbl_ch.pack(side=tk.LEFT, padx=(28, 6))
                p_val = "2" if r_player.get() == "2P" else "1"
                ch_cb = ttk.Combobox(row2, textvariable=r_char, values=get_char_names(p_val), width=24, state="readonly", font=("Segoe UI", 8))
                ch_cb.pack(side=tk.LEFT, padx=(0, 14))
                ch_cb.bind("<<ComboboxSelected>>", lambda _e, fn=save_rule: fn())

                lbl_dur = tk.Label(row2, text="Duración:", font=("Segoe UI", 8), bg=card["bg"])
                lbl_dur.pack(side=tk.LEFT, padx=(0, 6))
                dur_ent = tk.Entry(row2, textvariable=r_dur, width=5, font=("Segoe UI", 8), relief="solid", bd=1, justify=tk.CENTER)
                dur_ent.pack(side=tk.LEFT, padx=(0, 4))
                dur_ent.bind("<FocusOut>", lambda _e, fn=save_rule: fn())
                lbl_seg = tk.Label(row2, text="seg.", font=("Segoe UI", 8), bg=card["bg"])
                lbl_seg.pack(side=tk.LEFT, padx=(0, 16))

                copy_rule_btn = tk.Button(
                    row2, text="📋 Copiar enlace de esta alerta", font=("Segoe UI", 8, "bold"),
                    bg="#E0F2FE", fg="#0369A1", activebackground="#BAE6FD",
                    relief="solid", bd=1, padx=10, pady=2, cursor="hand2"
                )
                copy_rule_btn.pack(side=tk.RIGHT)

                def test_this(fn=save_rule, r=rule):
                    fn()
                    self._trigger_twitch_rule(r, {"event": r.get("event", "test")})

                test_btn = tk.Button(
                    row2, text="▶ Probar", font=("Segoe UI", 8, "bold"),
                    bg="#EDE9FE", fg="#6D28D9", activebackground="#DDD6FE",
                    relief="solid", bd=1, width=10, pady=2, cursor="hand2",
                    command=test_this
                )
                test_btn.pack(side=tk.RIGHT, padx=(0, 10))

                def copy_rule_link(fn=save_rule, r=rule, btn=copy_rule_btn):
                    fn()
                    ev_name = r.get("event") or "sub"
                    port_num = cfg.get("port", 8765)
                    link = f"http://127.0.0.1:{port_num}/trigger?event={ev_name}"
                    dlg.clipboard_clear()
                    dlg.clipboard_append(link)
                    btn.config(text="✅ ¡Enlace copiado!")
                    dlg.after(1400, lambda b=btn: b.config(text="📋 Copiar enlace de esta alerta") if b.winfo_exists() else None)

                copy_rule_btn.config(command=copy_rule_link)

                def apply_card_visual_state(
                    active_flag,
                    c_frame=card, r1=row1, r2=row2, cb_chk=chk,
                    labels=(lbl_ev, lbl_pl, lbl_ac, lbl_ch, lbl_dur, lbl_seg),
                    badge=state_badge, t_btn=test_btn, c_btn=copy_rule_btn,
                    d_ent=dur_ent
                ):
                    bg_c = "#FFFFFF" if active_flag else "#F1F5F9"
                    fg_main = "#334155" if active_flag else "#94A3B8"
                    c_frame.config(
                        bg=bg_c,
                        highlightthickness=2 if active_flag else 1,
                        highlightbackground="#94A3B8" if active_flag else "#CBD5E1"
                    )
                    r1.config(bg=bg_c)
                    r2.config(bg=bg_c)
                    cb_chk.config(bg=bg_c, activebackground=bg_c)
                    for lb in labels:
                        lb.config(bg=bg_c, fg=fg_main)
                    if active_flag:
                        badge.config(text="ACTIVA", bg="#DCFCE7", fg="#15803D")
                        t_btn.config(bg="#EDE9FE", fg="#6D28D9")
                        c_btn.config(bg="#E0F2FE", fg="#0369A1")
                        d_ent.config(fg="#0F172A", bg="#FFFFFF")
                    else:
                        badge.config(text="PAUSADA", bg="#E2E8F0", fg="#64748B")
                        t_btn.config(bg="#E2E8F0", fg="#94A3B8")
                        c_btn.config(bg="#E2E8F0", fg="#94A3B8")
                        d_ent.config(fg="#94A3B8", bg="#F8FAFC")

                def on_chk_toggle(fn=save_rule, ev_v=r_enabled, apply_fn=apply_card_visual_state):
                    fn()
                    apply_fn(bool(ev_v.get()))

                def on_badge_click(ev_v=r_enabled, toggle_fn=on_chk_toggle):
                    ev_v.set(not bool(ev_v.get()))
                    toggle_fn()

                chk.config(command=on_chk_toggle)
                state_badge.config(command=on_badge_click)
                apply_card_visual_state(is_active)

                def on_pl_or_ac(_e=None, fn=save_rule, p_v=r_player, a_v=r_action, c_box=ch_cb):
                    fn()
                    pv = "2" if p_v.get() == "2P" else "1"
                    c_box["values"] = get_char_names(pv)
                    c_box.config(state="readonly" if a_v.get() == "Cambiar personaje" else "disabled")

                pl_cb.bind("<<ComboboxSelected>>", on_pl_or_ac)
                ac_cb.bind("<<ComboboxSelected>>", on_pl_or_ac)
                if r_action.get() != "Cambiar personaje":
                    ch_cb.config(state="disabled")

        render_rules()

        ftr = tk.Frame(dlg, bg="#CBD5E1", padx=16, pady=10, relief="solid", bd=1)
        ftr.pack(fill=tk.X)

        def add_rule():
            p1_names = sorted(self.profiles.get("player1", {}).keys())
            cfg["rules"].append({
                "id": f"rule_{int(time.time() * 1000)}",
                "enabled": True,
                "event": "",
                "player": 1,
                "action": "character",
                "character": p1_names[0] if p1_names else "",
                "duration": 8.0,
            })
            self.save_global_config()
            render_rules()

        tk.Button(
            ftr, text="➕  Añadir regla",
            font=("Segoe UI", 9, "bold"),
            bg="#9146FF", fg="#FFFFFF", activebackground="#772CE8", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=14, pady=4, cursor="hand2",
            command=add_rule
        ).pack(side=tk.LEFT)

        tk.Label(
            ftr, text="💡 Puedes escribir el nombre de tu canje en 'Cuando pase'  •  Duración 0 = permanente",
            font=("Segoe UI", 8), bg="#CBD5E1", fg="#334155"
        ).pack(side=tk.LEFT, padx=(14, 0))

        tk.Button(
            ftr, text="✅  Listo",
            font=("Segoe UI", 10, "bold"),
            bg="#16A34A", fg="#FFFFFF", activebackground="#15803D", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=18, pady=4, cursor="hand2",
            command=dlg.destroy
        ).pack(side=tk.RIGHT)

    def _open_remote_control_placeholder(self):
        messagebox.showinfo(
            "📱 Control remoto (Experimental)",
            "Esta función está reservada para una próxima actualización.\n\n"
            "Permitirá controlar emociones, silencio y cambio de personajes desde tu celular o tablet en la red local."
        )

    def _open_4p_mode_placeholder(self):
        messagebox.showinfo(
            "👥 4 Players Mode (Experimental)",
            "Esta función está reservada para una próxima actualización.\n\n"
            "Permitirá ampliar la sala de 2 a 4 jugadores simultáneos con sus propias ventanas para OBS."
        )

    # =========================================================================
    # --- CICLO DE ACTUALIZACIÓN VISUAL Y MEDIDORES ---
    # =========================================================================
    def _update_ui_loop(self):
        is_coop = (self.global_config.get("game_mode") != "single")
        p1_muted = getattr(self.audio_engine, "mic_muted", False)
        p2_muted = getattr(self.audio_engine, "discord_muted", False)
        p1_thresh = self.p1_data.get("mic_threshold", 20)
        p2_thresh = self.p2_data.get("discord_threshold", 25)
        p1_has_scream = self._character_has_scream(self.p1_data)
        p2_has_scream = self._character_has_scream(self.p2_data)
        p1_scream_active = (self.p1_is_screaming or getattr(self, "_forced_scream", {}).get(1, False)) and p1_has_scream
        p2_scream_active = (self.p2_is_screaming or getattr(self, "_forced_scream", {}).get(2, False)) and p2_has_scream
        p2_talk_ctx = self.discord_talking if is_coop else False
        p2_scream_ctx = p2_scream_active if is_coop else False

        if self.current_screen == "lobby" and not getattr(self, "_eco_mode", False):
            if self.card_view_state.get(1) == "active":
                self.p1_live_avatar.update_state(
                    self.mic_talking, p1_scream_active,
                    muted=p1_muted, audio_level=self.mic_level, talk_threshold=p1_thresh,
                    partner_talking=p2_talk_ctx, partner_screaming=p2_scream_ctx
                )
                self._draw_mini_meter(
                    self.p1_mini_meter,
                    self.mic_level,
                    p1_thresh,
                    self.p1_data.get("scream_threshold", 55),
                    self.mic_talking,
                    p1_scream_active,
                    show_scream=p1_has_scream
                )

                if p1_muted:
                    self.p1_voice_badge.config(text="🔇 Muteado", bg="#64748B", fg="#FFFFFF")
                elif p1_scream_active:
                    self.p1_voice_badge.config(text="💥 ¡GRITO!", bg="#DC2626", fg="#FFFFFF")
                elif self.mic_talking:
                    self.p1_voice_badge.config(text="💬 Hablando", bg="#16A34A", fg="#FFFFFF")
                else:
                    self.p1_voice_badge.config(text="🤫 En silencio", bg="#25559C", fg="#E2E8F0")

            if is_coop and self.card_view_state.get(2) == "active":
                self.p2_live_avatar.update_state(
                    self.discord_talking, p2_scream_active,
                    muted=p2_muted, audio_level=self.discord_level, talk_threshold=p2_thresh,
                    partner_talking=self.mic_talking, partner_screaming=p1_scream_active
                )
                self._draw_mini_meter(
                    self.p2_mini_meter,
                    self.discord_level,
                    p2_thresh,
                    self.p2_data.get("scream_threshold", 55),
                    self.discord_talking,
                    p2_scream_active,
                    show_scream=p2_has_scream
                )

                if p2_muted:
                    self.p2_voice_badge.config(text="🔇 Muteado", bg="#64748B", fg="#FFFFFF")
                elif p2_scream_active:
                    self.p2_voice_badge.config(text="💥 ¡GRITO!", bg="#DC2626", fg="#FFFFFF")
                elif self.discord_talking:
                    self.p2_voice_badge.config(text="💬 Hablando", bg="#16A34A", fg="#FFFFFF")
                else:
                    self.p2_voice_badge.config(text="🤫 En silencio", bg="#B83F2E", fg="#E2E8F0")

        elif self.current_screen == "workshop" and not getattr(self, "_eco_mode", False):
            if self.workshop_player == 1:
                self.w_live_avatar.update_state(
                    self.mic_talking, p1_scream_active,
                    muted=p1_muted, audio_level=self.mic_level, talk_threshold=p1_thresh,
                    partner_talking=p2_talk_ctx, partner_screaming=p2_scream_ctx
                )
                self._draw_workshop_meter(
                    self.mic_level, p1_thresh, self.mic_talking, p1_scream_active,
                    self.p1_data.get("scream_threshold", 55), show_scream=p1_has_scream
                )
            else:
                self.w_live_avatar.update_state(
                    self.discord_talking, p2_scream_active,
                    muted=p2_muted, audio_level=self.discord_level, talk_threshold=p2_thresh,
                    partner_talking=self.mic_talking, partner_screaming=p1_scream_active
                )
                self._draw_workshop_meter(
                    self.discord_level, p2_thresh, self.discord_talking, p2_scream_active,
                    self.p2_data.get("scream_threshold", 55), show_scream=p2_has_scream
                )

        a1_open = self.avatar1_window and self.avatar1_window.winfo_exists()
        a2_open = self.avatar2_window and self.avatar2_window.winfo_exists()
        if a1_open:
            self.avatar1_window.set_talking(self.mic_talking)
            self.avatar1_window.set_screaming(p1_scream_active)
            self.avatar1_window.update_extra_context(
                muted=p1_muted, audio_level=self.mic_level, talk_threshold=p1_thresh,
                partner_talking=p2_talk_ctx, partner_screaming=p2_scream_ctx
            )
        if a2_open:
            self.avatar2_window.set_talking(self.discord_talking)
            self.avatar2_window.set_screaming(p2_scream_active)
            self.avatar2_window.update_extra_context(
                muted=p2_muted, audio_level=self.discord_level, talk_threshold=p2_thresh,
                partner_talking=self.mic_talking, partner_screaming=p1_scream_active
            )
        if not a1_open and not a2_open and "CERRAR" in self.btn_open.cget("text"):
            self.btn_open.config(text="🚀 ENVIAR A OBS (Abrir Avatares)", style="DSSend.TButton")
            self._refresh_eco_mode()

        delay_ms = 60 if getattr(self, "_eco_mode", False) else 20
        self.root.after(delay_ms, self._update_ui_loop)

    def _draw_mini_meter(self, canvas, level, threshold, scream_threshold, is_talking, is_screaming, show_scream=False):
        w = max(10, canvas.winfo_width())
        h = max(10, canvas.winfo_height())
        canvas.delete("all")

        # Cuadrícula sutil en el medidor estilo DS
        for pct_tick in (20, 40, 60, 80):
            gx = int((pct_tick / 100.0) * w)
            canvas.create_line(gx, 0, gx, h, fill="#CBD5E1", width=1)

        fill_w = int((min(100.0, max(0.0, level)) / 100.0) * w)
        color = "#EF4444" if (is_screaming and show_scream) else ("#22C55E" if is_talking else "#38BDF8")
        if fill_w > 0:
            canvas.create_rectangle(0, 0, fill_w, h, fill=color, width=0)

        # Línea punteada de histéresis (cierre de voz)
        if self.global_config.get("hysteresis_enabled", False):
            hx = int(((threshold * 0.70) / 100.0) * w)
            canvas.create_line(hx, 0, hx, h, fill="#0284C7", width=1, dash=(2, 2))

        # Marcador interactivo de Umbral de Voz (Rojo brillante + pestaña superior)
        tx = int((threshold / 100.0) * w)
        canvas.create_line(tx, 0, tx, h, fill="#E11D48", width=2)
        canvas.create_polygon(tx - 5, 0, tx + 5, 0, tx, 6, fill="#E11D48", outline="")

        # Marcador interactivo de Umbral de Grito (solo si existe un fotograma de grito en el personaje)
        if show_scream:
            sx = int((scream_threshold / 100.0) * w)
            canvas.create_line(sx, 0, sx, h, fill="#991B1B", width=2)
            canvas.create_polygon(sx - 5, h, sx + 5, h, sx, h - 6, fill="#991B1B", outline="")

    def _draw_workshop_meter(self, level, threshold, is_talking, is_screaming, scream_threshold, show_scream=False):
        canvas = self.w_audio_meter
        w = max(10, canvas.winfo_width())
        h = max(10, canvas.winfo_height())
        canvas.delete("all")

        fill_w = int((min(100.0, max(0.0, level)) / 100.0) * w)
        color = "#DC2626" if (is_screaming and show_scream) else ("#16A34A" if is_talking else "#38BDF8")

        if fill_w > 0:
            canvas.create_rectangle(0, 0, fill_w, h, fill=color, width=0)

        tx = int((threshold / 100.0) * w)
        canvas.create_line(tx, 0, tx, h, fill="#E11D48", width=2)

        if self.global_config.get("hysteresis_enabled", False):
            hx = int(((threshold * 0.70) / 100.0) * w)
            canvas.create_line(hx, 0, hx, h, fill="#0284C7", width=1, dash=(2, 2))

        if show_scream:
            sx = int((scream_threshold / 100.0) * w)
            canvas.create_line(sx, 0, sx, h, fill="#991B1B", width=2)

        if is_screaming and show_scream:
            canvas.create_text(w // 2, h // 2, text="💥 ¡GRITO DETECTADO!", fill="#FFFFFF", font=("Segoe UI", 8, "bold"))
        elif is_talking:
            canvas.create_text(w // 2, h // 2, text="HABLANDO...", fill="#FFFFFF", font=("Segoe UI", 8, "bold"))

    def _update_clock(self):
        now_str = datetime.now().strftime("%H:%M")
        self.clock_lbl.config(text=f"🕒 {now_str}")
        self.root.after(1000, self._update_clock)

    # =========================================================================
    # --- DISPOSITIVOS DE AUDIO ---
    # =========================================================================
    def _refresh_audio_devices(self):
        self.mic_devices = self.audio_engine.get_input_devices()
        self.discord_sources = self.audio_engine.get_discord_sources()
        self._sync_audio_combos_selection()

    def _sync_audio_combos_selection(self):
        if not hasattr(self, "mic_devices") or not hasattr(self, "discord_sources"):
            return

        mic_names = [d["name"] for d in self.mic_devices]
        curr_mic = self.p1_data.get("mic_device_name", "")
        mic_idx = 0
        for i, d in enumerate(self.mic_devices):
            if d["name"] == curr_mic or d.get("raw_name") == curr_mic:
                mic_idx = i
                break

        disc_names = [s["name"] for s in self.discord_sources]
        curr_disc_id = self.p2_data.get("discord_source_id", "app:discord")
        disc_idx = 0
        for i, s in enumerate(self.discord_sources):
            if s.get("id") == curr_disc_id:
                disc_idx = i
                break

        # Actualizar selector rápido de Micrófono en el Lobby (1P)
        if hasattr(self, "p1_lobby_dev_combo"):
            self.p1_lobby_dev_combo["values"] = mic_names
            if mic_names:
                self.p1_lobby_dev_combo.current(mic_idx)

        # Actualizar selector rápido de Discord en el Lobby (2P)
        if hasattr(self, "p2_lobby_dev_combo"):
            self.p2_lobby_dev_combo["values"] = disc_names
            if disc_names:
                self.p2_lobby_dev_combo.current(disc_idx)

        # Actualizar selector del Taller (Workshop)
        if hasattr(self, "w_audio_combo"):
            if self.workshop_player == 1:
                self.w_audio_combo["values"] = mic_names
                if mic_names:
                    self.w_audio_combo.current(mic_idx)
            else:
                self.w_audio_combo["values"] = disc_names
                if disc_names:
                    self.w_audio_combo.current(disc_idx)

    def _start_audio_engine(self):
        mic_idx = None
        saved_mic = self.p1_data.get("mic_device_name", "")
        for d in self.mic_devices:
            if d["name"] == saved_mic or d.get("raw_name") == saved_mic:
                mic_idx = d["index"]
                break
        if mic_idx is None and self.mic_devices:
            mic_idx = self.mic_devices[0]["index"]
            self.p1_data["mic_device_name"] = self.mic_devices[0]["name"]

        discord_info = None
        saved_src = self.p2_data.get("discord_source_id", "app:discord")
        for s in self.discord_sources:
            if s.get("id") == saved_src:
                discord_info = s
                break
        if discord_info is None and self.discord_sources:
            discord_info = self.discord_sources[0]
            self.p2_data["discord_source_id"] = discord_info.get("id", "app:discord")

        is_single = (self.global_config.get("game_mode") == "single")

        self.audio_engine.start(
            mic_device_index=mic_idx,
            discord_source_info=discord_info,
            mic_threshold=self.p1_data["mic_threshold"],
            discord_threshold=self.p2_data["discord_threshold"],
            mic_scream_threshold=self.p1_data.get("scream_threshold", 55),
            discord_scream_threshold=self.p2_data.get("scream_threshold", 55),
            single_player=is_single
        )

    # =========================================================================
    # --- VENTANAS DE OBS ---
    # =========================================================================
    def toggle_avatar_windows(self):
        a1_open = self.avatar1_window and self.avatar1_window.winfo_exists()
        a2_open = self.avatar2_window and self.avatar2_window.winfo_exists()

        if a1_open or a2_open:
            log_debug("[OBS] ❌ Cerrando ventanas flotantes de OBS...")
            if a1_open:
                try:
                    self.avatar1_window.destroy()
                except Exception:
                    pass
                self.avatar1_window = None
            if a2_open:
                try:
                    self.avatar2_window.destroy()
                except Exception:
                    pass
                self.avatar2_window = None
            self.btn_open.config(text="🚀 ENVIAR A OBS (Abrir Avatares)", style="DSSend.TButton")
        else:
            log_debug("[OBS] 🚀 Abriendo ventanas flotantes de OBS...")
            self.open_avatar_windows()

    def open_avatar_windows(self):
        # Determinar qué personajes están activos / seleccionados en las tarjetas
        p1_active = self.card_has_selected.get(1, False)
        p2_active = self.card_has_selected.get(2, False)

        # Si el usuario está en el Taller de edición y ninguna tarjeta estaba seleccionada,
        # abrir el personaje que está editando en ese momento
        if not p1_active and not p2_active:
            if self.current_screen == "workshop":
                if self.workshop_player == 1:
                    p1_active = True
                else:
                    p2_active = True
            else:
                messagebox.showinfo(
                    "Selecciona un Personaje",
                    "Por favor selecciona un personaje en la tarjeta del Jugador 1 o del Jugador 2 antes de abrir OBS."
                )
                return

        opened_any = False
        if p1_active:
            self._open_avatar1_window_only()
            opened_any = True

        if p2_active:
            self._open_avatar2_window_only()
            opened_any = True

        if opened_any and self.btn_open:
            self.btn_open.config(text="❌ CERRAR VENTANAS OBS", style="DSBlue.TButton")

    def _get_images_dict(self, player_num):
        target = self.p1_data if player_num == 1 else self.p2_data
        pref = "a1" if player_num == 1 else "a2"
        imgs = {
            "idle": target.get(f"{pref}_idle"),
            "idle_blink": target.get(f"{pref}_idle_blink"),
            "talk": target.get(f"{pref}_talk"),
            "talk_blink": target.get(f"{pref}_talk_blink"),
            "scream": target.get(f"{pref}_scream"),
        }
        for ex in target.get("extra_expressions", []) or []:
            r_id = ex.get("role")
            if r_id:
                imgs[r_id] = target.get(f"{pref}_{r_id}") or ex.get("file")
        return imgs

    def _open_avatar1_window_only(self):
        if self.avatar1_window and self.avatar1_window.winfo_exists():
            return
        bg = self.global_config["bg_color"]
        bounce = self.global_config["bounce_enabled"]
        p1_mode_4 = (self.p1_data.get("image_mode") == "4_states")
        a1_images = self._get_images_dict(1)

        self.avatar1_window = AvatarWindow(
            self.root,
            title="Avatar 1 (Micrófono) - Croma OBS",
            image_dict=a1_images,
            mode_4_states=p1_mode_4,
            bg_color=bg,
            bounce_enabled=bounce,
            on_hotkey=lambda act: self._on_window_hotkey(1, act),
            props_list=self.p1_data.get("props", []),
            motions_map=self._get_motions_dict(1),
            motion_speeds_map=self._get_motion_speeds_dict(1),
            extra_expressions=self.p1_data.get("extra_expressions", []),
            flip_x=bool(self.p1_data.get("flip_x", False))
        )
        self.avatar1_window.squash_enabled = self.global_config.get("squash_enabled", True)
        self.avatar1_window.congruence_enabled = self.global_config.get("congruence_enabled", True)
        self.avatar1_window.mouth_flutter_enabled = self.global_config.get("mouth_flutter_enabled", False)
        self.avatar1_window.geometry("450x550+80+100")
        self.avatar1_window.protocol("WM_DELETE_WINDOW", lambda: self._on_avatar_window_closed(1))
        if self.btn_open:
            self.btn_open.config(text="❌ CERRAR VENTANAS OBS", style="DSBlue.TButton")
        self._refresh_eco_mode()
        log_debug("[OBS] ✅ Ventana de Avatar 1 (1P) abierta")

    def _open_avatar2_window_only(self):
        if self.avatar2_window and self.avatar2_window.winfo_exists():
            return
        bg = self.global_config["bg_color"]
        bounce = self.global_config["bounce_enabled"]
        p2_mode_4 = (self.p2_data.get("image_mode") == "4_states")
        a2_images = self._get_images_dict(2)

        self.avatar2_window = AvatarWindow(
            self.root,
            title="Avatar 2 (Discord) - Croma OBS",
            image_dict=a2_images,
            mode_4_states=p2_mode_4,
            bg_color=bg,
            bounce_enabled=bounce,
            on_hotkey=lambda act: self._on_window_hotkey(2, act),
            props_list=self.p2_data.get("props", []),
            motions_map=self._get_motions_dict(2),
            motion_speeds_map=self._get_motion_speeds_dict(2),
            extra_expressions=self.p2_data.get("extra_expressions", []),
            flip_x=bool(self.p2_data.get("flip_x", False))
        )
        self.avatar2_window.squash_enabled = self.global_config.get("squash_enabled", True)
        self.avatar2_window.congruence_enabled = self.global_config.get("congruence_enabled", True)
        self.avatar2_window.mouth_flutter_enabled = self.global_config.get("mouth_flutter_enabled", False)
        # Si Avatar 1 no está abierto, posicionar de forma cómoda
        x_pos = 80 if not (self.avatar1_window and self.avatar1_window.winfo_exists()) else 560
        self.avatar2_window.geometry(f"450x550+{x_pos}+100")
        self.avatar2_window.protocol("WM_DELETE_WINDOW", lambda: self._on_avatar_window_closed(2))
        if self.btn_open:
            self.btn_open.config(text="❌ CERRAR VENTANAS OBS", style="DSBlue.TButton")
        self._refresh_eco_mode()
        log_debug("[OBS] ✅ Ventana de Avatar 2 (2P) abierta")

    def _on_avatar_window_closed(self, avatar_num):
        log_debug(f"[OBS] ❌ Ventana de Avatar {avatar_num} cerrada manualmente.")
        if avatar_num == 1:
            if self.avatar1_window:
                try:
                    self.avatar1_window.destroy()
                except Exception:
                    pass
                self.avatar1_window = None
        elif avatar_num == 2:
            if self.avatar2_window:
                try:
                    self.avatar2_window.destroy()
                except Exception:
                    pass
                self.avatar2_window = None

        a1_open = self.avatar1_window and self.avatar1_window.winfo_exists()
        a2_open = self.avatar2_window and self.avatar2_window.winfo_exists()
        if not a1_open and not a2_open and self.btn_open:
            self.btn_open.config(text="🚀 ENVIAR A OBS (Abrir Avatares)", style="DSSend.TButton")
        self._refresh_eco_mode()

    def _get_motions_dict(self, player_num):
        target = self.p1_data if player_num == 1 else self.p2_data
        pref = "a1" if player_num == 1 else "a2"
        def _norm_motion(m):
            return "Respiración" if m == "Rebote" else m

        m_dict = {
            "idle": _norm_motion(target.get(f"{pref}_idle_motion", "Respiración")),
            "idle_blink": _norm_motion(target.get(f"{pref}_idle_blink_motion", "Ninguna")),
            "talk": _norm_motion(target.get(f"{pref}_talk_motion", "Respiración")),
            "talk_blink": _norm_motion(target.get(f"{pref}_talk_blink_motion", "Ninguna")),
            "scream": _norm_motion(target.get(f"{pref}_scream_motion", "Sacudida")),
        }
        for ex in target.get("extra_expressions", []) or []:
            r_id = ex.get("role")
            if r_id:
                m_dict[r_id] = _norm_motion(target.get(f"{pref}_{r_id}_motion") or ex.get("motion", "Ninguna"))
        return m_dict

    def _get_motion_speeds_dict(self, player_num):
        target = self.p1_data if player_num == 1 else self.p2_data
        pref = "a1" if player_num == 1 else "a2"
        s_dict = {}
        for r in ("idle", "idle_blink", "talk", "talk_blink", "scream"):
            try:
                s_dict[r] = float(target.get(f"{pref}_{r}_speed", 1.0))
            except Exception:
                s_dict[r] = 1.0
        for ex in target.get("extra_expressions", []) or []:
            r_id = ex.get("role")
            if r_id:
                try:
                    s_dict[r_id] = float(target.get(f"{pref}_{r_id}_speed", ex.get("speed", 1.0)))
                except Exception:
                    s_dict[r_id] = 1.0
        return s_dict

    def _sync_windows_images(self):
        if self.avatar1_window and self.avatar1_window.winfo_exists():
            p1_mode_4 = (self.p1_data.get("image_mode") == "4_states")
            self.avatar1_window.update_images(
                self._get_images_dict(1), p1_mode_4,
                props_list=self.p1_data.get("props", []),
                motions_map=self._get_motions_dict(1),
                motion_speeds_map=self._get_motion_speeds_dict(1),
                extra_expressions=self.p1_data.get("extra_expressions", []),
                flip_x=bool(self.p1_data.get("flip_x", False))
            )

        if self.avatar2_window and self.avatar2_window.winfo_exists():
            p2_mode_4 = (self.p2_data.get("image_mode") == "4_states")
            self.avatar2_window.update_images(
                self._get_images_dict(2), p2_mode_4,
                props_list=self.p2_data.get("props", []),
                motions_map=self._get_motions_dict(2),
                motion_speeds_map=self._get_motion_speeds_dict(2),
                extra_expressions=self.p2_data.get("extra_expressions", []),
                flip_x=bool(self.p2_data.get("flip_x", False))
            )

    def _on_window_hotkey(self, avatar_num, action):
        if action == "mute":
            if avatar_num == 1:
                self.audio_engine.toggle_mic_mute()
            elif avatar_num == 2:
                self.audio_engine.toggle_discord_mute()
            self._sync_mute_buttons()
        elif action == "scream_toggle":
            if avatar_num == 1:
                self.p1_is_screaming = not self.p1_is_screaming
            elif avatar_num == 2:
                self.p2_is_screaming = not self.p2_is_screaming
        elif isinstance(action, str) and action.startswith("emote:"):
            key_name = action.split(":", 1)[1]
            if avatar_num == 1:
                self.p1_live_avatar.trigger_hotkey_emote(key_name)
                if self.current_screen == "workshop" and self.workshop_player == 1:
                    self.w_live_avatar.trigger_hotkey_emote(key_name)
            elif avatar_num == 2:
                self.p2_live_avatar.trigger_hotkey_emote(key_name)
                if self.current_screen == "workshop" and self.workshop_player == 2:
                    self.w_live_avatar.trigger_hotkey_emote(key_name)

    def _on_global_key_press(self, event):
        w = event.widget
        if isinstance(w, (tk.Entry, ttk.Entry)):
            return
        keysym = str(getattr(event, "keysym", ""))
        if not keysym:
            return
        if keysym.lower() == "m":
            if self.current_screen == "workshop" and self.workshop_player == 2:
                muted = self.audio_engine.toggle_discord_mute()
                if self.avatar2_window and self.avatar2_window.winfo_exists():
                    self.avatar2_window.is_muted = muted
                    self.avatar2_window._update_display()
            else:
                muted = self.audio_engine.toggle_mic_mute()
                if self.avatar1_window and self.avatar1_window.winfo_exists():
                    self.avatar1_window.is_muted = muted
                    self.avatar1_window._update_display()
            self._sync_mute_buttons()
            return

        # Disparar emotes configurados por tecla rápida en 1P, 2P, Taller y Ventanas OBS
        self.p1_live_avatar.trigger_hotkey_emote(keysym)
        self.p2_live_avatar.trigger_hotkey_emote(keysym)
        self.w_live_avatar.trigger_hotkey_emote(keysym)
        if self.avatar1_window and self.avatar1_window.winfo_exists():
            self.avatar1_window.trigger_hotkey_emote(keysym)
        if self.avatar2_window and self.avatar2_window.winfo_exists():
            self.avatar2_window.trigger_hotkey_emote(keysym)

    def _on_mic_level_thread(self, level):
        self.mic_level = level

    def _on_discord_level_thread(self, level):
        self.discord_level = level

    def _on_mic_state_thread(self, talking):
        self.mic_talking = talking

    def _on_discord_state_thread(self, talking):
        self.discord_talking = talking

    def _on_mic_scream_thread(self, screaming):
        self.p1_is_screaming = screaming

    def _on_discord_scream_thread(self, screaming):
        self.p2_is_screaming = screaming

    def _safe_set_avatar_talking(self, avatar_num, talking):
        try:
            if avatar_num == 1:
                if self.avatar1_window and self.avatar1_window.winfo_exists():
                    self.avatar1_window.set_talking(talking)
            elif avatar_num == 2:
                if self.avatar2_window and self.avatar2_window.winfo_exists():
                    self.avatar2_window.set_talking(talking)
        except Exception:
            pass

    def _safe_set_avatar_scream(self, avatar_num, screaming):
        try:
            if avatar_num == 1:
                if self.avatar1_window and self.avatar1_window.winfo_exists():
                    self.avatar1_window.set_screaming(screaming)
            elif avatar_num == 2:
                if self.avatar2_window and self.avatar2_window.winfo_exists():
                    self.avatar2_window.set_screaming(screaming)
        except Exception:
            pass

    # =========================================================================
    # --- SISTEMA DE CARPETAS DE PERSONAJES Y PERSISTENCIA ---
    # =========================================================================
    def _sanitize_folder_name(self, name):
        invalid_chars = '<>:"/\\|?*'
        cleaned = "".join("_" if c in invalid_chars else c for c in str(name).strip())
        cleaned = cleaned.rstrip(". ")
        return cleaned if cleaned else "Personaje"

    def _get_character_folder(self, name):
        os.makedirs(CHARACTERS_DIR, exist_ok=True)
        folder_name = self._sanitize_folder_name(name)
        folder_path = os.path.abspath(os.path.join(CHARACTERS_DIR, folder_name))
        os.makedirs(folder_path, exist_ok=True)
        return folder_path

    def _find_role_file_in_folder(self, folder_path, role):
        """Busca un archivo de expresión en la carpeta del personaje (.gif, .webp o .png)."""
        for ext in (".gif", ".webp", ".png"):
            cand = os.path.join(folder_path, f"{role}{ext}")
            if os.path.exists(cand):
                return cand
        return os.path.join(folder_path, f"{role}.png")

    def _ensure_character_folder_assets(self, name, p1_dict, p2_dict, default_prefix="a1"):
        """Garantiza que el personaje tenga su propia carpeta en 'personajes/<Nombre>/'
        con sus propios archivos de expresión (PNG, GIF o WEBP)."""
        folder_path = self._get_character_folder(name)
        roles = ("idle", "idle_blink", "talk", "talk_blink", "scream")

        for role in roles:
            dest_file = self._find_role_file_in_folder(folder_path, role)
            if not os.path.exists(dest_file):
                # Buscar imagen origen en el perfil actual o usar el asset base
                cand_p1 = p1_dict.get(f"a1_{role}", "") if isinstance(p1_dict, dict) else ""
                cand_p2 = p2_dict.get(f"a2_{role}", "") if isinstance(p2_dict, dict) else ""
                fallback = self.default_assets.get(f"{default_prefix}_{role}", self.default_assets[f"a1_{role}"])

                src_file = fallback
                if cand_p1 and os.path.exists(cand_p1):
                    src_file = cand_p1
                elif cand_p2 and os.path.exists(cand_p2):
                    src_file = cand_p2

                if src_file and os.path.exists(src_file):
                    ext = os.path.splitext(src_file)[1].lower()
                    save_ext = ext if ext in (".gif", ".webp", ".png") else ".png"
                    dest_file = os.path.join(folder_path, f"{role}{save_ext}")
                    try:
                        shutil.copy2(src_file, dest_file)
                    except Exception as e:
                        print(f"[Carpeta] Error inicializando {dest_file}: {e}")

            if isinstance(p1_dict, dict):
                p1_dict[f"a1_{role}"] = dest_file
            if isinstance(p2_dict, dict):
                p2_dict[f"a2_{role}"] = dest_file

        # Cargar props y expresiones situacionales desde character.json si existen
        meta_path = os.path.join(folder_path, "character.json")
        loaded_props = []
        loaded_extras = []
        meta_disk = {}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta_disk = json.load(f)
                    for p in meta_disk.get("props", []):
                        p_loaded = dict(p)
                        if p_loaded.get("file_rel"):
                            cand_rel = os.path.abspath(os.path.join(folder_path, p_loaded["file_rel"]))
                            if os.path.exists(cand_rel):
                                p_loaded["file"] = cand_rel
                        if not p_loaded.get("file") or not os.path.exists(p_loaded.get("file", "")):
                            cand = os.path.join(folder_path, "props", os.path.basename(p_loaded.get("file", "")))
                            if os.path.exists(cand):
                                p_loaded["file"] = cand
                        p_loaded.setdefault("visible_frames", "all")
                        p_loaded.setdefault("layer", "front")
                        p_loaded.setdefault("follows_bounce", False)
                        p_loaded.setdefault("offset_x", 0)
                        p_loaded.setdefault("offset_y", 0)
                        p_loaded.setdefault("scale", 100)
                        p_loaded.setdefault("enabled", True)
                        loaded_props.append(p_loaded)

                    for ex in meta_disk.get("extra_expressions", []):
                        ex_loaded = dict(ex)
                        r_id = ex_loaded.get("role", "")
                        if ex_loaded.get("file_rel"):
                            cand_f = os.path.abspath(os.path.join(folder_path, ex_loaded["file_rel"]))
                            if os.path.exists(cand_f):
                                ex_loaded["file"] = cand_f
                        if not ex_loaded.get("file") or not os.path.exists(ex_loaded.get("file", "")):
                            if r_id:
                                ex_loaded["file"] = self._find_role_file_in_folder(folder_path, r_id)
                        loaded_extras.append(ex_loaded)
            except Exception:
                pass

        # Detectar archivos en props/ que aún no estén registrados en character.json
        props_subdir = os.path.join(folder_path, "props")
        if os.path.isdir(props_subdir):
            known_files = {os.path.abspath(p.get("file", "")).lower() for p in loaded_props if p.get("file")}
            try:
                for fname in sorted(os.listdir(props_subdir)):
                    if fname.lower().endswith((".png", ".gif", ".webp")):
                        fpath = os.path.abspath(os.path.join(props_subdir, fname))
                        if fpath.lower() not in known_files:
                            bname = os.path.splitext(fname)[0].replace("_", " ").replace("-", " ").title()
                            loaded_props.append({
                                "id": f"prop_{self._sanitize_folder_name(fname)}_{len(loaded_props)+1}",
                                "name": bname,
                                "file": fpath,
                                "file_rel": f"props/{fname}",
                                "layer": "front",
                                "follows_bounce": False,
                                "offset_x": 0,
                                "offset_y": 0,
                                "scale": 100,
                                "enabled": True,
                                "visible_frames": "all",
                            })
                            known_files.add(fpath.lower())
            except Exception:
                pass

        disk_flip_x = meta_disk.get("flip_x", None)

        if isinstance(p1_dict, dict):
            if "flip_x" not in p1_dict and disk_flip_x is not None:
                p1_dict["flip_x"] = bool(disk_flip_x)
            elif "flip_x" not in p1_dict:
                p1_dict["flip_x"] = False
            if "props" not in p1_dict or not p1_dict["props"]:
                p1_dict["props"] = loaded_props if loaded_props else []
            if loaded_extras and ("extra_expressions" not in p1_dict or not p1_dict["extra_expressions"]):
                p1_dict["extra_expressions"] = [dict(x) for x in loaded_extras]
            for ex in p1_dict.get("extra_expressions", []) or []:
                r_id = ex.get("role")
                if r_id:
                    if ex.get("file"):
                        p1_dict[f"a1_{r_id}"] = ex["file"]
                    if ex.get("motion"):
                        p1_dict[f"a1_{r_id}_motion"] = ex["motion"]

        if isinstance(p2_dict, dict):
            if "flip_x" not in p2_dict and disk_flip_x is not None:
                p2_dict["flip_x"] = bool(disk_flip_x)
            elif "flip_x" not in p2_dict:
                p2_dict["flip_x"] = bool(p1_dict.get("flip_x", False)) if isinstance(p1_dict, dict) else False
            if "props" not in p2_dict or not p2_dict["props"]:
                p2_dict["props"] = [dict(x) for x in loaded_props] if loaded_props else []
            if loaded_extras and ("extra_expressions" not in p2_dict or not p2_dict["extra_expressions"]):
                p2_dict["extra_expressions"] = [dict(x) for x in loaded_extras]
            for ex in p2_dict.get("extra_expressions", []) or []:
                r_id = ex.get("role")
                if r_id:
                    if ex.get("file"):
                        p2_dict[f"a2_{r_id}"] = ex["file"]
                    if ex.get("motion"):
                        p2_dict[f"a2_{r_id}_motion"] = ex["motion"]

        # Cargar animaciones y velocidades asignadas por expresión
        saved_motions = meta_disk.get("motions", {})
        saved_speeds = meta_disk.get("motion_speeds", {})
        for r in roles:
            if r in saved_motions:
                m_val = "Respiración" if saved_motions[r] == "Rebote" else saved_motions[r]
                if isinstance(p1_dict, dict):
                    p1_dict[f"a1_{r}_motion"] = m_val
                if isinstance(p2_dict, dict):
                    p2_dict[f"a2_{r}_motion"] = m_val
            if r in saved_speeds:
                try:
                    sp_val = float(saved_speeds[r])
                except Exception:
                    sp_val = 1.0
                if isinstance(p1_dict, dict):
                    p1_dict[f"a1_{r}_speed"] = sp_val
                if isinstance(p2_dict, dict):
                    p2_dict[f"a2_{r}_speed"] = sp_val

        self._save_character_folder_meta(name, p1_dict, p2_dict)

    def _save_character_folder_meta(self, name, p1_dict=None, p2_dict=None, explicit_props=None):
        folder_path = self._get_character_folder(name)
        if p1_dict is None:
            p1_dict = self.profiles.get("player1", {}).get(name, self.p1_data)
        if p2_dict is None:
            p2_dict = self.profiles.get("player2", {}).get(name, self.p2_data)

        if explicit_props is not None:
            props_list = explicit_props
        elif isinstance(p1_dict, dict) and "props" in p1_dict and (p1_dict["props"] or not (isinstance(p2_dict, dict) and p2_dict.get("props"))):
            props_list = p1_dict["props"]
        elif isinstance(p2_dict, dict) and "props" in p2_dict:
            props_list = p2_dict["props"]
        else:
            props_list = []
        clean_props = []
        for p in props_list:
            p_copy = dict(p)
            f_path = p_copy.get("file", "")
            if f_path:
                try:
                    p_copy["file_rel"] = os.path.relpath(f_path, folder_path).replace("\\", "/")
                except Exception:
                    p_copy["file_rel"] = f"props/{os.path.basename(f_path)}"
            clean_props.append(p_copy)

        extras_list = p1_dict.get("extra_expressions") or p2_dict.get("extra_expressions") or []
        clean_extras = []
        for ex in extras_list:
            ex_copy = dict(ex)
            f_path = ex_copy.get("file", "")
            if f_path:
                try:
                    ex_copy["file_rel"] = os.path.relpath(f_path, folder_path).replace("\\", "/")
                except Exception:
                    ex_copy["file_rel"] = os.path.basename(f_path)
            clean_extras.append(ex_copy)

        # Guardar tipos de animación y velocidades asignadas por estado
        motions_map = {}
        speeds_map = {}
        for r in ("idle", "idle_blink", "talk", "talk_blink", "scream"):
            m = p1_dict.get(f"a1_{r}_motion") or p2_dict.get(f"a2_{r}_motion")
            if m:
                motions_map[r] = "Respiración" if m == "Rebote" else m
            sp = p1_dict.get(f"a1_{r}_speed")
            if sp is None:
                sp = p2_dict.get(f"a2_{r}_speed")
            if sp is not None:
                try:
                    speeds_map[r] = round(float(sp), 2)
                except Exception:
                    pass
        for ex in clean_extras:
            r_id = ex.get("role")
            if r_id:
                m = p1_dict.get(f"a1_{r_id}_motion") or p2_dict.get(f"a2_{r_id}_motion") or ex.get("motion")
                if m:
                    motions_map[r_id] = "Respiración" if m == "Rebote" else m
                sp = p1_dict.get(f"a1_{r_id}_speed")
                if sp is None:
                    sp = p2_dict.get(f"a2_{r_id}_speed")
                if sp is None:
                    sp = ex.get("speed")
                if sp is not None:
                    try:
                        speeds_map[r_id] = round(float(sp), 2)
                    except Exception:
                        pass

        meta = {
            "name": name,
            "image_mode": p1_dict.get("image_mode", p2_dict.get("image_mode", "4_states")),
            "flip_x": bool(p1_dict.get("flip_x", p2_dict.get("flip_x", False))),
            "mic_threshold": p1_dict.get("mic_threshold", 20),
            "discord_threshold": p2_dict.get("discord_threshold", 25),
            "scream_threshold": p1_dict.get("scream_threshold", 55),
            "props": clean_props,
            "extra_expressions": clean_extras,
            "motions": motions_map,
            "motion_speeds": speeds_map,
            "expressions": {
                r: os.path.basename(self._find_role_file_in_folder(folder_path, r))
                for r in ("idle", "idle_blink", "talk", "talk_blink", "scream")
            },
        }
        meta_path = os.path.join(folder_path, "character.json")
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _register_new_character_folder(self, name, mode, default_prefix="a1"):
        p1_entry = {
            "mic_device_name": self.p1_data.get("mic_device_name", ""),
            "mic_threshold": 20,
            "scream_threshold": 55,
            "image_mode": mode,
            "flip_x": False,
        }
        p2_entry = {
            "discord_source_id": self.p2_data.get("discord_source_id", "app:discord"),
            "discord_threshold": 25,
            "scream_threshold": 55,
            "image_mode": mode,
            "flip_x": False,
        }
        self._ensure_character_folder_assets(name, p1_entry, p2_entry, default_prefix=default_prefix)
        self.profiles["player1"][name] = p1_entry
        self.profiles["player2"][name] = p2_entry
        self.save_profiles_to_disk()

    def _scan_disk_character_folders(self):
        """Escanea la carpeta 'personajes/' para detectar carpetas añadidas manualmente."""
        os.makedirs(CHARACTERS_DIR, exist_ok=True)
        try:
            entries = sorted(os.listdir(CHARACTERS_DIR))
        except Exception:
            return

        existing_sanitized = {
            self._sanitize_folder_name(k): k
            for k in list(self.profiles.get("player1", {}).keys()) + list(self.profiles.get("player2", {}).keys())
        }

        for folder_name in entries:
            full_dir = os.path.abspath(os.path.join(CHARACTERS_DIR, folder_name))
            if not os.path.isdir(full_dir):
                continue

            meta_path = os.path.join(full_dir, "character.json")
            char_name = folder_name
            meta = {}
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        if meta.get("name"):
                            char_name = str(meta["name"]).strip()
                except Exception:
                    pass

            if folder_name in existing_sanitized:
                char_name = existing_sanitized[folder_name]

            if char_name not in self.profiles["player1"]:
                self.profiles["player1"][char_name] = {
                    "mic_device_name": self.p1_data.get("mic_device_name", ""),
                    "mic_threshold": meta.get("mic_threshold", 20),
                    "scream_threshold": meta.get("scream_threshold", 55),
                    "image_mode": meta.get("image_mode", "4_states"),
                    "flip_x": bool(meta.get("flip_x", False)),
                }
            if char_name not in self.profiles["player2"]:
                self.profiles["player2"][char_name] = {
                    "discord_source_id": self.p2_data.get("discord_source_id", "app:discord"),
                    "discord_threshold": meta.get("discord_threshold", 25),
                    "scream_threshold": meta.get("scream_threshold", 55),
                    "image_mode": meta.get("image_mode", "4_states"),
                    "flip_x": bool(meta.get("flip_x", False)),
                }

    def _open_root_characters_folder(self):
        os.makedirs(CHARACTERS_DIR, exist_ok=True)
        abs_dir = os.path.abspath(CHARACTERS_DIR)
        log_debug(f"[CARPETA] 📂 Abriendo directorio raíz de personajes: {abs_dir}")
        try:
            os.startfile(abs_dir)
        except Exception as e:
            messagebox.showinfo("Carpeta de Personajes", f"Ruta de personajes:\n{abs_dir}\n({e})")

    def _open_character_folder_in_explorer(self, name):
        folder_path = self._get_character_folder(name)
        log_debug(f"[CARPETA] 📂 Abriendo carpeta de '{name}': {folder_path}")
        try:
            os.startfile(folder_path)
        except Exception as e:
            messagebox.showinfo("Carpeta del Personaje", f"Ruta de '{name}':\n{folder_path}\n({e})")

    def _open_current_workshop_folder(self):
        curr = self.global_config.get(f"current_p{self.workshop_player}_profile", "Gatito Azul")
        self._open_character_folder_in_explorer(curr)

    def load_all_data(self):
        os.makedirs(CHARACTERS_DIR, exist_ok=True)

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved_cfg = json.load(f)
                    self.global_config.update(saved_cfg)
            except Exception:
                pass

        if os.path.exists(PROFILES_FILE):
            try:
                with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                    self.profiles = json.load(f)
            except Exception:
                self.profiles = {"player1": {}, "player2": {}}

        if "player1" not in self.profiles:
            self.profiles["player1"] = {}
        if "player2" not in self.profiles:
            self.profiles["player2"] = {}

        root_keys = [k for k in list(self.profiles.keys()) if k not in ("player1", "player2")]
        for k in root_keys:
            data = self.profiles.pop(k)
            if isinstance(data, dict):
                p1_char = {
                    "mic_device_name": data.get("mic_device_name", ""),
                    "mic_threshold": data.get("mic_threshold", 20),
                    "scream_threshold": data.get("scream_threshold", 55),
                    "image_mode": data.get("image_mode", "4_states"),
                    "props": data.get("props", []),
                    "a1_idle": data.get("a1_idle", self.default_assets["a1_idle"]),
                    "a1_idle_blink": data.get("a1_idle_blink", self.default_assets["a1_idle_blink"]),
                    "a1_talk": data.get("a1_talk", self.default_assets["a1_talk"]),
                    "a1_talk_blink": data.get("a1_talk_blink", self.default_assets["a1_talk_blink"]),
                    "a1_scream": data.get("a1_scream", self.default_assets["a1_scream"]),
                }
                if k not in self.profiles["player1"]:
                    self.profiles["player1"][k] = p1_char

        if not self.profiles["player1"]:
            self.profiles["player1"] = {"Gatito Azul": dict(self.p1_data)}

        if not self.profiles["player2"]:
            self.profiles["player2"] = {"Osito Discord": dict(self.p2_data)}

        # Escanear carpetas en 'personajes/' y unificar todos los personajes como carpetas propias
        self._scan_disk_character_folders()

        all_char_names = []
        for k in list(self.profiles["player1"].keys()) + list(self.profiles["player2"].keys()):
            if k not in all_char_names:
                all_char_names.append(k)

        for name in all_char_names:
            was_only_p2 = (name not in self.profiles["player1"] and name in self.profiles["player2"])
            if name not in self.profiles["player1"]:
                p2_ref = self.profiles["player2"][name]
                self.profiles["player1"][name] = {
                    "mic_device_name": self.p1_data.get("mic_device_name", ""),
                    "mic_threshold": 20,
                    "scream_threshold": p2_ref.get("scream_threshold", 55),
                    "image_mode": p2_ref.get("image_mode", "4_states"),
                    "props": list(p2_ref.get("props", [])),
                }
            if name not in self.profiles["player2"]:
                p1_ref = self.profiles["player1"][name]
                self.profiles["player2"][name] = {
                    "discord_source_id": self.p2_data.get("discord_source_id", "app:discord"),
                    "discord_threshold": 25,
                    "scream_threshold": p1_ref.get("scream_threshold", 55),
                    "image_mode": p1_ref.get("image_mode", "4_states"),
                    "props": list(p1_ref.get("props", [])),
                }

            default_pref = "a2" if (was_only_p2 or name == "Osito Discord") else "a1"
            self._ensure_character_folder_assets(
                name,
                self.profiles["player1"][name],
                self.profiles["player2"][name],
                default_prefix=default_pref
            )

        p1_name = self.global_config.get("current_p1_profile", "Gatito Azul")
        if p1_name in self.profiles["player1"]:
            self.p1_data.update(self.profiles["player1"][p1_name])
        else:
            first_p1 = list(self.profiles["player1"].keys())[0]
            self.p1_data.update(self.profiles["player1"][first_p1])
            self.global_config["current_p1_profile"] = first_p1

        p2_name = self.global_config.get("current_p2_profile", "Osito Discord")
        if p2_name in self.profiles["player2"]:
            self.p2_data.update(self.profiles["player2"][p2_name])
        else:
            first_p2 = list(self.profiles["player2"].keys())[0]
            self.p2_data.update(self.profiles["player2"][first_p2])
            self.global_config["current_p2_profile"] = first_p2

        for k in ["a1_idle", "a1_idle_blink", "a1_talk", "a1_talk_blink", "a1_scream"]:
            if not self.p1_data.get(k) or not os.path.exists(self.p1_data[k]):
                self.p1_data[k] = self.default_assets[k]

        for k in ["a2_idle", "a2_idle_blink", "a2_talk", "a2_talk_blink", "a2_scream"]:
            if not self.p2_data.get(k) or not os.path.exists(self.p2_data[k]):
                self.p2_data[k] = self.default_assets[k]

        self.save_profiles_to_disk()

    def _get_character_thumbnail(self, image_path, size=(44, 44)):
        if image_path and os.path.exists(image_path):
            try:
                img = Image.open(image_path).convert("RGBA")
                img.thumbnail(size, Image.Resampling.LANCZOS)
                thumb = Image.new("RGBA", size, (0, 0, 0, 0))
                offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
                thumb.paste(img, offset)
                return ImageTk.PhotoImage(thumb)
            except Exception:
                pass
        return None

    def _save_p1_profile(self):
        curr = self.global_config.get("current_p1_profile", "Gatito Azul")
        if "player1" not in self.profiles:
            self.profiles["player1"] = {}
        self.profiles["player1"][curr] = dict(self.p1_data)
        self.save_profiles_to_disk()
        self.save_global_config()

    def _save_p2_profile(self):
        curr = self.global_config.get("current_p2_profile", "Osito Discord")
        if "player2" not in self.profiles:
            self.profiles["player2"] = {}
        self.profiles["player2"][curr] = dict(self.p2_data)
        self.save_profiles_to_disk()
        self.save_global_config()

    def save_global_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.global_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] Error guardando config: {e}")

    def save_profiles_to_disk(self):
        try:
            with open(PROFILES_FILE, "w", encoding="utf-8") as f:
                json.dump(self.profiles, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Profiles] Error guardando profiles: {e}")

    def on_close(self):
        log_debug("[SISTEMA] Cerrando aplicación, guardando datos y terminando audio...")
        try:
            self.hotkey_listener.stop()
        except Exception:
            pass
        try:
            self.twitch_alert_server.stop()
        except Exception:
            pass
        self._save_p1_profile()
        self._save_p2_profile()
        self.save_global_config()
        self.audio_engine.terminate()
        self.root.destroy()
        log_debug("[SISTEMA] Aplicación finalizada correctamente.")


if __name__ == "__main__":
    log_debug("==================================================")
    log_debug("  PNGTuber Duo / Coop - Modo Debug Iniciado")
    log_debug("==================================================")
    root = tk.Tk()
    app = PNGTuberCoopApp(root)
    root.mainloop()
