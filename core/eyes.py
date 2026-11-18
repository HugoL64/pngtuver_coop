import math
import os
from PIL import Image, ImageChops, ImageTk


def default_independent_eyes():
    """Devuelve la configuración base por defecto para los ojos que siguen al mouse."""
    return {
        "enabled": False,
        "sprite": "",
        "sprite_rel": "",
        "mask_sprite": "",
        "mask_sprite_rel": "",
        "show_mask": False,
        "overlay_sprite": "",
        "overlay_sprite_rel": "",
        "offset_x": 0,
        "offset_y": 0,
        "scale": 100,
        "rotation": 0,
        "mouse_radius": 12,
        "smoothness": 35,
        "sensitivity": 300,
        "follows_bounce": True,
        "hide_on_blink": True,
        "frame_overrides": {},
    }


def _resolve_eye_asset_path(raw_abs, raw_rel, folder_path):
    abs_p = str(raw_abs or "")
    rel_p = str(raw_rel or "")
    if folder_path and rel_p:
        cand = os.path.abspath(os.path.join(folder_path, rel_p))
        if os.path.exists(cand):
            abs_p = cand
    if abs_p and not os.path.exists(abs_p) and folder_path:
        cand_e = os.path.join(folder_path, "eyes", os.path.basename(abs_p))
        if os.path.exists(cand_e):
            abs_p = cand_e

    final_abs = abs_p if (abs_p and os.path.exists(abs_p)) else ""
    if final_abs and folder_path:
        try:
            final_rel = os.path.relpath(final_abs, folder_path).replace("\\", "/")
        except Exception:
            final_rel = rel_p
    else:
        final_rel = ""
    return final_abs, final_rel


def normalize_independent_eyes(raw_cfg, folder_path=None):
    """Normaliza un diccionario de ojos independientes y resuelve rutas relativas."""
    base = default_independent_eyes()
    if not isinstance(raw_cfg, dict):
        return base

    base["enabled"] = bool(raw_cfg.get("enabled", False))
    base["show_mask"] = bool(raw_cfg.get("show_mask", False))
    base["offset_x"] = int(raw_cfg.get("offset_x", 0))
    base["offset_y"] = int(raw_cfg.get("offset_y", 0))
    base["scale"] = max(10, min(300, int(raw_cfg.get("scale", 100))))
    base["rotation"] = int(raw_cfg.get("rotation", 0))
    base["mouse_radius"] = max(1, min(80, int(raw_cfg.get("mouse_radius", 12))))
    base["smoothness"] = max(5, min(100, int(raw_cfg.get("smoothness", 35))))
    base["sensitivity"] = max(50, min(1200, int(raw_cfg.get("sensitivity", 300))))
    base["follows_bounce"] = bool(raw_cfg.get("follows_bounce", True))
    base["hide_on_blink"] = bool(raw_cfg.get("hide_on_blink", True))

    base["sprite"], base["sprite_rel"] = _resolve_eye_asset_path(
        raw_cfg.get("sprite"), raw_cfg.get("sprite_rel"), folder_path
    )
    base["mask_sprite"], base["mask_sprite_rel"] = _resolve_eye_asset_path(
        raw_cfg.get("mask_sprite"), raw_cfg.get("mask_sprite_rel"), folder_path
    )
    base["overlay_sprite"], base["overlay_sprite_rel"] = _resolve_eye_asset_path(
        raw_cfg.get("overlay_sprite"), raw_cfg.get("overlay_sprite_rel"), folder_path
    )

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


def has_eyes_sprite(eyes_cfg):
    if not isinstance(eyes_cfg, dict):
        return False
    sp = eyes_cfg.get("sprite") or ""
    return bool(sp) and os.path.exists(str(sp))


def is_independent_eyes_active(eyes_cfg):
    return bool(isinstance(eyes_cfg, dict) and eyes_cfg.get("enabled", False) and has_eyes_sprite(eyes_cfg))


def _canonical_role(role):
    if not role:
        return "idle"
    r = str(role)
    for prefix in ("a1_", "a2_"):
        if r.startswith(prefix):
            r = r[3:]
            break
    return r


def resolve_eyes_frame_config(eyes_cfg, role):
    """Resuelve (hidden, offset_x, offset_y, scale, rotation, override_key) para un rol dado."""
    if not isinstance(eyes_cfg, dict):
        return False, 0, 0, 100, 0, "idle"

    ov_key = _canonical_role(role)
    ov_map = eyes_cfg.get("frame_overrides") or {}
    ov = ov_map.get(ov_key)

    if isinstance(ov, dict):
        hidden = bool(ov.get("hidden", False))
        ox = int(ov.get("offset_x", eyes_cfg.get("offset_x", 0)))
        oy = int(ov.get("offset_y", eyes_cfg.get("offset_y", 0)))
        sc = int(ov.get("scale", eyes_cfg.get("scale", 100)))
        rot = int(ov.get("rotation", eyes_cfg.get("rotation", 0)))
    else:
        hidden = False
        ox = int(eyes_cfg.get("offset_x", 0))
        oy = int(eyes_cfg.get("offset_y", 0))
        sc = int(eyes_cfg.get("scale", 100))
        rot = int(eyes_cfg.get("rotation", 0))

    if not hidden and eyes_cfg.get("hide_on_blink", True) and ov_key in ("blink", "talk_blink"):
        hidden = True

    return hidden, ox, oy, sc, rot, ov_key


def compute_mouse_eye_offset(canvas, base_x, base_y, pos_scale, eyes_cfg, cur_ox=0.0, cur_oy=0.0):
    """Calcula el desplazamiento suave (ox, oy) de los ojos hacia el cursor global."""
    if not canvas or not canvas.winfo_exists():
        return cur_ox, cur_oy

    try:
        mx, my = canvas.winfo_pointerxy()
        win_cx = canvas.winfo_rootx() + base_x
        win_cy = canvas.winfo_rooty() + base_y
    except Exception:
        return cur_ox, cur_oy

    vx = mx - win_cx
    vy = my - win_cy
    dist = math.hypot(vx, vy)

    max_r = max(1.0, float(eyes_cfg.get("mouse_radius", 12))) * max(0.2, float(pos_scale))
    sens = max(50.0, float(eyes_cfg.get("sensitivity", 300)))
    alpha = max(0.05, min(1.0, float(eyes_cfg.get("smoothness", 35)) / 100.0))

    if dist > 0.5:
        factor = min(1.0, dist / sens)
        target_ox = (vx / dist) * max_r * factor
        target_oy = (vy / dist) * max_r * factor
    else:
        target_ox = 0.0
        target_oy = 0.0

    new_ox = cur_ox + (target_ox - cur_ox) * alpha
    new_oy = cur_oy + (target_oy - cur_oy) * alpha
    return new_ox, new_oy


def _load_rgba(path, flip_x=False):
    if path and os.path.exists(str(path)):
        try:
            im = Image.open(path).convert("RGBA")
            if flip_x:
                im = im.transpose(Image.FLIP_LEFT_RIGHT)
            return im
        except Exception:
            pass
    return None


def _scale_rotate_pil(im, pos_scale, scale_pct, rotation):
    if im is None:
        return None
    total_scale = max(0.05, float(pos_scale) * (int(scale_pct) / 100.0))
    nw = max(4, int(im.width * total_scale))
    nh = max(4, int(im.height * total_scale))
    out = im.resize((nw, nh), Image.Resampling.LANCZOS)
    if int(rotation) % 360 != 0:
        out = out.rotate(-int(rotation), expand=True, resample=Image.Resampling.BICUBIC)
    return out


class EyesRenderCache:
    """Cachea las imágenes PIL y PhotoImage de los ojos independientes (con recorte y pestañas)."""

    def __init__(self):
        self.pil_img = None
        self.mask_pil = None
        self.overlay_pil = None
        self._scaled_key = None
        self._scaled_pupil = None
        self._scaled_mask = None
        self._scaled_mask_alpha = None
        self._scaled_overlay = None
        self.tk_img = None
        self._comp_key = None

    def load_pil_frame(self, eyes_cfg, flip_x=False):
        self.pil_img = None
        self.mask_pil = None
        self.overlay_pil = None
        self._scaled_key = None
        self._scaled_pupil = None
        self._scaled_mask = None
        self._scaled_mask_alpha = None
        self._scaled_overlay = None
        self.tk_img = None
        self._comp_key = None

        if not isinstance(eyes_cfg, dict):
            return
        self.pil_img = _load_rgba(eyes_cfg.get("sprite"), flip_x=flip_x)
        self.mask_pil = _load_rgba(eyes_cfg.get("mask_sprite"), flip_x=flip_x)
        self.overlay_pil = _load_rgba(eyes_cfg.get("overlay_sprite"), flip_x=flip_x)

    def has_mask_or_overlay(self):
        return (self.mask_pil is not None) or (self.overlay_pil is not None)

    def _ensure_scaled(self, pos_scale, scale_pct=100, rotation=0):
        key = (round(float(pos_scale), 3), int(scale_pct), int(rotation))
        if key == self._scaled_key:
            return
        self._scaled_key = key
        self._scaled_pupil = _scale_rotate_pil(self.pil_img, pos_scale, scale_pct, rotation)
        self._scaled_mask = _scale_rotate_pil(self.mask_pil, pos_scale, scale_pct, rotation)
        self._scaled_mask_alpha = self._scaled_mask.getchannel("A") if self._scaled_mask is not None else None
        self._scaled_overlay = _scale_rotate_pil(self.overlay_pil, pos_scale, scale_pct, rotation)
        self._comp_key = None

    def get_tk_image(self, pos_scale, scale_pct=100, rotation=0, eye_ox=0.0, eye_oy=0.0, show_mask=False):
        """Devuelve (PhotoImage, anchored_at_base).

        Si hay máscara o pestañas (overlay), compone la pupila recortada en (eye_ox, eye_oy)
        y devuelve anchored_at_base=True (el item del canvas se queda fijo en la base).
        """
        if self.pil_img is None:
            return None, False

        self._ensure_scaled(pos_scale, scale_pct=scale_pct, rotation=rotation)
        if self._scaled_pupil is None:
            return None, False

        # Modo simple (sin máscara ni overlay): el PhotoImage no cambia con el mouse
        if self._scaled_mask is None and self._scaled_overlay is None:
            if self._comp_key != self._scaled_key or self.tk_img is None:
                self._comp_key = self._scaled_key
                self.tk_img = ImageTk.PhotoImage(self._scaled_pupil)
            return self.tk_img, False

        # Modo compuesto con máscara de recorte y/o pestañas arriba
        iox = int(round(eye_ox))
        ioy = int(round(eye_oy))
        ckey = (self._scaled_key, iox, ioy, bool(show_mask))
        if ckey == self._comp_key and self.tk_img is not None:
            return self.tk_img, True

        self._comp_key = ckey
        ref = self._scaled_mask or self._scaled_overlay
        cw, ch = ref.size

        pup_layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        px = (cw - self._scaled_pupil.width) // 2 + iox
        py = (ch - self._scaled_pupil.height) // 2 + ioy
        pup_layer.paste(self._scaled_pupil, (px, py), self._scaled_pupil)

        if self._scaled_mask_alpha is not None:
            clipped_a = ImageChops.multiply(pup_layer.getchannel("A"), self._scaled_mask_alpha)
            pup_layer.putalpha(clipped_a)
            if show_mask:
                base_layer = self._scaled_mask.copy()
                base_layer.alpha_composite(pup_layer)
                pup_layer = base_layer

        if self._scaled_overlay is not None:
            pup_layer.alpha_composite(self._scaled_overlay)

        self.tk_img = ImageTk.PhotoImage(pup_layer)
        return self.tk_img, True
