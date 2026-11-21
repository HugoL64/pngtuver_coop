import os

BASE_POSE_ROLES = ("idle", "idle_blink", "talk", "talk_blink", "scream")


def default_emotion_slots():
    """Devuelve los 5 perfiles de emoción por defecto numerados del 1 al 5."""
    return [
        {
            "name": str(i + 1),
            "images": {},
            "images_rel": {},
            "motions": {},
            "motion_speeds": {},
        }
        for i in range(5)
    ]


def normalize_emotion_slots(raw_slots, folder_path=None):
    """Normaliza la lista de 5 perfiles de emoción y resuelve rutas relativas."""
    base = default_emotion_slots()
    if not isinstance(raw_slots, list):
        return base

    for idx in range(min(5, len(raw_slots))):
        item = raw_slots[idx]
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip()
        base[idx]["name"] = name if name else str(idx + 1)

        raw_imgs = item.get("images") or {}
        raw_rels = item.get("images_rel") or {}
        if idx > 0:
            for r in BASE_POSE_ROLES:
                abs_p = str(raw_imgs.get(r, "") or "")
                rel_p = str(raw_rels.get(r, "") or "")
                if folder_path and rel_p:
                    cand = os.path.abspath(os.path.join(folder_path, rel_p))
                    if os.path.exists(cand):
                        abs_p = cand
                if abs_p and not os.path.exists(abs_p) and folder_path:
                    cand_e = os.path.join(folder_path, "emotions", f"slot_{idx + 1}", os.path.basename(abs_p))
                    if os.path.exists(cand_e):
                        abs_p = cand_e
                if abs_p and os.path.exists(abs_p):
                    base[idx]["images"][r] = abs_p
                    if folder_path:
                        try:
                            base[idx]["images_rel"][r] = os.path.relpath(abs_p, folder_path).replace("\\", "/")
                        except Exception:
                            base[idx]["images_rel"][r] = rel_p
                    else:
                        base[idx]["images_rel"][r] = rel_p

        raw_motions = item.get("motions") or {}
        if isinstance(raw_motions, dict):
            for r in BASE_POSE_ROLES:
                m = raw_motions.get(r)
                if m:
                    base[idx]["motions"][r] = "Respiración" if m == "Rebote" else str(m)

        raw_speeds = item.get("motion_speeds") or {}
        if isinstance(raw_speeds, dict):
            for r in BASE_POSE_ROLES:
                sp = raw_speeds.get(r)
                if sp is not None:
                    try:
                        base[idx]["motion_speeds"][r] = round(max(0.3, min(3.0, float(sp))), 2)
                    except Exception:
                        pass

    return base


def get_effective_pose_data(char_data, prefix="a1", slot_idx=None):
    """Combina las poses base (slot 0) con el perfil de emoción activo (slots 1..4)."""
    if not isinstance(char_data, dict):
        return {}, {}, {}

    if slot_idx is None:
        try:
            slot_idx = int(char_data.get("active_emotion", 0))
        except Exception:
            slot_idx = 0
    slot_idx = max(0, min(4, slot_idx))

    images = {}
    motions = {}
    speeds = {}
    for r in BASE_POSE_ROLES:
        p = char_data.get(f"{prefix}_{r}")
        if p:
            images[r] = p
        m = char_data.get(f"{prefix}_{r}_motion")
        if m:
            motions[r] = m
        sp = char_data.get(f"{prefix}_{r}_speed")
        if sp is not None:
            speeds[r] = sp

    if slot_idx > 0:
        slots = char_data.get("emotion_slots")
        if isinstance(slots, list) and slot_idx < len(slots) and isinstance(slots[slot_idx], dict):
            sl = slots[slot_idx]
            for r, p in (sl.get("images") or {}).items():
                if p and os.path.exists(str(p)):
                    images[r] = p
            for r, m in (sl.get("motions") or {}).items():
                if m:
                    motions[r] = m
            for r, sp in (sl.get("motion_speeds") or {}).items():
                if sp is not None:
                    speeds[r] = sp

    return images, motions, speeds
