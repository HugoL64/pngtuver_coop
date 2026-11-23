"""Diálogo de gestión Co-op por Internet (4 Jugadores, Lobby de Aprobación, Permisos y Pánico)."""

import os
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

from core.app_constants import DATA_DIR
from core.relay_schemas import PERMISSION_KEYS, VALID_SLOTS


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

        dlg = tk.Toplevel(self.root)
        self._coop_dialog = dlg
        dlg.title("🌐 Co-op Remoto (Hasta 4 Jugadores)")
        dlg.geometry("780x680")
        dlg.resizable(False, False)
        dlg.configure(bg="#DFE5EE")
        dlg.transient(self.root)

        self.root.update_idletasks()
        rx = self.root.winfo_x() + (self.root.winfo_width() - 780) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - 680) // 2
        dlg.geometry(f"+{max(10, rx)}+{max(10, ry)}")

        # Cabecera estilo Nintendo DS PictoChat
        hdr = tk.Frame(dlg, bg="#1E293B", padx=16, pady=10)
        hdr.pack(fill=tk.X)
        tk.Label(
            hdr,
            text="💬  PICTOCHAT  //  SALA CO-OP",
            font=("Consolas", 13, "bold"),
            bg="#1E293B",
            fg="#38BDF8",
        ).pack(side=tk.LEFT)

        pills_frame = tk.Frame(hdr, bg="#1E293B")
        pills_frame.pack(side=tk.LEFT, padx=(14, 0))
        tk.Label(
            pills_frame, text=" 1P HOST ", font=("Consolas", 8, "bold"),
            bg="#FACC15", fg="#1E293B", relief="solid", bd=1, padx=4, pady=1
        ).pack(side=tk.LEFT, padx=2)
        slot_pills = {}
        for s in VALID_SLOTS:
            sp = tk.Label(
                pills_frame, text=f" {s}P — ", font=("Consolas", 8, "bold"),
                bg="#334155", fg="#94A3B8", relief="solid", bd=1, padx=4, pady=1
            )
            sp.pack(side=tk.LEFT, padx=2)
            slot_pills[s] = sp

        panic_btn = tk.Button(
            hdr,
            text="🛑 CONGELAR INVITADOS",
            font=("Segoe UI", 9, "bold"),
            bg="#DC2626",
            fg="#FFFFFF",
            relief="solid",
            bd=1,
            padx=10,
            pady=3,
            cursor="hand2",
        )
        panic_btn.pack(side=tk.RIGHT)

        def toggle_panic():
            cur = self.guest_inbox.is_panic_frozen()
            self.guest_inbox.set_panic_freeze(not cur)
            refresh_panic_btn()

        def refresh_panic_btn():
            if self.guest_inbox.is_panic_frozen():
                panic_btn.config(text="▶ REANUDAR INVITADOS", bg="#16A34A")
            else:
                panic_btn.config(text="🛑 CONGELAR INVITADOS", bg="#DC2626")

        panic_btn.config(command=toggle_panic)
        refresh_panic_btn()

        # Tarjeta de conexión al Relay (modo simple + opciones avanzadas plegables)
        conn_card = tk.Frame(dlg, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", padx=12, pady=10)
        conn_card.pack(fill=tk.X, padx=14, pady=(10, 6))

        cfg = self.global_config.setdefault("coop_remote", {})
        relay_var = tk.StringVar(value=cfg.get("relay_url", "ws://127.0.0.1:8766"))
        web_var = tk.StringVar(value=cfg.get("web_url", "http://127.0.0.1:8766"))
        local_dev_var = tk.BooleanVar(value=bool(cfg.get("allow_insecure_local", True)))
        use_tunnel_var = tk.BooleanVar(value=bool(cfg.get("use_tunnel", False)))
        show_secrets_var = tk.BooleanVar(value=False)
        advanced_open = tk.BooleanVar(value=False)

        top_row = tk.Frame(conn_card, bg="#FFFFFF")
        top_row.pack(fill=tk.X)

        status_lbl = tk.Label(top_row, text="⚪ Sala cerrada", font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#64748B")
        status_lbl.pack(side=tk.LEFT)

        adv_btn = tk.Button(
            top_row,
            text="⚙ Avanzado ▾",
            font=("Segoe UI", 8, "bold"),
            bg="#F1F5F9",
            fg="#334155",
            relief="flat",
            padx=8,
            pady=2,
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
        tk.Checkbutton(
            tunnel_row,
            text="🌐 Compartir por Internet (túnel Cloudflare gratuito, sin abrir puertos)",
            variable=use_tunnel_var,
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        ).pack(side=tk.LEFT)

        btn_row = tk.Frame(conn_card, bg="#FFFFFF")
        btn_row.pack(fill=tk.X, pady=(8, 4))

        tk.Button(btn_row, text="▶ Abrir Sala", bg="#16A34A", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), padx=12, pady=4, command=do_connect, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="⏹ Cerrar", bg="#64748B", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), padx=10, pady=4, command=do_disconnect, cursor="hand2").pack(side=tk.LEFT, padx=(0, 12))
        tk.Button(btn_row, text="📋 Copiar enlace", bg="#0EA5E9", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), padx=10, pady=4, command=copy_invite, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="🌐 Probar en navegador", bg="#4F46E5", fg="#FFFFFF", font=("Segoe UI", 9, "bold"), padx=10, pady=4, command=open_in_browser, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="🔄 Nuevo enlace", bg="#F59E0B", fg="#1E293B", font=("Segoe UI", 9, "bold"), padx=8, pady=4, command=rotate_invite, cursor="hand2").pack(side=tk.LEFT)

        tk.Label(
            conn_card,
            text="1) Haz clic en 'Abrir Sala'   2) Copia el enlace y envíalo   3) Acepta a tus amigos abajo en el Lobby.",
            font=("Segoe UI", 8),
            bg="#FFFFFF",
            fg="#64748B",
        ).pack(anchor=tk.W, pady=(2, 0))

        # Barra transparente de progreso (solo visible al descargar o abrir túnel)
        progress_frame = tk.Frame(conn_card, bg="#F0F9FF", highlightthickness=1, highlightbackground="#BAE6FD", padx=8, pady=6)
        progress_lbl = tk.Label(progress_frame, text="", font=("Segoe UI", 8, "bold"), bg="#F0F9FF", fg="#0369A1", anchor=tk.W)
        progress_lbl.pack(fill=tk.X)
        progress_bar = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        progress_bar.pack(fill=tk.X, pady=(4, 0))
        progress_state = {"visible": False, "indeterminate": False}

        # Panel avanzado (oculto por defecto)
        adv_frame = tk.Frame(conn_card, bg="#F8FAFC", highlightthickness=1, highlightbackground="#E2E8F0", padx=8, pady=6)

        row1 = tk.Frame(adv_frame, bg="#F8FAFC")
        row1.pack(fill=tk.X, pady=2)
        tk.Label(row1, text="Relay WSS:", font=("Segoe UI", 8, "bold"), bg="#F8FAFC", width=12, anchor=tk.W).pack(side=tk.LEFT)
        tk.Entry(row1, textvariable=relay_var, font=("Segoe UI", 8), width=36).pack(side=tk.LEFT, padx=(0, 8))
        tk.Checkbutton(
            row1, text="Permitir ws://127.0.0.1 (local)", variable=local_dev_var, bg="#F8FAFC", font=("Segoe UI", 8)
        ).pack(side=tk.LEFT)

        row2 = tk.Frame(adv_frame, bg="#F8FAFC")
        row2.pack(fill=tk.X, pady=2)
        tk.Label(row2, text="Web Invitado:", font=("Segoe UI", 8, "bold"), bg="#F8FAFC", width=12, anchor=tk.W).pack(side=tk.LEFT)
        tk.Entry(row2, textvariable=web_var, font=("Segoe UI", 8), width=36).pack(side=tk.LEFT, padx=(0, 8))

        invite_lbl = tk.Label(row2, text="Sala: —", font=("Segoe UI", 8, "bold"), bg="#F8FAFC", fg="#1E293B")
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
        picto_bar.pack(fill=tk.X)
        tk.Label(
            picto_bar,
            text="💬 ENTRADA A LA SALA (PICTOCHAT)",
            font=("Consolas", 9, "bold"),
            bg="#334155",
            fg="#F8FAFC",
        ).pack(side=tk.LEFT)
        picto_count_lbl = tk.Label(
            picto_bar,
            text="0 solicitudes",
            font=("Consolas", 8, "bold"),
            bg="#334155",
            fg="#93C5FD",
        )
        picto_count_lbl.pack(side=tk.RIGHT)

        lobby_list_frame = tk.Frame(lobby_card, bg="#F8FAFC", padx=8, pady=6)
        lobby_list_frame.pack(fill=tk.X)

        # Slots 2P / 3P / 4P
        slots_card = tk.Frame(dlg, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", padx=12, pady=8)
        slots_card.pack(fill=tk.BOTH, expand=True, padx=14, pady=(4, 12))
        tk.Label(slots_card, text="👥 Jugadores Remotos (2P, 3P, 4P)", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#1E293B").pack(anchor=tk.W, pady=(0, 6))

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
                mb_done = dl_bytes / (1024 * 1024)
                if dl_total > 0:
                    mb_tot = dl_total / (1024 * 1024)
                    pct = int((dl_bytes * 100) / dl_total)
                    _show_progress(f"Paso 1/2: Descargando cloudflared oficial desde GitHub ({mb_done:.1f} MB / {mb_tot:.1f} MB — {pct}%)", pct)
                else:
                    _show_progress(f"Paso 1/2: Descargando cloudflared oficial desde GitHub ({mb_done:.1f} MB)...", None)
            elif t_state == "starting":
                status_lbl.config(text="🟡 Abriendo túnel de Internet...", fg="#B45309")
                _show_progress("Paso 2/2: Conectando con Cloudflare para crear tu enlace seguro (5–10 s)...", None)
            elif t_state == "error":
                status_lbl.config(text=f"🔴 Error de túnel: {t_err[:38]}", fg="#DC2626")
                _hide_progress()
            elif self.coop_relay_client.connected and t_state == "ready":
                status_lbl.config(text="🟢 Sala activa por Internet (Túnel listo)", fg="#15803D")
                _hide_progress()
            elif self.coop_relay_client.connected:
                status_lbl.config(text="🟢 Sala activa (Solo local)", fg="#15803D")
                _hide_progress()
            else:
                status_lbl.config(text="⚪ Sala cerrada", fg="#64748B")
                _hide_progress()
            refresh_invite_label()

            snap = self.guest_inbox.status_snapshot()["slots"]
            for slot in VALID_SLOTS:
                info = snap[slot]
                if info["connected"]:
                    bg_note = " (segundo plano)" if not info["foreground"] else ""
                    slot_widgets[slot].config(
                        text=f"{slot}P: 🟢 {info['display_name']}#{info['tag']}{bg_note}",
                        fg="#15803D",
                    )
                    slot_pills[slot].config(text=f" {slot}P ON ", bg="#16A34A", fg="#FFFFFF")
                else:
                    slot_widgets[slot].config(text=f"{slot}P: ⚪ Libre", fg="#64748B")
                    slot_pills[slot].config(text=f" {slot}P — ", bg="#334155", fg="#94A3B8")

            # Feed estilo PictoChat (estado + conectados + solicitudes)
            for child in lobby_list_frame.winfo_children():
                child.destroy()
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
                    for c_txt in connected_msgs:
                        tk.Label(
                            lobby_list_frame,
                            text=c_txt,
                            font=("Consolas", 8, "bold"),
                            bg="#DCFCE7",
                            fg="#166534",
                            anchor=tk.W,
                            padx=8,
                            pady=2,
                        ).pack(fill=tk.X, pady=1)
                if not reqs:
                    tk.Label(
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

            for req in reqs:
                bubble = tk.Frame(
                    lobby_list_frame,
                    bg="#FFFFFF",
                    highlightthickness=2,
                    highlightbackground="#334155",
                )
                bubble.pack(fill=tk.X, pady=3)

                b_left = tk.Frame(bubble, bg="#FFFFFF")
                b_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

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
                    tk.Button(
                        b_actions,
                        text=f"✓ {target_s}P",
                        font=("Consolas", 9, "bold"),
                        bg="#16A34A",
                        fg="#FFFFFF",
                        relief="solid",
                        bd=1,
                        padx=6,
                        cursor="hand2",
                        command=lambda r=req, s=target_s: self.decide_join_request(r["req_id"], True, s),
                    ).pack(side=tk.RIGHT, padx=2)

            dlg.after(400, refresh_ui)

        refresh_ui()
