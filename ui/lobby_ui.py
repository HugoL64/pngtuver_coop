import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import os
import random
import shutil
import time

from core.app_constants import CHARACTERS_DIR, log_debug, ScrollableFrame
from ui.live_avatar_preview import LiveAvatarPreview
from core.hotkeys import MODIFIER_VKS, current_modifiers, format_hotkey, pretty_key_label


class LobbyMixin:
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
            text="💡 Arrastra al borde = Ordenar • Al centro = Carpeta",
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
                    # Sobre otro personaje: borde (20% arriba/abajo) = reordenar; centro = crear carpeta
                    is_center = (0.20 <= rel_y <= 0.80) and (dt["folder_id"] is None)
                    drag_state["target_info"] = (dt, rel_y)
                    cancel_hold_timer()
                    drag_state["hover_key"] = hkey
                    if is_center:
                        drag_state["mode"] = "make_folder"
                        dt["widget"].configure(highlightbackground="#F59E0B", bg="#451A03")
                        if dt.get("hint_lbl"):
                            dt["hint_lbl"].config(text="📁 Soltar = carpeta")
                    else:
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

    def _set_performance_mode(self, mode_key):
        if mode_key not in ("performance", "balanced", "quality"):
            mode_key = "performance"
        self.global_config["performance_mode"] = mode_key
        self.save_global_config()
        if hasattr(self, "p1_live_avatar"):
            self.p1_live_avatar.perf_mode = mode_key
            self.p1_live_avatar.set_character(self.p1_data, prefix="a1")
        if hasattr(self, "p2_live_avatar"):
            self.p2_live_avatar.perf_mode = mode_key
            self.p2_live_avatar.set_character(self.p2_data, prefix="a2")
        if hasattr(self, "w_live_avatar"):
            self.w_live_avatar.perf_mode = mode_key
            is_p1 = (getattr(self, "workshop_player", 1) == 1)
            self.w_live_avatar.set_character(self.p1_data if is_p1 else self.p2_data, prefix="a1" if is_p1 else "a2")
        if self.avatar1_window and self.avatar1_window.winfo_exists():
            self.avatar1_window.perf_mode = mode_key
            self.avatar1_window.load_images()
        if self.avatar2_window and self.avatar2_window.winfo_exists():
            self.avatar2_window.perf_mode = mode_key
            self.avatar2_window.load_images()
        log_debug(f"[CONFIG] Modo de rendimiento cambiado a: {mode_key}")

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

        # Tarjeta de Modo de Rendimiento (RAM / Resolución / Frames)
        perf_card = tk.Frame(
            body, bg="#FFFFFF", highlightthickness=2,
            highlightbackground="#0EA5E9", padx=14, pady=10
        )
        perf_card.pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            perf_card, text="🚀  Modo de Rendimiento y Memoria RAM",
            font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#1E293B"
        ).pack(anchor=tk.W)

        perf_btns_f = tk.Frame(perf_card, bg="#FFFFFF")
        perf_btns_f.pack(fill=tk.X, pady=(6, 4))

        perf_modes_info = [
            ("performance", "⚡ Rendimiento", "Mínimo consumo de RAM (~360px en vistas previas, máx. 960px en OBS y 45 frames animados). Ideal para PCs modestas o ahorrar memoria."),
            ("balanced", "⚖️ Equilibrado", "Balance entre nitidez y memoria (~512px en vistas previas, máx. 1440px en OBS y 60 frames animados)."),
            ("quality", "✨ Alta Calidad", "Máxima nitidez y fluidez (sin límite de resolución en OBS, 60 FPS en vistas previas y hasta 90 frames). Recomendado solo para PCs potentes."),
        ]
        perf_desc_lbl = tk.Label(
            perf_card, text="", font=("Segoe UI", 8), bg="#FFFFFF", fg="#475569",
            justify=tk.LEFT, anchor=tk.W, wraplength=490
        )
        perf_desc_lbl.pack(fill=tk.X, pady=(2, 0))

        perf_btn_widgets = {}

        def refresh_perf_buttons():
            curr_m = self.global_config.get("performance_mode", "performance")
            for mk, mlbl, mdesc in perf_modes_info:
                b = perf_btn_widgets[mk]
                if mk == curr_m:
                    b.config(bg="#0284C7", fg="#FFFFFF", activebackground="#0369A1", activeforeground="#FFFFFF")
                    perf_desc_lbl.config(text=mdesc)
                else:
                    b.config(bg="#F1F5F9", fg="#334155", activebackground="#E2E8F0", activeforeground="#0F172A")

        def select_perf_mode(mode_k):
            self._set_performance_mode(mode_k)
            refresh_perf_buttons()

        for mk, mlbl, _ in perf_modes_info:
            b = tk.Button(
                perf_btns_f, text=mlbl, font=("Segoe UI", 8, "bold"),
                relief="solid", bd=1, padx=10, pady=4, cursor="hand2",
                command=lambda k=mk: select_perf_mode(k)
            )
            b.pack(side=tk.LEFT, padx=(0, 6))
            perf_btn_widgets[mk] = b
        refresh_perf_buttons()

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

