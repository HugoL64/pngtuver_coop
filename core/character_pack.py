import json
import os
import zipfile
from core.emotions import BASE_POSE_ROLES, default_emotion_slots


def _safe_rel_add(zf, abs_path, arc_name):
    if abs_path and os.path.isfile(abs_path):
        zf.write(abs_path, arc_name)


def export_character_zip(char_folder, char_name, out_zip_path, slot_idx=None):
    """Exporta un personaje completo o un perfil de emoción específico (0..4) a un archivo .zip."""
    meta_path = os.path.join(char_folder, "character.json")
    meta = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = {}

    if slot_idx is None:
        with zipfile.ZipFile(out_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root_dir, _dirs, files in os.walk(char_folder):
                if "__pycache__" in root_dir:
                    continue
                for fn in files:
                    if fn.endswith(".tmp"):
                        continue
                    full_p = os.path.join(root_dir, fn)
                    rel_p = os.path.relpath(full_p, char_folder).replace("\\", "/")
                    zf.write(full_p, rel_p)
        return out_zip_path

    slot_idx = max(0, min(4, int(slot_idx)))
    slots = meta.get("emotion_slots") if isinstance(meta.get("emotion_slots"), list) else []
    sl = slots[slot_idx] if slot_idx < len(slots) and isinstance(slots[slot_idx], dict) else {}

    export_meta = dict(meta)
    export_meta["emotion_slots"] = default_emotion_slots()
    export_meta["active_emotion"] = 0
    if slot_idx > 0:
        sl_name = str(sl.get("name") or "").strip()
        if sl_name and sl_name != str(slot_idx + 1):
            export_meta["name"] = f"{char_name} ({sl_name})"

    with zipfile.ZipFile(out_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Poses base (promoviendo las del slot elegido si slot_idx > 0)
        new_motions = dict(meta.get("motions") or {})
        new_speeds = dict(meta.get("motion_speeds") or {})
        new_exprs = {}
        for r in BASE_POSE_ROLES:
            chosen_abs = None
            if slot_idx > 0:
                rel_em = (sl.get("images_rel") or {}).get(r)
                if rel_em:
                    cand = os.path.join(char_folder, rel_em)
                    if os.path.isfile(cand):
                        chosen_abs = cand
                if chosen_abs is None:
                    abs_em = (sl.get("images") or {}).get(r)
                    if abs_em and os.path.isfile(abs_em):
                        chosen_abs = abs_em
                if (sl.get("motions") or {}).get(r):
                    new_motions[r] = sl["motions"][r]
                if (sl.get("motion_speeds") or {}).get(r) is not None:
                    new_speeds[r] = sl["motion_speeds"][r]

            if chosen_abs is None:
                for ext in (".gif", ".webp", ".png"):
                    cand = os.path.join(char_folder, f"{r}{ext}")
                    if os.path.isfile(cand):
                        chosen_abs = cand
                        break
            if chosen_abs and os.path.isfile(chosen_abs):
                ext = os.path.splitext(chosen_abs)[1].lower()
                arc = f"{r}{ext}"
                _safe_rel_add(zf, chosen_abs, arc)
                new_exprs[r] = arc

        export_meta["motions"] = new_motions
        export_meta["motion_speeds"] = new_speeds
        export_meta["expressions"] = new_exprs

        # 2. Subcarpetas compartidas (props, mouths, eyes) y extra_expressions si es slot 0
        shared_dirs = ["props", "mouths", "eyes"]
        for sd in shared_dirs:
            sd_path = os.path.join(char_folder, sd)
            if os.path.isdir(sd_path):
                for root_dir, _dirs, files in os.walk(sd_path):
                    for fn in files:
                        full_p = os.path.join(root_dir, fn)
                        rel_p = os.path.relpath(full_p, char_folder).replace("\\", "/")
                        zf.write(full_p, rel_p)

        if slot_idx == 0:
            for ex in meta.get("extra_expressions") or []:
                rel_ex = ex.get("file_rel")
                if rel_ex:
                    cand = os.path.join(char_folder, rel_ex)
                    if os.path.isfile(cand):
                        _safe_rel_add(zf, cand, rel_ex.replace("\\", "/"))
        else:
            export_meta["extra_expressions"] = []

        zf.writestr("character.json", json.dumps(export_meta, indent=2, ensure_ascii=False))

    return out_zip_path


def import_character_zip(zip_path, characters_dir):
    """Importa un archivo .zip de personaje a personajes/<Nombre>/ de forma segura."""
    os.makedirs(characters_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        if not members:
            raise ValueError("El archivo ZIP está vacío.")

        # Detectar si viene envuelto en una sola carpeta raíz
        top_dirs = {m.split("/")[0] for m in members if "/" in m and not m.startswith("__MACOSX")}
        has_root_json = "character.json" in members
        strip_prefix = ""
        if not has_root_json and len(top_dirs) == 1:
            only_dir = next(iter(top_dirs))
            if f"{only_dir}/character.json" in members or any(m.startswith(f"{only_dir}/idle.") for m in members):
                strip_prefix = f"{only_dir}/"

        base_name = os.path.splitext(os.path.basename(zip_path))[0].strip() or "Personaje"
        meta_bytes = None
        meta_arc = f"{strip_prefix}character.json"
        if meta_arc in members:
            try:
                meta_bytes = zf.read(meta_arc)
                meta_json = json.loads(meta_bytes.decode("utf-8"))
                if meta_json.get("name"):
                    base_name = str(meta_json["name"]).strip()
            except Exception:
                pass

        # Evitar colisiones con nombres existentes
        clean_folder = "".join(c for c in base_name if c not in '<>:"/\\|?*').strip() or "Personaje"
        dest_folder = os.path.join(characters_dir, clean_folder)
        final_name = clean_folder
        n_idx = 2
        while os.path.exists(dest_folder):
            final_name = f"{clean_folder} ({n_idx})"
            dest_folder = os.path.join(characters_dir, final_name)
            n_idx += 1

        os.makedirs(dest_folder, exist_ok=True)
        dest_abs = os.path.abspath(dest_folder)

        for m in members:
            if m.startswith("__MACOSX") or m.endswith("/"):
                continue
            rel_m = m[len(strip_prefix):] if (strip_prefix and m.startswith(strip_prefix)) else m
            rel_m = rel_m.lstrip("/\\")
            if not rel_m or ".." in rel_m.split("/"):
                continue
            target_p = os.path.abspath(os.path.join(dest_abs, rel_m))
            if not target_p.startswith(dest_abs):
                continue
            os.makedirs(os.path.dirname(target_p), exist_ok=True)
            with zf.open(m) as src, open(target_p, "wb") as dst:
                dst.write(src.read())

        # Actualizar name en character.json si fue renombrado por colisión
        meta_dest = os.path.join(dest_abs, "character.json")
        if os.path.exists(meta_dest):
            try:
                with open(meta_dest, "r", encoding="utf-8") as f:
                    mj = json.load(f)
                mj["name"] = final_name
                with open(meta_dest, "w", encoding="utf-8") as f:
                    json.dump(mj, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        return final_name, dest_abs
