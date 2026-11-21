import tkinter as tk
from PIL import Image, ImageTk
import os
import time
import random
import math
import gc

from core.app_constants import log_debug
from core.emotions import get_effective_pose_data
from core.async_loader import get_performance_preset, load_pil_frames_from_path, resize_avatar_frames, submit_bg_task
from core.lipsync import (
    MouthLipsyncEngine,
    MouthRenderCache,
    is_independent_mouth_active,
    resolve_mouth_frame_config,
)
from core.eyes import (
    EyesRenderCache,
    compute_mouse_eye_offset,
    is_independent_eyes_active,
    resolve_eye_set_for_role,
    resolve_eyes_frame_config,
)

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
        self.independent_mouth = {}
        self.mouth_engine = MouthLipsyncEngine()
        self.mouth_cache = MouthRenderCache()
        self.mouth_item = None
        self._mouth_slot = "closed"
        self._mouth_squash = 0
        self.independent_eyes = {}
        self.eyes_cache = EyesRenderCache()
        self.eyes_item = None
        self._eye_ox = 0.0
        self._eye_oy = 0.0
        self._load_gen = 0
        self.perf_mode = "performance"

        # Contexto para expresiones situacionales / extra
        self.extra_expressions = []
        self.is_muted = False
        self.audio_level = 0.0
        self.vowel_hint = None
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
        self.independent_mouth = self.char_data.get("independent_mouth") or {}
        self.independent_eyes = self.char_data.get("independent_eyes") or {}
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

        self._load_gen += 1
        gen_id = self._load_gen
        cw = max(self.size[0], self.canvas.winfo_width())
        ch = max(self.size[1], self.canvas.winfo_height())
        if cw <= 30 or ch <= 30:
            cw, ch = self.size[0], self.size[1]
        avail_w = max(20, cw - 16)
        avail_h = max(20, ch - 16)
        eff_imgs, _, _ = get_effective_pose_data(self.char_data, prefix=prefix)
        role_paths = {role: eff_imgs.get(role) or self.char_data.get(key) for role, key in keys_map.items()}
        props_snapshot = [dict(p) for p in (self.char_data.get("props", []) or [])]
        flip_x = self.flip_x
        mouth_cfg = dict(self.independent_mouth) if isinstance(self.independent_mouth, dict) else {}
        preset = get_performance_preset(getattr(self, "perf_mode", "performance"))
        av_max_dim = preset["preview_max_dim"]
        av_max_frames = preset["preview_max_frames"]
        m_max_dim = preset["preview_mouth_dim"]

        def _bg_load():
            raw_imgs = {}
            for role, path in role_paths.items():
                if self._load_gen != gen_id:
                    return
                frames = load_pil_frames_from_path(path, max_dim=av_max_dim, max_frames=av_max_frames)
                if frames:
                    raw_imgs[role] = frames

            raw_props = []
            for pr in props_snapshot:
                if self._load_gen != gen_id:
                    return
                f_path = pr.get("file", "")
                p_frames = load_pil_frames_from_path(f_path, max_dim=av_max_dim, max_frames=av_max_frames)
                if p_frames:
                    raw_props.append({
                        "id": pr.get("id", str(id(pr))),
                        "_file": f_path,
                        "raw_frames": p_frames,
                        "layer": pr.get("layer", "front"),
                        "follows_bounce": bool(pr.get("follows_bounce", False)),
                        "offset_x": int(pr.get("offset_x", 0)),
                        "offset_y": int(pr.get("offset_y", 0)),
                        "scale": float(pr.get("scale", 100)) / 100.0,
                        "rotation": float(pr.get("rotation", 0)),
                        "enabled": bool(pr.get("enabled", True)),
                        "visible_frames": pr.get("visible_frames", "all"),
                    })

            resized_imgs = resize_avatar_frames(raw_imgs, avail_w, avail_h, flip_x=flip_x)
            resized_props = []
            for cp in raw_props:
                sc_f = cp.get("scale", 1.0)
                rot_d = float(cp.get("rotation", 0))
                s_frames = []
                for raw_img, dur_sec in cp["raw_frames"]:
                    iw, ih = raw_img.size
                    if iw <= 0 or ih <= 0:
                        continue
                    ratio = min(avail_w / iw, avail_h / ih) * sc_f
                    nw = max(1, int(iw * ratio))
                    nh = max(1, int(ih * ratio))
                    res_p = raw_img.resize((nw, nh), Image.Resampling.LANCZOS)
                    if rot_d != 0:
                        res_p = res_p.rotate(-rot_d, resample=Image.Resampling.BICUBIC, expand=True)
                    s_frames.append((res_p, dur_sec))
                resized_props.append((cp, s_frames))

            mouth_cache_bg = MouthRenderCache()
            mouth_cache_bg.load_pil_frames(mouth_cfg, flip_x=flip_x, max_dim=m_max_dim)

            if self._load_gen == gen_id:
                try:
                    self.after(0, lambda: self._apply_async_character_assets(
                        gen_id, cw, ch, raw_imgs, raw_props, resized_imgs, resized_props, mouth_cache_bg
                    ))
                except Exception:
                    pass

        submit_bg_task(_bg_load)

    def _apply_async_character_assets(self, gen_id, cw, ch, raw_imgs, raw_props, resized_imgs, resized_props, mouth_cache_bg):
        if gen_id != self._load_gen or not self.winfo_exists():
            return
        self.raw_images = raw_imgs
        self.raw_props = raw_props
        self.mouth_cache = mouth_cache_bg
        self.eyes_cache.load_pil_frame(self.independent_eyes, flip_x=self.flip_x)
        self._last_rebuild_size = (cw, ch)
        self.images_cache.clear()
        self.base_resized_images.clear()
        self.squash_photo_cache.clear()
        gc.collect()

        for role, flist in resized_imgs.items():
            pil_frames = [fr for fr, _ in flist]
            scaled_frames = [(ImageTk.PhotoImage(fr), dur) for fr, dur in flist]
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
        for cp, s_frames in resized_props:
            self.photo_props.append({
                "id": cp["id"],
                "_file": cp.get("_file", ""),
                "_scale": cp.get("scale", 1.0),
                "_rotation": float(cp.get("rotation", 0)),
                "frames": [(ImageTk.PhotoImage(fr), dur) for fr, dur in s_frames],
                "layer": cp.get("layer", "front"),
                "follows_bounce": cp.get("follows_bounce", False),
                "offset_x": cp.get("offset_x", 0),
                "offset_y": cp.get("offset_y", 0),
                "enabled": cp.get("enabled", True),
                "visible_frames": cp.get("visible_frames", "all"),
            })
        self._render()

    def _rebuild_photo_cache(self):
        cw = max(self.size[0], self.canvas.winfo_width())
        ch = max(self.size[1], self.canvas.winfo_height())
        if cw <= 30 or ch <= 30:
            cw, ch = self.size[0], self.size[1]

        if getattr(self, "_last_rebuild_size", None) == (cw, ch):
            return
        if not self.raw_images:
            return
        self._last_rebuild_size = (cw, ch)

        padding = 8
        avail_w = max(20, cw - padding * 2)
        avail_h = max(20, ch - padding * 2)

        self.images_cache.clear()
        self.base_resized_images.clear()
        self.squash_photo_cache.clear()
        gc.collect()
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
        if talking and not is_independent_mouth_active(self.independent_mouth):
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

    def update_state(self, talking, screaming, muted=None, audio_level=None, talk_threshold=None, partner_talking=None, partner_screaming=None, vowel_hint=None):
        now = time.time()
        mute_changed = False
        if muted is not None:
            new_m = bool(muted)
            if self.is_muted != new_m:
                mute_changed = True
            self.is_muted = new_m
        if audio_level is not None:
            self.audio_level = float(audio_level)
        self.vowel_hint = vowel_hint
        if talk_threshold is not None:
            self.talk_threshold = float(talk_threshold)
        if partner_talking is not None:
            self.partner_talking = bool(partner_talking)
        if partner_screaming is not None:
            self.partner_screaming = bool(partner_screaming)

        if self.is_talking != talking:
            self.last_activity_time = now
            if talking and not is_independent_mouth_active(self.independent_mouth):
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

        if is_independent_mouth_active(self.independent_mouth):
            new_slot, new_msquash = self.mouth_engine.update(
                self.audio_level,
                self.talk_threshold,
                self.is_talking,
                self.is_screaming,
                self.is_muted,
                self.mouth_cache.pil_frames.keys(),
                squash_strength=self.independent_mouth.get("squash_strength", 100),
                mode=self.independent_mouth.get("mode", "volume"),
                vowel_hint=getattr(self, "vowel_hint", None),
            )
            if new_slot != self._mouth_slot or new_msquash != self._mouth_squash:
                self._mouth_slot = new_slot
                self._mouth_squash = new_msquash
                self._render()

        if is_independent_eyes_active(self.independent_eyes):
            self._tick_eyes_mouse_follow()

        self.after(get_performance_preset(getattr(self, "perf_mode", "performance"))["preview_fps_ms"], self._animate_loop)

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
        if len(self.squash_photo_cache) >= get_performance_preset(getattr(self, "perf_mode", "performance"))["squash_cache_max"]:
            self.squash_photo_cache.clear()
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

    def _get_pos_scale(self, w, h, role=None):
        avail_w = max(20, w - 16)
        avail_h = max(20, h - 16)
        frames = (self.raw_images.get(role) if role else None) or self.raw_images.get("idle")
        if frames:
            raw_img = frames[self.anim_frame_idx % len(frames)][0]
            rw, rh = max(1, raw_img.width), max(1, raw_img.height)
            fit_ratio = min(avail_w / rw, avail_h / rh)
            return fit_ratio * max(rw, rh) / 384.0
        return min(avail_w, avail_h) / 384.0

    def _update_position_only(self):
        w = max(self.size[0], self.canvas.winfo_width())
        h = max(self.size[1], self.canvas.winfo_height())
        base_x = (w // 2)
        base_y = (h // 2)
        role = self._get_current_role()
        pos_scale = self._get_pos_scale(w, h, role)

        if self.image_item is not None:
            x = base_x + self.jitter_x
            y = base_y + int(self.current_offset_y) + self.jitter_y + getattr(self, "squash_anchor_dy", 0)
            self.canvas.coords(self.image_item, x, y)
        self._update_eyes_position_only(base_x, base_y, pos_scale, role)
        self._update_mouth_position_only(base_x, base_y, pos_scale, role)

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
        pos_scale = self._get_pos_scale(w, h, role)

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
        eyes_canvas_item = self._render_preview_eyes_item(base_x, base_y, pos_scale, role)
        mouth_canvas_item = self._render_preview_mouth_item(base_x, base_y, pos_scale, role)
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
            if eyes_canvas_item is not None:
                self.canvas.tag_raise(eyes_canvas_item, prev_it)
                prev_it = eyes_canvas_item
            if mouth_canvas_item is not None:
                self.canvas.tag_raise(mouth_canvas_item, prev_it)
                prev_it = mouth_canvas_item
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

    def _get_mouth_coords(self, base_x, base_y, pos_scale, ox, oy):
        eff_ox = -ox if self.flip_x else ox
        dx = int(eff_ox * pos_scale)
        dy = int(oy * pos_scale)
        if self.independent_mouth.get("follows_bounce", True):
            return base_x + dx + self.jitter_x, base_y + dy + int(self.current_offset_y) + self.jitter_y
        return base_x + dx, base_y + dy

    def _update_mouth_position_only(self, base_x, base_y, pos_scale, role):
        if self.mouth_item is None:
            return
        if not is_independent_mouth_active(self.independent_mouth):
            try:
                self.canvas.itemconfig(self.mouth_item, state="hidden")
            except tk.TclError:
                self.mouth_item = None
            return
        hidden, ox, oy, _, _, _ = resolve_mouth_frame_config(self.independent_mouth, role)
        try:
            if hidden:
                self.canvas.itemconfig(self.mouth_item, state="hidden")
            else:
                mx, my = self._get_mouth_coords(base_x, base_y, pos_scale, ox, oy)
                self.canvas.coords(self.mouth_item, mx, my)
                self.canvas.itemconfig(self.mouth_item, state="normal")
        except tk.TclError:
            self.mouth_item = None

    def _render_preview_mouth_item(self, base_x, base_y, pos_scale, role):
        if not is_independent_mouth_active(self.independent_mouth):
            if self.mouth_item is not None:
                try:
                    self.canvas.itemconfig(self.mouth_item, state="hidden")
                except tk.TclError:
                    self.mouth_item = None
            return None

        hidden, ox, oy, sc_pct, rot_deg, ov_key = resolve_mouth_frame_config(self.independent_mouth, role)
        if hidden:
            if self.mouth_item is not None:
                try:
                    self.canvas.itemconfig(self.mouth_item, state="hidden")
                except tk.TclError:
                    self.mouth_item = None
            return None

        eff_rot = -rot_deg if self.flip_x else rot_deg
        m_photo = self.mouth_cache.get_photo(
            self._mouth_slot,
            ov_key,
            self.anim_frame_idx,
            self._mouth_squash,
            pos_scale,
            sc_pct,
            eff_rot,
            max_cache=get_performance_preset(getattr(self, "perf_mode", "performance"))["mouth_cache_max"],
        )
        if m_photo is None:
            if self.mouth_item is not None:
                try:
                    self.canvas.itemconfig(self.mouth_item, state="hidden")
                except tk.TclError:
                    self.mouth_item = None
            return None

        mx, my = self._get_mouth_coords(base_x, base_y, pos_scale, ox, oy)
        if self.mouth_item is None:
            self.mouth_item = self.canvas.create_image(mx, my, anchor="center", image=m_photo)
        else:
            try:
                self.canvas.itemconfig(self.mouth_item, image=m_photo, state="normal")
                self.canvas.coords(self.mouth_item, mx, my)
            except tk.TclError:
                self.mouth_item = self.canvas.create_image(mx, my, anchor="center", image=m_photo)
        self.canvas.current_mouth_photo = m_photo
        return self.mouth_item

    def update_independent_eyes_fast(self, eyes_cfg):
        self.independent_eyes = eyes_cfg or {}
        self.eyes_cache.load_pil_frame(self.independent_eyes, flip_x=self.flip_x)
        self._render()

    def _get_eyes_base_coords(self, base_x, base_y, pos_scale, ox, oy):
        eff_ox = -ox if self.flip_x else ox
        dx = int(eff_ox * pos_scale)
        dy = int(oy * pos_scale)
        if self.independent_eyes.get("follows_bounce", True):
            return base_x + dx + self.jitter_x, base_y + dy + int(self.current_offset_y) + self.jitter_y
        return base_x + dx, base_y + dy

    def _tick_eyes_mouse_follow(self):
        w = max(self.size[0], self.canvas.winfo_width())
        h = max(self.size[1], self.canvas.winfo_height())
        base_x = (w // 2)
        base_y = (h // 2)
        role = self._get_current_role()
        pos_scale = self._get_pos_scale(w, h, role)
        self._update_eyes_position_only(base_x, base_y, pos_scale, role)

    def _resolve_eyes_draw_params(self, base_x, base_y, pos_scale, role):
        if not is_independent_eyes_active(self.independent_eyes):
            return None
        hidden, ox, oy, sc_pct, rot_deg, _ = resolve_eyes_frame_config(self.independent_eyes, role)
        if hidden:
            return None
        set_id, set_cfg = resolve_eye_set_for_role(self.independent_eyes, role)
        if set_id == "none" or set_cfg is None:
            return None
        bx, by = self._get_eyes_base_coords(base_x, base_y, pos_scale, ox, oy)
        if set_cfg.get("track_mouse", True):
            self._eye_ox, self._eye_oy = compute_mouse_eye_offset(
                self.canvas, bx, by, pos_scale, set_cfg, self._eye_ox, self._eye_oy
            )
        else:
            self._eye_ox, self._eye_oy = 0.0, 0.0
        eff_rot = -rot_deg if self.flip_x else rot_deg
        show_mask = bool(set_cfg.get("show_mask", False))
        return bx, by, sc_pct, eff_rot, set_id, show_mask

    def _update_eyes_position_only(self, base_x, base_y, pos_scale, role):
        if self.eyes_item is None:
            return
        params = self._resolve_eyes_draw_params(base_x, base_y, pos_scale, role)
        if params is None:
            try:
                self.canvas.itemconfig(self.eyes_item, state="hidden")
            except tk.TclError:
                self.eyes_item = None
            return
        bx, by, sc_pct, eff_rot, set_id, show_mask = params
        try:
            if self.eyes_cache.has_mask_or_overlay(set_id=set_id):
                e_photo, anchored = self.eyes_cache.get_tk_image(
                    pos_scale,
                    scale_pct=sc_pct,
                    rotation=eff_rot,
                    eye_ox=self._eye_ox,
                    eye_oy=self._eye_oy,
                    show_mask=show_mask,
                    set_id=set_id,
                )
                if e_photo is not None:
                    self.canvas.itemconfig(self.eyes_item, image=e_photo, state="normal")
                    self.canvas.current_eyes_photo = e_photo
                ex, ey = (bx, by) if anchored else (bx + self._eye_ox, by + self._eye_oy)
                self.canvas.coords(self.eyes_item, ex, ey)
            else:
                self.canvas.coords(self.eyes_item, bx + self._eye_ox, by + self._eye_oy)
                self.canvas.itemconfig(self.eyes_item, state="normal")
        except tk.TclError:
            self.eyes_item = None

    def _render_preview_eyes_item(self, base_x, base_y, pos_scale, role):
        params = self._resolve_eyes_draw_params(base_x, base_y, pos_scale, role)
        if params is None:
            if self.eyes_item is not None:
                try:
                    self.canvas.itemconfig(self.eyes_item, state="hidden")
                except tk.TclError:
                    self.eyes_item = None
            return None

        bx, by, sc_pct, eff_rot, set_id, show_mask = params
        e_photo, anchored = self.eyes_cache.get_tk_image(
            pos_scale,
            scale_pct=sc_pct,
            rotation=eff_rot,
            eye_ox=self._eye_ox,
            eye_oy=self._eye_oy,
            show_mask=show_mask,
            set_id=set_id,
        )
        if e_photo is None:
            if self.eyes_item is not None:
                try:
                    self.canvas.itemconfig(self.eyes_item, state="hidden")
                except tk.TclError:
                    self.eyes_item = None
            return None

        ex, ey = (bx, by) if anchored else (bx + self._eye_ox, by + self._eye_oy)
        if self.eyes_item is None:
            self.eyes_item = self.canvas.create_image(ex, ey, anchor="center", image=e_photo)
        else:
            try:
                self.canvas.itemconfig(self.eyes_item, image=e_photo, state="normal")
                self.canvas.coords(self.eyes_item, ex, ey)
            except tk.TclError:
                self.eyes_item = self.canvas.create_image(ex, ey, anchor="center", image=e_photo)
        self.canvas.current_eyes_photo = e_photo
        return self.eyes_item

