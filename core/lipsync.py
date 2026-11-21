import os
import time
from PIL import Image, ImageTk

MOUTH_SLOTS = ("closed", "half", "open", "wide")
VOWEL_SLOTS = ("vowel_a", "vowel_e", "vowel_i", "vowel_o", "vowel_u")
ALL_MOUTH_SLOTS = MOUTH_SLOTS + VOWEL_SLOTS

MOUTH_SLOT_LABELS = {
    "closed": "Cerrada",
    "half": "Semi-abierta",
    "open": "Abierta",
    "wide": "Muy abierta / O",
    "vowel_a": "Vocal A",
    "vowel_e": "Vocal E",
    "vowel_i": "Vocal I",
    "vowel_o": "Vocal O",
    "vowel_u": "Vocal U",
}

_SQUASH_RATIOS = (1.0, 1.10, 1.22)


def default_independent_mouth():
    """Devuelve la configuración base por defecto para la boca independiente."""
    return {
        "enabled": False,
        "mode": "volume",
        "offset_x": 0,
        "offset_y": 0,
        "scale": 100,
        "rotation": 0,
        "follows_bounce": True,
        "squash_strength": 100,
        "sprites": {s: "" for s in ALL_MOUTH_SLOTS},
        "sprites_rel": {s: "" for s in ALL_MOUTH_SLOTS},
        "frame_overrides": {},
    }


def normalize_independent_mouth(raw_cfg, folder_path=None):
    """Normaliza un diccionario de boca independiente y resuelve rutas relativas."""
    base = default_independent_mouth()
    if not isinstance(raw_cfg, dict):
        return base

    base["enabled"] = bool(raw_cfg.get("enabled", False))
    raw_mode = str(raw_cfg.get("mode", "volume") or "volume")
    base["mode"] = raw_mode if raw_mode in ("volume", "vowels") else "volume"
    base["offset_x"] = int(raw_cfg.get("offset_x", 0))
    base["offset_y"] = int(raw_cfg.get("offset_y", 0))
    base["scale"] = max(10, min(300, int(raw_cfg.get("scale", 100))))
    base["rotation"] = int(raw_cfg.get("rotation", 0))
    base["follows_bounce"] = bool(raw_cfg.get("follows_bounce", True))
    base["squash_strength"] = max(0, min(200, int(raw_cfg.get("squash_strength", 100))))

    raw_sprites = raw_cfg.get("sprites") or {}
    raw_rel = raw_cfg.get("sprites_rel") or {}
    for s in ALL_MOUTH_SLOTS:
        abs_p = str(raw_sprites.get(s, "") or "")
        rel_p = str(raw_rel.get(s, "") or "")
        if folder_path and rel_p:
            cand = os.path.abspath(os.path.join(folder_path, rel_p))
            if os.path.exists(cand):
                abs_p = cand
        if abs_p and not os.path.exists(abs_p) and folder_path:
            cand_m = os.path.join(folder_path, "mouths", os.path.basename(abs_p))
            if os.path.exists(cand_m):
                abs_p = cand_m
        base["sprites"][s] = abs_p if (abs_p and os.path.exists(abs_p)) else ""
        if base["sprites"][s] and folder_path:
            try:
                base["sprites_rel"][s] = os.path.relpath(base["sprites"][s], folder_path).replace("\\", "/")
            except Exception:
                base["sprites_rel"][s] = rel_p
        else:
            base["sprites_rel"][s] = ""

    raw_ov = raw_cfg.get("frame_overrides") or {}
    if isinstance(raw_ov, dict):
        clean_ov = {}
        for role_k, ov in raw_ov.items():
            if not isinstance(ov, dict):
                continue
            clean_ov[str(role_k)] = {
                "offset_x": int(ov.get("offset_x", base["offset_x"])),
                "offset_y": int(ov.get("offset_y", base["offset_y"])),
                "scale": max(10, min(300, int(ov.get("scale", base["scale"])))),
                "rotation": int(ov.get("rotation", base["rotation"])),
                "hidden": bool(ov.get("hidden", False)),
            }
        base["frame_overrides"] = clean_ov

    return base


def has_any_mouth_sprite(mouth_cfg):
    if not isinstance(mouth_cfg, dict):
        return False
    sprites = mouth_cfg.get("sprites") or {}
    return any(bool(sprites.get(s)) and os.path.exists(str(sprites.get(s))) for s in ALL_MOUTH_SLOTS)


def is_independent_mouth_active(mouth_cfg):
    return bool(isinstance(mouth_cfg, dict) and mouth_cfg.get("enabled", False) and has_any_mouth_sprite(mouth_cfg))


def _canonical_role(role):
    if not role:
        return "idle"
    r = str(role)
    for prefix in ("a1_", "a2_"):
        if r.startswith(prefix):
            r = r[3:]
            break
    return r


def resolve_mouth_frame_config(mouth_cfg, active_role):
    """Devuelve (hidden, offset_x, offset_y, scale, rotation, override_key) para el frame actual."""
    if not isinstance(mouth_cfg, dict):
        return (True, 0, 0, 100, 0, "base")

    role_k = _canonical_role(active_role)
    ov = (mouth_cfg.get("frame_overrides") or {}).get(role_k)
    if isinstance(ov, dict):
        return (
            bool(ov.get("hidden", False)),
            int(ov.get("offset_x", mouth_cfg.get("offset_x", 0))),
            int(ov.get("offset_y", mouth_cfg.get("offset_y", 0))),
            int(ov.get("scale", mouth_cfg.get("scale", 100))),
            int(ov.get("rotation", mouth_cfg.get("rotation", 0))),
            role_k,
        )

    return (
        False,
        int(mouth_cfg.get("offset_x", 0)),
        int(mouth_cfg.get("offset_y", 0)),
        int(mouth_cfg.get("scale", 100)),
        int(mouth_cfg.get("rotation", 0)),
        "base",
    )


class MouthLipsyncEngine:
    """Motor ligero de lipsync por envolvente de volumen + squash tipo Honk (Modo A)."""

    def __init__(self):
        self.envelope = 0.0
        self.prev_raw = 0.0
        self.squash_impulse = 0.0
        self.adaptive_peak = 36.0
        self._last_desired = "closed"
        self._last_vowel = None
        self._last_vowel_time = 0.0
        self.last_time = time.time()

    def reset(self):
        self.envelope = 0.0
        self.prev_raw = 0.0
        self.squash_impulse = 0.0
        self.adaptive_peak = 36.0
        self._last_desired = "closed"
        self._last_vowel = None
        self._last_vowel_time = 0.0
        self.last_time = time.time()

    def update(self, audio_level, talk_threshold, is_talking, is_screaming, is_muted, available_slots, squash_strength=100, mode="volume", vowel_hint=None):
        now = time.time()
        dt = max(0.001, min(0.05, now - self.last_time))
        self.last_time = now

        lvl = float(audio_level or 0.0)
        thresh = max(1.0, float(talk_threshold or 20.0))
        min_peak = min(100.0, thresh + 22.0)
        if self.adaptive_peak < min_peak:
            self.adaptive_peak = min_peak

        if is_muted or (not is_talking and not is_screaming and lvl < thresh):
            target = 0.0
            raw = 0.0
            self.adaptive_peak = max(min_peak, self.adaptive_peak - 6.0 * dt)
        else:
            if lvl > self.adaptive_peak:
                self.adaptive_peak += (lvl - self.adaptive_peak) * min(1.0, 14.0 * dt)
            else:
                self.adaptive_peak = max(min_peak, self.adaptive_peak - 5.5 * dt)

            base_floor = thresh * 0.88
            denom = max(12.0, self.adaptive_peak - base_floor)
            lin = max(0.0, min(1.0, (lvl - base_floor) / denom))
            # Curva de compresión suave para que la voz normal recorra half -> open -> wide
            raw = lin ** 0.85
            if is_talking:
                raw = max(raw, 0.20)
            if is_screaming:
                raw = 1.0
            target = raw

        rate = 32.0 if target > self.envelope else 16.0
        alpha = min(1.0, rate * dt)
        self.envelope += (target - self.envelope) * alpha

        delta = raw - self.prev_raw
        self.prev_raw = raw
        if delta > 0.08 and (is_talking or is_screaming) and not is_muted:
            self.squash_impulse = min(1.0, self.squash_impulse + delta * 1.8)
        self.squash_impulse = max(0.0, self.squash_impulse - 8.5 * dt)

        # Histéresis suave para evitar parpadeo en los bordes de transición
        e = self.envelope
        prev = self._last_desired
        h = 0.03
        if prev == "closed":
            desired = "half" if e >= (0.12 + h) else "closed"
        elif prev == "half":
            if e < (0.12 - h):
                desired = "closed"
            elif e >= (0.34 + h):
                desired = "open"
            else:
                desired = "half"
        elif prev == "open":
            if e < (0.34 - h):
                desired = "half"
            elif e >= (0.70 + h):
                desired = "wide"
            else:
                desired = "open"
        else:  # wide
            desired = "open" if e < (0.70 - h) else "wide"

        # Permitir saltos directos en picos fuertes
        if e >= 0.76:
            desired = "wide"
        elif e < 0.08:
            desired = "closed"
        self._last_desired = desired

        if mode == "vowels" and vowel_hint in VOWEL_SLOTS and not is_muted and e >= 0.14:
            if is_screaming:
                desired_out = "wide" if "wide" in available_slots else "vowel_o"
            else:
                if vowel_hint != self._last_vowel and (now - self._last_vowel_time) >= 0.045:
                    self._last_vowel = vowel_hint
                    self._last_vowel_time = now
                desired_out = self._last_vowel or vowel_hint
        else:
            desired_out = desired

        slot = self._pick_available_slot(desired_out, available_slots)

        squash_idx = 0
        if squash_strength > 0 and self.squash_impulse > 0.12:
            eff = self.squash_impulse * (squash_strength / 100.0)
            if eff >= 0.52:
                squash_idx = 2
            elif eff >= 0.18:
                squash_idx = 1

        return slot, squash_idx

    @staticmethod
    def _pick_available_slot(desired, available_slots):
        if desired in available_slots:
            return desired
        fallbacks = {
            "closed": ("closed", "half", "open", "wide"),
            "half": ("half", "open", "closed", "wide"),
            "open": ("open", "half", "wide", "closed"),
            "wide": ("wide", "open", "half", "closed"),
            "vowel_a": ("vowel_a", "open", "wide", "half", "closed"),
            "vowel_e": ("vowel_e", "half", "open", "vowel_i", "closed"),
            "vowel_i": ("vowel_i", "half", "vowel_e", "open", "closed"),
            "vowel_o": ("vowel_o", "wide", "open", "half", "closed"),
            "vowel_u": ("vowel_u", "half", "vowel_o", "closed", "open"),
        }
        for cand in fallbacks.get(desired, ALL_MOUTH_SLOTS):
            if cand in available_slots:
                return cand
        return next(iter(available_slots), "closed")


class MouthRenderCache:
    """Caché de frames PIL y PhotoImage para renderizar la boca sin costo por frame."""

    def __init__(self):
        self.pil_frames = {}   # { slot: [(PIL.Image, dur), ...] }
        self.norm_scales = {}  # { slot: [orig_w / thumb_w, ...] }
        self.pil_cache = {}    # { key: PIL.Image }
        self.photo_cache = {}  # { (slot, ov_key, frame_idx, squash_idx): ImageTk.PhotoImage }
        self._last_sig = None

    def clear(self):
        self.pil_frames.clear()
        self.norm_scales.clear()
        self.pil_cache.clear()
        self.photo_cache.clear()
        self._last_sig = None

    def load_pil_frames(self, mouth_cfg, flip_x=False, max_dim=None):
        self.clear()
        if not isinstance(mouth_cfg, dict):
            return
        sprites = mouth_cfg.get("sprites") or {}
        for slot in ALL_MOUTH_SLOTS:
            path = sprites.get(slot, "")
            if not path or not os.path.exists(path):
                continue
            frames = []
            scales = []
            try:
                with Image.open(path) as img:
                    n_frames = min(getattr(img, "n_frames", 1), 30)
                    # Solo limitar resolución en animaciones multi-frame para ahorrar RAM;
                    # los PNG estáticos de lienzo completo (ej. 1080x1080) deben conservar su nitidez.
                    eff_max_dim = max_dim if n_frames > 1 else None
                    for i in range(n_frames):
                        if n_frames > 1:
                            img.seek(i)
                        fr = img.convert("RGBA").copy()
                        orig_w = max(1, fr.width)
                        if eff_max_dim and max(fr.size) > eff_max_dim:
                            fr.thumbnail((eff_max_dim, eff_max_dim), Image.Resampling.LANCZOS)
                        norm_sc = orig_w / max(1, fr.width)
                        if flip_x:
                            fr = fr.transpose(Image.FLIP_LEFT_RIGHT)
                        dur = max(0.02, float(img.info.get("duration", 100)) / 1000.0)
                        frames.append((fr, dur))
                        scales.append(norm_sc)
            except Exception:
                pass
            if frames:
                self.pil_frames[slot] = frames
                self.norm_scales[slot] = scales

    def get_pil(self, slot, ov_key, frame_idx, squash_idx, base_scale, scale_pct, rotation_deg, max_cache=64):
        frames = self.pil_frames.get(slot)
        if not frames:
            return None
        f_idx = frame_idx % len(frames)
        cache_key = (slot, ov_key, f_idx, squash_idx, round(base_scale, 3), int(scale_pct), int(rotation_deg))
        cached = self.pil_cache.get(cache_key)
        if cached is not None:
            return cached

        pil_img = frames[f_idx][0]
        scales = self.norm_scales.get(slot)
        norm_sc = scales[f_idx] if scales and f_idx < len(scales) else 1.0
        sc_factor = max(0.05, float(base_scale) * (float(scale_pct) / 100.0)) * norm_sc
        nw = max(1, int(pil_img.width * sc_factor))
        nh = max(1, int(pil_img.height * sc_factor))

        if squash_idx in (1, 2):
            sy = _SQUASH_RATIOS[squash_idx]
            sx = 1.0 / (sy ** 0.5)
            nw = max(1, int(nw * sx))
            nh = max(1, int(nh * sy))

        res_img = pil_img.resize((nw, nh), Image.Resampling.LANCZOS)
        if int(rotation_deg) != 0:
            res_img = res_img.rotate(-int(rotation_deg), expand=True, resample=Image.Resampling.BICUBIC)

        if len(self.pil_cache) > max_cache:
            self.pil_cache.clear()
        self.pil_cache[cache_key] = res_img
        return res_img

    def get_photo(self, slot, ov_key, frame_idx, squash_idx, base_scale, scale_pct, rotation_deg, max_cache=64):
        frames = self.pil_frames.get(slot)
        if not frames:
            return None
        f_idx = frame_idx % len(frames)
        cache_key = (slot, ov_key, f_idx, squash_idx, round(base_scale, 3), int(scale_pct), int(rotation_deg))
        cached = self.photo_cache.get(cache_key)
        if cached is not None:
            return cached

        res_img = self.get_pil(slot, ov_key, frame_idx, squash_idx, base_scale, scale_pct, rotation_deg, max_cache=max_cache)
        if res_img is None:
            return None

        photo = ImageTk.PhotoImage(res_img)
        if len(self.photo_cache) > max_cache:
            self.photo_cache.clear()
        self.photo_cache[cache_key] = photo
        return photo
