"""Diálogo de gestión Co-op por Internet (4 Jugadores, Lobby de Aprobación, Permisos y Pánico)."""
"""Diálogo de gestión Co-op por Internet (4 Jugadores, Lobby de Aprobación, Permisos y Pánico)
con estética de selección de equipo estilo Pokémon Blanco y Negro."""

import os
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

from core.app_constants import DATA_DIR
from core.relay_schemas import PERMISSION_KEYS, VALID_SLOTS


# Paleta Pokémon Blanco y Negro (pantalla de Equipo / C-Gear)
_BW_BG = "#0F232C"          # Fondo principal verde-azulado oscuro
_BW_GRID_SUB = "#163442"    # Retícula fina secundaria
_BW_GRID_MAIN = "#1E4B5E"   # Retícula principal
_BW_GRID_TICK = "#2D6A82"   # Cruces en intersecciones de la retícula

_BW_HDR_BG = "#0B141B"      # Cabecera metálica oscura
_BW_HDR_LINE = "#2DD4BF"    # Línea neón turquesa BW
_BW_PANEL_BG = "#132934"    # Panel de conexión / C-Gear
_BW_PANEL_BORDER = "#2B5B6E"

_BW_SLOT_LEAD_BG = "#153E52"
_BW_SLOT_LEAD_BD = "#38BDF8"
_BW_SLOT_ON_BG = "#134747"
_BW_SLOT_ON_BD = "#2DD4BF"
_BW_SLOT_OFF_BG = "#101E27"
_BW_SLOT_OFF_BD = "#254050"

_BW_HP_TRACK = "#0A1218"
_BW_HP_GREEN = "#22C55E"
_BW_HP_YELLOW = "#FACC15"
_BW_HP_RED = "#EF4444"


def _draw_bw_reticle(canvas: tk.Canvas, width: int, height: int):
    """Dibuja la retícula característica del menú de equipo de Pokémon Blanco y Negro."""
    canvas.delete("reticle")
    sub_step = 24
    main_step = 48

    for x in range(0, width + 1, sub_step):
        is_main = (x % main_step == 0)
        canvas.create_line(
            x, 0, x, height,
            fill=_BW_GRID_MAIN if is_main else _BW_GRID_SUB,
            width=1,
            tags="reticle",
        )
    for y in range(0, height + 1, sub_step):
        is_main = (y % main_step == 0)
        canvas.create_line(
            0, y, width, y,
            fill=_BW_GRID_MAIN if is_main else _BW_GRID_SUB,
            width=1,
            tags="reticle",
        )

    # Pequeñas cruces en las intersecciones principales para dar efecto retícula DS
    for x in range(main_step, width, main_step):
        for y in range(main_step, height, main_step):
            canvas.create_line(x - 3, y, x + 4, y, fill=_BW_GRID_TICK, width=1, tags="reticle")
            canvas.create_line(x, y - 3, x, y + 4, fill=_BW_GRID_TICK, width=1, tags="reticle")


def _draw_pokeball(canvas: tk.Canvas, active: bool, is_lead: bool = False):
    """Dibuja una Pokéball pixel/vectorial limpia para indicar si el slot está ocupado."""
    canvas.delete("all")
    cx, cy, r = 16, 16, 12
    if active:
        top_col = "#38BDF8" if is_lead else "#EF4444"
        bot_col = "#F8FAFC"
        band_col = "#0F172A"
        core_col = "#FACC15" if is_lead else "#FFFFFF"
        outline_col = "#E2E8F0"
    else:
        top_col = "#1E3442"
        bot_col = "#152530"
        band_col = "#0D1820"
        core_col = "#334E5E"
        outline_col = "#2E4C5E"

    canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=bot_col, outline=outline_col, width=2)
    canvas.create_arc(
        cx - r, cy - r, cx + r, cy + r,
        start=0, extent=180, fill=top_col, outline=outline_col, width=2,
    )
    canvas.create_line(cx - r, cy, cx + r, cy, fill=band_col, width=3)
    canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=core_col, outline=band_col, width=2)


class CoopRemoteDialogMixin:
    """Interfaz Tkinter para administrar la sala Co-op remota y los slots 2P/3P/4P."""

    def _open_coop_remote_dialog(self):
        existing = getattr(self, "_coop_dialog", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    return
            except Exception:
                pass

        dlg_w, dlg_h = 840, 720
        dlg = tk.Toplevel(self.root)
        self._coop_dialog = dlg
        dlg.title("🌐 Co-op Remoto (Hasta 4 Jugadores)")
        dlg.geometry("780x680")
        dlg.title("🌐 Sala Co-op — Equipo Pokémon B/N (Hasta 4 Jugadores)")
        dlg.geometry(f"{dlg_w}x{dlg_h}")
        dlg.resizable(False, False)
        dlg.configure(bg="#DFE5EE")
        dlg.configure(bg=_BW_BG)
        dlg.transient(self.root)

        self.root.update_idletasks()
        rx = self.root.winfo_x() + (self.root.winfo_width() - 780) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - 680) // 2
        rx = self.root.winfo_x() + (self.root.winfo_width() - dlg_w) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - dlg_h) // 2
        dlg.geometry(f"+{max(10, rx)}+{max(10, ry)}")

        # Cabecera estilo Nintendo DS PictoChat
        hdr = tk.Frame(dlg, bg="#1E293B", padx=16, pady=10)
        # =====================================================================
        # CABECERA SUPERIOR ESTILO POKÉMON BLANCO Y NEGRO
        # =====================================================================
        hdr = tk.Frame(dlg, bg=_BW_HDR_BG, padx=16, pady=9)
        hdr.pack(fill=tk.X)

        tk.Label(
            hdr,
            text="💬  PICTOCHAT  //  SALA CO-OP",
            text="◈  EQUIPO CO-OP  //  SALA",
            font=("Consolas", 13, "bold"),
            bg="#1E293B",
            bg=_BW_HDR_BG,
            fg="#38BDF8",
        ).pack(side=tk.LEFT)

        pills_frame = tk.Frame(hdr, bg="#1E293B")
        pills_frame.pack(side=tk.LEFT, padx=(14, 0))
        pills_frame = tk.Frame(hdr, bg=_BW_HDR_BG)
        pills_frame.pack(side=tk.LEFT, padx=(16, 0))
        tk.Label(
            pills_frame, text=" 1P HOST ", font=("Consolas", 8, "bold"),
            bg="#FACC15", fg="#1E293B", relief="solid", bd=1, padx=4, pady=1
            pills_frame, text=" ★ 1P HOST ", font=("Consolas", 8, "bold"),
            bg="#FACC15", fg="#0F172A", relief="solid", bd=1, padx=5, pady=1
        ).pack(side=tk.LEFT, padx=2)
        slot_pills = {}
        for s in VALID_SLOTS:
            sp = tk.Label(
                pills_frame, text=f" {s}P — ", font=("Consolas", 8, "bold"),
                bg="#334155", fg="#94A3B8", relief="solid", bd=1, padx=4, pady=1
                bg="#1E293B", fg="#64748B", relief="solid", bd=1, padx=5, pady=1
            )
            sp.pack(side=tk.LEFT, padx=2)
            slot_pills[s] = sp

        panic_btn = tk.Button(
            hdr,
            text="🛑 CONGELAR INVITADOS",
            font=("Segoe UI", 9, "bold"),
            bg="#DC2626",
            fg="#FFFFFF",
            activebackground="#B91C1C",
            activeforeground="#FFFFFF",
            relief="solid",
            bd=1,
            padx=10,
            pady=3,
            pady=2,
            cursor="hand2",
        )
        panic_btn.pack(side=tk.RIGHT)

        # Línea divisoria neón BW
        tk.Frame(dlg, bg=_BW_HDR_LINE, height=2).pack(fill=tk.X)

        def toggle_panic():
            cur = self.guest_inbox.is_panic_frozen()
            self.guest_inbox.set_panic_freeze(not cur)
            refresh_panic_btn()

        def refresh_panic_btn():
            if self.guest_inbox.is_panic_frozen():
                panic_btn.config(text="▶ REANUDAR INVITADOS", bg="#16A34A")
                panic_btn.config(text="▶ REANUDAR INVITADOS", bg="#16A34A", activebackground="#15803D")
            else:
                panic_btn.config(text="🛑 CONGELAR INVITADOS", bg="#DC2626")
                panic_btn.config(text="🛑 CONGELAR INVITADOS", bg="#DC2626", activebackground="#B91C1C")

        panic_btn.config(command=toggle_panic)
        refresh_panic_btn()

        # Tarjeta de conexión al Relay (modo simple + opciones avanzadas plegables)
        conn_card = tk.Frame(dlg, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", padx=12, pady=10)
        conn_card.pack(fill=tk.X, padx=14, pady=(10, 6))
        # =====================================================================
        # ÁREA PRINCIPAL CON RETÍCULA DE FONDO (CANVAS + CONTENEDOR)
        # =====================================================================
        bg_canvas = tk.Canvas(dlg, bg=_BW_BG, highlightthickness=0, bd=0)
        bg_canvas.pack(fill=tk.BOTH, expand=True)
        _draw_bw_reticle(bg_canvas, dlg_w, dlg_h - 46)

        content = tk.Frame(bg_canvas, bg=_BW_BG)
        # Colocamos el contenedor dentro del canvas dejando ver la retícula en los márgenes y espacios entre tarjetas
        bg_canvas.create_window(0, 0, anchor="nw", window=content, width=dlg_w, height=dlg_h - 46)

        # Hacemos transparente visualmente el frame contenedor repintando la retícula en un canvas interno para la zona de equipo
        content.configure(bg=_BW_BG)

        # =====================================================================
        # BARRA DE CONEXIÓN AL RELAY (ESTILO MENÚ DS)
        # =====================================================================
        conn_card = tk.Frame(
            content, bg=_BW_PANEL_BG,
            highlightthickness=2, highlightbackground=_BW_PANEL_BORDER,
            padx=12, pady=8,
        )
        conn_card.pack(fill=tk.X, padx=14, pady=(10, 8))

        cfg = self.global_config.setdefault("coop_remote", {})
        relay_var = tk.StringVar(value=cfg.get("relay_url", "ws://127.0.0.1:8766"))
        web_var = tk.StringVar(value=cfg.get("web_url", "http://127.0.0.1:8766"))
        local_dev_var = tk.BooleanVar(value=bool(cfg.get("allow_insecure_local", True)))
        use_tunnel_var = tk.BooleanVar(value=bool(cfg.get("use_tunnel", False)))
        pin_var = tk.StringVar(value="")
        show_secrets_var = tk.BooleanVar(value=False)
        advanced_open = tk.BooleanVar(value=False)

        top_row = tk.Frame(conn_card, bg="#FFFFFF")
        top_row = tk.Frame(conn_card, bg=_BW_PANEL_BG)
        top_row.pack(fill=tk.X)

        status_lbl = tk.Label(top_row, text="⚪ Sala cerrada", font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#64748B")
        status_lbl = tk.Label(
            top_row, text="⚪ Sala cerrada",
            font=("Consolas", 10, "bold"), bg=_BW_PANEL_BG, fg="#94A3B8"
        )
        status_lbl.pack(side=tk.LEFT)

        adv_btn = tk.Button(
            top_row,
            text="⚙ Avanzado ▾",
            font=("Segoe UI", 8, "bold"),
            bg="#F1F5F9",
            fg="#334155",
            relief="flat",
            bg="#1E3A4A",
            fg="#E2E8F0",
            activebackground="#274E63",
            activeforeground="#FFFFFF",
            relief="solid",
            bd=1,
            padx=8,
            pady=2,
            pady=1,
            cursor="hand2",
        )
        adv_btn.pack(side=tk.RIGHT)

        def _build_invite_url():
            rc = getattr(self.coop_relay_client, "room_code", None)
            tok = getattr(self.coop_relay_client, "invite_token", "")
            if not rc:
                return None
            t_url = getattr(getattr(self, "local_coop_host", None), "tunnel_url", "")
            base = (t_url or web_var.get().strip()).rstrip("/")
            return f"{base}/#room={rc}&invite={tok}"

        def _ask_cloudflared_consent():
            """Muestra un diálogo transparente explicando qué es cloudflared, de dónde viene y dónde se guarda."""
            result = {"ok": False}
            win = tk.Toplevel(dlg)
            win.title("🌐 Componente necesario para Internet")
            win.geometry("500x360")
            win.resizable(False, False)
            win.configure(bg="#FFFFFF")
            win.transient(dlg)
            win.grab_set()

            dlg.update_idletasks()
            wx = dlg.winfo_x() + (dlg.winfo_width() - 500) // 2
            wy = dlg.winfo_y() + (dlg.winfo_height() - 360) // 2
            win.geometry(f"+{max(10, wx)}+{max(10, wy)}")

            hdr_c = tk.Frame(win, bg="#0F172A", padx=14, pady=10)
            hdr_c.pack(fill=tk.X)
            tk.Label(
                hdr_c,
                text="Se necesita descargar una herramienta oficial (1 sola vez)",
                font=("Segoe UI", 10, "bold"),
                bg="#0F172A",
                fg="#38BDF8",
            ).pack(anchor=tk.W)

            body = tk.Frame(win, bg="#FFFFFF", padx=16, pady=12)
            body.pack(fill=tk.BOTH, expand=True)

            dest_path = os.path.join(DATA_DIR, "bin", "cloudflared.exe")
            info_items = [
                ("📦 Qué es:", "cloudflared.exe (~35–40 MB), herramienta oficial y gratuita de Cloudflare."),
                ("🎯 Para qué sirve:", "Crea un enlace seguro temporal (https://...trycloudflare.com) para que tus amigos entren por Internet sin abrir puertos ni exponer tu IP."),
                ("🔒 De dónde viene:", "Se descarga directo desde github.com/cloudflare/cloudflared (sin instaladores ni adware)."),
                ("📁 Dónde se guarda:", dest_path),
                ("💡 Solo una vez:", "Cuando termine, no volverá a descargarse. Puedes seguir en modo local si prefieres no descargarlo."),
            ]
            for title_txt, desc_txt in info_items:
                row_i = tk.Frame(body, bg="#FFFFFF")
                row_i.pack(fill=tk.X, pady=3)
                tk.Label(row_i, text=title_txt, font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#1E293B", width=16, anchor=tk.NW).pack(side=tk.LEFT)
                tk.Label(row_i, text=desc_txt, font=("Segoe UI", 8), bg="#FFFFFF", fg="#475569", wraplength=340, justify=tk.LEFT, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)

            foot = tk.Frame(win, bg="#F8FAFC", padx=16, pady=10)
            foot.pack(fill=tk.X, side=tk.BOTTOM)

            def accept():
                result["ok"] = True
                win.destroy()

            def cancel():
                result["ok"] = False
                win.destroy()

            tk.Button(foot, text="✅ Sí, descargar y abrir sala", bg="#16A34A", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), padx=12, pady=5, command=accept, cursor="hand2").pack(side=tk.RIGHT, padx=(6, 0))
            tk.Button(foot, text="Cancelar (usar solo local)", bg="#E2E8F0", fg="#1E293B", font=("Segoe UI", 9), padx=10, pady=5, command=cancel, cursor="hand2").pack(side=tk.RIGHT)

            win.protocol("WM_DELETE_WINDOW", cancel)
            dlg.wait_window(win)
            return result["ok"]

        def do_connect():
            want_tunnel = bool(use_tunnel_var.get())
            if want_tunnel and hasattr(self, "local_coop_host") and not self.local_coop_host.find_cloudflared():
                if not _ask_cloudflared_consent():
                    use_tunnel_var.set(False)
                    want_tunnel = False
            cfg["relay_url"] = relay_var.get().strip()
            cfg["web_url"] = web_var.get().strip()
            cfg["allow_insecure_local"] = bool(local_dev_var.get())
            cfg["use_tunnel"] = want_tunnel
            self.save_global_config()
            if hasattr(self.coop_relay_client, "set_pin"):
                self.coop_relay_client.set_pin(pin_var.get().strip()[:16])
            try:
                self.start_coop_relay(
                    cfg["relay_url"],
                    allow_insecure_local=cfg["allow_insecure_local"],
                    web_url=cfg["web_url"],
                    use_tunnel=want_tunnel,
                )
            except Exception as exc:
                messagebox.showerror("Error de conexión", str(exc), parent=dlg)

        def do_disconnect():
            self.stop_coop_relay()

        def _check_tunnel_pending():
            lch = getattr(self, "local_coop_host", None)
            if use_tunnel_var.get() and lch and lch.tunnel_state in ("downloading", "starting"):
                messagebox.showinfo(
                    "Túnel iniciando",
                    "El túnel de Internet aún se está preparando.\nEspera unos segundos a que aparezca '🟢 Sala activa por Internet'.",
                    parent=dlg,
                )
                return True
            return False

        def copy_invite():
            if _check_tunnel_pending():
                return
            url = _build_invite_url()
            if not url:
                messagebox.showinfo("Sala no activa", "Primero haz clic en 'Abrir Sala'.", parent=dlg)
                return
            dlg.clipboard_clear()
            dlg.clipboard_append(url)
            messagebox.showinfo("Copiado", "Enlace de invitación copiado al portapapeles.\nCompártelo con tus amigos para que se unan.", parent=dlg)

        def open_in_browser():
            if _check_tunnel_pending():
                return
            url = _build_invite_url()
            if not url:
                messagebox.showinfo("Sala no activa", "Primero haz clic en 'Abrir Sala'.", parent=dlg)
                return
            webbrowser.open(url)

        def rotate_invite():
            if not self.coop_relay_client.connected:
                return
            self.coop_relay_client.rotate_invite_token()
            refresh_invite_label()

        tunnel_row = tk.Frame(conn_card, bg="#FFFFFF")
        tunnel_row.pack(fill=tk.X, pady=(6, 0))
        tunnel_row = tk.Frame(conn_card, bg=_BW_PANEL_BG)
        tunnel_row.pack(fill=tk.X, pady=(5, 0))
        tk.Checkbutton(
            tunnel_row,
            text="🌐 Compartir por Internet (túnel Cloudflare gratuito, sin abrir puertos)",
            variable=use_tunnel_var,
            bg="#FFFFFF",
            fg="#0F172A",
            bg=_BW_PANEL_BG,
            fg="#E2E8F0",
            selectcolor="#0F172A",
            activebackground=_BW_PANEL_BG,
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        ).pack(side=tk.LEFT)

        tk.Label(tunnel_row, text="PIN (opcional):", font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#475569").pack(side=tk.RIGHT, padx=(8, 4))
        tk.Entry(tunnel_row, textvariable=pin_var, font=("Segoe UI", 8), width=10, show="•", relief="solid", bd=1).pack(side=tk.RIGHT)
        tk.Label(tunnel_row, text="PIN (opcional):", font=("Segoe UI", 8, "bold"), bg=_BW_PANEL_BG, fg="#94A3B8").pack(side=tk.RIGHT, padx=(8, 4))
        tk.Entry(
            tunnel_row, textvariable=pin_var, font=("Consolas", 8), width=10,
            show="•", relief="solid", bd=1, bg="#0B161E", fg="#F8FAFC", insertbackground="#38BDF8"
        ).pack(side=tk.RIGHT)

        btn_row = tk.Frame(conn_card, bg="#FFFFFF")
        btn_row.pack(fill=tk.X, pady=(8, 4))
        btn_row = tk.Frame(conn_card, bg=_BW_PANEL_BG)
        btn_row.pack(fill=tk.X, pady=(7, 3))

        tk.Button(btn_row, text="▶ Abrir Sala", bg="#16A34A", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), padx=12, pady=4, command=do_connect, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="⏹ Cerrar", bg="#64748B", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), padx=10, pady=4, command=do_disconnect, cursor="hand2").pack(side=tk.LEFT, padx=(0, 12))
        tk.Button(btn_row, text="📋 Copiar enlace", bg="#0EA5E9", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), padx=10, pady=4, command=copy_invite, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="🌐 Probar en navegador", bg="#4F46E5", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), padx=10, pady=4, command=open_in_browser, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="🔄 Nuevo enlace", bg="#F59E0B", fg="#1E293B", font=("Segoe UI", 9, "bold"), padx=8, pady=4, command=rotate_invite, cursor="hand2").pack(side=tk.LEFT)
        tk.Button(btn_row, text="▶ Abrir Sala", bg="#16A34A", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), relief="solid", bd=1, padx=12, pady=3, command=do_connect, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="⏹ Cerrar", bg="#475569", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), relief="solid", bd=1, padx=10, pady=3, command=do_disconnect, cursor="hand2").pack(side=tk.LEFT, padx=(0, 12))
        tk.Button(btn_row, text="📋 Copiar enlace", bg="#0284C7", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), relief="solid", bd=1, padx=10, pady=3, command=copy_invite, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="🌐 Probar en navegador", bg="#4F46E5", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), relief="solid", bd=1, padx=10, pady=3, command=open_in_browser, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="🔄 Nuevo enlace", bg="#D97706", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), relief="solid", bd=1, padx=8, pady=3, command=rotate_invite, cursor="hand2").pack(side=tk.LEFT)

        tk.Label(
            conn_card,
            text="1) Haz clic en 'Abrir Sala'   2) Copia el enlace y envíalo   3) Acepta a tus amigos abajo en el Lobby.",
            text="1) Pulsa 'Abrir Sala'   2) Copia y comparte el enlace   3) Acepta a tus compañeros en el C-Gear abajo.",
            font=("Segoe UI", 8),
            bg="#FFFFFF",
            fg="#64748B",
            bg=_BW_PANEL_BG,
            fg="#7DD3FC",
        ).pack(anchor=tk.W, pady=(2, 0))

        # Barra transparente de progreso (solo visible al descargar o abrir túnel)
        progress_frame = tk.Frame(conn_card, bg="#F0F9FF", highlightthickness=1, highlightbackground="#BAE6FD", padx=8, pady=6)
        progress_lbl = tk.Label(progress_frame, text="", font=("Segoe UI", 8, "bold"), bg="#F0F9FF", fg="#0369A1", anchor=tk.W)
        # Barra de progreso (descarga / túnel)
        progress_frame = tk.Frame(conn_card, bg="#0F2936", highlightthickness=1, highlightbackground="#38BDF8", padx=8, pady=6)
        progress_lbl = tk.Label(progress_frame, text="", font=("Segoe UI", 8, "bold"), bg="#0F2936", fg="#7DD3FC", anchor=tk.W)
        progress_lbl.pack(fill=tk.X)
        progress_bar = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        progress_bar.pack(fill=tk.X, pady=(4, 0))
        progress_state = {"visible": False, "indeterminate": False}

        # Panel avanzado (oculto por defecto)
        adv_frame = tk.Frame(conn_card, bg="#F8FAFC", highlightthickness=1, highlightbackground="#E2E8F0", padx=8, pady=6)
        adv_frame = tk.Frame(conn_card, bg="#0C1C24", highlightthickness=1, highlightbackground="#2B5B6E", padx=8, pady=6)

        row1 = tk.Frame(adv_frame, bg="#F8FAFC")
        row1 = tk.Frame(adv_frame, bg="#0C1C24")
        row1.pack(fill=tk.X, pady=2)
        tk.Label(row1, text="Relay WSS:", font=("Segoe UI", 8, "bold"), bg="#F8FAFC", width=12, anchor=tk.W).pack(side=tk.LEFT)
        tk.Entry(row1, textvariable=relay_var, font=("Segoe UI", 8), width=36).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(row1, text="Relay WSS:", font=("Segoe UI", 8, "bold"), bg="#0C1C24", fg="#CBD5E1", width=12, anchor=tk.W).pack(side=tk.LEFT)
        tk.Entry(row1, textvariable=relay_var, font=("Consolas", 8), width=36, bg="#081218", fg="#F8FAFC", insertbackground="#38BDF8").pack(side=tk.LEFT, padx=(0, 8))
        tk.Checkbutton(
            row1, text="Permitir ws://127.0.0.1 (local)", variable=local_dev_var, bg="#F8FAFC", font=("Segoe UI", 8)
            row1, text="Permitir ws://127.0.0.1 (local)", variable=local_dev_var,
            bg="#0C1C24", fg="#CBD5E1", selectcolor="#081218", activebackground="#0C1C24", font=("Segoe UI", 8)
        ).pack(side=tk.LEFT)

        row2 = tk.Frame(adv_frame, bg="#F8FAFC")
        row2 = tk.Frame(adv_frame, bg="#0C1C24")
        row2.pack(fill=tk.X, pady=2)
        tk.Label(row2, text="Web Invitado:", font=("Segoe UI", 8, "bold"), bg="#F8FAFC", width=12, anchor=tk.W).pack(side=tk.LEFT)
        tk.Entry(row2, textvariable=web_var, font=("Segoe UI", 8), width=36).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(row2, text="Web Invitado:", font=("Segoe UI", 8, "bold"), bg="#0C1C24", fg="#CBD5E1", width=12, anchor=tk.W).pack(side=tk.LEFT)
        tk.Entry(row2, textvariable=web_var, font=("Consolas", 8), width=36, bg="#081218", fg="#F8FAFC", insertbackground="#38BDF8").pack(side=tk.LEFT, padx=(0, 8))

        invite_lbl = tk.Label(row2, text="Sala: —", font=("Segoe UI", 8, "bold"), bg="#F8FAFC", fg="#1E293B")
        invite_lbl = tk.Label(row2, text="Sala: —", font=("Consolas", 8, "bold"), bg="#0C1C24", fg="#38BDF8")
        invite_lbl.pack(side=tk.RIGHT)

        def refresh_invite_label():
            rc = getattr(self.coop_relay_client, "room_code", None)
            if not rc:
                invite_lbl.config(text="Sala: —")
            elif show_secrets_var.get():
                invite_lbl.config(text=f"Sala: {rc}")
            else:
                invite_lbl.config(text="Sala: ••••••••")

        tk.Checkbutton(row2, text="👁", variable=show_secrets_var, bg="#F8FAFC", command=refresh_invite_label).pack(side=tk.RIGHT)
        tk.Checkbutton(
            row2, text="👁", variable=show_secrets_var,
            bg="#0C1C24", fg="#CBD5E1", selectcolor="#081218", activebackground="#0C1C24",
            command=refresh_invite_label
        ).pack(side=tk.RIGHT)

        def toggle_advanced():
            if advanced_open.get():
                advanced_open.set(False)
                adv_frame.pack_forget()
                adv_btn.config(text="⚙ Avanzado ▾")
            else:
                advanced_open.set(True)
                adv_frame.pack(fill=tk.X, pady=(6, 0))
                adv_btn.config(text="⚙ Avanzado ▴")

        adv_btn.config(command=toggle_advanced)

        # Entrada a la Sala estilo PictoChat (Lobby de aprobación)
        lobby_card = tk.Frame(dlg, bg="#F8FAFC", highlightthickness=2, highlightbackground="#334155")
        lobby_card.pack(fill=tk.X, padx=14, pady=4)
        picto_bar = tk.Frame(lobby_card, bg="#334155", padx=10, pady=4)
        # =====================================================================
        # SECCIÓN DE EQUIPO POKÉMON BLANCO Y NEGRO (RETÍCULA + GRID 2x2)
        # =====================================================================
        party_w = dlg_w - 28
        party_h = 340
        party_canvas = tk.Canvas(content, bg=_BW_BG, highlightthickness=0, bd=0, width=party_w, height=party_h)
        party_canvas.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 6))
        _draw_bw_reticle(party_canvas, party_w, party_h)

        # Sub-header flotante dentro del área de equipo
        # (Colocamos los 4 slots 1P, 2P, 3P, 4P directamente sobre el canvas para que se vea la retícula)
        slot_cards = {}
        perm_labels = {"emotion": "Emociones", "prop": "Props", "flip_x": "Flip X", "scream": "Grito", "character": "Personaje"}

        pad_x = 10
        pad_y = 8
        gap_x = 18
        gap_y = 14
        card_w = (party_w - (pad_x * 2) - gap_x) // 2
        card_h = (party_h - (pad_y * 2) - gap_y) // 2

        def _build_party_card(row_idx: int, col_idx: int, slot_num: int, is_lead: bool = False):
            bg_col = _BW_SLOT_LEAD_BG if is_lead else _BW_SLOT_OFF_BG
            bd_col = _BW_SLOT_LEAD_BD if is_lead else _BW_SLOT_OFF_BD

            card = tk.Frame(
                party_canvas, bg=bg_col,
                highlightthickness=2, highlightbackground=bd_col,
                padx=10, pady=8,
            )
            cx = pad_x + col_idx * (card_w + gap_x)
            cy = pad_y + row_idx * (card_h + gap_y)
            party_canvas.create_window(cx, cy, anchor="nw", window=card, width=card_w, height=card_h)

            # Fila superior: Pokéball + Nombre + Badges/Botones
            top_f = tk.Frame(card, bg=bg_col)
            top_f.pack(fill=tk.X)

            ball_cv = tk.Canvas(top_f, width=32, height=32, bg=bg_col, highlightthickness=0, bd=0)
            ball_cv.pack(side=tk.LEFT, padx=(0, 8))
            _draw_pokeball(ball_cv, active=is_lead, is_lead=is_lead)

            info_f = tk.Frame(top_f, bg=bg_col)
            info_f.pack(side=tk.LEFT, fill=tk.X, expand=True)

            slot_tag = "★ 1P LÍDER" if is_lead else f"{slot_num}P COMPAÑERO"
            tag_bg = "#FACC15" if is_lead else "#1E293B"
            tag_fg = "#0F172A" if is_lead else "#94A3B8"

            title_row = tk.Frame(info_f, bg=bg_col)
            title_row.pack(fill=tk.X)

            badge_lbl = tk.Label(
                title_row, text=f" {slot_tag} ", font=("Consolas", 8, "bold"),
                bg=tag_bg, fg=tag_fg, padx=4, pady=0
            )
            badge_lbl.pack(side=tk.LEFT, padx=(0, 6))

            name_lbl = tk.Label(
                title_row,
                text=("ANFITRIÓN (TÚ)" if is_lead else "RANURA VACÍA"),
                font=("Segoe UI", 10, "bold"),
                bg=bg_col,
                fg="#F8FAFC" if is_lead else "#64748B",
                anchor=tk.W,
            )
            name_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

            sub_lbl = tk.Label(
                info_f,
                text=("Listo en sala" if is_lead else "Esperando invitado..."),
                font=("Consolas", 8),
                bg=bg_col,
                fg="#7DD3FC" if is_lead else "#475569",
                anchor=tk.W,
            )
            sub_lbl.pack(fill=tk.X, pady=(1, 0))

            # Botones de acción (OBS / Expulsar) solo para slots remotos
            btns_f = tk.Frame(top_f, bg=bg_col)
            btns_f.pack(side=tk.RIGHT, anchor=tk.N)
            if not is_lead:
                if slot_num in (3, 4):
                    tk.Button(
                        btns_f,
                        text=f"🪟 OBS",
                        font=("Segoe UI", 8, "bold"),
                        bg="#4F46E5",
                        fg="#FFFFFF",
                        relief="solid",
                        bd=1,
                        padx=6,
                        pady=1,
                        cursor="hand2",
                        command=lambda s=slot_num: self.open_remote_avatar_window(s),
                    ).pack(side=tk.LEFT, padx=(0, 4))
                tk.Button(
                    btns_f,
                    text="✕",
                    font=("Consolas", 8, "bold"),
                    bg="#DC2626",
                    fg="#FFFFFF",
                    relief="solid",
                    bd=1,
                    padx=6,
                    pady=1,
                    cursor="hand2",
                    command=lambda s=slot_num: self.kick_coop_guest(s, ban=False),
                ).pack(side=tk.LEFT)

            # Barra estilo HP de Pokémon BW (Nivel de voz / señal)
            hp_row = tk.Frame(card, bg=bg_col)
            hp_row.pack(fill=tk.X, pady=(8, 4))

            tk.Label(
                hp_row, text="VOZ", font=("Consolas", 8, "bold"),
                bg="#0B1319", fg="#FACC15", padx=4, pady=0
            ).pack(side=tk.LEFT)

            hp_canvas = tk.Canvas(hp_row, height=12, bg=_BW_HP_TRACK, highlightthickness=1, highlightbackground="#334155")
            hp_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 6))

            hp_val_lbl = tk.Label(
                hp_row, text=("ONLINE" if is_lead else "LIBRE"),
                font=("Consolas", 8, "bold"), bg=bg_col,
                fg="#4ADE80" if is_lead else "#475569", width=8, anchor=tk.E
            )
            hp_val_lbl.pack(side=tk.RIGHT)

            # Permisos / Notas en la parte inferior de la tarjeta
            perm_f = tk.Frame(card, bg=bg_col)
            perm_f.pack(fill=tk.X, pady=(4, 0))
            perm_widgets = []

            if is_lead:
                lead_note = tk.Label(
                    perm_f,
                    text="Control total de la sala, aprobaciones y mezcla de audio.",
                    font=("Segoe UI", 8),
                    bg=bg_col,
                    fg="#BAE6FD",
                    anchor=tk.W,
                )
                lead_note.pack(fill=tk.X)
                perm_widgets.append(lead_note)
            else:
                p_vars = {}
                cur_perms = self.guest_executor.get_permissions(slot_num)
                for idx, k in enumerate(PERMISSION_KEYS):
                    var = tk.BooleanVar(value=bool(cur_perms.get(k, False)))
                    p_vars[k] = var
                    cb = tk.Checkbutton(
                        perm_f,
                        text=perm_labels[k],
                        variable=var,
                        bg=bg_col,
                        fg="#CBD5E1",
                        selectcolor="#0A1218",
                        activebackground=bg_col,
                        activeforeground="#FFFFFF",
                        font=("Segoe UI", 8),
                        cursor="hand2",
                        command=lambda s=slot_num, pv=p_vars: self.update_guest_slot_permissions(
                            s, {pk: v.get() for pk, v in pv.items()}
                        ),
                    )
                    cb.grid(row=idx // 3, column=idx % 3, sticky=tk.W, padx=(0, 6), pady=1)
                    perm_widgets.append(cb)

            slot_cards[slot_num] = {
                "card": card,
                "top_f": top_f,
                "info_f": info_f,
                "title_row": title_row,
                "btns_f": btns_f,
                "hp_row": hp_row,
                "perm_f": perm_f,
                "perm_widgets": perm_widgets,
                "ball_cv": ball_cv,
                "badge_lbl": badge_lbl,
                "name_lbl": name_lbl,
                "sub_lbl": sub_lbl,
                "hp_canvas": hp_canvas,
                "hp_val_lbl": hp_val_lbl,
                "last_active": None,
            }

        # Distribución 2x2: 1P (izq arriba), 2P (der arriba), 3P (izq abajo), 4P (der abajo)
        _build_party_card(0, 0, 1, is_lead=True)
        _build_party_card(0, 1, 2, is_lead=False)
        _build_party_card(1, 0, 3, is_lead=False)
        _build_party_card(1, 1, 4, is_lead=False)

        def _paint_hp_bar(cv: tk.Canvas, pct: float, active: bool):
            cv.delete("bar")
            w = max(cv.winfo_width(), 120)
            h = max(cv.winfo_height(), 12)
            if not active:
                return
            fill_pct = max(0.06, min(1.0, pct / 100.0)) if pct > 0 else 0.08
            bar_w = int((w - 2) * fill_pct)
            col = _BW_HP_RED if pct >= 70 else (_BW_HP_YELLOW if pct >= 40 else _BW_HP_GREEN)
            cv.create_rectangle(1, 1, 1 + bar_w, h - 1, fill=col, width=0, tags="bar")

        def _recolor_card(sc: dict, bg_col: str, bd_col: str):
            sc["card"].config(bg=bg_col, highlightbackground=bd_col)
            for key in ("top_f", "info_f", "title_row", "btns_f", "hp_row", "perm_f", "ball_cv", "name_lbl", "sub_lbl", "hp_val_lbl"):
                sc[key].config(bg=bg_col)
            for w in sc["perm_widgets"]:
                w.config(bg=bg_col, activebackground=bg_col)

        # =====================================================================
        # BARRA INFERIOR C-GEAR: SOLICITUDES DE ENTRADA
        # =====================================================================
        lobby_card = tk.Frame(
            content, bg=_BW_PANEL_BG,
            highlightthickness=2, highlightbackground="#38BDF8"
        )
        lobby_card.pack(fill=tk.X, padx=14, pady=(2, 12))

        picto_bar = tk.Frame(lobby_card, bg="#0B141B", padx=10, pady=4)
        picto_bar.pack(fill=tk.X)
        tk.Label(
            picto_bar,
            text="💬 ENTRADA A LA SALA (PICTOCHAT)",
            text="📡 ENTRADA A LA SALA (C-GEAR)",
            font=("Consolas", 9, "bold"),
            bg="#334155",
            fg="#F8FAFC",
            bg="#0B141B",
            fg="#38BDF8",
        ).pack(side=tk.LEFT)
        picto_count_lbl = tk.Label(
            picto_bar,
            text="0 solicitudes",
            font=("Consolas", 8, "bold"),
            bg="#334155",
            fg="#93C5FD",
            bg="#0B141B",
            fg="#2DD4BF",
        )
        picto_count_lbl.pack(side=tk.RIGHT)

        lobby_list_frame = tk.Frame(lobby_card, bg="#F8FAFC", padx=8, pady=6)
        lobby_list_frame = tk.Frame(lobby_card, bg=_BW_PANEL_BG, padx=8, pady=6)
        lobby_list_frame.pack(fill=tk.X)

        # Slots 2P / 3P / 4P
        slots_card = tk.Frame(dlg, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", padx=12, pady=8)
        slots_card.pack(fill=tk.BOTH, expand=True, padx=14, pady=(4, 12))
        tk.Label(slots_card, text="👥 Jugadores Remotos (2P, 3P, 4P)", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#1E293B").pack(anchor=tk.W, pady=(0, 6))
        last_lobby_sig = {"sig": None}

        slot_widgets = {}
        perm_labels = {"emotion": "Emociones", "prop": "Props", "flip_x": "Flip X", "scream": "Grito", "character": "Personaje"}

        for slot in VALID_SLOTS:
            sf = tk.Frame(slots_card, bg="#F8FAFC", highlightthickness=1, highlightbackground="#CBD5E1", padx=10, pady=6)
            sf.pack(fill=tk.X, pady=4)

            top = tk.Frame(sf, bg="#F8FAFC")
            top.pack(fill=tk.X)
            lbl = tk.Label(top, text=f"{slot}P: Libre", font=("Segoe UI", 9, "bold"), bg="#F8FAFC", fg="#475569")
            lbl.pack(side=tk.LEFT)

            if slot in (3, 4):
                tk.Button(
                    top,
                    text=f"🪟 Abrir OBS {slot}P",
                    font=("Segoe UI", 8, "bold"),
                    bg="#6366F1",
                    fg="#FFFFFF",
                    padx=8,
                    pady=1,
                    cursor="hand2",
                    command=lambda s=slot: self.open_remote_avatar_window(s),
                ).pack(side=tk.RIGHT, padx=(4, 0))

            tk.Button(
                top,
                text="Expulsar",
                font=("Segoe UI", 8, "bold"),
                bg="#EF4444",
                fg="#FFFFFF",
                padx=8,
                pady=1,
                cursor="hand2",
                command=lambda s=slot: self.kick_coop_guest(s, ban=False),
            ).pack(side=tk.RIGHT, padx=(4, 0))

            perm_row = tk.Frame(sf, bg="#F8FAFC")
            perm_row.pack(fill=tk.X, pady=(4, 0))
            p_vars = {}
            cur_perms = self.guest_executor.get_permissions(slot)
            for k in PERMISSION_KEYS:
                var = tk.BooleanVar(value=bool(cur_perms.get(k, False)))
                p_vars[k] = var
                tk.Checkbutton(
                    perm_row,
                    text=perm_labels[k],
                    variable=var,
                    bg="#F8FAFC",
                    font=("Segoe UI", 8),
                    command=lambda s=slot, pv=p_vars: self.update_guest_slot_permissions(s, {pk: v.get() for pk, v in pv.items()}),
                ).pack(side=tk.LEFT, padx=(0, 8))

            slot_widgets[slot] = lbl

        # =====================================================================
        # BUCLE DE REFRESCO EN VIVO
        # =====================================================================
        def refresh_ui():
            if not dlg.winfo_exists():
                return
            lch = getattr(self, "local_coop_host", None)
            t_state = getattr(lch, "tunnel_state", "idle")
            t_err = getattr(lch, "tunnel_error", "")
            dl_bytes = getattr(lch, "download_bytes", 0)
            dl_total = getattr(lch, "download_total", 0)

            def _show_progress(text, pct=None):
                if not progress_state["visible"]:
                    progress_frame.pack(fill=tk.X, pady=(6, 0))
                    progress_state["visible"] = True
                progress_lbl.config(text=text)
                if pct is None:
                    if not progress_state["indeterminate"]:
                        progress_bar.config(mode="indeterminate")
                        progress_bar.start(12)
                        progress_state["indeterminate"] = True
                else:
                    if progress_state["indeterminate"]:
                        progress_bar.stop()
                        progress_bar.config(mode="determinate")
                        progress_state["indeterminate"] = False
                    progress_bar["value"] = max(0, min(100, pct))

            def _hide_progress():
                if progress_state["indeterminate"]:
                    progress_bar.stop()
                    progress_state["indeterminate"] = False
                if progress_state["visible"]:
                    progress_frame.pack_forget()
                    progress_state["visible"] = False

            if t_state == "downloading":
                status_lbl.config(text="🟡 Descargando cloudflared (1 sola vez)...", fg="#B45309")
                status_lbl.config(text="🟡 Descargando cloudflared (1 sola vez)...", fg="#FACC15")
                mb_done = dl_bytes / (1024 * 1024)
                if dl_total > 0:
                    mb_tot = dl_total / (1024 * 1024)
                    pct = int((dl_bytes * 100) / dl_total)
                    _show_progress(f"Paso 1/2: Descargando cloudflared oficial desde GitHub ({mb_done:.1f} MB / {mb_tot:.1f} MB — {pct}%)", pct)
                else:
                    _show_progress(f"Paso 1/2: Descargando cloudflared oficial desde GitHub ({mb_done:.1f} MB)...", None)
            elif t_state == "starting":
                status_lbl.config(text="🟡 Abriendo túnel de Internet...", fg="#B45309")
                status_lbl.config(text="🟡 Abriendo túnel de Internet...", fg="#FACC15")
                _show_progress("Paso 2/2: Conectando con Cloudflare para crear tu enlace seguro (5–10 s)...", None)
            elif t_state == "error":
                status_lbl.config(text=f"🔴 Error de túnel: {t_err[:38]}", fg="#DC2626")
                status_lbl.config(text=f"🔴 Error de túnel: {t_err[:38]}", fg="#F87171")
                _hide_progress()
            elif self.coop_relay_client.connected and t_state == "ready":
                status_lbl.config(text="🟢 Sala activa por Internet (Túnel listo)", fg="#15803D")
                status_lbl.config(text="🟢 Sala activa por Internet (Túnel listo)", fg="#4ADE80")
                _hide_progress()
            elif self.coop_relay_client.connected:
                status_lbl.config(text="🟢 Sala activa (Solo local)", fg="#15803D")
                status_lbl.config(text="🟢 Sala activa (Solo local)", fg="#4ADE80")
                _hide_progress()
            else:
                status_lbl.config(text="⚪ Sala cerrada", fg="#64748B")
                status_lbl.config(text="⚪ Sala cerrada", fg="#94A3B8")
                _hide_progress()
            refresh_invite_label()

            snap = self.guest_inbox.status_snapshot()["slots"]
            voice_snap = {}
            try:
                voice_snap = self.guest_inbox.voice_snapshot()
            except Exception:
                voice_snap = {}

            # Actualizar 1P Lead
            p1_sc = slot_cards[1]
            p1_char = ""
            try:
                p1_char = str((getattr(self, "p1_data", None) or {}).get("character_name") or "").strip()
            except Exception:
                p1_char = ""
            p1_sc["sub_lbl"].config(text=f"Personaje: {p1_char}" if p1_char else "Anfitrión de la sala")
            _paint_hp_bar(p1_sc["hp_canvas"], 30.0 if self.coop_relay_client.connected else 12.0, True)
            p1_sc["hp_val_lbl"].config(
                text=("ACTIVO" if self.coop_relay_client.connected else "LISTO"),
                fg="#4ADE80" if self.coop_relay_client.connected else "#7DD3FC",
            )

            # Actualizar 2P, 3P, 4P
            remote_players = getattr(self, "remote_players", {}) or {}
            for slot in VALID_SLOTS:
                info = snap[slot]
                if info["connected"]:
                    bg_note = " (segundo plano)" if not info["foreground"] else ""
                    slot_widgets[slot].config(
                        text=f"{slot}P: 🟢 {info['display_name']}#{info['tag']}{bg_note}",
                        fg="#15803D",
                sc = slot_cards[slot]
                is_conn = bool(info["connected"])
                if sc["last_active"] != is_conn:
                    sc["last_active"] = is_conn
                    if is_conn:
                        _recolor_card(sc, _BW_SLOT_ON_BG, _BW_SLOT_ON_BD)
                        _draw_pokeball(sc["ball_cv"], active=True, is_lead=False)
                        sc["badge_lbl"].config(bg="#2DD4BF", fg="#0F172A")
                    else:
                        _recolor_card(sc, _BW_SLOT_OFF_BG, _BW_SLOT_OFF_BD)
                        _draw_pokeball(sc["ball_cv"], active=False, is_lead=False)
                        sc["badge_lbl"].config(bg="#1E293B", fg="#94A3B8")

                if is_conn:
                    bg_note = " (2º plano)" if not info["foreground"] else ""
                    g_name = f"{info['display_name']}#{info['tag']}{bg_note}"
                    char_name = str((remote_players.get(slot) or {}).get("character_name") or "").strip()
                    sc["name_lbl"].config(text=g_name, fg="#F8FAFC")
                    sc["sub_lbl"].config(
                        text=(f"Avatar: {char_name}" if char_name else "Conectado en la sala"),
                        fg="#99F6E4",
                    )
                    lvl = float(voice_snap.get(slot, 0.0) or 0.0)
                    _paint_hp_bar(sc["hp_canvas"], lvl, True)
                    sc["hp_val_lbl"].config(text=f"{int(lvl):>3d}%", fg="#4ADE80" if lvl < 70 else "#FACC15")
                    slot_pills[slot].config(text=f" {slot}P ON ", bg="#16A34A", fg="#FFFFFF")
                else:
                    slot_widgets[slot].config(text=f"{slot}P: ⚪ Libre", fg="#64748B")
                    slot_pills[slot].config(text=f" {slot}P — ", bg="#334155", fg="#94A3B8")
                    sc["name_lbl"].config(text="RANURA VACÍA", fg="#64748B")
                    sc["sub_lbl"].config(text="Esperando invitado...", fg="#475569")
                    _paint_hp_bar(sc["hp_canvas"], 0.0, False)
                    sc["hp_val_lbl"].config(text="LIBRE", fg="#475569")
                    slot_pills[slot].config(text=f" {slot}P — ", bg="#1E293B", fg="#64748B")

            # Feed estilo PictoChat (estado + conectados + solicitudes)
            for child in lobby_list_frame.winfo_children():
                child.destroy()
            # Feed C-Gear de solicitudes (solo reconstruye si cambió el estado)
            reqs = list(getattr(self, "_pending_join_requests", []))
            picto_count_lbl.config(text=f"{len(reqs)} pendiente{'s' if len(reqs) != 1 else ''}")

            if not self.coop_relay_client.connected:
                tk.Label(
                    lobby_list_frame,
                    text="» Sala cerrada. Pulsa '▶ Abrir Sala' arriba para abrir el chat.",
                    font=("Consolas", 8),
                    bg="#E2E8F0",
                    fg="#475569",
                    anchor=tk.W,
                    padx=8,
                    pady=4,
                ).pack(fill=tk.X, pady=1)
            else:
                connected_msgs = [
                    f"» 🟢 {snap[s]['display_name']}#{snap[s]['tag']} entró a la sala ({s}P)"
                    for s in VALID_SLOTS if snap[s]["connected"]
                ]
                if connected_msgs:
            cur_sig = (
                bool(self.coop_relay_client.connected),
                tuple((s, bool(snap[s]["connected"]), snap[s].get("display_name", ""), snap[s].get("tag", "")) for s in VALID_SLOTS),
                tuple((r["req_id"], r.get("display_name", ""), r.get("tag", "")) for r in reqs),
            )
            if cur_sig != last_lobby_sig["sig"]:
                last_lobby_sig["sig"] = cur_sig
                for child in lobby_list_frame.winfo_children():
                    child.destroy()

                if not self.coop_relay_client.connected:
                    tk.Label(
                        lobby_list_frame,
                        text="» Sala cerrada. Pulsa '▶ Abrir Sala' arriba para activar el C-Gear.",
                        font=("Consolas", 8),
                        bg="#0C1C24",
                        fg="#94A3B8",
                        anchor=tk.W,
                        padx=8,
                        pady=5,
                    ).pack(fill=tk.X, pady=1)
                else:
                    connected_msgs = [
                        f"» 🟢 {snap[s]['display_name']}#{snap[s]['tag']} se unió al equipo ({s}P)"
                        for s in VALID_SLOTS if snap[s]["connected"]
                    ]
                    for c_txt in connected_msgs:
                        tk.Label(
                            lobby_list_frame,
                            text=c_txt,
                            font=("Consolas", 8, "bold"),
                            bg="#DCFCE7",
                            fg="#166534",
                            bg="#0F3A33",
                            fg="#5EEAD4",
                            anchor=tk.W,
                            padx=8,
                            pady=2,
                        ).pack(fill=tk.X, pady=1)
                if not reqs:
                    tk.Label(
                    if not reqs:
                        tk.Label(
                            lobby_list_frame,
                            text="» Buscando señales... Esperando que un amigo entre con tu enlace.",
                            font=("Consolas", 8),
                            bg="#0C1C24",
                            fg="#7DD3FC",
                            anchor=tk.W,
                            padx=8,
                            pady=5,
                            highlightthickness=1,
                            highlightbackground="#1E4B5E",
                        ).pack(fill=tk.X, pady=2)

                for req in reqs:
                    bubble = tk.Frame(
                        lobby_list_frame,
                        text="» Esperando que alguien toque la puerta con tu enlace...",
                        font=("Consolas", 8),
                        bg="#FFFFFF",
                        fg="#64748B",
                        anchor=tk.W,
                        padx=8,
                        pady=4,
                        highlightthickness=1,
                        highlightbackground="#CBD5E1",
                    ).pack(fill=tk.X, pady=2)
                        bg="#163544",
                        highlightthickness=2,
                        highlightbackground="#38BDF8",
                    )
                    bubble.pack(fill=tk.X, pady=3)

            for req in reqs:
                bubble = tk.Frame(
                    lobby_list_frame,
                    bg="#FFFFFF",
                    highlightthickness=2,
                    highlightbackground="#334155",
                )
                bubble.pack(fill=tk.X, pady=3)
                    b_left = tk.Frame(bubble, bg="#163544")
                    b_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

                b_left = tk.Frame(bubble, bg="#FFFFFF")
                b_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                    tag_hdr = tk.Frame(b_left, bg="#0E2530", padx=6, pady=2)
                    tag_hdr.pack(fill=tk.X)
                    tk.Label(
                        tag_hdr,
                        text=f"📩 {req['display_name']}#{req['tag']}  —  ¡Quiere unirse al equipo!",
                        font=("Consolas", 9, "bold"),
                        bg="#0E2530",
                        fg="#F8FAFC",
                    ).pack(side=tk.LEFT)

                tag_hdr = tk.Frame(b_left, bg="#E2E8F0", padx=6, pady=2)
                tag_hdr.pack(fill=tk.X)
                tk.Label(
                    tag_hdr,
                    text=f"📩 {req['display_name']}#{req['tag']}",
                    font=("Consolas", 9, "bold"),
                    bg="#E2E8F0",
                    fg="#0F172A",
                ).pack(side=tk.LEFT)

                tk.Label(
                    b_left,
                    text="¡Hola! Quiero entrar a la sala.",
                    font=("Segoe UI", 9),
                    bg="#FFFFFF",
                    fg="#1E293B",
                    anchor=tk.W,
                    padx=8,
                    pady=4,
                ).pack(fill=tk.X)

                b_actions = tk.Frame(bubble, bg="#F1F5F9", padx=6, pady=6)
                b_actions.pack(side=tk.RIGHT, fill=tk.Y)
                tk.Button(
                    b_actions,
                    text="✕",
                    font=("Consolas", 9, "bold"),
                    bg="#EF4444",
                    fg="#FFFFFF",
                    relief="solid",
                    bd=1,
                    padx=6,
                    cursor="hand2",
                    command=lambda r=req: self.decide_join_request(r["req_id"], False, 2),
                ).pack(side=tk.RIGHT, padx=2)
                for target_s in VALID_SLOTS:
                    b_actions = tk.Frame(bubble, bg="#102935", padx=6, pady=4)
                    b_actions.pack(side=tk.RIGHT, fill=tk.Y)
                    tk.Button(
                        b_actions,
                        text=f"✓ {target_s}P",
                        text="✕",
                        font=("Consolas", 9, "bold"),
                        bg="#16A34A",
                        bg="#EF4444",
                        fg="#FFFFFF",
                        relief="solid",
                        bd=1,
                        padx=6,
                        padx=7,
                        cursor="hand2",
                        command=lambda r=req, s=target_s: self.decide_join_request(r["req_id"], True, s),
                        command=lambda r=req: self.decide_join_request(r["req_id"], False, 2),
                    ).pack(side=tk.RIGHT, padx=2)
                    for target_s in reversed(VALID_SLOTS):
                        tk.Button(
                            b_actions,
                            text=f"✓ {target_s}P",
                            font=("Consolas", 9, "bold"),
                            bg="#16A34A",
                            fg="#FFFFFF",
                            relief="solid",
                            bd=1,
                            padx=7,
                            cursor="hand2",
                            command=lambda r=req, s=target_s: self.decide_join_request(r["req_id"], True, s),
                        ).pack(side=tk.RIGHT, padx=2)

            dlg.after(400, refresh_ui)
            dlg.after(300, refresh_ui)

        refresh_ui()
