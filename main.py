import tkinter as tk
from tkinter import ttk
import os
import sys

from core.audio_engine import AudioEngine
from core.hotkeys import GlobalHotkeyListener
from core.twitch_alerts import TwitchAlertServer

from core.app_constants import get_resource_path, log_debug
from ui.lobby_ui import LobbyMixin
from ui.workshop_ui import WorkshopMixin
from ui.coop_remote_dialog import CoopRemoteDialogMixin
from services.character_manager import CharacterManagerMixin
from services.audio_calibration import AudioCalibrationMixin
from services.obs_and_alerts import ObsAndAlertsMixin
from services.remote_control import RemoteControlMixin

# Asegurar soporte de salida UTF-8 en consolas Windows para emojis y caracteres especiales
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


# ============================================================================
# --- APLICACIÓN PRINCIPAL (PNGTUBER DUO CO-OP) ---
# ============================================================================
class PNGTuberCoopApp(
    LobbyMixin,
    WorkshopMixin,
    CoopRemoteDialogMixin,
    CharacterManagerMixin,
    AudioCalibrationMixin,
    ObsAndAlertsMixin,
    RemoteControlMixin,
):
    def __init__(self, root):
        log_debug("🚀 [SISTEMA] Iniciando PNGTuber Duo Co-op...")
        self.root = root
        self.root.title("PNGTuber Duo Co-op")
        self.root.geometry("980x820")
        self.root.minsize(920, 720)
        self.root.configure(bg="#DFE5EE")

        self.audio_engine = AudioEngine(
            on_mic_level=self._on_mic_level_thread,
            on_discord_level=self._on_discord_level_thread,
            on_mic_state=self._on_mic_state_thread,
            on_discord_state=self._on_discord_state_thread,
            on_mic_scream=self._on_mic_scream_thread,
            on_discord_scream=self._on_discord_scream_thread
        )

        self.avatar1_window = None
        self.avatar2_window = None
        self.btn_open = None

        self.mic_level = 0.0
        self.discord_level = 0.0
        self.mic_talking = False
        self.discord_talking = False

        self.p1_is_screaming = False
        self.p2_is_screaming = False

        self.thumbnails = {}
        self.current_screen = "lobby"
        self.workshop_player = 1

        self.default_assets = {
            "a1_idle": get_resource_path(os.path.join("assets", "Defy", "default_idle.png")),
            "a1_idle_blink": get_resource_path(os.path.join("assets", "Defy", "default_blink.png")),
            "a1_talk": get_resource_path(os.path.join("assets", "Defy", "default_talk.png")),
            "a1_talk_blink": get_resource_path(os.path.join("assets", "Defy", "default_talk_blink.png")),
            "a1_scream": "",

            "a2_idle": get_resource_path(os.path.join("assets", "Defy", "default_idle.png")),
            "a2_idle_blink": get_resource_path(os.path.join("assets", "Defy", "default_blink.png")),
            "a2_talk": get_resource_path(os.path.join("assets", "Defy", "default_talk.png")),
            "a2_talk_blink": get_resource_path(os.path.join("assets", "Defy", "default_talk_blink.png")),
            "a2_scream": "",
        }

        # Segundo jugador sale desactivado por defecto
        self.global_config = {
            "game_mode": "single",
            "current_p1_profile": "Gatito Azul",
            "current_p2_profile": "Osito Discord",
            "bg_color": "#00FF00",
            "bounce_enabled": True,
            "squash_enabled": True,
            "hysteresis_enabled": False,
            "congruence_enabled": True,
            "mouth_flutter_enabled": False,
            "experimental_enabled": False,
            "performance_mode": "performance",
            "dim_on_silence": False,
            "auto_open_obs": False,
            "obs_window_1_geo": "450x550+80+100",
            "obs_window_2_geo": "450x550+560+100",
            "twitch_alerts": {
                "enabled": False,
                "port": 8765,
                "rules": [
                    {"id": "rule_follow", "enabled": True, "event": "follow", "player": 1, "action": "character", "character": "", "duration": 8.0},
                    {"id": "rule_sub", "enabled": True, "event": "sub", "player": 1, "action": "scream", "character": "", "duration": 5.0},
                    {"id": "rule_raid", "enabled": True, "event": "raid", "player": 1, "action": "scream", "character": "", "duration": 7.0},
                ]
            },
            "hotkeys": {"1": [], "2": []},
            "character_layout": []
        }

        self.profiles = {"player1": {}, "player2": {}}

        self.p1_data = {
            "mic_device_name": "",
            "mic_threshold": 20,
            "scream_threshold": 55,
            "image_mode": "4_states",
            "props": [],
            "extra_expressions": [],
            "a1_idle": self.default_assets["a1_idle"],
            "a1_idle_blink": self.default_assets["a1_idle_blink"],
            "a1_talk": self.default_assets["a1_talk"],
            "a1_talk_blink": self.default_assets["a1_talk_blink"],
            "a1_scream": self.default_assets["a1_scream"]
        }

        self.p2_data = {
            "discord_source_id": "app:discord",
            "discord_threshold": 25,
            "scream_threshold": 55,
            "image_mode": "4_states",
            "props": [],
            "extra_expressions": [],
            "a2_idle": self.default_assets["a2_idle"],
            "a2_idle_blink": self.default_assets["a2_idle_blink"],
            "a2_talk": self.default_assets["a2_talk"],
            "a2_talk_blink": self.default_assets["a2_talk_blink"],
            "a2_scream": self.default_assets["a2_scream"]
        }

        self.load_all_data()
        self.audio_engine.hysteresis_ratio = 0.70 if self.global_config.get("hysteresis_enabled", False) else 1.0
        log_debug(f"[CONFIG] Perfil 1P activo: '{self.global_config.get('current_p1_profile')}', 2P activo: '{self.global_config.get('current_p2_profile')}', Modo: '{self.global_config.get('game_mode')}'")

        self._setup_styles()
        self._build_ui()
        self._refresh_audio_devices()

        # Iniciar en modo single con las dos tarjetas en blanco listas para elegir personaje
        self._set_game_mode("single")

        self._start_audio_engine()
        log_debug("[SISTEMA] Motor de audio iniciado y listo para capturar.")
        self._update_ui_loop()

        self.root.bind("<KeyPress>", self._on_global_key_press)
        self.root.bind("<FocusOut>", lambda e: self._refresh_eco_mode())
        self.root.bind("<FocusIn>", lambda e: self._refresh_eco_mode())
        self.root.bind("<Unmap>", lambda e: self._refresh_eco_mode() if e.widget == self.root else None)
        self.root.bind("<Map>", lambda e: self._refresh_eco_mode() if e.widget == self.root else None)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Congruencia entre fotogramas (activada por defecto) y alternado de boca (desactivado por defecto)
        self._apply_congruence_to_all()
        self._apply_mouth_flutter_to_all()

        # Atajos globales para cambiar de personaje (1P / 2P), funcionan aunque estés jugando
        self._hotkey_base = {1: None, 2: None}
        self.hotkey_listener = GlobalHotkeyListener(
            lambda bid: self.root.after(0, lambda b=bid: self._on_hotkey_triggered(b))
        )
        self._refresh_hotkey_bindings()
        self.hotkey_listener.start()

        # Modo ahorro de recursos mientras se transmite a OBS
        self._eco_mode = False

        # Receptor local de alertas de Twitch (cola por jugador)
        self._init_guest_runtime()
        self._alert_queues = {1: [], 2: []}
        self._alert_active = {1: False, 2: False}
        self._alert_restore = {1: None, 2: None}
        self._alert_timer = {1: None, 2: None}
        self.twitch_alert_server = TwitchAlertServer(
            lambda payload: self.root.after(0, lambda p=payload: self._handle_twitch_alert(p)),
            on_state_callback=lambda: self._run_on_ui_sync(self.get_remote_state),
            on_action_callback=lambda payload: self._run_on_ui_sync(
                lambda p=payload: self.dispatch_remote_action(p, source="http")
            ),
        )
        self._sync_twitch_alert_server()
        self._refresh_experimental_buttons()
        if self.global_config.get("auto_open_obs", False):
            self.root.after(450, self.open_avatar_windows)

    def _setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.style.configure(".", background="#DFE5EE", foreground="#1A222C", font=("Segoe UI", 9))
        self.style.configure("TLabel", background="#DFE5EE", foreground="#1A222C")
        self.style.configure("White.TLabel", background="#FFFFFF", foreground="#1A222C")
        self.style.configure("WhiteTip.TLabel", background="#FFFFFF", foreground="#5D6D82", font=("Segoe UI", 8))

        self.style.configure(
            "DSButton.TButton",
            font=("Segoe UI", 9, "bold"),
            background="#FFFFFF",
            foreground="#1A222C",
            borderwidth=1,
            relief="solid"
        )
        self.style.map(
            "DSButton.TButton",
            background=[("active", "#EBF2FA"), ("pressed", "#D3E0F0")],
            foreground=[("active", "#101620")]
        )

        self.style.configure(
            "DSBlue.TButton",
            font=("Segoe UI", 9, "bold"),
            background="#3671C6",
            foreground="#FFFFFF",
            borderwidth=1,
            relief="solid"
        )
        self.style.map(
            "DSBlue.TButton",
            background=[("active", "#4885DB"), ("pressed", "#285FA8")]
        )

        self.style.configure(
            "DSSend.TButton",
            font=("Segoe UI", 11, "bold"),
            background="#E45B47",
            foreground="#FFFFFF",
            borderwidth=2,
            relief="solid"
        )
        self.style.map(
            "DSSend.TButton",
            background=[("active", "#F06E5C"), ("pressed", "#C74230")]
        )

        self.style.configure(
            "DSRedMini.TButton",
            font=("Segoe UI", 8, "bold"),
            background="#E45B47",
            foreground="#FFFFFF",
            borderwidth=1,
            relief="solid"
        )
        self.style.map(
            "DSRedMini.TButton",
            background=[("active", "#F06E5C"), ("pressed", "#C74230")]
        )

        self.style.configure(
            "DSArrow.TButton",
            font=("Segoe UI", 12, "bold"),
            background="#FFFFFF",
            foreground="#1E293B",
            borderwidth=1,
            relief="solid"
        )
        self.style.map(
            "DSArrow.TButton",
            background=[("active", "#E0F2FE"), ("pressed", "#BAE6FD")],
            foreground=[("active", "#0284C7")]
        )

        self.style.configure(
            "DSGearBlue.TButton",
            font=("Segoe UI", 10, "bold"),
            background="#3671C6",
            foreground="#FFFFFF",
            borderwidth=2,
            relief="solid",
            padding=(8, 8)
        )
        self.style.map(
            "DSGearBlue.TButton",
            background=[("active", "#2563EB"), ("pressed", "#1D4ED8")]
        )

        self.style.configure(
            "DSGearRed.TButton",
            font=("Segoe UI", 10, "bold"),
            background="#E45B47",
            foreground="#FFFFFF",
            borderwidth=2,
            relief="solid",
            padding=(8, 8)
        )
        self.style.map(
            "DSGearRed.TButton",
            background=[("active", "#DC2626"), ("pressed", "#B91C1C")]
        )

        self.style.configure(
            "DSBack.TButton",
            font=("Segoe UI", 10, "bold"),
            background="#059669",
            foreground="#FFFFFF",
            borderwidth=2,
            relief="solid",
            padding=(8, 6)
        )
        self.style.map(
            "DSBack.TButton",
            background=[("active", "#10B981"), ("pressed", "#047857")]
        )

        self.style.configure(
            "ModeActive.TButton",
            font=("Segoe UI", 9, "bold"),
            background="#3671C6",
            foreground="#FFFFFF"
        )
        self.style.configure(
            "ModeInactive.TButton",
            font=("Segoe UI", 9),
            background="#FFFFFF",
            foreground="#4A5868"
        )

        self.style.configure("TScale", background="#FFFFFF", troughcolor="#E2E7EE")
        self.style.configure("TCombobox", fieldbackground="#FFFFFF", background="#D4DCE8", foreground="#1A222C")
        self.style.map("TCombobox", fieldbackground=[("readonly", "#FFFFFF")], foreground=[("readonly", "#1A222C")])

    def _build_ui(self):
        # 1. BARRA SUPERIOR DS
        ds_header = tk.Frame(self.root, bg="#3671C6", height=42, padx=14)
        ds_header.pack(fill=tk.X)
        ds_header.pack_propagate(False)

        left_h = tk.Frame(ds_header, bg="#3671C6")
        left_h.pack(side=tk.LEFT, fill=tk.Y)

        tk.Label(
            left_h, text="PNGTUBER DUO", font=("Segoe UI", 11, "bold"),
            bg="#3671C6", fg="#FFFFFF"
        ).pack(side=tk.LEFT, pady=8)

        right_h = tk.Frame(ds_header, bg="#3671C6")
        right_h.pack(side=tk.RIGHT, fill=tk.Y)

        self.clock_lbl = tk.Label(right_h, text="🕒 12:00", font=("Segoe UI", 9, "bold"), bg="#3671C6", fg="#FFFFFF")
        self.clock_lbl.pack(side=tk.RIGHT, pady=8, padx=(6, 0))

        # 2. CONTENEDOR PRINCIPAL: LOBBY (CON TARJETAS WORKSHOP ESTILO RIVALS OF AETHER) Y TALLER
        self.screen_container = tk.Frame(self.root, bg="#DFE5EE")
        self.screen_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        self._build_lobby_screen()
        self._build_workshop_screen()

        # 3. CONSOLA INFERIOR DS
        ds_bottom = tk.Frame(self.root, bg="#CBD5E1", height=54, padx=14, pady=6, relief="solid", bd=1)
        ds_bottom.pack(fill=tk.X)

        self.opts_f = tk.Frame(ds_bottom, bg="#CBD5E1")
        self.opts_f.pack(side=tk.LEFT)

        tk.Label(self.opts_f, text="🟩 Fondo OBS (Croma):", font=("Segoe UI", 8, "bold"), bg="#CBD5E1", fg="#1E293B").pack(side=tk.LEFT, padx=(4, 4))
        self.bg_combo = ttk.Combobox(self.opts_f, values=["Verde (#00FF00)", "Azul (#0000FF)", "Magenta (#FF00FF)", "Negro (#000000)", "Transparente (Alpha)"], state="readonly", width=18)
        bg_map = {"#00FF00": 0, "#0000FF": 1, "#FF00FF": 2, "#000000": 3, "TRANSPARENT": 4}
        self.bg_combo.current(bg_map.get(self.global_config.get("bg_color"), 0))
        self.bg_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.bg_combo.bind("<<ComboboxSelected>>", self._on_bg_color_changed)

        self.bounce_var = tk.BooleanVar(value=self.global_config.get("bounce_enabled", True))
        self.squash_var = tk.BooleanVar(value=self.global_config.get("squash_enabled", True))
        self.hysteresis_var = tk.BooleanVar(value=self.global_config.get("hysteresis_enabled", False))
        perf_m = self.global_config.get("performance_mode", "performance")
        if hasattr(self, "p1_live_avatar"):
            self.p1_live_avatar.perf_mode = perf_m
        if hasattr(self, "p2_live_avatar"):
            self.p2_live_avatar.perf_mode = perf_m
        if hasattr(self, "w_live_avatar"):
            self.w_live_avatar.perf_mode = perf_m
        if hasattr(self, "p1_live_avatar"):
            self.p1_live_avatar.squash_enabled = self.squash_var.get()
        if hasattr(self, "p2_live_avatar"):
            self.p2_live_avatar.squash_enabled = self.squash_var.get()
        if hasattr(self, "w_live_avatar"):
            self.w_live_avatar.squash_enabled = self.squash_var.get()

        self.btn_open = ttk.Button(
            ds_bottom, text="Abrir avatares",
            style="DSSend.TButton", command=self.toggle_avatar_windows
        )
        self.btn_open.pack(side=tk.RIGHT, padx=4)

        self.btn_workshop_accept = tk.Button(
            ds_bottom, text="✅ Aceptar",
            font=("Segoe UI", 10, "bold"),
            bg="#16A34A", fg="#FFFFFF",
            activebackground="#15803D", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=18, pady=2, cursor="hand2",
            command=lambda: self._switch_screen("lobby")
        )

        # Iniciar directamente en el Lobby con las 2 tarjetas en blanco listas para elegir personaje
        self._switch_screen("lobby")

        self._update_clock()


    def on_close(self):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        log_debug("[SISTEMA] Cerrando aplicación, guardando datos y terminando audio...")
        for fn in (self._save_p1_profile, self._save_p2_profile, self.save_global_config):
            try:
                fn()
            except Exception as e:
                log_debug(f"[SISTEMA] Error guardando al cerrar: {e}")
        for win_attr, geo_key in (("avatar1_window", "obs_window_1_geo"), ("avatar2_window", "obs_window_2_geo")):
            win = getattr(self, win_attr, None)
            if win is not None:
                try:
                    if win.winfo_exists():
                        self.global_config[geo_key] = win.geometry()
                        win.on_close()
                except Exception:
                    pass
        for extra_win in (getattr(self, "extra_avatar_windows", {}) or {}).values():
            if extra_win is not None:
                try:
                    if extra_win.winfo_exists():
                        extra_win.on_close()
                except Exception:
                    pass
        try:
            self.save_global_config()
        except Exception:
            pass
        try:
            self.hotkey_listener.stop()
        except Exception:
            pass
        try:
            self.stop_coop_relay()
        except Exception:
            pass
        try:
            self.twitch_alert_server.stop()
        except Exception:
            pass
        try:
            self.audio_engine.terminate()
        except Exception:
            pass
        try:
            self.root.quit()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        log_debug("[SISTEMA] Aplicación finalizada correctamente.")


if __name__ == "__main__":
    log_debug("==================================================")
    log_debug("  PNGTuber Duo / Coop - Modo Debug Iniciado")
    log_debug("==================================================")
    root = tk.Tk()
    app = PNGTuberCoopApp(root)
    root.mainloop()