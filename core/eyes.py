import math
import os
from PIL import Image, ImageChops, ImageTk


def default_eye_set(name="Normal"):
    """Devuelve la configuración por defecto de un set/pieza de ojos reutilizable."""
    return {
        "name": str(name or "Normal"),
        "pupil_mode": "single",
        "sprite": "",
        "sprite_rel": "",
        "left_sprite": "",
        "left_sprite_rel": "",
        "left_offset_x": -30,
        "left_offset_y": 0,
        "left_scale": 100,
        "left_rotation": 0,
        "right_sprite": "",
        "right_sprite_rel": "",
        "right_offset_x": 30,
        "right_offset_y": 0,
        "right_scale": 100,
        "right_rotation": 0,
        "mask_sprite": "",
        "mask_sprite_rel": "",
        "show_mask": False,
        "overlay_sprite": "",
        "overlay_sprite_rel": "",
        "track_mouse": True,
        "mouse_radius": 12,
        "smoothness": 35,
        "sensitivity": 300,
    }


def default_independent_eyes():
    """Devuelve la configuración base por defecto para los ojos que siguen al mouse."""
    return {
        "enabled": False,
        "active_set": "default",
        "eye_sets": {},
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


def _normalize_eye_set(raw_set, folder_path=None, fallback_name="Normal", defaults=None):
    """Normaliza un set individual de ojos (pupilas, máscara, pestañas y seguimiento)."""
    src = raw_set if isinstance(raw_set, dict) else {}
    ref = defaults if isinstance(defaults, dict) else default_eye_set(fallback_name)
    out = default_eye_set(src.get("name", ref.get("name", fallback_name)))

    out["pupil_mode"] = "dual" if str(src.get("pupil_mode", ref.get("pupil_mode", "single"))) == "dual" else "single"
    out["show_mask"] = bool(src.get("show_mask", ref.get("show_mask", False)))
    out["track_mouse"] = bool(src.get("track_mouse", ref.get("track_mouse", True)))
    out["mouse_radius"] = max(1, min(80, int(src.get("mouse_radius", ref.get("mouse_radius", 12)))))
    out["smoothness"] = max(5, min(100, int(src.get("smoothness", ref.get("smoothness", 35)))))
    out["sensitivity"] = max(50, min(1200, int(src.get("sensitivity", ref.get("sensitivity", 300)))))

    out["left_offset_x"] = int(src.get("left_offset_x", ref.get("left_offset_x", -30)))
    out["left_offset_y"] = int(src.get("left_offset_y", ref.get("left_offset_y", 0)))
    out["left_scale"] = max(10, min(300, int(src.get("left_scale", ref.get("left_scale", 100)))))
    out["left_rotation"] = int(src.get("left_rotation", ref.get("left_rotation", 0)))

    out["right_offset_x"] = int(src.get("right_offset_x", ref.get("right_offset_x", 30)))
    out["right_offset_y"] = int(src.get("right_offset_y", ref.get("right_offset_y", 0)))
    out["right_scale"] = max(10, min(300, int(src.get("right_scale", ref.get("right_scale", 100)))))
    out["right_rotation"] = int(src.get("right_rotation", ref.get("right_rotation", 0)))

    out["sprite"], out["sprite_rel"] = _resolve_eye_asset_path(
        src.get("sprite"), src.get("sprite_rel"), folder_path
    )
    out["left_sprite"], out["left_sprite_rel"] = _resolve_eye_asset_path(
        src.get("left_sprite"), src.get("left_sprite_rel"), folder_path
    )
    out["right_sprite"], out["right_sprite_rel"] = _resolve_eye_asset_path(
        src.get("right_sprite"), src.get("right_sprite_rel"), folder_path
    )
    out["mask_sprite"], out["mask_sprite_rel"] = _resolve_eye_asset_path(
        src.get("mask_sprite"), src.get("mask_sprite_rel"), folder_path
    )
    out["overlay_sprite"], out["overlay_sprite_rel"] = _resolve_eye_asset_path(
        src.get("overlay_sprite"), src.get("overlay_sprite_rel"), folder_path
    )
    return out


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

    # Normalizar biblioteca de sets de ojos (eye_sets)
    raw_sets = raw_cfg.get("eye_sets")
    clean_sets = {}
    if isinstance(raw_sets, dict):
        for set_id, raw_set in raw_sets.items():
            sid = str(set_id or "").strip()
            if not sid or sid == "none" or not isinstance(raw_set, dict):
                continue
            clean_sets[sid] = _normalize_eye_set(
                raw_set, folder_path=folder_path, fallback_name=sid.capitalize(), defaults=base
            )

    # Retrocompatibilidad: si no hay eye_sets pero sí sprites sueltos en la raíz, migrar a "default"
    if not clean_sets and (base["sprite"] or base["mask_sprite"] or base["overlay_sprite"]):
        clean_sets["default"] = _normalize_eye_set(
            {
                "name": "Normal",
                "sprite": base["sprite"],
                "sprite_rel": base["sprite_rel"],
                "mask_sprite": base["mask_sprite"],
                "mask_sprite_rel": base["mask_sprite_rel"],
                "show_mask": base["show_mask"],
                "overlay_sprite": base["overlay_sprite"],
                "overlay_sprite_rel": base["overlay_sprite_rel"],
                "track_mouse": True,
                "mouse_radius": base["mouse_radius"],
                "smoothness": base["smoothness"],
                "sensitivity": base["sensitivity"],
            },
            folder_path=folder_path,
            fallback_name="Normal",
        )

    base["eye_sets"] = clean_sets

    active_set = str(raw_cfg.get("active_set") or "default").strip()
    if clean_sets:
        if active_set not in clean_sets:
            active_set = "default" if "default" in clean_sets else next(iter(clean_sets))
        # Mantener campos raíz sincronizados con active_set para compatibilidad
        act = clean_sets[active_set]
        base["sprite"] = act["sprite"]
        base["sprite_rel"] = act["sprite_rel"]
        base["mask_sprite"] = act["mask_sprite"]
        base["mask_sprite_rel"] = act["mask_sprite_rel"]
        base["show_mask"] = act["show_mask"]
        base["overlay_sprite"] = act["overlay_sprite"]
        base["overlay_sprite_rel"] = act["overlay_sprite_rel"]
        base["mouse_radius"] = act["mouse_radius"]
        base["smoothness"] = act["smoothness"]
        base["sensitivity"] = act["sensitivity"]
    base["active_set"] = active_set or "default"

    raw_ov = raw_cfg.get("frame_overrides") or {}
    if isinstance(raw_ov, dict):
        clean_ov = {}
        for role_k, ov in raw_ov.items():
            if not isinstance(ov, dict):
                continue
            entry = {
                "offset_x": int(ov.get("offset_x", base["offset_x"])),
                "offset_y": int(ov.get("offset_y", base["offset_y"])),
                "scale": max(10, min(300, int(ov.get("scale", base["scale"])))),
                "rotation": int(ov.get("rotation", base["rotation"])),
                "hidden": bool(ov.get("hidden", False)),
            }
            eye_set_id = str(ov.get("eye_set", "") or "").strip()
            if eye_set_id:
                entry["eye_set"] = eye_set_id
            clean_ov[str(role_k)] = entry
        base["frame_overrides"] = clean_ov

    return base


def has_eyes_sprite(eyes_cfg):
    if not isinstance(eyes_cfg, dict):
        return False
    sp = eyes_cfg.get("sprite") or ""
    if sp and os.path.exists(str(sp)):
        return True
    eye_sets = eyes_cfg.get("eye_sets") or {}
    if isinstance(eye_sets, dict):
        for s in eye_sets.values():
            if isinstance(s, dict):
                for key in ("sprite", "left_sprite", "right_sprite", "overlay_sprite"):
                    ssp = s.get(key) or ""
                    if ssp and os.path.exists(str(ssp)):
                        return True
    return False


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


def resolve_eye_set_for_role(eyes_cfg, role):
    """Devuelve (set_id, set_cfg) activo para una escena/rol dado."""
    if not isinstance(eyes_cfg, dict):
        return "none", None

    ov_key = _canonical_role(role)
    ov_map = eyes_cfg.get("frame_overrides") or {}
    ov = ov_map.get(ov_key)
    eye_sets = eyes_cfg.get("eye_sets") or {}

    if isinstance(ov, dict):
        ov_set = str(ov.get("eye_set", "") or "").strip()
        if ov_set == "none":
            return "none", None
        if ov_set and isinstance(eye_sets, dict) and ov_set in eye_sets:
            return ov_set, eye_sets[ov_set]

    active_id = str(eyes_cfg.get("active_set") or "default").strip()
    if isinstance(eye_sets, dict) and eye_sets:
        if active_id in eye_sets:
            return active_id, eye_sets[active_id]
        first_id = next(iter(eye_sets))
        return first_id, eye_sets[first_id]

    # Fallback si es una config sin eye_sets construida manualmente
    return "default", eyes_cfg


def resolve_eyes_frame_config(eyes_cfg, role):
    """Resuelve (hidden, offset_x, offset_y, scale, rotation, override_key) para un rol dado."""
    if not isinstance(eyes_cfg, dict):
        return False, 0, 0, 100, 0, "idle"

    ov_key = _canonical_role(role)
    ov_map = eyes_cfg.get("frame_overrides") or {}
    ov = ov_map.get(ov_key)

    if isinstance(ov, dict):
        hidden = bool(ov.get("hidden", False)) or (str(ov.get("eye_set", "") or "").strip() == "none")
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

    if not hidden and eyes_cfg.get("hide_on_blink", True) and ov_key in ("blink", "idle_blink", "talk_blink"):
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
    """Cachea las imágenes PIL y PhotoImage de los sets de ojos independientes (con recorte y pestañas)."""

    def __init__(self):
        self._sets = {}
        self._default_set_id = "default"
        # Atributos heredados para compatibilidad con callers simples
        self.pil_img = None
        self.mask_pil = None
        self.overlay_pil = None
        self.tk_img = None

    def _empty_slot(self):
        return {
            "pupil_mode": "single",
            "pil_img": None,
            "left_pil": None,
            "right_pil": None,
            "left_ox": -30,
            "left_oy": 0,
            "left_scale": 100,
            "left_rot": 0,
            "right_ox": 30,
            "right_oy": 0,
            "right_scale": 100,
            "right_rot": 0,
            "flip_x": False,
            "mask_pil": None,
            "overlay_pil": None,
            "scaled_key": None,
            "scaled_pupil": None,
            "scaled_left": None,
            "scaled_right": None,
            "scaled_mask": None,
            "scaled_mask_alpha": None,
            "scaled_overlay": None,
            "tk_img": None,
            "comp_pil": None,
            "comp_key": None,
        }

    def load_pil_frame(self, eyes_cfg, flip_x=False):
        self._sets = {}
        self._default_set_id = "default"
        self.pil_img = None
        self.mask_pil = None
        self.overlay_pil = None
        self.tk_img = None

        if not isinstance(eyes_cfg, dict):
            return

        eye_sets = eyes_cfg.get("eye_sets")
        if isinstance(eye_sets, dict) and eye_sets:
            self._default_set_id = str(eyes_cfg.get("active_set") or "default")
            if self._default_set_id not in eye_sets:
                self._default_set_id = next(iter(eye_sets))
            for sid, scfg in eye_sets.items():
                if not isinstance(scfg, dict):
                    continue
                slot = self._empty_slot()
                slot["pupil_mode"] = "dual" if scfg.get("pupil_mode") == "dual" else "single"
                slot["flip_x"] = bool(flip_x)
                slot["pil_img"] = _load_rgba(scfg.get("sprite"), flip_x=flip_x)
                slot["left_pil"] = _load_rgba(scfg.get("left_sprite"), flip_x=flip_x)
                slot["right_pil"] = _load_rgba(scfg.get("right_sprite"), flip_x=flip_x)
                lox = int(scfg.get("left_offset_x", -30))
                rox = int(scfg.get("right_offset_x", 30))
                lrot = int(scfg.get("left_rotation", 0))
                rrot = int(scfg.get("right_rotation", 0))
                slot["left_ox"] = -lox if flip_x else lox
                slot["left_oy"] = int(scfg.get("left_offset_y", 0))
                slot["left_scale"] = int(scfg.get("left_scale", 100))
                slot["left_rot"] = -lrot if flip_x else lrot
                slot["right_ox"] = -rox if flip_x else rox
                slot["right_oy"] = int(scfg.get("right_offset_y", 0))
                slot["right_scale"] = int(scfg.get("right_scale", 100))
                slot["right_rot"] = -rrot if flip_x else rrot
                slot["mask_pil"] = _load_rgba(scfg.get("mask_sprite"), flip_x=flip_x)
                slot["overlay_pil"] = _load_rgba(scfg.get("overlay_sprite"), flip_x=flip_x)
                self._sets[str(sid)] = slot
        else:
            slot = self._empty_slot()
            slot["pil_img"] = _load_rgba(eyes_cfg.get("sprite"), flip_x=flip_x)
            slot["mask_pil"] = _load_rgba(eyes_cfg.get("mask_sprite"), flip_x=flip_x)
            slot["overlay_pil"] = _load_rgba(eyes_cfg.get("overlay_sprite"), flip_x=flip_x)
            self._sets["default"] = slot
            self._default_set_id = "default"

        def_slot = self._sets.get(self._default_set_id)
        if def_slot:
            self.pil_img = def_slot["pil_img"]
            self.mask_pil = def_slot["mask_pil"]
            self.overlay_pil = def_slot["overlay_pil"]

    def _get_slot(self, set_id=None):
        sid = str(set_id or self._default_set_id)
        return self._sets.get(sid) or self._sets.get(self._default_set_id)

    def has_mask_or_overlay(self, set_id=None):
        slot = self._get_slot(set_id)
        if not slot:
            return False
        return (
            (slot["mask_pil"] is not None)
            or (slot["overlay_pil"] is not None)
            or (slot.get("pupil_mode") == "dual")
        )

    def _ensure_scaled(self, slot, pos_scale, scale_pct=100, rotation=0):
        key = (
            round(float(pos_scale), 3),
            int(scale_pct),
            int(rotation),
            slot.get("pupil_mode"),
            slot.get("left_scale"),
            slot.get("left_rot"),
            slot.get("right_scale"),
            slot.get("right_rot"),
        )
        if key == slot["scaled_key"]:
            return
        slot["scaled_key"] = key
        slot["scaled_pupil"] = _scale_rotate_pil(slot["pil_img"], pos_scale, scale_pct, rotation)
        if slot.get("pupil_mode") == "dual":
            l_sc = max(10, int(round(int(scale_pct) * (int(slot.get("left_scale", 100)) / 100.0))))
            r_sc = max(10, int(round(int(scale_pct) * (int(slot.get("right_scale", 100)) / 100.0))))
            slot["scaled_left"] = _scale_rotate_pil(
                slot["left_pil"], pos_scale, l_sc, int(rotation) + int(slot.get("left_rot", 0))
            )
            slot["scaled_right"] = _scale_rotate_pil(
                slot["right_pil"], pos_scale, r_sc, int(rotation) + int(slot.get("right_rot", 0))
            )
        else:
            slot["scaled_left"] = None
            slot["scaled_right"] = None
        slot["scaled_mask"] = _scale_rotate_pil(slot["mask_pil"], pos_scale, scale_pct, rotation)
        slot["scaled_mask_alpha"] = slot["scaled_mask"].getchannel("A") if slot["scaled_mask"] is not None else None
        slot["scaled_overlay"] = _scale_rotate_pil(slot["overlay_pil"], pos_scale, scale_pct, rotation)
        slot["comp_key"] = None

    def _compose_pupils_layer(self, slot, pos_scale, scale_pct, rotation, eye_ox, eye_oy, show_mask):
        """Compone el frame RGBA final para 1 o 2 pupilas, máscara y overlay."""
        self._ensure_scaled(slot, pos_scale, scale_pct=scale_pct, rotation=rotation)
        is_dual = (slot.get("pupil_mode") == "dual")
        s_pupil = slot["scaled_pupil"]
        s_left = slot["scaled_left"]
        s_right = slot["scaled_right"]
        s_mask = slot["scaled_mask"]
        s_mask_a = slot["scaled_mask_alpha"]
        s_overlay = slot["scaled_overlay"]

        has_any_pupil = (s_left is not None or s_right is not None) if is_dual else (s_pupil is not None)
        if not has_any_pupil and s_overlay is None:
            return None, False, False

        if not is_dual and s_mask is None and s_overlay is None:
            return s_pupil, False, True

        if not has_any_pupil and s_overlay is not None:
            return s_overlay, True, True

        iox = int(round(eye_ox))
        ioy = int(round(eye_oy))
        tot_sc = max(0.05, float(pos_scale) * (int(scale_pct) / 100.0))
        lox = int(round(int(slot.get("left_ox", -30)) * tot_sc))
        loy = int(round(int(slot.get("left_oy", 0)) * tot_sc))
        rox = int(round(int(slot.get("right_ox", 30)) * tot_sc))
        roy = int(round(int(slot.get("right_oy", 0)) * tot_sc))

        ckey = (slot["scaled_key"], iox, ioy, bool(show_mask), lox, loy, rox, roy)
        if ckey == slot["comp_key"] and slot.get("comp_pil") is not None:
            return slot["comp_pil"], True, False

        slot["comp_key"] = ckey
        ref = s_mask or s_overlay
        if ref is not None:
            cw, ch = ref.size
        else:
            # Lienzo suficiente para ambas pupilas y su desplazamiento respecto al centro
            max_half_w = 32
            max_half_h = 32
            for im, ox, oy in ((s_left, lox, loy), (s_right, rox, roy)):
                if im is not None:
                    max_half_w = max(max_half_w, abs(ox) + im.width // 2 + abs(iox) + 8)
                    max_half_h = max(max_half_h, abs(oy) + im.height // 2 + abs(ioy) + 8)
            cw = max(64, max_half_w * 2)
            ch = max(64, max_half_h * 2)

        pup_layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        if is_dual:
            for im, ox, oy in ((s_left, lox, loy), (s_right, rox, roy)):
                if im is not None:
                    px = (cw - im.width) // 2 + ox + iox
                    py = (ch - im.height) // 2 + oy + ioy
                    pup_layer.paste(im, (px, py), im)
        else:
            px = (cw - s_pupil.width) // 2 + iox
            py = (ch - s_pupil.height) // 2 + ioy
            pup_layer.paste(s_pupil, (px, py), s_pupil)

        if s_mask_a is not None:
            clipped_a = ImageChops.multiply(pup_layer.getchannel("A"), s_mask_a)
            pup_layer.putalpha(clipped_a)
            if show_mask:
                base_layer = s_mask.copy()
                base_layer.alpha_composite(pup_layer)
                pup_layer = base_layer

        if s_overlay is not None:
            pup_layer.alpha_composite(s_overlay)

        slot["comp_pil"] = pup_layer
        return pup_layer, True, False

    def get_tk_image(self, pos_scale, scale_pct=100, rotation=0, eye_ox=0.0, eye_oy=0.0, show_mask=False, set_id=None):
        """Devuelve (PhotoImage, anchored_at_base)."""
        slot = self._get_slot(set_id)
        if not slot:
            return None, False
        comp_pil, anchored, is_static = self._compose_pupils_layer(
            slot, pos_scale, scale_pct, rotation, eye_ox, eye_oy, show_mask
        )
        if comp_pil is None:
            return None, False
        if is_static and slot["comp_key"] == slot["scaled_key"] and slot["tk_img"] is not None:
            self.tk_img = slot["tk_img"]
            return slot["tk_img"], anchored
        if is_static:
            slot["comp_key"] = slot["scaled_key"]
            slot["tk_img"] = ImageTk.PhotoImage(comp_pil)
        else:
            slot["tk_img"] = ImageTk.PhotoImage(comp_pil)
        self.tk_img = slot["tk_img"]
        return slot["tk_img"], anchored

    def get_composed_pil(self, pos_scale, scale_pct=100, rotation=0, eye_ox=0, eye_oy=0, show_mask=False, set_id=None):
        """Devuelve (PIL.Image RGBA, is_composed) reutilizando el caché para composición Alpha."""
        slot = self._get_slot(set_id)
        if not slot:
            return None, False
        comp_pil, anchored, _ = self._compose_pupils_layer(
            slot, pos_scale, scale_pct, rotation, eye_ox, eye_oy, show_mask
        )
        return comp_pil, anchored
