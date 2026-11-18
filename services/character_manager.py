import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from PIL import Image, ImageTk
import json
import os
import shutil

from core.app_constants import PROFILES_FILE, CONFIG_FILE, CHARACTERS_DIR, log_debug
from core.lipsync import normalize_independent_mouth
from core.eyes import normalize_independent_eyes


class CharacterManagerMixin:
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
            card_modes, text="✨ Modo Pro (4 poses por defecto)", variable=mode_var, value="4_states",
            bg="#F1F5F9", fg="#1E293B", selectcolor="#FFFFFF", font=("Segoe UI", 9, "bold")
        )
        rb_pro.pack(anchor=tk.W)
        tk.Label(card_modes, text="   idle.png, idle_blink.png, talk.png, talk_blink.png", font=("Segoe UI", 8), fg="#64748B", bg="#F1F5F9").pack(anchor=tk.W, pady=(0, 6))

        rb_simple = tk.Radiobutton(
            card_modes, text="⚡ Modo Simple (2 poses por defecto)", variable=mode_var, value="2_states",
            bg="#F1F5F9", fg="#1E293B", selectcolor="#FFFFFF", font=("Segoe UI", 9, "bold")
        )
        rb_simple.pack(anchor=tk.W)
        tk.Label(card_modes, text="   idle.png, talk.png (puedes agregar grito u otros fotogramas después)", font=("Segoe UI", 8), fg="#64748B", bg="#F1F5F9").pack(anchor=tk.W)

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

        loaded_mouth = normalize_independent_mouth(meta_disk.get("independent_mouth"), folder_path=folder_path)
        loaded_eyes = normalize_independent_eyes(meta_disk.get("independent_eyes"), folder_path=folder_path)
        if isinstance(p1_dict, dict):
            if "independent_mouth" not in p1_dict or not isinstance(p1_dict["independent_mouth"], dict):
                p1_dict["independent_mouth"] = normalize_independent_mouth(loaded_mouth, folder_path=folder_path)
            else:
                p1_dict["independent_mouth"] = normalize_independent_mouth(p1_dict["independent_mouth"], folder_path=folder_path)
            if "independent_eyes" not in p1_dict or not isinstance(p1_dict["independent_eyes"], dict):
                p1_dict["independent_eyes"] = normalize_independent_eyes(loaded_eyes, folder_path=folder_path)
            else:
                p1_dict["independent_eyes"] = normalize_independent_eyes(p1_dict["independent_eyes"], folder_path=folder_path)
        if isinstance(p2_dict, dict):
            if "independent_mouth" not in p2_dict or not isinstance(p2_dict["independent_mouth"], dict):
                p2_dict["independent_mouth"] = normalize_independent_mouth(loaded_mouth, folder_path=folder_path)
            else:
                p2_dict["independent_mouth"] = normalize_independent_mouth(p2_dict["independent_mouth"], folder_path=folder_path)
            if "independent_eyes" not in p2_dict or not isinstance(p2_dict["independent_eyes"], dict):
                p2_dict["independent_eyes"] = normalize_independent_eyes(loaded_eyes, folder_path=folder_path)
            else:
                p2_dict["independent_eyes"] = normalize_independent_eyes(p2_dict["independent_eyes"], folder_path=folder_path)

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

        raw_mouth = None
        if isinstance(p1_dict, dict) and isinstance(p1_dict.get("independent_mouth"), dict):
            raw_mouth = p1_dict.get("independent_mouth")
        elif isinstance(p2_dict, dict) and isinstance(p2_dict.get("independent_mouth"), dict):
            raw_mouth = p2_dict.get("independent_mouth")
        clean_mouth = normalize_independent_mouth(raw_mouth, folder_path=folder_path)

        raw_eyes = None
        if isinstance(p1_dict, dict) and isinstance(p1_dict.get("independent_eyes"), dict):
            raw_eyes = p1_dict.get("independent_eyes")
        elif isinstance(p2_dict, dict) and isinstance(p2_dict.get("independent_eyes"), dict):
            raw_eyes = p2_dict.get("independent_eyes")
        clean_eyes = normalize_independent_eyes(raw_eyes, folder_path=folder_path)

        meta = {
            "name": name,
            "image_mode": p1_dict.get("image_mode", p2_dict.get("image_mode", "4_states")),
            "flip_x": bool(p1_dict.get("flip_x", p2_dict.get("flip_x", False))),
            "mic_threshold": p1_dict.get("mic_threshold", 20),
            "discord_threshold": p2_dict.get("discord_threshold", 25),
            "scream_threshold": p1_dict.get("scream_threshold", 55),
            "props": clean_props,
            "extra_expressions": clean_extras,
            "independent_mouth": clean_mouth,
            "independent_eyes": clean_eyes,
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
        for r in ("idle", "idle_blink", "talk", "talk_blink", "scream"):
            p1_entry[f"a1_{r}_motion"] = "Ninguna"
            p2_entry[f"a2_{r}_motion"] = "Ninguna"
            p1_entry[f"a1_{r}_speed"] = 1.0
            p2_entry[f"a2_{r}_speed"] = 1.0
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

