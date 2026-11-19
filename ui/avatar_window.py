import tkinter as tk
from PIL import Image, ImageTk
import os
import random
import time
import math
import gc
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
    resolve_eyes_frame_config,
)

class AvatarWindow(tk.Toplevel):
    def __init__(self, master, title, image_dict, mode_4_states=False, bg_color="#00FF00", bounce_enabled=True, on_hotkey=None, props_list=None, motions_map=None, motion_speeds_map=None, extra_expressions=None, flip_x=False, independent_mouth=None, independent_eyes=None, perf_mode="performance"):
        super().__init__(master)

        self.title(title)
        self.geometry("450x550")
        self.minsize(200, 200)
        self.configure(bg=bg_color)

        self.bg_color = bg_color
        self.bounce_enabled = bounce_enabled
        self.squash_enabled = True
        self.squash_state = 0
        self.flip_x = bool(flip_x)
        self.mode_4_states = mode_4_states
        self.on_hotkey = on_hotkey

        # Estados de visualización
        self.is_talking = False
        self.is_blinking = False
        self.is_screaming = False
        self.is_muted = False
        self.audio_level = 0.0
        self.talk_threshold = 20.0
        self.partner_talking = False
        self.partner_screaming = False

        # Temporizadores para transiciones, inactividad (AFK/Fidget) y emotes
        now_init = time.time()
        self.last_activity_time = now_init
        self.talk_start_time = 0.0
        self.talk_end_time = 0.0
        self.scream_start_time = 0.0
        self.blink_start_time = 0.0
        self.whisper_until = 0.0
        self.next_fidget_time = now_init + random.uniform(8.0, 16.0)
        self.fidget_end_time = 0.0
        self.fidget_active_role = None
        self.active_emote_role = None
        self.active_emote_until = 0.0
        self.preview_override_role = None
        self.preview_override_until = 0.0

        # Rutas de imágenes del avatar y expresiones extra
        self.images_paths = image_dict or {}
        self.motions_map = motions_map or {}
        self.motion_speeds_map = motion_speeds_map or {}
        self.congruence_enabled = True
        self.mouth_flutter_enabled = False
        self.extra_expressions = extra_expressions or []

        # Accesorios / Props independientes (escritorio, tableta, manos con mando, etc.)
        self.props = props_list or []
        self.cached_props = []
        self.photo_props = []
        self.prop_canvas_items = {}
        self.independent_mouth = independent_mouth or {}
        self.mouth_engine = MouthLipsyncEngine()
        self.mouth_cache = MouthRenderCache()
        self.mouth_item = None
        self._mouth_slot = "closed"
        self._mouth_squash = 0
        self.independent_eyes = independent_eyes or {}
        self.eyes_cache = EyesRenderCache()
        self.eyes_item = None
        self._eye_ox = 0.0
        self._eye_oy = 0.0
        self._load_gen = 0
        self.perf_mode = perf_mode or "performance"

        # Raw PIL frames y cache de PhotoImage pre-escaladas por estado (soporta PNG estático, APNG, GIF y WEBP animado)
        # Formato: { key: [(pil_rgba_image, duration_sec), ...] }
        self.cached_images = {}
        # Formato base redimensionado: { key: [PIL.Image, ...] }
        self.base_resized_images = {}
        # Formato: { key: [(PhotoImage, duration_sec), ...] }
        self.photo_cache = {}
        # Caché bajo demanda para Squash & Stretch: { (key, idx, squash_state): PhotoImage }
        self.squash_photo_cache = {}
        self._last_window_size = (0, 0)

        # Control de reproducción de frames para expresiones animadas (GIF / APNG)
        self.anim_frame_idx = 0
        self.next_frame_time = 0.0
        self._last_active_key = None

        # Animación de movimiento y temblor de grito
        self.current_offset_y = 0.0
        self.target_offset_y = 0.0
        self.jitter_x = 0
        self.jitter_y = 0

        # Temporizador de pestañeo de ojos aleatorio (solo en modo 4 estados con imágenes)
        self.next_blink_time = time.time() + random.uniform(3.0, 6.0)
        self.blink_end_time = 0.0

        # Canvas para renderizado sin bordes
        self.canvas = tk.Canvas(self, bg=self.bg_color, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Elementos persistentes en el Canvas (reutilizados para eliminar todo parpadeo)
        self.image_item = None
        self.placeholder_item = None
        self.mute_item = None

        self.load_images()

        self.canvas.bind("<Configure>", self._on_resize)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Enlazar teclas de atajos y emotes
        self.bind("<KeyPress-m>", lambda e: self._toggle_mute_local())
        self.bind("<KeyPress-M>", lambda e: self._toggle_mute_local())
        self.bind("<KeyPress>", self._on_window_key_press)

        # Iniciar bucle de animación a 60 FPS
        self._animate_loop()

    def load_images(self):
        self._load_gen += 1
        gen_id = self._load_gen
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 20 or h <= 20:
            w, h = 450, 550
        padding = 20
        avail_w = max(10, w - padding * 2)
        avail_h = max(10, h - padding * 2)
        paths_snapshot = dict(self.images_paths)
        props_snapshot = [dict(p) for p in (self.props or [])]
        flip_x = self.flip_x
        mouth_cfg = dict(self.independent_mouth) if isinstance(self.independent_mouth, dict) else {}
        preset = get_performance_preset(getattr(self, "perf_mode", "performance"))
        av_max_dim = preset["obs_max_dim"]
        av_max_frames = preset["obs_max_frames"]
        pr_max_dim = preset["obs_prop_dim"]
        m_max_dim = preset["obs_mouth_dim"]

        def _bg_load():
            raw_imgs = {}
            for key, path in paths_snapshot.items():
                if self._load_gen != gen_id:
                    return
                frames = load_pil_frames_from_path(path, max_dim=av_max_dim, max_frames=av_max_frames)
                if frames:
                    raw_imgs[key] = frames

            raw_props = []
            for pr in props_snapshot:
                if self._load_gen != gen_id:
                    return
                f_path = pr.get("file", "")
                p_frames = load_pil_frames_from_path(f_path, max_dim=pr_max_dim, max_frames=av_max_frames)
                if p_frames:
                    raw_props.append({
                        "id": pr.get("id", str(id(pr))),
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
                    self.after(0, lambda: self._apply_async_loaded_images(
                        gen_id, w, h, raw_imgs, raw_props, resized_imgs, resized_props, mouth_cache_bg
                    ))
                except Exception:
                    pass

        submit_bg_task(_bg_load)

    def _apply_async_loaded_images(self, gen_id, w, h, raw_imgs, raw_props, resized_imgs, resized_props, mouth_cache_bg):
        if gen_id != self._load_gen or not self.winfo_exists():
            return
        self.cached_images = raw_imgs
        self.cached_props = raw_props
        self.mouth_cache = mouth_cache_bg
        self.eyes_cache.load_pil_frame(self.independent_eyes, flip_x=self.flip_x)
        self._last_window_size = (w, h)
        self.photo_cache.clear()
        self.base_resized_images.clear()
        self.squash_photo_cache.clear()
        gc.collect()

        for key, flist in resized_imgs.items():
            pil_frames = [fr for fr, _ in flist]
            scaled_frames = [(ImageTk.PhotoImage(fr), dur) for fr, dur in flist]
            if scaled_frames:
                self.photo_cache[key] = scaled_frames
                self.base_resized_images[key] = pil_frames

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
        self._update_display()

    def _rebuild_photo_cache(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 20 or h <= 20:
            w = 450
            h = 550

        padding = 20
        if not self.cached_images:
            return
        available_w = max(10, w - padding * 2)
        available_h = max(10, h - padding * 2)

        self.photo_cache.clear()
        self.base_resized_images.clear()
        self.squash_photo_cache.clear()
        gc.collect()
        for key, frame_list in self.cached_images.items():
            if not frame_list:
                continue
            scaled_frames = []
            pil_frames = []
            for raw_img, dur_sec in frame_list:
                img_w, img_h = raw_img.size
                if img_w <= 0 or img_h <= 0:
                    continue
                ratio = min(available_w / img_w, available_h / img_h)
                base_w = max(1, int(img_w * ratio))
                base_h = max(1, int(img_h * ratio))

                resized = raw_img.resize((base_w, base_h), Image.Resampling.LANCZOS)
                if getattr(self, "flip_x", False):
                    resized = resized.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                pil_frames.append(resized)
                scaled_frames.append((ImageTk.PhotoImage(resized), dur_sec))
            if scaled_frames:
                self.photo_cache[key] = scaled_frames
                self.base_resized_images[key] = pil_frames

        # Reconstruir cache de accesorios para la resolución actual
        for old_id in list(self.prop_canvas_items.values()):
            try:
                self.canvas.delete(old_id)
            except Exception:
                pass
        self.prop_canvas_items.clear()
        self.photo_props.clear()
        for cp in self.cached_props:
            prop_scaled_frames = []
            scale_factor = cp.get("scale", 1.0)
            rot_deg = float(cp.get("rotation", 0))
            for raw_img, dur_sec in cp["raw_frames"]:
                img_w, img_h = raw_img.size
                if img_w <= 0 or img_h <= 0:
                    continue
                ratio = min(available_w / img_w, available_h / img_h) * scale_factor
                base_w = max(1, int(img_w * ratio))
                base_h = max(1, int(img_h * ratio))
                resized = raw_img.resize((base_w, base_h), Image.Resampling.LANCZOS)
                if rot_deg != 0:
                    resized = resized.rotate(-rot_deg, resample=Image.Resampling.BICUBIC, expand=True)
                prop_scaled_frames.append((ImageTk.PhotoImage(resized), dur_sec))

            self.photo_props.append({
                "id": cp["id"],
                "frames": prop_scaled_frames,
                "layer": cp["layer"],
                "follows_bounce": cp["follows_bounce"],
                "offset_x": cp["offset_x"],
                "offset_y": cp["offset_y"],
                "enabled": cp["enabled"],
                "visible_frames": cp.get("visible_frames", "all"),
            })

    def _on_resize(self, event=None):
        if event:
            new_w = event.width
            new_h = event.height
            if new_w < 50 or new_h < 50:
                return
            if (new_w, new_h) == self._last_window_size:
                return
            self._last_window_size = (new_w, new_h)

        self._rebuild_photo_cache()
        self._update_display()

    def update_props_fast(self, props_list):
        """Actualiza solo los accesorios en memoria sin recargar las imágenes del personaje."""
        self.props = props_list or []
        old_raw_by_id = {cp["id"]: cp for cp in self.cached_props}
        old_photo_by_id = {pp["id"]: pp for pp in self.photo_props}

        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 20 or h <= 20:
            w, h = 450, 550
        padding = 20
        available_w = max(10, w - padding * 2)
        available_h = max(10, h - padding * 2)

        new_cached = []
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
            new_cached.append({
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
                    ratio = min(available_w / img_w, available_h / img_h) * sc_factor
                    base_w = max(1, int(img_w * ratio))
                    base_h = max(1, int(img_h * ratio))
                    resized = raw_img.resize((base_w, base_h), Image.Resampling.BILINEAR)
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

        self.cached_props = new_cached
        self.photo_props = new_photos
        self._update_display()

    def update_images(self, image_dict, mode_4_states, props_list=None, motions_map=None, motion_speeds_map=None, extra_expressions=None, flip_x=None, independent_mouth=None, independent_eyes=None):
        self.images_paths = image_dict or {}
        self.mode_4_states = mode_4_states
        if props_list is not None:
            self.props = props_list
        if motions_map is not None:
            self.motions_map = motions_map
        if motion_speeds_map is not None:
            self.motion_speeds_map = motion_speeds_map
        if extra_expressions is not None:
            self.extra_expressions = extra_expressions
        if flip_x is not None:
            self.flip_x = bool(flip_x)
        if independent_mouth is not None:
            self.independent_mouth = independent_mouth
        if independent_eyes is not None:
            self.independent_eyes = independent_eyes
        self.talk_start_time = 0.0
        self.talk_end_time = 0.0
        self.scream_start_time = 0.0
        self.preview_override_role = None
        self.active_emote_role = None
        self._last_active_key = None
        self._motion_key = None
        self._pending_key = None
        self.load_images()

    def update_extra_context(self, muted=None, audio_level=None, talk_threshold=None, partner_talking=None, partner_screaming=None):
        if muted is not None:
            self.is_muted = bool(muted)
        if audio_level is not None:
            self.audio_level = float(audio_level)
        if talk_threshold is not None:
            self.talk_threshold = float(talk_threshold)
        if partner_talking is not None:
            self.partner_talking = bool(partner_talking)
        if partner_screaming is not None:
            self.partner_screaming = bool(partner_screaming)

    def trigger_preview_role(self, role_id, duration=2.5):
        self.preview_override_role = role_id
        self.preview_override_until = time.time() + duration
        self._update_display()

    def trigger_hotkey_emote(self, key_pressed):
        key_upper = str(key_pressed).upper()
        if key_upper in ("0", "ESCAPE"):
            if self.active_emote_role is not None:
                self.active_emote_role = None
                self.active_emote_until = 0.0
                self._update_display()
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
                    self._update_display()
                    return True
        return False

    def _on_window_key_press(self, event):
        keysym = str(getattr(event, "keysym", ""))
        if not keysym:
            return
        if keysym.lower() == "m":
            return
        if self.trigger_hotkey_emote(keysym):
            if self.on_hotkey:
                self.on_hotkey(f"emote:{keysym}")
            return
        if keysym == "1":
            self.set_expression("normal")
        elif keysym == "2":
            self.set_expression("scream")

    def update_bg_color(self, color):
        self.bg_color = color
        self.configure(bg=color)
        self.canvas.configure(bg=color)
        if self.placeholder_item is not None:
            text_color = "#333333" if color.upper() not in ("#000000", "BLACK") else "#FFFFFF"
            self.canvas.itemconfig(self.placeholder_item, fill=text_color)

    def set_talking(self, talking):
        if self.is_muted:
            talking = False

        if not talking:
            self.is_screaming = False
            self._manual_scream = False

        if self.is_talking != talking:
            now = time.time()
            self.is_talking = talking
            self.last_activity_time = now
            if talking:
                self.talk_start_time = now
                self.fidget_end_time = 0.0
            else:
                self.talk_end_time = now

            if self.bounce_enabled:
                if self.is_screaming:
                    self.target_offset_y = -18.0
                elif talking:
                    self.target_offset_y = -14.0
                else:
                    self.target_offset_y = 0.0
            else:
                self.target_offset_y = 0.0

            self._update_display()

    def _has_scream_expression(self):
        for ex in (getattr(self, "extra_expressions", []) or []):
            if ex.get("trigger") == "state_scream" and ex.get("role") in self.cached_images:
                return True
        return False

    def set_screaming(self, screaming):
        """Activa o desactiva la expresión de grito."""
        if not self._has_scream_expression():
            screaming = False

        if self.is_screaming != screaming:
            now = time.time()
            self.is_screaming = screaming
            self.last_activity_time = now
            if screaming:
                self.scream_start_time = now
            if self.bounce_enabled:
                if screaming:
                    self.target_offset_y = -18.0
                elif self.is_talking:
                    self.target_offset_y = -14.0
                else:
                    self.target_offset_y = 0.0
            else:
                self.target_offset_y = 0.0
            self._update_display()

    def _toggle_scream_manual(self):
        if self._has_scream_expression():
            self.is_screaming = not self.is_screaming
            self._manual_scream = self.is_screaming
            self._update_display()
            if self.on_hotkey:
                self.on_hotkey("scream_toggle")

    def set_expression(self, expr):
        if expr == "scream":
            self._toggle_scream_manual()
        else:
            self.set_screaming(False)

    def _toggle_mute_local(self):
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.set_talking(False)
            self.set_screaming(False)
        self._update_display()
        if self.on_hotkey:
            self.on_hotkey("mute")

    def _can_blink(self):
        if self.is_screaming:
            return False
        has_blink_mid = any(
            ex.get("trigger") in ("trans_blink_inbetween", "trans_blink_talk_inbetween") and ex.get("role") in self.cached_images
            for ex in (getattr(self, "extra_expressions", []) or [])
        )
        if not self.mode_4_states and not has_blink_mid:
            return False
        talking = self.is_talking and not self.is_muted
        if talking:
            return ("talk_blink" in self.cached_images) or has_blink_mid
        else:
            return ("idle_blink" in self.cached_images) or has_blink_mid

    def _is_scream_role(self, r):
        if r == "scream":
            return True
        for ex in (getattr(self, "extra_expressions", []) or []):
            if ex.get("role") == r and ex.get("trigger") in ("state_scream", "state_scream_alt", "trans_pre_scream"):
                return True
        return False

    def _congruent_motion_key(self, key, now):
        """Congruencia: un fotograma fugaz (p. ej. un pestañeo) conserva la animación del anterior.
        Solo si el nuevo fotograma se mantiene un instante adopta su propia animación."""
        if not getattr(self, "congruence_enabled", True):
            self._motion_key = key
            self._pending_key = None
            return key
        cur = getattr(self, "_motion_key", None)
        if cur is None or cur == key:
            self._motion_key = key
            self._pending_key = None
            return key
        if getattr(self, "_pending_key", None) != key:
            self._pending_key = key
            self._pending_since = now
        hold = 0.0 if (self.is_screaming or self._is_scream_role(key) or self._is_scream_role(cur)) else 0.25
        if now - self._pending_since >= hold:
            self._motion_key = key
            self._pending_key = None
        return self._motion_key

    def _animate_loop(self):
        if not self.winfo_exists():
            return

        now = time.time()

        # 1. Pestañeo de ojos aleatorio (únicamente si existen sprites de parpadeo configurados y no está gritando)
        if self._can_blink() and not self.is_screaming:
            if not self.is_blinking and now >= self.next_blink_time:
                self.is_blinking = True
                self.blink_start_time = now
                has_blink_mid = any(
                    ex.get("trigger") == "trans_blink_inbetween" and ex.get("role") in self.cached_images
                    for ex in (getattr(self, "extra_expressions", []) or [])
                )
                dur_s = 0.21 if has_blink_mid else random.uniform(0.12, 0.18)
                self.blink_end_time = now + dur_s
                self._update_display()
            elif self.is_blinking and now >= self.blink_end_time:
                self.is_blinking = False
                self.next_blink_time = now + random.uniform(3.0, 6.0)
                self._update_display()

        # 1.b Avance de fotograma si la expresión activa es un GIF / APNG animado
        active_key = self._get_active_key()
        if active_key != self._last_active_key:
            self._last_active_key = active_key
            self.anim_frame_idx = 0
            frames_for_key = self.photo_cache.get(active_key, [])
            if len(frames_for_key) > 1:
                self.next_frame_time = now + frames_for_key[0][1]
            self._update_display()
        elif active_key:
            frames_for_key = self.photo_cache.get(active_key, [])
            if len(frames_for_key) > 1 and now >= self.next_frame_time:
                self.anim_frame_idx = (self.anim_frame_idx + 1) % len(frames_for_key)
                self.next_frame_time = now + frames_for_key[self.anim_frame_idx][1]
                self._update_display()

        # 2. Movimientos dinámicos según el tipo seleccionado (Respiración, Saltitos, Elástico, Balanceo, Sacudida, Flotar)
        pos_changed = False
        prev_offset_y = self.current_offset_y
        congruence_on = getattr(self, "congruence_enabled", True)
        motion_key = self._congruent_motion_key(active_key, now)
        role_fallback = "talk" if (self.is_talking and not self.is_muted) else "idle"
        if not getattr(self, "bounce_enabled", True):
            motion_type = "Ninguna"
        elif getattr(self, "is_muted", False):
            motion_type = "Ninguna"
            for ex in getattr(self, "extra_expressions", []) or []:
                if ex.get("trigger") == "state_muted" and ex.get("role") == active_key:
                    motion_type = self.motions_map.get(active_key, ex.get("motion", "Ninguna"))
                    break
        elif motion_key and motion_key in self.motions_map:
            motion_type = self.motions_map[motion_key]
        else:
            motion_type = self.motions_map.get(role_fallback, "Respiración" if role_fallback in ("idle", "talk") else "Ninguna")

        if motion_type == "Rebote":
            motion_type = "Respiración"

        motion_speed = 1.0
        speeds = getattr(self, "motion_speeds_map", {}) or {}
        try:
            if motion_key and motion_key in speeds:
                motion_speed = float(speeds[motion_key])
            elif role_fallback in speeds:
                motion_speed = float(speeds[role_fallback])
        except Exception:
            motion_speed = 1.0
        motion_speed = max(0.2, min(5.0, motion_speed))
        dt = min(0.1, max(0.0, now - getattr(self, "_last_anim_tick", now)))
        self._last_anim_tick = now
        self._anim_phase = getattr(self, "_anim_phase", 0.0) + dt * motion_speed
        p = self._anim_phase

        if motion_type != getattr(self, "_last_motion_type", None):
            self._last_motion_type = motion_type
            self._blend_from_y = self.current_offset_y
            self._blend_from_x = self.jitter_x
            self._blend_from_squash = self.squash_state
            self._blend_start = now if congruence_on else 0.0

        # Sacudida (únicamente si esa pose tiene asignada Sacudida)
        if motion_type == "Sacudida":
            step_period = max(0.015, 0.04 / motion_speed)
            if (now - getattr(self, "_last_shake_t", 0.0)) >= step_period:
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
            target_y = -((math.sin(p * 2.2) + 1.0) * 0.5) * 5.0
            self.current_offset_y += (target_y - self.current_offset_y) * 0.25
            pos_changed = True

        elif motion_type == "Saltitos":
            # Saltitos continuos y rítmicos
            self.current_offset_y = -abs(math.sin(p * 12.0)) * 12.0
            pos_changed = True

        elif motion_type == "Elástico":
            # Rebote elástico suave y continuo (mismo ritmo sin acelerarse frenéticamente entre poses)
            self.current_offset_y = -max(0.0, math.sin(p * 4.5)) * 9.0
            pos_changed = True

        elif motion_type == "Balanceo":
            # Vaivén lateral continuo
            self.jitter_x = int(math.sin(p * 7.0) * 8.0)
            self.jitter_y = 0
            diff_y = 0.0 - self.current_offset_y
            if abs(diff_y) > 0.3:
                self.current_offset_y += diff_y * 0.35
            else:
                self.current_offset_y = 0.0
            pos_changed = True

        elif motion_type == "Flotar":
            # Suave vaivén vertical
            self.current_offset_y = math.sin(p * 3.5) * 8.0
            pos_changed = True

        else: # Ninguna / Sacudida
            if self.current_offset_y != 0.0:
                diff_y = 0.0 - self.current_offset_y
                if abs(diff_y) > 0.3:
                    self.current_offset_y += diff_y * 0.35
                else:
                    self.current_offset_y = 0.0
                pos_changed = True

        # 3. Efecto "Squash & Stretch" (Estirar y Aplastar elástico). La respiración NO deforma la imagen.
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
                if vel_y < -1.5:
                    new_squash = 2 if vel_y < -3.0 else 1
                elif vel_y > 1.4:
                    new_squash = -2 if vel_y > 2.8 else -1
                elif self.current_offset_y < -9.5:
                    new_squash = 1

        # 4. Congruencia: el nuevo fotograma arranca en la posición y tamaño del anterior y se transforma suavemente
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
            self._update_display()
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
            )
            if new_slot != self._mouth_slot or new_msquash != self._mouth_squash:
                self._mouth_slot = new_slot
                self._mouth_squash = new_msquash
                self._update_display()

        if is_independent_eyes_active(self.independent_eyes):
            self._tick_eyes_mouse_follow()

        self.after(16, self._animate_loop)

    def _get_squash_photo(self, active_key, frame_idx):
        frames_list = self.photo_cache.get(active_key) if active_key else None
        if not frames_list:
            return None
        idx = frame_idx % len(frames_list)
        if self.squash_state == 0:
            return frames_list[idx][0]

        cache_key = (active_key, idx, self.squash_state)
        cached = self.squash_photo_cache.get(cache_key)
        if cached is not None:
            return cached

        pil_list = self.base_resized_images.get(active_key)
        if not pil_list:
            return frames_list[idx][0]

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
        res = ImageTk.PhotoImage(deformed)
        if len(self.squash_photo_cache) >= get_performance_preset(getattr(self, "perf_mode", "performance"))["squash_cache_max"]:
            self.squash_photo_cache.clear()
        self.squash_photo_cache[cache_key] = res
        return res

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

    def _get_active_key(self):
        now = time.time()
        talking = self.is_talking and not self.is_muted
        screaming = self.is_screaming and (talking or getattr(self, "_manual_scream", False))

        if talking or screaming:
            self.last_activity_time = now

        # 1. Prueba manual desde el Taller (botón "▶ Probar")
        if self.preview_override_role and now < self.preview_override_until:
            if self.preview_override_role in self.cached_images:
                return self.preview_override_role
        elif self.preview_override_role and now >= self.preview_override_until:
            self.preview_override_role = None

        extras = getattr(self, "extra_expressions", []) or []

        def find_extra(trig_type):
            for ex in extras:
                r_id = ex.get("role")
                if ex.get("trigger") == trig_type and r_id in self.cached_images:
                    return ex
            return None

        # 2. Estado Muteado (state_muted) o quieto sin movimiento si no tiene frame de mute
        if self.is_muted:
            ex_mute = find_extra("state_muted")
            if ex_mute:
                return ex_mute["role"]
            if self.mode_4_states and self.is_blinking and "idle_blink" in self.cached_images:
                return "idle_blink"
            return "idle" if "idle" in self.cached_images else None

        # 3. Emoción activada por Tecla Rápida (hotkey_emote)
        if self.active_emote_role:
            if self.active_emote_until > 0 and now >= self.active_emote_until:
                self.active_emote_role = None
                self.active_emote_until = 0.0
            elif self.active_emote_role in self.cached_images:
                return self.active_emote_role

        # 4. Grito (state_scream), Variantes de Grito (state_scream_alt) y Transición Pre-Grito (trans_pre_scream)
        if screaming:
            ex_scream = find_extra("state_scream")
            if ex_scream:
                ex_pre_scream = find_extra("trans_pre_scream")
                if ex_pre_scream and self.scream_start_time > 0:
                    dur_ms = self._parse_ms_param(ex_pre_scream.get("param", "80ms"), 80)
                    if (now - self.scream_start_time) < (dur_ms / 1000.0):
                        return ex_pre_scream["role"]
                scream_alts = [ex for ex in extras if ex.get("trigger") == "state_scream_alt" and ex.get("role") in self.cached_images]
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
                if self.mode_4_states and "talk_blink" in self.cached_images:
                    return "talk_blink"

            if getattr(self, "mouth_flutter_enabled", False) and ex_mouth_mid and self.talk_start_time > 0:
                elapsed_talk = now - self.talk_start_time
                if elapsed_talk >= 0.28:
                    if int((elapsed_talk - 0.28) / 0.11) % 2 == 1:
                        return ex_mouth_mid["role"]

            if "talk" in self.cached_images:
                return "talk"
            return "idle" if "idle" in self.cached_images else None

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
            if now < self.fidget_end_time and self.fidget_active_role in self.cached_images:
                return self.fidget_active_role
            elif now >= self.next_fidget_time:
                fidget_list = [e for e in extras if e.get("trigger") == "idle_fidget" and e.get("role") in self.cached_images]
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
            if self.mode_4_states and "idle_blink" in self.cached_images:
                return "idle_blink"
        return "idle" if "idle" in self.cached_images else None

    @staticmethod
    def _is_prop_visible_for_role(prop, active_key):
        vf = prop.get("visible_frames", "all")
        if vf == "all" or not vf:
            return True
        if isinstance(vf, list):
            return active_key in vf
        return True

    def _get_avatar_center_and_scale(self, w, h, padding=20):
        avail_w = max(10, w - padding * 2)
        avail_h = max(10, h - padding * 2)
        raw_imgs = getattr(self, "raw_images", None) or {}
        active_key = self._get_active_key() if hasattr(self, "_get_active_key") else "idle"
        frames = raw_imgs.get(active_key) or raw_imgs.get("idle")
        if frames:
            raw_img = frames[self.anim_frame_idx % len(frames)][0]
            rw, rh = max(1, raw_img.width), max(1, raw_img.height)
            fit_ratio = min(avail_w / rw, avail_h / rh)
            pos_scale = fit_ratio * max(rw, rh) / 384.0
        else:
            pos_scale = min(avail_w, avail_h) / 384.0
        base_x = w // 2
        base_y = h - padding
        av_h = getattr(self, "_last_avatar_h", 0) or (avail_h // 2)
        return base_x, base_y - (av_h // 2), pos_scale

    def _update_position_only(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 20 or h <= 20:
            w = 450
            h = 550
        padding = 20
        base_x = (w // 2)
        base_y = (h - padding)

        # 1. Mover el avatar principal
        if self.image_item is not None:
            pos_x = base_x + self.jitter_x
            pos_y = base_y + int(self.current_offset_y) + self.jitter_y
            self.canvas.coords(self.image_item, pos_x, pos_y)

        active_key = self._get_active_key()
        av_cx, av_cy, pos_scale = self._get_avatar_center_and_scale(w, h, padding)

        # 2. Mover cada accesorio según si sigue o no el rebote
        self._update_eyes_position_only(av_cx, av_cy, pos_scale, active_key)
        self._update_mouth_position_only(av_cx, av_cy, pos_scale, active_key)
        for p in self.photo_props:
            item_id = self.prop_canvas_items.get(p["id"])
            if item_id:
                if p["enabled"] and self._is_prop_visible_for_role(p, active_key):
                    dx = int(p["offset_x"] * pos_scale)
                    dy = int(p["offset_y"] * pos_scale)
                    if p["follows_bounce"]:
                        px = av_cx + dx + self.jitter_x
                        py = av_cy + dy + int(self.current_offset_y) + self.jitter_y
                    else:
                        px = av_cx + dx
                        py = av_cy + dy
                    self.canvas.coords(item_id, px, py)
                    self.canvas.itemconfig(item_id, state="normal")
                else:
                    self.canvas.itemconfig(item_id, state="hidden")

    def _update_display(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 20 or h <= 20:
            w = 450
            h = 550
        padding = 20
        base_x = (w // 2)
        base_y = (h - padding)

        # Limpiar items de accesorios eliminados
        valid_pids = {p["id"] for p in self.photo_props}
        for old_pid in list(self.prop_canvas_items.keys()):
            if old_pid not in valid_pids:
                try:
                    self.canvas.delete(self.prop_canvas_items.pop(old_pid))
                except Exception:
                    pass

        active_key = self._get_active_key()
        photo = self._get_squash_photo(active_key, self.anim_frame_idx) if active_key else None
        if photo:
            try:
                self._last_avatar_h = photo.height()
            except Exception:
                pass
        av_cx, av_cy, pos_scale = self._get_avatar_center_and_scale(w, h, padding)

        # 1. DIBUJAR ACCESORIOS DE FONDO (BACK PROPS)
        back_items = []
        for p in self.photo_props:
            if p["layer"] != "back":
                continue
            item_id = self._render_single_prop_item(p, av_cx, av_cy, pos_scale, active_key)
            if item_id:
                back_items.append(item_id)

        # 2. DIBUJAR AVATAR PRINCIPAL
        if photo:
            pos_x = base_x + self.jitter_x
            pos_y = base_y + int(self.current_offset_y) + self.jitter_y

            if self.image_item is None:
                self.image_item = self.canvas.create_image(pos_x, pos_y, anchor=tk.S, image=photo)
            else:
                self.canvas.itemconfig(self.image_item, image=photo, state="normal")
                self.canvas.coords(self.image_item, pos_x, pos_y)
            self.canvas.current_photo = photo

            if self.placeholder_item is not None:
                self.canvas.itemconfig(self.placeholder_item, state="hidden")
        else:
            if self.image_item is not None:
                self.canvas.itemconfig(self.image_item, state="hidden")

            msg = "Sin imagen seleccionada\n(Elige un PNG en la consola)"
            text_color = "#333333" if self.bg_color.upper() not in ("#000000", "BLACK") else "#FFFFFF"
            if self.placeholder_item is None:
                self.placeholder_item = self.canvas.create_text(
                    w // 2, h // 2,
                    text=msg,
                    fill=text_color,
                    font=("Segoe UI", 12, "bold"),
                    justify=tk.CENTER
                )
            else:
                self.canvas.itemconfig(self.placeholder_item, text=msg, fill=text_color, state="normal")
                self.canvas.coords(self.placeholder_item, w // 2, h // 2)

        # 3. DIBUJAR ACCESORIOS DE FRENTE (FRONT PROPS)
        eyes_canvas_item = self._render_eyes_item(av_cx, av_cy, pos_scale, active_key)
        mouth_canvas_item = self._render_mouth_item(av_cx, av_cy, pos_scale, active_key)
        front_items = []
        for p in self.photo_props:
            if p["layer"] == "back":
                continue
            item_id = self._render_single_prop_item(p, av_cx, av_cy, pos_scale, active_key)
            if item_id:
                front_items.append(item_id)

        # Asegurar orden de capas (Z-Order): Fondo -> Avatar -> Frente (preservando orden exacto)
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

        # Icono de mute
        if self.is_muted:
            if self.mute_item is None:
                self.mute_item = self.canvas.create_text(
                    w - 25, 25,
                    text="🔇",
                    font=("Segoe UI", 16)
                )
            else:
                self.canvas.itemconfig(self.mute_item, state="normal")
                self.canvas.coords(self.mute_item, w - 25, 25)
            self.canvas.tag_raise(self.mute_item)
        elif self.mute_item is not None:
            self.canvas.itemconfig(self.mute_item, state="hidden")

    def _render_single_prop_item(self, prop, av_cx, av_cy, pos_scale, active_key):
        pid = prop["id"]
        if not prop["enabled"] or not prop["frames"] or not self._is_prop_visible_for_role(prop, active_key):
            if pid in self.prop_canvas_items:
                self.canvas.itemconfig(self.prop_canvas_items[pid], state="hidden")
            return None

        # Selección de frame para props animados
        f_idx = self.anim_frame_idx % len(prop["frames"])
        p_photo = prop["frames"][f_idx][0]

        dx = int(prop["offset_x"] * pos_scale)
        dy = int(prop["offset_y"] * pos_scale)
        if prop["follows_bounce"]:
            px = av_cx + dx + self.jitter_x
            py = av_cy + dy + int(self.current_offset_y) + self.jitter_y
        else:
            px = av_cx + dx
            py = av_cy + dy

        item_id = self.prop_canvas_items.get(pid)
        if item_id is None:
            item_id = self.canvas.create_image(px, py, anchor=tk.CENTER, image=p_photo)
            self.prop_canvas_items[pid] = item_id
        else:
            self.canvas.itemconfig(item_id, image=p_photo, state="normal")
            self.canvas.coords(item_id, px, py)

        return item_id

    def update_independent_mouth_fast(self, mouth_cfg):
        self.independent_mouth = mouth_cfg or {}
        self.mouth_cache.load_pil_frames(self.independent_mouth, flip_x=self.flip_x)
        self._update_display()

    def _get_mouth_coords(self, av_cx, av_cy, pos_scale, ox, oy):
        eff_ox = -ox if self.flip_x else ox
        dx = int(eff_ox * pos_scale)
        dy = int(oy * pos_scale)
        if self.independent_mouth.get("follows_bounce", True):
            return av_cx + dx + self.jitter_x, av_cy + dy + int(self.current_offset_y) + self.jitter_y
        return av_cx + dx, av_cy + dy

    def _update_mouth_position_only(self, av_cx, av_cy, pos_scale, active_key):
        if self.mouth_item is None:
            return
        if not is_independent_mouth_active(self.independent_mouth):
            self.canvas.itemconfig(self.mouth_item, state="hidden")
            return
        hidden, ox, oy, _, _, _ = resolve_mouth_frame_config(self.independent_mouth, active_key)
        if hidden:
            self.canvas.itemconfig(self.mouth_item, state="hidden")
            return
        mx, my = self._get_mouth_coords(av_cx, av_cy, pos_scale, ox, oy)
        self.canvas.coords(self.mouth_item, mx, my)
        self.canvas.itemconfig(self.mouth_item, state="normal")

    def _render_mouth_item(self, av_cx, av_cy, pos_scale, active_key):
        if not is_independent_mouth_active(self.independent_mouth):
            if self.mouth_item is not None:
                self.canvas.itemconfig(self.mouth_item, state="hidden")
            return None

        hidden, ox, oy, sc_pct, rot_deg, ov_key = resolve_mouth_frame_config(self.independent_mouth, active_key)
        if hidden:
            if self.mouth_item is not None:
                self.canvas.itemconfig(self.mouth_item, state="hidden")
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
                self.canvas.itemconfig(self.mouth_item, state="hidden")
            return None

        mx, my = self._get_mouth_coords(av_cx, av_cy, pos_scale, ox, oy)
        if self.mouth_item is None:
            self.mouth_item = self.canvas.create_image(mx, my, anchor=tk.CENTER, image=m_photo)
        else:
            self.canvas.itemconfig(self.mouth_item, image=m_photo, state="normal")
            self.canvas.coords(self.mouth_item, mx, my)
        self.canvas.current_mouth_photo = m_photo
        return self.mouth_item

    def update_independent_eyes_fast(self, eyes_cfg):
        self.independent_eyes = eyes_cfg or {}
        self.eyes_cache.load_pil_frame(self.independent_eyes, flip_x=self.flip_x)
        self._update_display()

    def _get_eyes_base_coords(self, av_cx, av_cy, pos_scale, ox, oy):
        eff_ox = -ox if self.flip_x else ox
        dx = int(eff_ox * pos_scale)
        dy = int(oy * pos_scale)
        if self.independent_eyes.get("follows_bounce", True):
            return av_cx + dx + self.jitter_x, av_cy + dy + int(self.current_offset_y) + self.jitter_y
        return av_cx + dx, av_cy + dy

    def _tick_eyes_mouse_follow(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 20 or h <= 20:
            w, h = 450, 550
        av_cx, av_cy, pos_scale = self._get_avatar_center_and_scale(w, h, 20)
        active_key = self._get_active_key()
        self._update_eyes_position_only(av_cx, av_cy, pos_scale, active_key)

    def _update_eyes_position_only(self, av_cx, av_cy, pos_scale, active_key):
        if self.eyes_item is None:
            return
        if not is_independent_eyes_active(self.independent_eyes):
            self.canvas.itemconfig(self.eyes_item, state="hidden")
            return
        hidden, ox, oy, sc_pct, rot_deg, _ = resolve_eyes_frame_config(self.independent_eyes, active_key)
        if hidden:
            self.canvas.itemconfig(self.eyes_item, state="hidden")
            return
        bx, by = self._get_eyes_base_coords(av_cx, av_cy, pos_scale, ox, oy)
        self._eye_ox, self._eye_oy = compute_mouse_eye_offset(
            self.canvas, bx, by, pos_scale, self.independent_eyes, self._eye_ox, self._eye_oy
        )
        if self.eyes_cache.has_mask_or_overlay():
            eff_rot = -rot_deg if self.flip_x else rot_deg
            e_photo, anchored = self.eyes_cache.get_tk_image(
                pos_scale,
                scale_pct=sc_pct,
                rotation=eff_rot,
                eye_ox=self._eye_ox,
                eye_oy=self._eye_oy,
                show_mask=bool(self.independent_eyes.get("show_mask", False)),
            )
            if e_photo is not None:
                self.canvas.itemconfig(self.eyes_item, image=e_photo, state="normal")
                self.canvas.current_eyes_photo = e_photo
            ex, ey = (bx, by) if anchored else (bx + self._eye_ox, by + self._eye_oy)
            self.canvas.coords(self.eyes_item, ex, ey)
        else:
            self.canvas.coords(self.eyes_item, bx + self._eye_ox, by + self._eye_oy)
            self.canvas.itemconfig(self.eyes_item, state="normal")

    def _render_eyes_item(self, av_cx, av_cy, pos_scale, active_key):
        if not is_independent_eyes_active(self.independent_eyes):
            if self.eyes_item is not None:
                self.canvas.itemconfig(self.eyes_item, state="hidden")
            return None

        hidden, ox, oy, sc_pct, rot_deg, _ = resolve_eyes_frame_config(self.independent_eyes, active_key)
        if hidden:
            if self.eyes_item is not None:
                self.canvas.itemconfig(self.eyes_item, state="hidden")
            return None

        bx, by = self._get_eyes_base_coords(av_cx, av_cy, pos_scale, ox, oy)
        self._eye_ox, self._eye_oy = compute_mouse_eye_offset(
            self.canvas, bx, by, pos_scale, self.independent_eyes, self._eye_ox, self._eye_oy
        )
        eff_rot = -rot_deg if self.flip_x else rot_deg
        e_photo, anchored = self.eyes_cache.get_tk_image(
            pos_scale,
            scale_pct=sc_pct,
            rotation=eff_rot,
            eye_ox=self._eye_ox,
            eye_oy=self._eye_oy,
            show_mask=bool(self.independent_eyes.get("show_mask", False)),
        )
        if e_photo is None:
            if self.eyes_item is not None:
                self.canvas.itemconfig(self.eyes_item, state="hidden")
            return None

        ex, ey = (bx, by) if anchored else (bx + self._eye_ox, by + self._eye_oy)
        if self.eyes_item is None:
            self.eyes_item = self.canvas.create_image(ex, ey, anchor=tk.CENTER, image=e_photo)
        else:
            self.canvas.itemconfig(self.eyes_item, image=e_photo, state="normal")
            self.canvas.coords(self.eyes_item, ex, ey)
        self.canvas.current_eyes_photo = e_photo
        return self.eyes_item

    def _render_current_frame(self):
        """Compatibilidad con llamadas externas existentes."""
        self._update_display()

    def on_close(self):
        self.cached_images.clear()
        self.base_resized_images.clear()
        self.photo_cache.clear()
        self.squash_photo_cache.clear()
        self.cached_props.clear()
        self.photo_props.clear()
        self.mouth_cache.clear()
        self.destroy()
        gc.collect()
