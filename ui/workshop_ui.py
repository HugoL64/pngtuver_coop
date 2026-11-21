import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import json
import math
import os
import shutil
import time

from core.app_constants import EXTRA_EXPRESSION_CATALOG, log_debug, ScrollableFrame
from ui.live_avatar_preview import LiveAvatarPreview
from core.hotkeys import format_hotkey, pretty_key_label
from core.emotions import (
    BASE_POSE_ROLES,
    default_emotion_slots,
    get_effective_pose_data,
    normalize_emotion_slots,
)
from core.lipsync import (
    MOUTH_SLOTS,
    VOWEL_SLOTS,
    MOUTH_SLOT_LABELS,
    MouthLipsyncEngine,
    MouthRenderCache,
    default_independent_mouth,
    has_any_mouth_sprite,
    normalize_independent_mouth,
    resolve_mouth_frame_config,
)
from core.eyes import (
    EyesRenderCache,
    compute_mouse_eye_offset,
    default_eye_set,
    default_independent_eyes,
    has_eyes_sprite,
    normalize_independent_eyes,
    resolve_eye_set_for_role,
    resolve_eyes_frame_config,
)


class WorkshopMixin:
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

        self.w_emotion_bar = tk.Frame(top_w, bg="#FFFFFF")
        self.w_emotion_bar.pack(side=tk.LEFT, padx=(10, 0))
        self.w_emotion_btns = []
        for em_i in range(5):
            eb = tk.Button(
                self.w_emotion_bar, text=str(em_i + 1), font=("Segoe UI", 8, "bold"),
                bg="#F1F5F9", fg="#334155", relief="solid", bd=1, padx=8, pady=2, cursor="hand2",
                command=lambda idx=em_i: self._select_emotion_slot(idx)
            )
            eb.bind("<Button-3>", lambda e, idx=em_i: self._on_emotion_slot_right_click(e, idx))
            eb.pack(side=tk.LEFT, padx=2)
            self.w_emotion_btns.append(eb)

        mouth_hdr_f = tk.Frame(top_w, bg="#FFFFFF")
        mouth_hdr_f.pack(side=tk.RIGHT)

        self.w_indep_eyes_var = tk.BooleanVar(value=False)
        self.w_eyes_cfg_btn = tk.Button(
            mouth_hdr_f, text="👀 Ojos", font=("Segoe UI", 8, "bold"),
            bg="#F1F5F9", fg="#334155", activebackground="#3671C6", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=10, pady=2, cursor="hand2",
            command=self._open_independent_eyes_dialog
        )
        self.w_eyes_cfg_btn.pack(side=tk.RIGHT, padx=(8, 0))

        self.w_indep_mouth_var = tk.BooleanVar(value=False)
        self.w_mouth_cfg_btn = tk.Button(
            mouth_hdr_f, text="👄 Boca", font=("Segoe UI", 8, "bold"),
            bg="#F1F5F9", fg="#334155", activebackground="#3671C6", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=10, pady=2, cursor="hand2",
            command=self._open_independent_mouth_dialog
        )
        self.w_mouth_cfg_btn.pack(side=tk.RIGHT)

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
        if hasattr(self, "w_indep_mouth_var"):
            m_cfg = target_data.get("independent_mouth") or {}
            m_on = bool(m_cfg.get("enabled", False))
            self.w_indep_mouth_var.set(m_on)
            self._update_mouth_switch_style(m_on)
        if hasattr(self, "w_indep_eyes_var"):
            e_cfg = target_data.get("independent_eyes") or {}
            e_on = bool(e_cfg.get("enabled", False))
            self.w_indep_eyes_var.set(e_on)
            self._update_eyes_switch_style(e_on)
        self.w_live_avatar.set_character(target_data, prefix=prefix)

        self._refresh_emotion_slots_bar(target_data)

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
            text="➕\n\nAgregar fotograma\n",
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
            # Usar copia del sprite base existente como imagen inicial para que la tarjeta sea visible de inmediato
            base_key = f"{prefix}_scream" if trig == "state_scream" else f"{prefix}_idle"
            cand_base = target_dict.get(base_key) or self.default_assets.get(base_key)
            if cand_base and os.path.exists(cand_base):
                idle_src = cand_base
            else:
                cand_idle = target_dict.get(f"{prefix}_idle") or self.default_assets.get(f"{prefix}_idle")
                idle_src = cand_idle if (cand_idle and os.path.exists(cand_idle)) else ""
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

        is_p1_card = (target_dict is self.p1_data)
        pref_card = "a1" if is_p1_card else "a2"
        active_em = self._get_active_emotion_idx(target_dict)
        is_base_role = (role_id in BASE_POSE_ROLES) and (key == f"{pref_card}_{role_id}")
        slot_obj = self._get_emotion_slot_obj(target_dict, active_em) if (is_base_role and active_em > 0) else None
        own_img = (slot_obj.get("images") or {}).get(role_id) if slot_obj else target_dict.get(key)
        is_inherited = bool(slot_obj is not None and not own_img)
        disp_title = f"{title_text} (de 1)" if is_inherited else title_text

        # Título arriba
        title_lbl = tk.Label(
            card, text=disp_title, font=("Segoe UI", 9, "bold"),
            bg="#FFFFFF", fg="#64748B" if is_inherited else "#1E293B", cursor="hand2"
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
        if slot_obj is not None:
            current_motion = (slot_obj.get("motions") or {}).get(role_id) or target_dict.get(f"{key}_motion")
        else:
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
        if slot_obj is not None:
            curr_speed = (slot_obj.get("motion_speeds") or {}).get(role_id, target_dict.get(f"{key}_speed", 1.0))
        else:
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
            target_dict[f"{key}_motion"] = val if slot_obj is None else target_dict.get(f"{key}_motion", val)
            target_dict[f"{key}_speed"] = spd if slot_obj is None else target_dict.get(f"{key}_speed", spd)
            is_p1 = (target_dict is self.p1_data)
            curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
            for p_key, pref, rt_dict in (
                ("player1", "a1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
                ("player2", "a2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
            ):
                prof = self.profiles.get(p_key, {}).get(curr_name)
                for d in (prof, rt_dict):
                    if isinstance(d, dict):
                        if slot_obj is not None:
                            slots = d.setdefault("emotion_slots", default_emotion_slots())
                            if active_em < len(slots):
                                slots[active_em].setdefault("motions", {})[role_id] = val
                                slots[active_em].setdefault("motion_speeds", {})[role_id] = spd
                        else:
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
        active_em = self._get_active_emotion_idx(target_dict)
        if active_em > 0 and role_id in BASE_POSE_ROLES:
            for p_key, rt_dict in (
                ("player1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
                ("player2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
            ):
                prof = self.profiles.get(p_key, {}).get(curr_name)
                for d in (prof, rt_dict):
                    if isinstance(d, dict):
                        slots = d.setdefault("emotion_slots", default_emotion_slots())
                        if active_em < len(slots):
                            slots[active_em].setdefault("images", {}).pop(role_id, None)
                            slots[active_em].setdefault("images_rel", {}).pop(role_id, None)
        else:
            target_dict[key] = ""
            for p_key, pref, rt_dict in (
                ("player1", "a1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
                ("player2", "a2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
            ):
                prof = self.profiles.get(p_key, {}).get(curr_name)
                for d in (prof, rt_dict):
                    if isinstance(d, dict):
                        d[f"{pref}_{role_id}"] = ""
        self._rebuild_workshop_sprite_slots(target_dict, "a1" if is_p1 else "a2")
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
            active_em = self._get_active_emotion_idx(target_dict)
            is_em_slot = (active_em > 0) and (role in BASE_POSE_ROLES) and (key == f"{'a1' if is_p1 else 'a2'}_{role}")
            dest_dir = os.path.join(char_folder, "emotions", f"slot_{active_em + 1}") if is_em_slot else char_folder
            os.makedirs(dest_dir, exist_ok=True)
            ext = os.path.splitext(file_path)[1].lower()
            save_ext = ext if ext in (".gif", ".webp", ".png") else ".png"
            dest_path = os.path.join(dest_dir, f"{role}{save_ext}")

            # Limpiar versiones anteriores de esta expresión con distinta extensión dentro de la carpeta
            for old_ext in (".png", ".gif", ".webp"):
                old_candidate = os.path.join(dest_dir, f"{role}{old_ext}")
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
            if is_em_slot:
                rel_p = os.path.relpath(dest_path, char_folder).replace("\\", "/")
                for p_key, rt_d in (
                    ("player1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
                    ("player2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
                ):
                    prof_d = self.profiles.get(p_key, {}).get(curr_name)
                    for d_obj in (prof_d, rt_d):
                        if isinstance(d_obj, dict):
                            slots = d_obj.setdefault("emotion_slots", default_emotion_slots())
                            if active_em < len(slots):
                                slots[active_em].setdefault("images", {})[role] = dest_path
                                slots[active_em].setdefault("images_rel", {})[role] = rel_p
                self._rebuild_workshop_sprite_slots(target_dict, "a1" if is_p1 else "a2")
            else:
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
        pref = "a1" if (target_dict is self.p1_data) else "a2"
        role = key.split("_", 1)[1] if key.startswith(f"{pref}_") else ""
        active_em = self._get_active_emotion_idx(target_dict)
        path = None
        if active_em > 0 and role in BASE_POSE_ROLES:
            slot_obj = self._get_emotion_slot_obj(target_dict, active_em)
            if slot_obj:
                path = (slot_obj.get("images") or {}).get(role)
        if not path:
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
            num = getattr(event, "num", None)
            if num == 4:
                step = 5
            elif num == 5:
                step = -5
            else:
                step = 5 if getattr(event, "delta", 0) > 0 else -5
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
        editor_canvas.bind("<Button-4>", on_canvas_wheel)
        editor_canvas.bind("<Button-5>", on_canvas_wheel)
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
    # --- BOCA INDEPENDIENTE CON LIPSYNC (ESTILO HONK) ---
    # =========================================================================
    def _update_mouth_switch_style(self, enabled):
        if hasattr(self, "w_mouth_cfg_btn"):
            if enabled:
                self.w_mouth_cfg_btn.config(
                    text="👄 Boca ✓", bg="#DCFCE7", fg="#166534", activebackground="#BBF7D0"
                )
            else:
                self.w_mouth_cfg_btn.config(
                    text="👄 Boca", bg="#F1F5F9", fg="#334155", activebackground="#E2E8F0"
                )

    def _apply_independent_mouth_to_character(self, char_name, mouth_cfg):
        folder_path = self._get_character_folder(char_name)
        clean_cfg = normalize_independent_mouth(mouth_cfg, folder_path=folder_path)

        for p_key, rt_dict in (
            ("player1", self.p1_data if self.global_config.get("current_p1_profile") == char_name else None),
            ("player2", self.p2_data if self.global_config.get("current_p2_profile") == char_name else None),
        ):
            prof = self.profiles.get(p_key, {}).get(char_name)
            for d in (prof, rt_dict):
                if isinstance(d, dict):
                    d["independent_mouth"] = normalize_independent_mouth(clean_cfg, folder_path=folder_path)

        self._save_character_folder_meta(char_name)
        self.save_profiles_to_disk()

        self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
        self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
        is_p1 = (self.workshop_player == 1)
        target_dict = self.p1_data if is_p1 else self.p2_data
        self.w_live_avatar.set_character(target_dict, prefix="a1" if is_p1 else "a2")
        self._sync_windows_images()

    def _on_workshop_indep_mouth_toggle(self):
        val = bool(self.w_indep_mouth_var.get())
        is_p1 = (self.workshop_player == 1)
        curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
        target_dict = self.p1_data if is_p1 else self.p2_data
        folder_path = self._get_character_folder(curr_name)

        mouth_cfg = normalize_independent_mouth(target_dict.get("independent_mouth"), folder_path=folder_path)
        mouth_cfg["enabled"] = val
        self._update_mouth_switch_style(val)
        self._apply_independent_mouth_to_character(curr_name, mouth_cfg)
        log_debug(f"[TALLER] 👄 Boca independiente para '{curr_name}' -> {val}")

        if val and not has_any_mouth_sprite(mouth_cfg):
            self._open_independent_mouth_dialog()

    def _open_independent_mouth_dialog(self):
        is_p1 = (self.workshop_player == 1)
        curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
        target_dict = self.p1_data if is_p1 else self.p2_data
        prefix = "a1" if is_p1 else "a2"
        folder_path = self._get_character_folder(curr_name)
        flip_x = bool(target_dict.get("flip_x", False))

        mouth_cfg = normalize_independent_mouth(target_dict.get("independent_mouth"), folder_path=folder_path)

        frames_meta = [("idle", "Base / Quieto")]
        if target_dict.get("image_mode") == "4_states":
            frames_meta.append(("idle_blink", "Pestañeo"))
        if target_dict.get(f"{prefix}_scream") and os.path.exists(str(target_dict.get(f"{prefix}_scream", ""))):
            frames_meta.append(("scream", "Grito"))
        for ex in target_dict.get("extra_expressions", []) or []:
            r_id = ex.get("role")
            if r_id and target_dict.get(f"{prefix}_{r_id}"):
                title = ex.get("title", r_id)
                short_t = title.split("(")[0].strip()
                if len(short_t) > 18:
                    short_t = short_t[:16] + "…"
                frames_meta.append((r_id, short_t))

        dlg = tk.Toplevel(self.root)
        dlg.title(f"👄 Estudio de Boca (Estilo Mii) — {curr_name}")
        dlg.geometry("940x670")
        dlg.minsize(840, 600)
        dlg.configure(bg="#DFE5EE")
        dlg.transient(self.root)
        dlg.grab_set()

        main_f = tk.Frame(dlg, bg="#DFE5EE", padx=12, pady=10)
        main_f.pack(fill=tk.BOTH, expand=True)

        # Cabecera
        hdr = tk.Frame(main_f, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", padx=12, pady=8)
        hdr.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            hdr, text=f"👄 Estudio de Boca (Lipsync) — {curr_name}",
            font=("Segoe UI", 11, "bold"), bg="#FFFFFF", fg="#0F172A"
        ).pack(side=tk.LEFT)
        tk.Label(
            hdr, text="Arrastra la boca o usa la cruceta; clic en una tarjeta para probarla",
            font=("Segoe UI", 8), bg="#FFFFFF", fg="#64748B"
        ).pack(side=tk.LEFT, padx=(12, 0))

        body = tk.Frame(main_f, bg="#DFE5EE")
        body.pack(fill=tk.BOTH, expand=True)

        # =====================================================================
        # COLUMNA IZQUIERDA: VISTA PREVIA + CONTROLES MII + PRUEBA DE APERTURA
        # =====================================================================
        left_col = tk.Frame(body, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", padx=12, pady=10)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 8))

        frame_tabs_f = tk.Frame(left_col, bg="#FFFFFF")
        frame_tabs_f.pack(fill=tk.X, pady=(0, 6))
        tk.Label(frame_tabs_f, text="Escena / Pose:", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#0F172A").pack(side=tk.LEFT)
        frame_combo = ttk.Combobox(frame_tabs_f, state="readonly", width=24)
        frame_combo.pack(side=tk.RIGHT)

        prev_size = 310
        preview_canvas = tk.Canvas(
            left_col, width=prev_size, height=prev_size, bg="#F8FBFF",
            highlightthickness=2, highlightbackground="#94A3B8", cursor="fleur"
        )
        preview_canvas.pack(pady=(0, 6))

        ox_var = tk.IntVar(value=mouth_cfg["offset_x"])
        oy_var = tk.IntVar(value=mouth_cfg["offset_y"])
        sc_var = tk.IntVar(value=mouth_cfg["scale"])
        rot_var = tk.IntVar(value=mouth_cfg["rotation"])
        hidden_var = tk.BooleanVar(value=False)
        bounce_var = tk.BooleanVar(value=mouth_cfg.get("follows_bounce", True))
        squash_var = tk.IntVar(value=mouth_cfg.get("squash_strength", 100))

        state = {
            "role": "idle",
            "body_cache": {},
            "thumb_cache": {},
            "mouth_cache": MouthRenderCache(),
            "engine": MouthLipsyncEngine(),
            "drag_active": False,
            "drag_start_xy": (0, 0),
            "drag_orig_off": (0, 0),
            "updating_vars": False,
            "adv_open": False,
            "preview_vowel": None,
        }
        state["mouth_cache"].load_pil_frames(mouth_cfg, flip_x=flip_x)

        def save_and_sync():
            self._apply_independent_mouth_to_character(curr_name, mouth_cfg)
            if hasattr(self, "w_indep_mouth_var"):
                on = bool(mouth_cfg.get("enabled", False))
                self.w_indep_mouth_var.set(on)
                self._update_mouth_switch_style(on)

        def get_body_photo(role_k):
            if role_k in state["body_cache"]:
                return state["body_cache"][role_k]
            path = target_dict.get(f"{prefix}_{role_k}", "")
            if not path or not os.path.exists(str(path)):
                path = target_dict.get(f"{prefix}_idle", "")
            if not path or not os.path.exists(str(path)):
                return None
            try:
                img = Image.open(path).convert("RGBA")
                if flip_x:
                    img = img.transpose(Image.FLIP_LEFT_RIGHT)
                max_dim = prev_size - 16
                ratio = min(max_dim / max(1, img.width), max_dim / max(1, img.height))
                nw = max(1, int(img.width * ratio))
                nh = max(1, int(img.height * ratio))
                ph = ImageTk.PhotoImage(img.resize((nw, nh), Image.Resampling.LANCZOS))
                state["body_cache"][role_k] = ph
                return ph
            except Exception:
                return None

        # Cruceta Mii + Tamaño + Giro
        mii_bar = tk.Frame(left_col, bg="#F1F5F9", padx=8, pady=6, relief="solid", bd=1)
        mii_bar.pack(fill=tk.X, pady=(0, 6))

        dpad_f = tk.Frame(mii_bar, bg="#F1F5F9")
        dpad_f.pack(side=tk.LEFT)

        def nudge_pos(dx, dy):
            eff_dx = -dx if flip_x else dx
            ox_var.set(max(-180, min(180, int(ox_var.get()) + eff_dx)))
            oy_var.set(max(-180, min(180, int(oy_var.get()) + dy)))
            commit_position_change()

        def nudge_scale(ds):
            sc_var.set(max(15, min(250, int(sc_var.get()) + ds)))
            commit_position_change()

        def nudge_rot(dr):
            rot_var.set(max(-45, min(45, int(rot_var.get()) + dr)))
            commit_position_change()

        def center_x():
            ox_var.set(0)
            commit_position_change()

        btn_s = {"font": ("Segoe UI", 8, "bold"), "bg": "#FFFFFF", "fg": "#0F172A", "relief": "solid", "bd": 1, "cursor": "hand2", "width": 3}
        tk.Button(dpad_f, text="▲", command=lambda: nudge_pos(0, -2), **btn_s).grid(row=0, column=1, padx=1, pady=1)
        tk.Button(dpad_f, text="◀", command=lambda: nudge_pos(-2, 0), **btn_s).grid(row=1, column=0, padx=1, pady=1)
        tk.Button(dpad_f, text="⊙", command=center_x, **btn_s).grid(row=1, column=1, padx=1, pady=1)
        tk.Button(dpad_f, text="▶", command=lambda: nudge_pos(2, 0), **btn_s).grid(row=1, column=2, padx=1, pady=1)
        tk.Button(dpad_f, text="▼", command=lambda: nudge_pos(0, 2), **btn_s).grid(row=2, column=1, padx=1, pady=1)

        sr_f = tk.Frame(mii_bar, bg="#F1F5F9")
        sr_f.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

        sz_row = tk.Frame(sr_f, bg="#F1F5F9")
        sz_row.pack(fill=tk.X, pady=(2, 6))
        tk.Label(sz_row, text="Tamaño:", font=("Segoe UI", 8, "bold"), bg="#F1F5F9", fg="#334155", width=7, anchor="w").pack(side=tk.LEFT)
        tk.Button(sz_row, text="➖", command=lambda: nudge_scale(-5), **btn_s).pack(side=tk.LEFT, padx=2)
        size_val_lbl = tk.Label(sz_row, text=f"{sc_var.get()}%", font=("Segoe UI", 8, "bold"), bg="#F1F5F9", fg="#0369A1", width=5)
        size_val_lbl.pack(side=tk.LEFT)
        tk.Button(sz_row, text="➕", command=lambda: nudge_scale(5), **btn_s).pack(side=tk.LEFT, padx=2)

        rt_row = tk.Frame(sr_f, bg="#F1F5F9")
        rt_row.pack(fill=tk.X, pady=(0, 2))
        tk.Label(rt_row, text="Girar:", font=("Segoe UI", 8, "bold"), bg="#F1F5F9", fg="#334155", width=7, anchor="w").pack(side=tk.LEFT)
        tk.Button(rt_row, text="↺", command=lambda: nudge_rot(-5), **btn_s).pack(side=tk.LEFT, padx=2)
        rot_val_lbl = tk.Label(rt_row, text=f"{rot_var.get()}°", font=("Segoe UI", 8, "bold"), bg="#F1F5F9", fg="#0369A1", width=5)
        rot_val_lbl.pack(side=tk.LEFT)
        tk.Button(rt_row, text="↻", command=lambda: nudge_rot(5), **btn_s).pack(side=tk.LEFT, padx=2)
        tk.Button(rt_row, text="0°", font=("Segoe UI", 7, "bold"), bg="#E2E8F0", fg="#334155", relief="solid", bd=1, cursor="hand2", padx=4, command=lambda: (rot_var.set(0), commit_position_change())).pack(side=tk.LEFT, padx=(4, 0))

        # Barra de prueba de lipsync en vivo
        test_f = tk.Frame(left_col, bg="#F1F5F9", padx=8, pady=5, relief="solid", bd=1)
        test_f.pack(fill=tk.X)
        test_hdr = tk.Frame(test_f, bg="#F1F5F9")
        test_hdr.pack(fill=tk.X)
        tk.Label(test_hdr, text="🎚️ Probar apertura (Lipsync):", font=("Segoe UI", 8, "bold"), bg="#F1F5F9", fg="#0F172A").pack(side=tk.LEFT)
        test_slot_lbl = tk.Label(test_hdr, text="Cerrada", font=("Segoe UI", 8, "bold"), bg="#F1F5F9", fg="#3671C6")
        test_slot_lbl.pack(side=tk.RIGHT)
        test_lvl_var = tk.DoubleVar(value=0.0)
        test_scale = ttk.Scale(test_f, from_=0.0, to=100.0, variable=test_lvl_var)
        test_scale.pack(fill=tk.X, pady=(2, 0))

        # =====================================================================
        # COLUMNA DERECHA: MODO EN ESCENA + 4 TARJETAS EN FILA + AVANZADO
        # =====================================================================
        right_scroll = ScrollableFrame(body, bg="#FFFFFF")
        right_scroll.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        rc = right_scroll.content

        # --- SECCIÓN 1: MODO EN ESTA ESCENA (SIN CHECKBOX PREVIO) ---
        mode_box = tk.LabelFrame(
            rc, text=" 1. Boca en esta escena ",
            font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#0F172A", padx=10, pady=8
        )
        mode_box.pack(fill=tk.X, padx=8, pady=(6, 8))

        scene_info_lbl = tk.Label(
            mode_box, text="Escena actual: Base / Quieto",
            font=("Segoe UI", 8, "bold"), bg="#E0F2FE", fg="#0369A1", padx=6, pady=2, anchor="w"
        )
        scene_info_lbl.pack(fill=tk.X, pady=(0, 6))

        mode_cards_f = tk.Frame(mode_box, bg="#FFFFFF")
        mode_cards_f.pack(fill=tk.X)

        def set_mouth_scene_mode(use_modular):
            r = state["role"]
            if r == "idle":
                mouth_cfg["enabled"] = bool(use_modular)
            else:
                if use_modular:
                    mouth_cfg["enabled"] = True
                ov = mouth_cfg.setdefault("frame_overrides", {})
                cur = ov.get(r, {"offset_x": mouth_cfg["offset_x"], "offset_y": mouth_cfg["offset_y"], "scale": mouth_cfg["scale"], "rotation": mouth_cfg["rotation"]})
                cur["hidden"] = not bool(use_modular)
                ov[r] = cur
                hidden_var.set(not bool(use_modular))
            refresh_mode_cards()
            refresh_tab_styles()
            render_preview()
            save_and_sync()

        def refresh_mode_cards():
            for w in mode_cards_f.winfo_children():
                w.destroy()
            r = state["role"]
            if r == "idle":
                is_mod = bool(mouth_cfg.get("enabled", False))
            else:
                hid, *_ = resolve_mouth_frame_config(mouth_cfg, r)
                is_mod = bool(mouth_cfg.get("enabled", False)) and (not hid)

            for mod_val, ico_t, title_t in ((False, "🚫", "Dibujo del PNG"), (True, "👄", "Boca Animada (Lipsync)")):
                is_sel = (is_mod == mod_val)
                c = tk.Frame(
                    mode_cards_f,
                    bg="#DBEAFE" if is_sel else "#F8FAFC",
                    highlightthickness=2 if is_sel else 1,
                    highlightbackground="#2563EB" if is_sel else "#CBD5E1",
                    padx=10, pady=6, cursor="hand2"
                )
                c.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=3)
                l1 = tk.Label(c, text=f"{ico_t} {title_t}", font=("Segoe UI", 8, "bold"), bg=c["bg"], fg="#1E3A8A" if is_sel else "#334155")
                l1.pack()
                for w in (c, l1):
                    w.bind("<Button-1>", lambda _e, m=mod_val: set_mouth_scene_mode(m))

        # --- SECCIÓN 2: LAS 4 BOCAS EN FILA HORIZONTAL (TARJETAS VISUALES) ---
        slots_box = tk.LabelFrame(
            rc, text=" 2. Formas de Boca (Clic para previsualizar o cargar) ",
            font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#0F172A", padx=10, pady=8
        )
        slots_box.pack(fill=tk.X, padx=8, pady=(0, 8))

        ls_mode_f = tk.Frame(slots_box, bg="#FFFFFF")
        ls_mode_f.pack(fill=tk.X, pady=(0, 6))
        tk.Label(ls_mode_f, text="Modo Lipsync:", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#334155").pack(side=tk.LEFT, padx=(0, 6))
        ls_mode_btns = {}

        def set_lipsync_mode(m_val):
            mouth_cfg["mode"] = m_val
            state["preview_vowel"] = None
            refresh_ls_mode_btns()
            refresh_slot_cards()
            render_preview()
            save_and_sync()

        def refresh_ls_mode_btns():
            cur_m = mouth_cfg.get("mode", "volume")
            for mk, mb in ls_mode_btns.items():
                if mk == cur_m:
                    mb.config(bg="#0284C7", fg="#FFFFFF", activebackground="#0369A1", activeforeground="#FFFFFF")
                else:
                    mb.config(bg="#F1F5F9", fg="#334155", activebackground="#E2E8F0", activeforeground="#0F172A")

        for mk, mlbl in (("volume", "🔊 Modo A: Volumen"), ("vowels", "🗣️ Modo B: Vocales FFT (A/E/I/O/U)")):
            b = tk.Button(
                ls_mode_f, text=mlbl, font=("Segoe UI", 8, "bold"),
                relief="solid", bd=1, padx=8, pady=2, cursor="hand2",
                command=lambda k=mk: set_lipsync_mode(k)
            )
            b.pack(side=tk.LEFT, padx=(0, 4))
            ls_mode_btns[mk] = b

        slots_grid = tk.Frame(slots_box, bg="#FFFFFF")
        slots_grid.pack(fill=tk.X)

        vowels_hdr = tk.Label(
            slots_box, text="Vocales Modo B (opcional: si falta alguna, usa tus 4 bocas base):",
            font=("Segoe UI", 7, "bold"), bg="#FFFFFF", fg="#0369A1", anchor="w"
        )
        vowels_grid = tk.Frame(slots_box, bg="#FFFFFF")

        slot_test_levels = {
            "closed": 0.0, "half": 35.0, "open": 65.0, "wide": 95.0,
            "vowel_a": 65.0, "vowel_e": 55.0, "vowel_i": 50.0, "vowel_o": 75.0, "vowel_u": 45.0,
        }

        def pick_mouth_sprite(slot_k):
            fp = filedialog.askopenfilename(
                parent=dlg,
                title=f"Seleccionar boca: {MOUTH_SLOT_LABELS[slot_k]}",
                filetypes=[("Imágenes", "*.png *.gif *.webp"), ("Todos", "*.*")]
            )
            if not fp:
                return
            mouths_dir = os.path.join(folder_path, "mouths")
            os.makedirs(mouths_dir, exist_ok=True)
            ext = os.path.splitext(fp)[1].lower()
            if ext not in (".png", ".gif", ".webp"):
                ext = ".png"
            dest = os.path.join(mouths_dir, f"{slot_k}{ext}")
            try:
                if os.path.abspath(fp) != os.path.abspath(dest):
                    shutil.copy2(fp, dest)
                mouth_cfg.setdefault("sprites", {})[slot_k] = dest
                mouth_cfg.setdefault("sprites_rel", {})[slot_k] = f"mouths/{slot_k}{ext}"
                mouth_cfg["enabled"] = True
                state["thumb_cache"].pop(slot_k, None)
                state["mouth_cache"].load_pil_frames(mouth_cfg, flip_x=flip_x)
                test_lvl_var.set(slot_test_levels.get(slot_k, 0.0))
                refresh_mode_cards()
                refresh_slot_cards()
                render_preview()
                save_and_sync()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo copiar la imagen:\n{e}", parent=dlg)

        def clear_mouth_sprite(slot_k):
            mouth_cfg.setdefault("sprites", {})[slot_k] = ""
            mouth_cfg.setdefault("sprites_rel", {})[slot_k] = ""
            state["thumb_cache"].pop(slot_k, None)
            state["mouth_cache"].load_pil_frames(mouth_cfg, flip_x=flip_x)
            refresh_slot_cards()
            render_preview()
            save_and_sync()

        def preview_slot(slot_k):
            p = (mouth_cfg.get("sprites") or {}).get(slot_k, "")
            if not p or not os.path.exists(str(p)):
                pick_mouth_sprite(slot_k)
                return
            mouth_cfg["enabled"] = True
            state["preview_vowel"] = slot_k if slot_k in VOWEL_SLOTS else None
            test_lvl_var.set(slot_test_levels.get(slot_k, 0.0))
            refresh_mode_cards()
            render_preview()
            save_and_sync()

        def render_cards_into(grid_parent, slot_list):
            for w in grid_parent.winfo_children():
                w.destroy()
            for col_i, s in enumerate(slot_list):
                p = (mouth_cfg.get("sprites") or {}).get(s, "")
                has_img = bool(p and os.path.exists(str(p)))
                card = tk.Frame(
                    grid_parent,
                    bg="#F8FAFC" if has_img else "#F1F5F9",
                    highlightthickness=1,
                    highlightbackground="#94A3B8" if has_img else "#CBD5E1",
                    padx=5, pady=5
                )
                card.grid(row=0, column=col_i, padx=2, pady=2, sticky="nsew")

                lbl_name = MOUTH_SLOT_LABELS[s].split("(")[0].strip()
                t_lbl = tk.Label(card, text=lbl_name, font=("Segoe UI", 8, "bold"), bg=card["bg"], fg="#0F172A", cursor="hand2")
                t_lbl.pack()

                if has_img:
                    th = state["thumb_cache"].get(s)
                    if th is None:
                        try:
                            im = Image.open(p).convert("RGBA")
                            im.thumbnail((42, 42), Image.Resampling.LANCZOS)
                            th = ImageTk.PhotoImage(im)
                            state["thumb_cache"][s] = th
                        except Exception:
                            th = None
                    if th is not None:
                        ico = tk.Label(card, image=th, bg=card["bg"], width=44, height=44, cursor="hand2")
                        ico._th = th
                        ico.pack(pady=3)
                    else:
                        ico = tk.Label(card, text="👄", font=("Segoe UI", 14), bg=card["bg"], cursor="hand2")
                        ico.pack(pady=3)
                else:
                    ico = tk.Label(card, text="➕", font=("Segoe UI", 14), bg=card["bg"], fg="#64748B", width=4, height=2, cursor="hand2")
                    ico.pack(pady=3)

                for w in (card, t_lbl, ico):
                    w.bind("<Button-1>", lambda _e, sk=s: preview_slot(sk))

                b_row = tk.Frame(card, bg=card["bg"])
                b_row.pack(fill=tk.X, pady=(2, 0))
                tk.Button(
                    b_row, text="📂", font=("Segoe UI", 7), bg="#E0F2FE", fg="#0369A1",
                    relief="solid", bd=1, padx=4, cursor="hand2",
                    command=lambda sk=s: pick_mouth_sprite(sk)
                ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
                tk.Button(
                    b_row, text="✕", font=("Segoe UI", 7), bg="#FEE2E2", fg="#B91C1C",
                    relief="solid", bd=1, padx=4, cursor="hand2",
                    command=lambda sk=s: clear_mouth_sprite(sk)
                ).pack(side=tk.RIGHT)

            for c in range(len(slot_list)):
                grid_parent.columnconfigure(c, weight=1)

        def refresh_slot_cards():
            refresh_ls_mode_btns()
            render_cards_into(slots_grid, MOUTH_SLOTS)
            if mouth_cfg.get("mode", "volume") == "vowels":
                vowels_hdr.pack(fill=tk.X, pady=(6, 2), before=el_f)
                vowels_grid.pack(fill=tk.X, before=el_f)
                render_cards_into(vowels_grid, VOWEL_SLOTS)
            else:
                vowels_hdr.pack_forget()
                vowels_grid.pack_forget()

        # Presets rápidos de elasticidad
        el_f = tk.Frame(slots_box, bg="#FFFFFF")
        el_f.pack(fill=tk.X, pady=(8, 0))
        tk.Label(el_f, text="Elasticidad:", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#334155").pack(side=tk.LEFT, padx=(0, 6))

        def apply_squash_preset(val):
            squash_var.set(val)
            mouth_cfg["squash_strength"] = val
            save_and_sync()

        for lbl, val in (("Rígida", 0), ("Normal", 100), ("Elástica", 160)):
            tk.Button(
                el_f, text=lbl, font=("Segoe UI", 8, "bold"),
                bg="#F1F5F9", fg="#0F172A", relief="solid", bd=1, padx=8, pady=1, cursor="hand2",
                command=lambda v=val: apply_squash_preset(v)
            ).pack(side=tk.LEFT, padx=2)

        # --- SECCIÓN 3: ACORDEÓN AVANZADO ---
        adv_hdr = tk.Frame(rc, bg="#FFFFFF")
        adv_hdr.pack(fill=tk.X, padx=8, pady=(0, 4))
        adv_box = tk.LabelFrame(rc, text=" Ajustes finos y físicas ", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#475569", padx=10, pady=8)

        def toggle_adv():
            state["adv_open"] = not state["adv_open"]
            if state["adv_open"]:
                adv_btn.config(text="▼ Ocultar Avanzado (Físicas y Opciones)")
                adv_box.pack(fill=tk.X, padx=8, pady=(0, 8))
            else:
                adv_btn.config(text="▶ Avanzado (Físicas y Opciones)")
                adv_box.pack_forget()

        adv_btn = tk.Button(
            adv_hdr, text="▶ Avanzado (Físicas y Opciones)", font=("Segoe UI", 8, "bold"),
            bg="#F1F5F9", fg="#475569", relief="solid", bd=1, padx=8, pady=3, cursor="hand2",
            anchor="w", command=toggle_adv
        )
        adv_btn.pack(fill=tk.X)

        def commit_position_change(*_args):
            if state["updating_vars"]:
                return
            rk = state["role"]
            ox = int(ox_var.get())
            oy = int(oy_var.get())
            sc = int(sc_var.get())
            rot = int(rot_var.get())
            size_val_lbl.config(text=f"{sc}%")
            rot_val_lbl.config(text=f"{rot}°")
            if rk == "idle":
                mouth_cfg["offset_x"] = ox
                mouth_cfg["offset_y"] = oy
                mouth_cfg["scale"] = sc
                mouth_cfg["rotation"] = rot
            else:
                mouth_cfg.setdefault("frame_overrides", {})[rk] = {
                    "offset_x": ox,
                    "offset_y": oy,
                    "scale": sc,
                    "rotation": rot,
                    "hidden": bool(hidden_var.get()),
                }
            refresh_tab_styles()
            render_preview()
            save_and_sync()

        def make_slider_row(parent, label, var, from_v, to_v):
            row = tk.Frame(parent, bg="#FFFFFF")
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label, width=14, anchor=tk.W, font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#334155").pack(side=tk.LEFT)
            val_lbl = tk.Label(row, text=str(var.get()), width=5, anchor=tk.E, font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#3671C6")
            val_lbl.pack(side=tk.RIGHT)
            sc = ttk.Scale(
                row, from_=from_v, to=to_v, variable=var,
                command=lambda v: (var.set(int(round(float(v)))), val_lbl.config(text=str(var.get())), commit_position_change())
            )
            sc.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
            var.trace_add("write", lambda *_: val_lbl.config(text=str(var.get())))

        make_slider_row(adv_box, "Posición X:", ox_var, -180, 180)
        make_slider_row(adv_box, "Posición Y:", oy_var, -180, 180)
        make_slider_row(adv_box, "Escala (%):", sc_var, 15, 250)
        make_slider_row(adv_box, "Rotación (°):", rot_var, -45, 45)

        sq_row = tk.Frame(adv_box, bg="#FFFFFF")
        sq_row.pack(fill=tk.X, pady=2)
        tk.Label(sq_row, text="Squash Honk:", width=14, anchor=tk.W, font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#334155").pack(side=tk.LEFT)
        sq_lbl = tk.Label(sq_row, text=f"{squash_var.get()}%", width=5, anchor=tk.E, font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#3671C6")
        sq_lbl.pack(side=tk.RIGHT)
        ttk.Scale(
            sq_row, from_=0, to=200, variable=squash_var,
            command=lambda v: (
                squash_var.set(int(round(float(v)))),
                sq_lbl.config(text=f"{squash_var.get()}%"),
                mouth_cfg.__setitem__("squash_strength", int(squash_var.get())),
                save_and_sync(),
            )
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        tk.Checkbutton(
            adv_box, text="Seguir rebote / sacudida del cuerpo",
            variable=bounce_var,
            command=lambda: (mouth_cfg.__setitem__("follows_bounce", bool(bounce_var.get())), save_and_sync()),
            bg="#FFFFFF", fg="#1E293B", selectcolor="#FFFFFF", font=("Segoe UI", 8, "bold"), cursor="hand2"
        ).pack(anchor=tk.W, pady=(4, 2))

        def reset_current_override():
            rk = state["role"]
            if rk == "idle":
                mouth_cfg["offset_x"] = 0
                mouth_cfg["offset_y"] = 0
                mouth_cfg["scale"] = 100
                mouth_cfg["rotation"] = 0
            else:
                (mouth_cfg.get("frame_overrides") or {}).pop(rk, None)
            load_controls_for_role(rk)
            save_and_sync()

        tk.Button(
            adv_box, text="⟲ Restablecer posición de esta escena", font=("Segoe UI", 8),
            bg="#F1F5F9", fg="#334155", relief="solid", bd=1, padx=8, pady=2, cursor="hand2",
            command=reset_current_override
        ).pack(anchor=tk.E, pady=(4, 0))

        # =====================================================================
        # RENDERIZADO Y SINCRONIZACIÓN
        # =====================================================================
        def render_preview():
            preview_canvas.delete("all")
            cx, cy = prev_size // 2, prev_size // 2
            pos_scale = max(20, prev_size - 16) / 384.0

            b_ph = get_body_photo(state["role"])
            if b_ph is not None:
                preview_canvas.create_image(cx, cy, anchor=tk.CENTER, image=b_ph)
                preview_canvas._b_ph = b_ph

            hidden, ox, oy, sc_pct, rot_deg, ov_key = resolve_mouth_frame_config(mouth_cfg, state["role"])
            if state["role"] == "idle" and not mouth_cfg.get("enabled", False):
                hidden = True

            if hidden:
                preview_canvas.create_text(
                    cx, prev_size - 14, text="🚫 Usando boca dibujada en el PNG",
                    font=("Segoe UI", 8, "bold"), fill="#64748B"
                )
                return

            if ox == 0:
                preview_canvas.create_line(cx, 8, cx, prev_size - 8, fill="#38BDF8", dash=(4, 4), width=1)

            lvl = float(test_lvl_var.get())
            avail = state["mouth_cache"].pil_frames.keys()
            slot, sq_idx = state["engine"].update(
                lvl, 15.0, lvl >= 15.0, lvl >= 85.0, False, avail,
                squash_strength=mouth_cfg.get("squash_strength", 100),
                mode=mouth_cfg.get("mode", "volume"),
                vowel_hint=state.get("preview_vowel"),
            )
            test_slot_lbl.config(text=MOUTH_SLOT_LABELS.get(slot, slot))

            eff_rot = -rot_deg if flip_x else rot_deg
            m_ph = state["mouth_cache"].get_photo(slot, ov_key, 0, sq_idx, pos_scale, sc_pct, eff_rot)
            if m_ph is not None:
                eff_ox = -ox if flip_x else ox
                mx = cx + int(eff_ox * pos_scale)
                my = cy + int(oy * pos_scale)
                preview_canvas.create_image(mx, my, anchor=tk.CENTER, image=m_ph)
                preview_canvas._m_ph = m_ph
            else:
                preview_canvas.create_text(
                    cx, cy, text="Elige una boca en las tarjetas\n(ej. Cerrada y Abierta)",
                    font=("Segoe UI", 9, "bold"), fill="#64748B", justify=tk.CENTER
                )

        def refresh_tab_styles():
            ovs = mouth_cfg.get("frame_overrides") or {}
            combo_vals = []
            sel_idx = 0
            for idx_f, (r_k, base_lbl) in enumerate(frames_meta):
                if r_k != "idle" and r_k in ovs:
                    prefix_ico = "🚫 " if ovs[r_k].get("hidden") else "• "
                else:
                    prefix_ico = ""
                combo_vals.append(f"{prefix_ico}{base_lbl}")
                if state["role"] == r_k:
                    sel_idx = idx_f
            frame_combo["values"] = combo_vals
            if combo_vals:
                frame_combo.current(sel_idx)

        def load_controls_for_role(role_k):
            state["role"] = role_k
            label_txt = dict(frames_meta).get(role_k, role_k)
            scene_info_lbl.config(text=f"Escena actual: {label_txt}")
            state["updating_vars"] = True
            hidden, ox, oy, sc_pct, rot_deg, _ = resolve_mouth_frame_config(mouth_cfg, role_k)
            ox_var.set(ox)
            oy_var.set(oy)
            sc_var.set(sc_pct)
            rot_var.set(rot_deg)
            hidden_var.set(hidden)
            size_val_lbl.config(text=f"{sc_pct}%")
            rot_val_lbl.config(text=f"{rot_deg}°")
            state["updating_vars"] = False
            refresh_mode_cards()
            refresh_tab_styles()
            render_preview()

        def on_frame_combo_selected(_event=None):
            idx_f = frame_combo.current()
            if 0 <= idx_f < len(frames_meta):
                load_controls_for_role(frames_meta[idx_f][0])

        frame_combo.bind("<<ComboboxSelected>>", on_frame_combo_selected)

        def on_canvas_down(event):
            state["drag_active"] = True
            state["drag_start_xy"] = (event.x, event.y)
            state["drag_orig_off"] = (ox_var.get(), oy_var.get())

        def on_canvas_move(event):
            if not state["drag_active"]:
                return
            pos_scale = max(20, prev_size - 16) / 384.0
            dx_px = event.x - state["drag_start_xy"][0]
            dy_px = event.y - state["drag_start_xy"][1]
            dx_off = int(round(dx_px / max(0.1, pos_scale)))
            if flip_x:
                dx_off = -dx_off
            dy_off = int(round(dy_px / max(0.1, pos_scale)))
            new_ox = max(-180, min(180, state["drag_orig_off"][0] + dx_off))
            if abs(new_ox) <= 3:
                new_ox = 0
            state["updating_vars"] = True
            ox_var.set(new_ox)
            oy_var.set(max(-180, min(180, state["drag_orig_off"][1] + dy_off)))
            state["updating_vars"] = False
            commit_position_change()

        def on_canvas_up(_event):
            state["drag_active"] = False

        def on_canvas_wheel(event):
            num = getattr(event, "num", None)
            step = 5 if (num == 4 or getattr(event, "delta", 0) > 0) else -5
            new_sc = max(15, min(250, int(sc_var.get()) + step))
            if new_sc != sc_var.get():
                state["updating_vars"] = True
                sc_var.set(new_sc)
                state["updating_vars"] = False
                commit_position_change()

        preview_canvas.bind("<ButtonPress-1>", on_canvas_down)
        preview_canvas.bind("<B1-Motion>", on_canvas_move)
        preview_canvas.bind("<ButtonRelease-1>", on_canvas_up)
        preview_canvas.bind("<MouseWheel>", on_canvas_wheel)
        preview_canvas.bind("<Button-4>", on_canvas_wheel)
        preview_canvas.bind("<Button-5>", on_canvas_wheel)
        test_scale.configure(command=lambda _v: render_preview())

        tk.Button(
            main_f, text="✅ Listo", font=("Segoe UI", 9, "bold"),
            bg="#16A34A", fg="#FFFFFF", activebackground="#15803D", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=16, pady=5, cursor="hand2",
            command=dlg.destroy
        ).pack(side=tk.BOTTOM, anchor=tk.E, pady=(8, 0))

        refresh_slot_cards()
        load_controls_for_role("idle")

    # =========================================================================
    # --- CONFIGURACIÓN DE OJOS QUE SIGUEN AL MOUSE (ESTILO HONK) ---
    # =========================================================================
    def _update_eyes_switch_style(self, enabled):
        if hasattr(self, "w_eyes_cfg_btn"):
            if enabled:
                self.w_eyes_cfg_btn.config(
                    text="👀 Ojos ✓", bg="#DCFCE7", fg="#166534", activebackground="#BBF7D0"
                )
            else:
                self.w_eyes_cfg_btn.config(
                    text="👀 Ojos", bg="#F1F5F9", fg="#334155", activebackground="#E2E8F0"
                )

    def _apply_independent_eyes_to_character(self, char_name, eyes_cfg):
        folder_path = self._get_character_folder(char_name)
        clean_cfg = normalize_independent_eyes(eyes_cfg, folder_path=folder_path)

        for p_key, rt_dict in (
            ("player1", self.p1_data if self.global_config.get("current_p1_profile") == char_name else None),
            ("player2", self.p2_data if self.global_config.get("current_p2_profile") == char_name else None),
        ):
            prof = self.profiles.get(p_key, {}).get(char_name)
            for d in (prof, rt_dict):
                if isinstance(d, dict):
                    d["independent_eyes"] = normalize_independent_eyes(clean_cfg, folder_path=folder_path)

        self._save_character_folder_meta(char_name)
        self.save_profiles_to_disk()

        self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
        self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
        is_p1 = (self.workshop_player == 1)
        target_dict = self.p1_data if is_p1 else self.p2_data
        self.w_live_avatar.set_character(target_dict, prefix="a1" if is_p1 else "a2")
        self._sync_windows_images()

    def _on_workshop_indep_eyes_toggle(self):
        val = bool(self.w_indep_eyes_var.get())
        is_p1 = (self.workshop_player == 1)
        curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
        target_dict = self.p1_data if is_p1 else self.p2_data
        folder_path = self._get_character_folder(curr_name)

        eyes_cfg = normalize_independent_eyes(target_dict.get("independent_eyes"), folder_path=folder_path)
        eyes_cfg["enabled"] = val
        self._update_eyes_switch_style(val)
        self._apply_independent_eyes_to_character(curr_name, eyes_cfg)
        log_debug(f"[TALLER] 👀 Ojos al mouse para '{curr_name}' -> {val}")

        if val and not has_eyes_sprite(eyes_cfg):
            self._open_independent_eyes_dialog()

    def _open_independent_eyes_dialog(self):
        is_p1 = (self.workshop_player == 1)
        curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
        target_dict = self.p1_data if is_p1 else self.p2_data
        prefix = "a1" if is_p1 else "a2"
        folder_path = self._get_character_folder(curr_name)
        flip_x = bool(target_dict.get("flip_x", False))

        eyes_cfg = normalize_independent_eyes(target_dict.get("independent_eyes"), folder_path=folder_path)
        if not eyes_cfg.get("eye_sets"):
            eyes_cfg["eye_sets"] = {"default": default_eye_set("Normal")}
            eyes_cfg["active_set"] = "default"

        dlg = tk.Toplevel(self.root)
        dlg.title(f"👀 Estudio de Ojos (Estilo Mii) — {curr_name}")
        dlg.geometry("960x690")
        dlg.minsize(860, 620)
        dlg.configure(bg="#DFE5EE")
        dlg.transient(self.root)
        dlg.grab_set()

        main_f = tk.Frame(dlg, bg="#DFE5EE", padx=12, pady=10)
        main_f.pack(fill=tk.BOTH, expand=True)

        # Cabecera limpia
        hdr = tk.Frame(main_f, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", padx=12, pady=8)
        hdr.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            hdr, text=f"👀 Estudio de Ojos — {curr_name}",
            font=("Segoe UI", 11, "bold"), bg="#FFFFFF", fg="#0F172A"
        ).pack(side=tk.LEFT)
        tk.Label(
            hdr, text="Elige qué set usa cada escena con 1 clic, o arma tus sets aparte",
            font=("Segoe UI", 8), bg="#FFFFFF", fg="#64748B"
        ).pack(side=tk.LEFT, padx=(12, 0))

        body = tk.Frame(main_f, bg="#DFE5EE")
        body.pack(fill=tk.BOTH, expand=True)

        # =====================================================================
        # COLUMNA IZQUIERDA: VISTA PREVIA + CONTROLES MII (CRUCETA / ± / GIRO)
        # =====================================================================
        left_col = tk.Frame(body, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", padx=12, pady=10)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 8))

        pose_row = tk.Frame(left_col, bg="#FFFFFF")
        pose_row.pack(fill=tk.X, pady=(0, 6))
        tk.Label(pose_row, text="Escena / Pose:", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#0F172A").pack(side=tk.LEFT)

        pose_choices = [
            ("idle", "Base / Quieto"),
            ("talk", "Hablando"),
            ("idle_blink", "Pestañeo"),
            ("talk_blink", "Hablando + Pestañeo"),
            ("scream", "Grito"),
        ]
        for ex in (target_dict.get("extra_expressions") or []):
            r_id = ex.get("role")
            if r_id:
                pose_choices.append((r_id, ex.get("title", ex.get("name", r_id)).split("(")[0].strip()))

        label_to_role = {lbl: r for r, lbl in pose_choices}
        role_to_label = {r: lbl for r, lbl in pose_choices}
        pose_var = tk.StringVar(value=role_to_label.get("idle", "Base / Quieto"))
        pose_combo = ttk.Combobox(pose_row, textvariable=pose_var, values=[lbl for _, lbl in pose_choices], state="readonly", width=24)
        pose_combo.pack(side=tk.RIGHT)

        prev_size = 320
        preview_canvas = tk.Canvas(
            left_col, width=prev_size, height=prev_size, bg="#F8FBFF",
            highlightthickness=2, highlightbackground="#94A3B8", cursor="fleur"
        )
        preview_canvas.pack(pady=(0, 6))

        live_test_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            left_col, text="🎯 Probar seguimiento con mi mouse (arrastra para mover, rueda = tamaño)",
            variable=live_test_var, bg="#FFFFFF", fg="#0369A1",
            font=("Segoe UI", 8, "bold"), cursor="hand2"
        ).pack(anchor=tk.W, pady=(0, 6))

        # Cruceta Mii + Tamaño + Giro
        mii_bar = tk.Frame(left_col, bg="#F1F5F9", padx=8, pady=6, relief="solid", bd=1)
        mii_bar.pack(fill=tk.X)

        dpad_f = tk.Frame(mii_bar, bg="#F1F5F9")
        dpad_f.pack(side=tk.LEFT)

        ox_var = tk.IntVar(value=int(eyes_cfg.get("offset_x", 0)))
        oy_var = tk.IntVar(value=int(eyes_cfg.get("offset_y", 0)))
        sc_var = tk.IntVar(value=int(eyes_cfg.get("scale", 100)))
        rot_var = tk.IntVar(value=int(eyes_cfg.get("rotation", 0)))

        # Variables del set actualmente en edición
        active_sid = str(eyes_cfg.get("active_set") or "default")
        if active_sid not in eyes_cfg["eye_sets"]:
            active_sid = next(iter(eyes_cfg["eye_sets"]))

        state = {
            "role": "idle",
            "editing_set": active_sid,
            "updating_vars": False,
            "sync_job": None,
            "drag_active": False,
            "drag_start_xy": (0, 0),
            "drag_orig_off": (0, 0),
            "pil_cache": {},
            "thumb_cache": {},
            "eyes_cache": EyesRenderCache(),
            "eye_ox": 0.0,
            "eye_oy": 0.0,
            "adv_open": False,
        }

        def load_eyes_pil():
            state["eyes_cache"].load_pil_frame(eyes_cfg, flip_x=flip_x)

        def get_avatar_pil(role):
            if role in state["pil_cache"]:
                return state["pil_cache"][role]
            path = target_dict.get(f"{prefix}_{role}") or target_dict.get(f"{prefix}_idle")
            if path and os.path.exists(str(path)):
                try:
                    im = Image.open(path).convert("RGBA")
                    if flip_x:
                        im = im.transpose(Image.FLIP_LEFT_RIGHT)
                    state["pil_cache"][role] = im
                    return im
                except Exception:
                    pass
            state["pil_cache"][role] = None
            return None

        def commit_and_sync(immediate=False):
            if state["sync_job"]:
                try:
                    dlg.after_cancel(state["sync_job"])
                except Exception:
                    pass
                state["sync_job"] = None
            if immediate:
                self._apply_independent_eyes_to_character(curr_name, eyes_cfg)
                if hasattr(self, "w_indep_eyes_var"):
                    on = bool(eyes_cfg.get("enabled", False))
                    self.w_indep_eyes_var.set(on)
                    self._update_eyes_switch_style(on)
            else:
                def _do():
                    self._apply_independent_eyes_to_character(curr_name, eyes_cfg)
                    if hasattr(self, "w_indep_eyes_var"):
                        on = bool(eyes_cfg.get("enabled", False))
                        self.w_indep_eyes_var.set(on)
                        self._update_eyes_switch_style(on)
                state["sync_job"] = dlg.after(160, _do)

        def nudge_pos(dx, dy):
            eff_dx = -dx if flip_x else dx
            ox_var.set(max(-180, min(180, int(ox_var.get()) + eff_dx)))
            oy_var.set(max(-180, min(180, int(oy_var.get()) + dy)))
            commit_position_change()

        def nudge_scale(ds):
            sc_var.set(max(10, min(280, int(sc_var.get()) + ds)))
            commit_position_change()

        def nudge_rot(dr):
            rot_var.set(max(-180, min(180, int(rot_var.get()) + dr)))
            commit_position_change()

        def center_x():
            ox_var.set(0)
            commit_position_change()

        btn_s = {"font": ("Segoe UI", 8, "bold"), "bg": "#FFFFFF", "fg": "#0F172A", "relief": "solid", "bd": 1, "cursor": "hand2", "width": 3}
        tk.Button(dpad_f, text="▲", command=lambda: nudge_pos(0, -2), **btn_s).grid(row=0, column=1, padx=1, pady=1)
        tk.Button(dpad_f, text="◀", command=lambda: nudge_pos(-2, 0), **btn_s).grid(row=1, column=0, padx=1, pady=1)
        tk.Button(dpad_f, text="⊙", command=center_x, **btn_s).grid(row=1, column=1, padx=1, pady=1)
        tk.Button(dpad_f, text="▶", command=lambda: nudge_pos(2, 0), **btn_s).grid(row=1, column=2, padx=1, pady=1)
        tk.Button(dpad_f, text="▼", command=lambda: nudge_pos(0, 2), **btn_s).grid(row=2, column=1, padx=1, pady=1)

        sr_f = tk.Frame(mii_bar, bg="#F1F5F9")
        sr_f.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

        sz_row = tk.Frame(sr_f, bg="#F1F5F9")
        sz_row.pack(fill=tk.X, pady=(2, 6))
        tk.Label(sz_row, text="Tamaño:", font=("Segoe UI", 8, "bold"), bg="#F1F5F9", fg="#334155", width=7, anchor="w").pack(side=tk.LEFT)
        tk.Button(sz_row, text="➖", command=lambda: nudge_scale(-5), **btn_s).pack(side=tk.LEFT, padx=2)
        size_val_lbl = tk.Label(sz_row, text="100%", font=("Segoe UI", 8, "bold"), bg="#F1F5F9", fg="#0369A1", width=5)
        size_val_lbl.pack(side=tk.LEFT)
        tk.Button(sz_row, text="➕", command=lambda: nudge_scale(5), **btn_s).pack(side=tk.LEFT, padx=2)

        rt_row = tk.Frame(sr_f, bg="#F1F5F9")
        rt_row.pack(fill=tk.X, pady=(0, 2))
        tk.Label(rt_row, text="Girar:", font=("Segoe UI", 8, "bold"), bg="#F1F5F9", fg="#334155", width=7, anchor="w").pack(side=tk.LEFT)
        tk.Button(rt_row, text="↺", command=lambda: nudge_rot(-5), **btn_s).pack(side=tk.LEFT, padx=2)
        rot_val_lbl = tk.Label(rt_row, text="0°", font=("Segoe UI", 8, "bold"), bg="#F1F5F9", fg="#0369A1", width=5)
        rot_val_lbl.pack(side=tk.LEFT)
        tk.Button(rt_row, text="↻", command=lambda: nudge_rot(5), **btn_s).pack(side=tk.LEFT, padx=2)
        tk.Button(rt_row, text="0°", font=("Segoe UI", 7, "bold"), bg="#E2E8F0", fg="#334155", relief="solid", bd=1, cursor="hand2", padx=4, command=lambda: (rot_var.set(0), commit_position_change())).pack(side=tk.LEFT, padx=(4, 0))

        # =====================================================================
        # COLUMNA DERECHA: CUADRÍCULA MII + TALLER DE PIEZA + AVANZADO
        # =====================================================================
        right_scroll = ScrollableFrame(body, bg="#FFFFFF")
        right_scroll.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        rc = right_scroll.content

        # --- SECCIÓN 1: CUADRÍCULA TIPO MII ("¿Qué ojos usa esta escena?") ---
        mii_box = tk.LabelFrame(
            rc, text=" 1. Ojos en esta escena (1 clic para cambiar) ",
            font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#0F172A", padx=10, pady=8
        )
        mii_box.pack(fill=tk.X, padx=8, pady=(6, 8))

        mii_hdr = tk.Frame(mii_box, bg="#FFFFFF")
        mii_hdr.pack(fill=tk.X, pady=(0, 6))
        scene_info_lbl = tk.Label(
            mii_hdr, text="Escena actual: Base / Quieto",
            font=("Segoe UI", 8, "bold"), bg="#E0F2FE", fg="#0369A1", padx=6, pady=2
        )
        scene_info_lbl.pack(side=tk.LEFT)

        grid_frame = tk.Frame(mii_box, bg="#FFFFFF")
        grid_frame.pack(fill=tk.X)

        def make_set_thumb(scfg):
            key = (scfg.get("sprite", ""), scfg.get("mask_sprite", ""), scfg.get("overlay_sprite", ""), bool(scfg.get("show_mask", False)))
            if key in state["thumb_cache"]:
                return state["thumb_cache"][key]
            # Componer mini-vista del set
            tmp = EyesRenderCache()
            tmp.load_pil_frame({"eye_sets": {"t": scfg}, "active_set": "t"}, flip_x=False)
            slot = tmp._get_slot("t")
            base_im = None
            if slot:
                ref = slot["mask_pil"] or slot["overlay_pil"] or slot["pil_img"]
                if ref is not None:
                    cw, ch = ref.size
                    comp = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                    if slot["mask_pil"] is not None and scfg.get("show_mask", False):
                        comp.alpha_composite(slot["mask_pil"])
                    if slot["pil_img"] is not None:
                        px = (cw - slot["pil_img"].width) // 2
                        py = (ch - slot["pil_img"].height) // 2
                        comp.paste(slot["pil_img"], (px, py), slot["pil_img"])
                    if slot["overlay_pil"] is not None:
                        comp.alpha_composite(slot["overlay_pil"])
                    comp.thumbnail((40, 40), Image.Resampling.LANCZOS)
                    base_im = ImageTk.PhotoImage(comp)
            state["thumb_cache"][key] = base_im
            return base_im

        def select_set_for_scene(sid):
            r = state["role"]
            if sid == "none":
                if r == "idle":
                    eyes_cfg["enabled"] = False
                else:
                    ov = eyes_cfg.setdefault("frame_overrides", {})
                    cur = ov.get(r, {"offset_x": eyes_cfg["offset_x"], "offset_y": eyes_cfg["offset_y"], "scale": eyes_cfg["scale"], "rotation": eyes_cfg["rotation"], "hidden": True})
                    cur["eye_set"] = "none"
                    cur["hidden"] = True
                    ov[r] = cur
            else:
                eyes_cfg["enabled"] = True
                if r == "idle":
                    eyes_cfg["active_set"] = sid
                else:
                    ov = eyes_cfg.setdefault("frame_overrides", {})
                    cur = ov.get(r, {"offset_x": eyes_cfg["offset_x"], "offset_y": eyes_cfg["offset_y"], "scale": eyes_cfg["scale"], "rotation": eyes_cfg["rotation"], "hidden": False})
                    cur["eye_set"] = sid
                    cur["hidden"] = False
                    ov[r] = cur
                state["editing_set"] = sid
                load_piece_editor()
            refresh_mii_grid()
            commit_and_sync()
            render_preview()

        def create_new_eye_set():
            idx = len(eyes_cfg["eye_sets"]) + 1
            new_id = f"set_{idx}"
            while new_id in eyes_cfg["eye_sets"]:
                idx += 1
                new_id = f"set_{idx}"
            eyes_cfg["eye_sets"][new_id] = default_eye_set(f"Ojos {idx}")
            select_set_for_scene(new_id)

        def delete_current_eye_set():
            if len(eyes_cfg["eye_sets"]) <= 1:
                return
            sid = state["editing_set"]
            if sid in eyes_cfg["eye_sets"]:
                eyes_cfg["eye_sets"].pop(sid, None)
            first_sid = next(iter(eyes_cfg["eye_sets"]))
            if eyes_cfg.get("active_set") == sid:
                eyes_cfg["active_set"] = first_sid
            for ov in (eyes_cfg.get("frame_overrides") or {}).values():
                if isinstance(ov, dict) and ov.get("eye_set") == sid:
                    ov.pop("eye_set", None)
            state["editing_set"] = first_sid
            load_eyes_pil()
            load_piece_editor()
            refresh_mii_grid()
            commit_and_sync()
            render_preview()

        tk.Button(
            mii_hdr, text="➕ Nuevo Set", font=("Segoe UI", 8, "bold"),
            bg="#DCFCE7", fg="#166534", relief="solid", bd=1, padx=8, pady=1, cursor="hand2",
            command=create_new_eye_set
        ).pack(side=tk.RIGHT)

        def refresh_mii_grid():
            for w in grid_frame.winfo_children():
                w.destroy()
            r = state["role"]
            if r == "idle" and not eyes_cfg.get("enabled", False):
                curr_sid = "none"
            else:
                curr_sid, _ = resolve_eye_set_for_role(eyes_cfg, r)
                hid, *_ = resolve_eyes_frame_config(eyes_cfg, r)
                if hid:
                    curr_sid = "none"

            cards = [("none", "Dibujo PNG", None)] + [(sid, scfg.get("name", sid), scfg) for sid, scfg in eyes_cfg["eye_sets"].items()]
            cols = 4
            for i, (sid, label, scfg) in enumerate(cards):
                is_sel = (curr_sid == sid)
                card = tk.Frame(
                    grid_frame,
                    bg="#DBEAFE" if is_sel else "#F8FAFC",
                    highlightthickness=2 if is_sel else 1,
                    highlightbackground="#2563EB" if is_sel else "#CBD5E1",
                    padx=6, pady=6, cursor="hand2"
                )
                card.grid(row=i // cols, column=i % cols, padx=4, pady=4, sticky="nsew")

                if sid == "none":
                    ico = tk.Label(card, text="🚫", font=("Segoe UI", 16), bg=card["bg"])
                    ico.pack()
                else:
                    th = make_set_thumb(scfg)
                    if th is not None:
                        ico = tk.Label(card, image=th, bg=card["bg"], width=42, height=42)
                        ico._th = th
                        ico.pack()
                    else:
                        ico = tk.Label(card, text="👀", font=("Segoe UI", 16), bg=card["bg"])
                        ico.pack()

                txt = tk.Label(
                    card, text=label[:12], font=("Segoe UI", 8, "bold" if is_sel else "normal"),
                    bg=card["bg"], fg="#1E3A8A" if is_sel else "#334155"
                )
                txt.pack(pady=(2, 0))

                for w in (card, ico, txt):
                    w.bind("<Button-1>", lambda _e, s=sid: select_set_for_scene(s))

            for c in range(cols):
                grid_frame.columnconfigure(c, weight=1)

        # --- SECCIÓN 2: TALLER DE LA PIEZA (CAPAS EN ORDEN VISUAL) ---
        piece_box = tk.LabelFrame(
            rc, text=" 2. Editar Pieza de Ojos (Aparte) ",
            font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#0F172A", padx=10, pady=8
        )
        piece_box.pack(fill=tk.X, padx=8, pady=(0, 8))

        piece_top = tk.Frame(piece_box, bg="#FFFFFF")
        piece_top.pack(fill=tk.X, pady=(0, 6))
        tk.Label(piece_top, text="Nombre del set:", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#334155").pack(side=tk.LEFT)
        set_name_var = tk.StringVar(value="Normal")
        set_name_entry = tk.Entry(piece_top, textvariable=set_name_var, font=("Segoe UI", 8, "bold"), width=18, relief="solid", bd=1)
        set_name_entry.pack(side=tk.LEFT, padx=(6, 8))

        def on_rename_set(*_a):
            if state["updating_vars"]:
                return
            sid = state["editing_set"]
            if sid in eyes_cfg["eye_sets"]:
                eyes_cfg["eye_sets"][sid]["name"] = set_name_var.get().strip() or sid
                refresh_mii_grid()
                commit_and_sync()

        set_name_var.trace_add("write", on_rename_set)

        del_set_btn = tk.Button(
            piece_top, text="🗑️ Borrar Set", font=("Segoe UI", 8),
            bg="#FEE2E2", fg="#991B1B", relief="solid", bd=1, padx=6, pady=1, cursor="hand2",
            command=delete_current_eye_set
        )
        del_set_btn.pack(side=tk.RIGHT)

        track_mouse_var = tk.BooleanVar(value=True)
        show_mask_var = tk.BooleanVar(value=False)

        def on_piece_toggle():
            sid = state["editing_set"]
            scfg = eyes_cfg["eye_sets"].get(sid)
            if not scfg:
                return
            scfg["track_mouse"] = bool(track_mouse_var.get())
            scfg["show_mask"] = bool(show_mask_var.get())
            state["thumb_cache"].clear()
            refresh_mii_grid()
            commit_and_sync()
            render_preview()

        tk.Checkbutton(
            piece_box, text="🎯 Seguir al mouse (desactívalo para ojos fijos como ^_^ o cerrados)",
            variable=track_mouse_var, command=on_piece_toggle,
            bg="#FFFFFF", fg="#0369A1", font=("Segoe UI", 8, "bold"), cursor="hand2"
        ).pack(anchor=tk.W, pady=(0, 6))

        # Sándwich de 3 capas
        layer_rows = {}

        def choose_layer_file(cfg_key, rel_key, fname_prefix, title_txt):
            path = filedialog.askopenfilename(
                parent=dlg, title=title_txt,
                filetypes=[("Imágenes PNG / WebP / GIF", "*.png *.webp *.gif"), ("Todos los archivos", "*.*")]
            )
            if not path:
                return
            sid = state["editing_set"]
            scfg = eyes_cfg["eye_sets"].get(sid)
            if not scfg:
                return
            eyes_dir = os.path.join(folder_path, "eyes")
            os.makedirs(eyes_dir, exist_ok=True)
            ext = os.path.splitext(path)[1].lower() or ".png"
            suffix = "" if sid == "default" else f"_{sid}"
            dest = os.path.join(eyes_dir, f"{fname_prefix}{suffix}{ext}")
            try:
                if os.path.abspath(path) != os.path.abspath(dest):
                    shutil.copy2(path, dest)
            except Exception:
                dest = path
            scfg[cfg_key] = dest
            try:
                scfg[rel_key] = os.path.relpath(dest, folder_path).replace("\\", "/")
            except Exception:
                scfg[rel_key] = ""
            eyes_cfg["enabled"] = True
            state["thumb_cache"].clear()
            load_eyes_pil()
            refresh_layer_cards()
            refresh_mii_grid()
            commit_and_sync()
            render_preview()

        def clear_layer_file(cfg_key, rel_key):
            sid = state["editing_set"]
            scfg = eyes_cfg["eye_sets"].get(sid)
            if not scfg:
                return
            scfg[cfg_key] = ""
            scfg[rel_key] = ""
            state["thumb_cache"].clear()
            load_eyes_pil()
            refresh_layer_cards()
            refresh_mii_grid()
            commit_and_sync()
            render_preview()

        layers_spec = [
            ("overlay_sprite", "overlay_sprite_rel", "lashes", "✨ Arriba: Pestañas / Contorno", "Seleccionar pestañas / contorno superior"),
            ("sprite", "sprite_rel", "pupils", "🎯 Medio: Pupilas (se mueven)", "Seleccionar pupilas"),
            ("mask_sprite", "mask_sprite_rel", "mask", "👁️ Fondo: Máscara / Blanco", "Seleccionar máscara de recorte"),
        ]

        for ck, rk, fp, title_l, dlg_t in layers_spec:
            card = tk.Frame(piece_box, bg="#F8FAFC", relief="solid", bd=1, padx=8, pady=5)
            card.pack(fill=tk.X, pady=2)
            th_lbl = tk.Label(card, text="—", width=5, height=2, bg="#E2E8F0", fg="#64748B", font=("Segoe UI", 8))
            th_lbl.pack(side=tk.LEFT, padx=(0, 8))
            info_f = tk.Frame(card, bg="#F8FAFC")
            info_f.pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(info_f, text=title_l, font=("Segoe UI", 8, "bold"), bg="#F8FAFC", fg="#0F172A", anchor="w").pack(fill=tk.X)
            fn_lbl = tk.Label(info_f, text="Sin imagen", font=("Segoe UI", 8), bg="#F8FAFC", fg="#64748B", anchor="w")
            fn_lbl.pack(fill=tk.X)

            btns_f = tk.Frame(card, bg="#F8FAFC")
            btns_f.pack(side=tk.RIGHT)
            if ck == "mask_sprite":
                tk.Checkbutton(
                    btns_f, text="Blanco detrás", variable=show_mask_var, command=on_piece_toggle,
                    bg="#F8FAFC", fg="#334155", font=("Segoe UI", 8), cursor="hand2"
                ).pack(side=tk.LEFT, padx=(0, 6))
            tk.Button(
                btns_f, text="📂", font=("Segoe UI", 8), bg="#E0F2FE", fg="#0369A1",
                relief="solid", bd=1, padx=6, pady=1, cursor="hand2",
                command=lambda c=ck, r=rk, p=fp, t=dlg_t: choose_layer_file(c, r, p, t)
            ).pack(side=tk.LEFT)
            tk.Button(
                btns_f, text="🗑️", font=("Segoe UI", 8), bg="#FEE2E2", fg="#991B1B",
                relief="solid", bd=1, padx=6, pady=1, cursor="hand2",
                command=lambda c=ck, r=rk: clear_layer_file(c, r)
            ).pack(side=tk.LEFT, padx=(4, 0))
            layer_rows[ck] = (th_lbl, fn_lbl)

        def refresh_layer_cards():
            scfg = eyes_cfg["eye_sets"].get(state["editing_set"]) or {}
            for ck, _, _, _, _ in layers_spec:
                th_lbl, fn_lbl = layer_rows[ck]
                p = scfg.get(ck) or ""
                if p and os.path.exists(str(p)):
                    fn_lbl.config(text=f"✅ {os.path.basename(str(p))}", fg="#15803D")
                    try:
                        im = Image.open(p).convert("RGBA")
                        im.thumbnail((32, 32), Image.Resampling.LANCZOS)
                        tk_im = ImageTk.PhotoImage(im)
                        th_lbl.config(image=tk_im, text="", width=34, height=34)
                        th_lbl._im = tk_im
                    except Exception:
                        th_lbl.config(image="", text="PNG", width=5, height=2)
                else:
                    fn_lbl.config(text="Opcional / Sin imagen" if ck != "sprite" else "Sin pupilas", fg="#64748B")
                    th_lbl.config(image="", text="—", width=5, height=2)
            del_set_btn.config(state=tk.NORMAL if len(eyes_cfg["eye_sets"]) > 1 else tk.DISABLED)

        # Presets rápidos de movimiento
        preset_f = tk.Frame(piece_box, bg="#FFFFFF")
        preset_f.pack(fill=tk.X, pady=(6, 0))
        tk.Label(preset_f, text="Movimiento:", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#334155").pack(side=tk.LEFT, padx=(0, 6))

        radius_var = tk.IntVar(value=12)
        smooth_var = tk.IntVar(value=35)
        sens_var = tk.IntVar(value=300)
        bounce_var = tk.BooleanVar(value=bool(eyes_cfg.get("follows_bounce", True)))
        hide_blink_var = tk.BooleanVar(value=bool(eyes_cfg.get("hide_on_blink", True)))

        def apply_preset(rad, sm, se):
            radius_var.set(rad)
            smooth_var.set(sm)
            sens_var.set(se)
            commit_tracking_change()

        for lbl, rad, sm, se in (("Sutil", 8, 28, 420), ("Normal", 16, 40, 300), ("Exagerado", 28, 55, 200)):
            tk.Button(
                preset_f, text=lbl, font=("Segoe UI", 8, "bold"),
                bg="#F1F5F9", fg="#0F172A", relief="solid", bd=1, padx=8, pady=1, cursor="hand2",
                command=lambda r=rad, s=sm, e=se: apply_preset(r, s, e)
            ).pack(side=tk.LEFT, padx=2)

        # --- SECCIÓN 3: ACORDEÓN AVANZADO ---
        adv_hdr = tk.Frame(rc, bg="#FFFFFF")
        adv_hdr.pack(fill=tk.X, padx=8, pady=(0, 4))
        adv_box = tk.LabelFrame(rc, text=" Físicas y opciones avanzadas ", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#475569", padx=10, pady=8)

        def toggle_adv():
            state["adv_open"] = not state["adv_open"]
            if state["adv_open"]:
                adv_btn.config(text="▼ Ocultar Avanzado (Físicas y Opciones)")
                adv_box.pack(fill=tk.X, padx=8, pady=(0, 8))
            else:
                adv_btn.config(text="▶ Avanzado (Físicas y Opciones)")
                adv_box.pack_forget()

        adv_btn = tk.Button(
            adv_hdr, text="▶ Avanzado (Físicas y Opciones)", font=("Segoe UI", 8, "bold"),
            bg="#F1F5F9", fg="#475569", relief="solid", bd=1, padx=8, pady=3, cursor="hand2",
            anchor="w", command=toggle_adv
        )
        adv_btn.pack(fill=tk.X)

        def commit_tracking_change(*_a):
            if state["updating_vars"]:
                return
            scfg = eyes_cfg["eye_sets"].get(state["editing_set"])
            if scfg:
                scfg["mouse_radius"] = int(radius_var.get())
                scfg["smoothness"] = int(smooth_var.get())
                scfg["sensitivity"] = int(sens_var.get())
            eyes_cfg["follows_bounce"] = bool(bounce_var.get())
            eyes_cfg["hide_on_blink"] = bool(hide_blink_var.get())
            commit_and_sync()
            render_preview()

        def add_slider(parent, label, var, lo, hi, cmd):
            row = tk.Frame(parent, bg="#FFFFFF")
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label, width=19, anchor="w", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#334155").pack(side=tk.LEFT)
            val_lbl = tk.Label(row, text=str(var.get()), width=5, font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#0369A1")
            val_lbl.pack(side=tk.RIGHT)
            s = ttk.Scale(row, from_=lo, to=hi, orient=tk.HORIZONTAL, variable=var, command=lambda v: (val_lbl.config(text=str(int(float(v)))), cmd()))
            s.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=4)
            return val_lbl

        add_slider(adv_box, "Rango de movimiento:", radius_var, 1, 80, commit_tracking_change)
        add_slider(adv_box, "Suavizado (%):", smooth_var, 5, 100, commit_tracking_change)
        add_slider(adv_box, "Sensibilidad:", sens_var, 50, 900, commit_tracking_change)

        chk_row = tk.Frame(adv_box, bg="#FFFFFF")
        chk_row.pack(fill=tk.X, pady=(4, 0))
        tk.Checkbutton(chk_row, text="Seguir rebote", variable=bounce_var, command=commit_tracking_change, bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
        tk.Checkbutton(chk_row, text="Ocultar al pestañear", variable=hide_blink_var, command=commit_tracking_change, bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(10, 0))

        def reset_pose_override():
            r = state["role"]
            if r == "idle":
                eyes_cfg["offset_x"] = 0
                eyes_cfg["offset_y"] = 0
                eyes_cfg["scale"] = 100
                eyes_cfg["rotation"] = 0
            else:
                (eyes_cfg.get("frame_overrides") or {}).pop(r, None)
            load_controls_for_role(r)
            commit_and_sync()

        tk.Button(
            adv_box, text="⟲ Restablecer posición de esta escena", font=("Segoe UI", 8),
            bg="#F1F5F9", fg="#334155", relief="solid", bd=1, padx=8, pady=2, cursor="hand2",
            command=reset_pose_override
        ).pack(anchor=tk.E, pady=(6, 0))

        # =====================================================================
        # SINCRONIZACIÓN DE CONTROLES Y RENDERIZADO DE PREVIEW
        # =====================================================================
        def load_piece_editor():
            state["updating_vars"] = True
            scfg = eyes_cfg["eye_sets"].get(state["editing_set"]) or {}
            set_name_var.set(scfg.get("name", state["editing_set"]))
            track_mouse_var.set(bool(scfg.get("track_mouse", True)))
            show_mask_var.set(bool(scfg.get("show_mask", False)))
            radius_var.set(int(scfg.get("mouse_radius", 12)))
            smooth_var.set(int(scfg.get("smoothness", 35)))
            sens_var.set(int(scfg.get("sensitivity", 300)))
            state["updating_vars"] = False
            refresh_layer_cards()

        def commit_position_change(*_a):
            if state["updating_vars"]:
                return
            r = state["role"]
            ox = int(ox_var.get())
            oy = int(oy_var.get())
            sc = int(sc_var.get())
            rot = int(rot_var.get())
            size_val_lbl.config(text=f"{sc}%")
            rot_val_lbl.config(text=f"{rot}°")
            if r == "idle":
                eyes_cfg["offset_x"] = ox
                eyes_cfg["offset_y"] = oy
                eyes_cfg["scale"] = sc
                eyes_cfg["rotation"] = rot
            else:
                ov = eyes_cfg.setdefault("frame_overrides", {})
                cur = ov.get(r, {})
                cur.update({"offset_x": ox, "offset_y": oy, "scale": sc, "rotation": rot})
                if "hidden" not in cur:
                    cur["hidden"] = False
                ov[r] = cur
            commit_and_sync()
            render_preview()

        def load_controls_for_role(role):
            state["role"] = role
            scene_info_lbl.config(text=f"Escena actual: {role_to_label.get(role, role)}")
            state["updating_vars"] = True
            _, ox, oy, sc, rot, _ = resolve_eyes_frame_config(eyes_cfg, role)
            ox_var.set(ox)
            oy_var.set(oy)
            sc_var.set(sc)
            rot_var.set(rot)
            size_val_lbl.config(text=f"{sc}%")
            rot_val_lbl.config(text=f"{rot}°")
            sid, _ = resolve_eye_set_for_role(eyes_cfg, role)
            if sid != "none" and sid in eyes_cfg["eye_sets"]:
                state["editing_set"] = sid
            state["updating_vars"] = False
            load_piece_editor()
            refresh_mii_grid()
            render_preview()

        def render_preview():
            if not dlg.winfo_exists():
                return
            preview_canvas.delete("all")
            r = state["role"]
            av_pil = get_avatar_pil(r)
            pos_scale = max(20, prev_size - 16) / 384.0
            cx, cy = prev_size // 2, prev_size // 2

            if av_pil:
                avail = prev_size - 16
                ratio = min(avail / av_pil.width, avail / av_pil.height)
                nw, nh = max(4, int(av_pil.width * ratio)), max(4, int(av_pil.height * ratio))
                av_tk = ImageTk.PhotoImage(av_pil.resize((nw, nh), Image.Resampling.LANCZOS))
                preview_canvas.create_image(cx, cy, anchor=tk.CENTER, image=av_tk)
                preview_canvas._av_tk = av_tk

            hid, ox, oy, sc_pct, rot_deg, _ = resolve_eyes_frame_config(eyes_cfg, r)
            sid, scfg = resolve_eye_set_for_role(eyes_cfg, r)
            if r == "idle" and not eyes_cfg.get("enabled", False):
                hid = True

            if not hid and sid != "none" and scfg is not None:
                eff_ox = -ox if flip_x else ox
                bx = cx + int(eff_ox * pos_scale)
                by = cy + int(oy * pos_scale)

                if ox == 0:
                    preview_canvas.create_line(cx, 8, cx, prev_size - 8, fill="#38BDF8", dash=(4, 4), width=1)

                if live_test_var.get() and not state["drag_active"] and scfg.get("track_mouse", True):
                    state["eye_ox"], state["eye_oy"] = compute_mouse_eye_offset(
                        preview_canvas, bx, by, pos_scale, scfg, state["eye_ox"], state["eye_oy"]
                    )
                else:
                    state["eye_ox"], state["eye_oy"] = 0.0, 0.0

                eff_rot = -rot_deg if flip_x else rot_deg
                e_tk, anchored = state["eyes_cache"].get_tk_image(
                    pos_scale,
                    scale_pct=sc_pct,
                    rotation=eff_rot,
                    eye_ox=state["eye_ox"],
                    eye_oy=state["eye_oy"],
                    show_mask=bool(scfg.get("show_mask", False)),
                    set_id=sid,
                )
                if e_tk is not None:
                    ex, ey = (bx, by) if anchored else (bx + state["eye_ox"], by + state["eye_oy"])
                    if scfg.get("track_mouse", True):
                        rad_px = max(2, int(scfg.get("mouse_radius", 12) * pos_scale))
                        preview_canvas.create_oval(
                            bx - rad_px, by - rad_px, bx + rad_px, by + rad_px,
                            outline="#38BDF8", dash=(3, 3), width=1
                        )
                    preview_canvas.create_image(ex, ey, anchor=tk.CENTER, image=e_tk)
                    preview_canvas._e_tk = e_tk

        def tick_preview_loop():
            if not dlg.winfo_exists():
                return
            if live_test_var.get() and not state["drag_active"]:
                render_preview()
            dlg.after(30, tick_preview_loop)

        pose_combo.bind("<<ComboboxSelected>>", lambda _e=None: load_controls_for_role(label_to_role.get(pose_var.get(), "idle")))

        def on_canvas_down(event):
            state["drag_active"] = True
            state["drag_start_xy"] = (event.x, event.y)
            state["drag_orig_off"] = (ox_var.get(), oy_var.get())

        def on_canvas_move(event):
            if not state["drag_active"]:
                return
            pos_scale = max(20, prev_size - 16) / 384.0
            dx_px = event.x - state["drag_start_xy"][0]
            dy_px = event.y - state["drag_start_xy"][1]
            dx_off = int(round(dx_px / max(0.1, pos_scale)))
            if flip_x:
                dx_off = -dx_off
            dy_off = int(round(dy_px / max(0.1, pos_scale)))
            new_ox = max(-180, min(180, state["drag_orig_off"][0] + dx_off))
            if abs(new_ox) <= 3:
                new_ox = 0
            state["updating_vars"] = True
            ox_var.set(new_ox)
            oy_var.set(max(-180, min(180, state["drag_orig_off"][1] + dy_off)))
            state["updating_vars"] = False
            commit_position_change()

        def on_canvas_up(_event):
            state["drag_active"] = False

        def on_canvas_wheel(event):
            num = getattr(event, "num", None)
            step = 5 if (num == 4 or getattr(event, "delta", 0) > 0) else -5
            new_sc = max(10, min(280, int(sc_var.get()) + step))
            if new_sc != sc_var.get():
                state["updating_vars"] = True
                sc_var.set(new_sc)
                state["updating_vars"] = False
                commit_position_change()

        preview_canvas.bind("<ButtonPress-1>", on_canvas_down)
        preview_canvas.bind("<B1-Motion>", on_canvas_move)
        preview_canvas.bind("<ButtonRelease-1>", on_canvas_up)
        preview_canvas.bind("<MouseWheel>", on_canvas_wheel)
        preview_canvas.bind("<Button-4>", on_canvas_wheel)
        preview_canvas.bind("<Button-5>", on_canvas_wheel)

        tk.Button(
            main_f, text="✅ Listo", font=("Segoe UI", 9, "bold"),
            bg="#16A34A", fg="#FFFFFF", activebackground="#15803D", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=16, pady=5, cursor="hand2",
            command=dlg.destroy
        ).pack(side=tk.BOTTOM, anchor=tk.E, pady=(8, 0))

        load_eyes_pil()
        load_controls_for_role("idle")
        dlg.after(30, tick_preview_loop)

    # =========================================================================
    # --- PERFILES DE EMOCIÓN (5 CUADROS NUMERADOS / RENOMBRABLES) ---
    # =========================================================================
    def _get_active_emotion_idx(self, target_dict):
        if not isinstance(target_dict, dict):
            return 0
        try:
            idx = int(target_dict.get("active_emotion", 0) or 0)
        except Exception:
            idx = 0
        return max(0, min(4, idx))

    def _get_emotion_slot_obj(self, target_dict, idx):
        if not isinstance(target_dict, dict):
            return None
        slots = target_dict.get("emotion_slots")
        if not isinstance(slots, list) or len(slots) < 5:
            slots = default_emotion_slots()
            target_dict["emotion_slots"] = slots
        if 0 <= idx < len(slots):
            return slots[idx]
        return None

    def _refresh_emotion_slots_bar(self, target_dict):
        if not hasattr(self, "w_emotion_btns"):
            return
        active_idx = self._get_active_emotion_idx(target_dict)
        slots = target_dict.get("emotion_slots")
        if not isinstance(slots, list) or len(slots) < 5:
            slots = default_emotion_slots()
            target_dict["emotion_slots"] = slots
        for idx, btn in enumerate(self.w_emotion_btns):
            sl = slots[idx] if idx < len(slots) else {}
            lbl = str(sl.get("name") or str(idx + 1)).strip() or str(idx + 1)
            if len(lbl) > 12:
                lbl = lbl[:11] + "…"
            has_own = (idx == 0) or bool(sl.get("images"))
            is_sel = (idx == active_idx)
            btn.config(
                text=lbl,
                bg="#2563EB" if is_sel else ("#E0F2FE" if has_own else "#F1F5F9"),
                fg="#FFFFFF" if is_sel else ("#0369A1" if has_own else "#475569"),
                activebackground="#1D4ED8" if is_sel else "#CBD5E1",
                activeforeground="#FFFFFF" if is_sel else "#0F172A",
            )

    def _sync_emotion_change(self, curr_name, is_p1):
        self._save_character_folder_meta(curr_name)
        self.save_profiles_to_disk()
        target_dict = self.p1_data if is_p1 else self.p2_data
        self._refresh_emotion_slots_bar(target_dict)
        self._rebuild_workshop_sprite_slots(target_dict, "a1" if is_p1 else "a2")
        self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
        self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
        self.w_live_avatar.set_character(target_dict, prefix="a1" if is_p1 else "a2")
        self._sync_windows_images()

    def _select_emotion_slot(self, idx):
        is_p1 = (self.workshop_player == 1)
        curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
        idx = max(0, min(4, int(idx)))
        for p_key, rt_d in (
            ("player1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
            ("player2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
        ):
            prof = self.profiles.get(p_key, {}).get(curr_name)
            for d in (prof, rt_d):
                if isinstance(d, dict):
                    d["active_emotion"] = idx
        self._sync_emotion_change(curr_name, is_p1)

    def _on_emotion_slot_right_click(self, event, idx):
        is_p1 = (self.workshop_player == 1)
        curr_name = self.global_config.get("current_p1_profile" if is_p1 else "current_p2_profile", "Gatito Azul")
        target_dict = self.p1_data if is_p1 else self.p2_data
        sl = self._get_emotion_slot_obj(target_dict, idx) or {}
        cur_label = str(sl.get("name") or str(idx + 1))

        menu = tk.Menu(self.root, tearoff=0, bg="#0F172A", fg="#F8FAFC", activebackground="#2563EB", activeforeground="#FFFFFF", font=("Segoe UI", 9, "bold"))

        def rename_slot():
            new_n = simpledialog.askstring(
                "Renombrar perfil de emoción",
                f"Nombre para el perfil {idx + 1} (vacío para volver al número '{idx + 1}'):",
                initialvalue=cur_label,
                parent=self.root
            )
            if new_n is None:
                return
            final_n = new_n.strip() or str(idx + 1)
            for p_key, rt_d in (
                ("player1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
                ("player2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
            ):
                prof = self.profiles.get(p_key, {}).get(curr_name)
                for d in (prof, rt_d):
                    if isinstance(d, dict):
                        slots = d.setdefault("emotion_slots", default_emotion_slots())
                        if idx < len(slots):
                            slots[idx]["name"] = final_n
            self._sync_emotion_change(curr_name, is_p1)

        def clear_slot_poses():
            if idx == 0:
                return
            for p_key, rt_d in (
                ("player1", self.p1_data if self.global_config.get("current_p1_profile") == curr_name else None),
                ("player2", self.p2_data if self.global_config.get("current_p2_profile") == curr_name else None),
            ):
                prof = self.profiles.get(p_key, {}).get(curr_name)
                for d in (prof, rt_d):
                    if isinstance(d, dict):
                        slots = d.setdefault("emotion_slots", default_emotion_slots())
                        if idx < len(slots):
                            slots[idx]["images"] = {}
                            slots[idx]["images_rel"] = {}
                            slots[idx]["motions"] = {}
                            slots[idx]["motion_speeds"] = {}
            self._sync_emotion_change(curr_name, is_p1)

        menu.add_command(label=f"✏️ Renombrar '{cur_label}'...", command=rename_slot)
        if idx > 0:
            menu.add_separator()
            menu.add_command(label="🧹 Limpiar poses propias (heredar de 1)", command=clear_slot_poses)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
