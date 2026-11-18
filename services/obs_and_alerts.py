import tkinter as tk
from tkinter import ttk, messagebox
import os
import random
import time

from core.app_constants import log_debug, ScrollableFrame
from ui.avatar_window import AvatarWindow
from core.hotkeys import MODIFIER_VKS, current_modifiers, format_hotkey, pretty_key_label


class ObsAndAlertsMixin:
    # =========================================================================
    # --- ALERTAS TWITCH (RECEPTOR LOCAL) Y OPCIONES EXPERIMENTALES ---
    # =========================================================================
    def _get_twitch_cfg(self):
        cfg = self.global_config.setdefault("twitch_alerts", {})
        cfg.setdefault("enabled", False)
        cfg.setdefault("port", 8765)
        cfg.setdefault("rules", [])
        return cfg

    def _sync_twitch_alert_server(self):
        cfg = self._get_twitch_cfg()
        if cfg.get("enabled", False):
            ok = self.twitch_alert_server.start(cfg.get("port", 8765))
            if ok:
                log_debug(f"[TWITCH] Receptor local escuchando en http://127.0.0.1:{self.twitch_alert_server.port}")
            else:
                log_debug(f"[TWITCH] Error al iniciar receptor local: {self.twitch_alert_server.last_error}")
        else:
            self.twitch_alert_server.stop()

    def _handle_twitch_alert(self, payload):
        ev = str(payload.get("event", "")).strip().lower()
        reward = str(payload.get("reward", "")).strip().lower()
        log_debug(f"[TWITCH] Alerta recibida -> event='{ev}' reward='{reward}' payload={payload}")
        if not ev and not reward:
            return
        cfg = self._get_twitch_cfg()
        matched = False
        for rule in cfg.get("rules", []):
            if not rule.get("enabled", True):
                continue
            r_ev = str(rule.get("event", "")).strip().lower()
            if not r_ev:
                continue
            if r_ev == ev or (reward and r_ev == reward):
                matched = True
                self._trigger_twitch_rule(rule, payload)
        if not matched:
            log_debug(f"[TWITCH] Ninguna regla activa coincidió con event='{ev}' / reward='{reward}'")

    def _trigger_twitch_rule(self, rule, payload=None):
        target_p = rule.get("player", 1)
        players = [1, 2] if str(target_p) == "both" else ([2] if int(target_p) == 2 else [1])
        for pnum in players:
            self._alert_queues[pnum].append(dict(rule))
            if not self._alert_active[pnum]:
                self._run_next_twitch_alert(pnum)

    def _set_player_forced_scream(self, pnum, active):
        if not hasattr(self, "_forced_scream"):
            self._forced_scream = {1: False, 2: False}
        self._forced_scream[pnum] = bool(active)
        if pnum == 1:
            self.p1_is_screaming = bool(active)
            win = self.avatar1_window
            prev = getattr(self, "p1_live_avatar", None)
        else:
            self.p2_is_screaming = bool(active)
            win = self.avatar2_window
            prev = getattr(self, "p2_live_avatar", None)
        if win and win.winfo_exists():
            win._manual_scream = bool(active)
            win.set_screaming(bool(active))
        if prev and prev.winfo_exists():
            prev._manual_scream = bool(active)
            prev.update_state(prev.is_talking, bool(active))

    def _set_player_forced_flip_x(self, pnum, flip_val):
        target_data = self.p1_data if pnum == 1 else self.p2_data
        target_data["flip_x"] = bool(flip_val)
        prev = getattr(self, "p1_live_avatar" if pnum == 1 else "p2_live_avatar", None)
        if prev and prev.winfo_exists():
            prev.flip_x = bool(flip_val)
            prev._rebuild_photo_cache()
            prev._render()
        self._sync_windows_images()

    def _set_player_forced_mute(self, pnum, muted):
        if pnum == 1:
            if bool(self.audio_engine.mic_muted) != bool(muted):
                self.audio_engine.toggle_mic_mute()
        else:
            if bool(self.audio_engine.discord_muted) != bool(muted):
                self.audio_engine.toggle_discord_mute()

    def _run_next_twitch_alert(self, pnum):
        if not self._alert_queues[pnum]:
            self._alert_active[pnum] = False
            base = self._alert_restore.get(pnum)
            self._alert_restore[pnum] = None
            prof_key = f"player{pnum}"
            if base and base in self.profiles.get(prof_key, {}):
                curr_key = "current_p1_profile" if pnum == 1 else "current_p2_profile"
                if self.global_config.get(curr_key) != base:
                    self._choose_character_from_card_list(pnum, base)
            return

        self._alert_active[pnum] = True
        rule = self._alert_queues[pnum].pop(0)
        curr_key = "current_p1_profile" if pnum == 1 else "current_p2_profile"
        prof_key = f"player{pnum}"
        if self._alert_restore.get(pnum) is None:
            self._alert_restore[pnum] = self.global_config.get(curr_key, "")

        action = rule.get("action", "character")
        try:
            dur = max(0.0, float(rule.get("duration", 8.0)))
        except Exception:
            dur = 8.0

        restore_info = {"scream": False, "mute_prev": None, "flip_prev": None}
        log_debug(f"[TWITCH] Ejecutando alerta en {pnum}P: action={action}, char='{rule.get('character', '')}', dur={dur}s")
        if action == "character":
            target_char = rule.get("character", "")
            if target_char and target_char in self.profiles.get(prof_key, {}):
                self._choose_character_from_card_list(pnum, target_char)
        elif action == "random_character":
            names = list(self.profiles.get(prof_key, {}).keys())
            curr_name = self.global_config.get(curr_key, "")
            choices = [n for n in names if n != curr_name] or names
            if choices:
                self._choose_character_from_card_list(pnum, random.choice(choices))
        elif action == "scream":
            self._set_player_forced_scream(pnum, True)
            restore_info["scream"] = True
        elif action == "mute":
            prev_m = bool(self.audio_engine.mic_muted if pnum == 1 else self.audio_engine.discord_muted)
            restore_info["mute_prev"] = prev_m
            self._set_player_forced_mute(pnum, True)
        elif action == "flip_x":
            target_data = self.p1_data if pnum == 1 else self.p2_data
            prev_f = bool(target_data.get("flip_x", False))
            restore_info["flip_prev"] = prev_f
            self._set_player_forced_flip_x(pnum, not prev_f)

        if dur <= 0.0:
            # Cambio permanente (sin restaurar al anterior)
            if action in ("character", "random_character"):
                self._alert_restore[pnum] = None
            self._run_next_twitch_alert(pnum)
            return

        old_tid = self._alert_timer.get(pnum)
        if old_tid:
            try:
                self.root.after_cancel(old_tid)
            except Exception:
                pass
        self._alert_timer[pnum] = self.root.after(
            int(dur * 1000),
            lambda p=pnum, ri=restore_info: self._finish_twitch_alert(p, ri)
        )

    def _finish_twitch_alert(self, pnum, restore_info):
        self._alert_timer[pnum] = None
        if restore_info.get("scream"):
            self._set_player_forced_scream(pnum, False)
        if restore_info.get("mute_prev") is not None:
            self._set_player_forced_mute(pnum, restore_info["mute_prev"])
        if restore_info.get("flip_prev") is not None:
            self._set_player_forced_flip_x(pnum, restore_info["flip_prev"])
        self._run_next_twitch_alert(pnum)

    def _open_twitch_alerts_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("🟣 Alertas de Twitch - PNGTuber Duo Co-op")
        dlg.geometry("860x690")
        dlg.resizable(False, False)
        dlg.configure(bg="#DFE5EE")
        dlg.transient(self.root)
        dlg.grab_set()

        self.root.update_idletasks()
        rx = self.root.winfo_x() + (self.root.winfo_width() - 860) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - 690) // 2
        dlg.geometry(f"+{max(10, rx)}+{max(10, ry)}")

        cfg = self._get_twitch_cfg()
        EVENT_PLACEHOLDER = "Selecciona o escribe un evento..."

        hdr = tk.Frame(dlg, bg="#1E293B", padx=18, pady=12)
        hdr.pack(fill=tk.X)
        hdr_top = tk.Frame(hdr, bg="#1E293B")
        hdr_top.pack(fill=tk.X)
        tk.Label(
            hdr_top, text="🟣  ALERTAS DE TWITCH",
            font=("Segoe UI", 13, "bold"), bg="#1E293B", fg="#C084FC"
        ).pack(side=tk.LEFT)

        def open_help_guide():
            help_win = tk.Toplevel(dlg)
            help_win.title("❓ Cómo conectar Twitch paso a paso")
            help_win.geometry("560x440")
            help_win.resizable(False, False)
            help_win.configure(bg="#FFFFFF")
            help_win.transient(dlg)
            help_win.grab_set()

            tk.Label(
                help_win, text="❓ GUÍA RÁPIDA (SIN SABER DE REDES)",
                font=("Segoe UI", 11, "bold"), bg="#9146FF", fg="#FFFFFF", pady=10
            ).pack(fill=tk.X)

            guide_txt = (
                "No necesitas abrir puertos del router ni saber de redes. Todo funciona dentro de tu propia PC:\n\n"
                "1️⃣ ACTIVA EL INTERRUPTOR\n"
                "   Marca 'Activar alertas de Twitch' hasta que diga 🟢 Listo para recibir alertas.\n\n"
                "2️⃣ CREA O EDITA UNA REGLA\n"
                "   Elige qué evento quieres (ej. follow, sub, bits, raid o el nombre de un canje)\n"
                "   y qué hará tu personaje (cambiar a otra emoción/personaje o gritar unos segundos).\n"
                "   Usa '▶ Probar' para ver cómo se ve sin esperar una alerta real.\n\n"
                "3️⃣ COPIA EL ENLACE Y PÉGALO EN TU PROGRAMA DE ALERTAS\n"
                "   Cada regla tiene su botón '📋 Copiar enlace'. Cópialo y pégalo según uses:\n"
                "   • Streamer.bot: En tu acción → Add Sub-Action → Core → Network → Fetch URL → pega el enlace.\n"
                "   • Mix It Up: En tu comando/evento → Action: Web Request → pega el enlace.\n"
                "   • SAMMI: En tu botón → HTTP Request (GET) → pega el enlace.\n\n"
                "💡 TRUCO: Si pegas ese enlace en Chrome/Edge y presionas Enter, ¡también dispara la alerta!"
            )
            tk.Label(
                help_win, text=guide_txt, font=("Segoe UI", 9),
                bg="#FFFFFF", fg="#1E293B", justify=tk.LEFT, wraplength=520, padx=18, pady=14
            ).pack(fill=tk.BOTH, expand=True)
            tk.Button(
                help_win, text="Entendido", font=("Segoe UI", 9, "bold"),
                bg="#16A34A", fg="#FFFFFF", relief="solid", bd=1, padx=18, pady=4,
                cursor="hand2", command=help_win.destroy
            ).pack(pady=(0, 14))

        tk.Button(
            hdr_top, text="❓ Guía detallada", font=("Segoe UI", 8, "bold"),
            bg="#334155", fg="#F8FAFC", activebackground="#475569", activeforeground="#FFFFFF",
            relief="solid", bd=1, padx=10, pady=2, cursor="hand2", command=open_help_guide
        ).pack(side=tk.RIGHT)

        tk.Label(
            hdr,
            text="Haz que tu personaje cambie o reaccione automáticamente cuando recibas follows, subs, raids o canjes.",
            font=("Segoe UI", 9), bg="#1E293B", fg="#E2E8F0"
        ).pack(anchor=tk.W, pady=(2, 0))

        # 1. Panel superior de conexión + acordeón colapsable con 3 tarjetas de pasos
        srv_card = tk.Frame(dlg, bg="#FFFFFF", highlightthickness=2, highlightbackground="#242E3B", padx=14, pady=10)
        srv_card.pack(fill=tk.X, padx=16, pady=(10, 6))

        top_row = tk.Frame(srv_card, bg="#FFFFFF")
        top_row.pack(fill=tk.X)

        enabled_var = tk.BooleanVar(value=bool(cfg.get("enabled", False)))
        port_var = tk.StringVar(value=str(cfg.get("port", 8765)))
        status_lbl = tk.Label(top_row, text="", font=("Segoe UI", 9, "bold"), bg="#FFFFFF")

        def update_status_label():
            if self.twitch_alert_server.running:
                status_lbl.config(text="🟢 Listo para recibir alertas", fg="#15803D")
            elif self.twitch_alert_server.last_error:
                status_lbl.config(
                    text="🔴 Puerto ocupado (abre ⚙️ Avanzado y cambia el número)",
                    fg="#DC2626"
                )
            else:
                status_lbl.config(text="⚪ Apagado (marca la casilla para encender)", fg="#64748B")

        def apply_server():
            cfg["enabled"] = bool(enabled_var.get())
            try:
                cfg["port"] = max(1024, min(65535, int(port_var.get().strip())))
            except Exception:
                cfg["port"] = 8765
            port_var.set(str(cfg["port"]))
            self._sync_twitch_alert_server()
            self.save_global_config()
            update_status_label()

        tk.Checkbutton(
            top_row, text="Activar alertas de Twitch", variable=enabled_var,
            font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#1E293B",
            activebackground="#FFFFFF", cursor="hand2", command=apply_server
        ).pack(side=tk.LEFT)
        status_lbl.pack(side=tk.LEFT, padx=(14, 0))

        adv_frame = tk.Frame(srv_card, bg="#F8FAFC", padx=10, pady=6, highlightthickness=1, highlightbackground="#CBD5E1")
        adv_frame.pack(fill=tk.X, pady=(8, 0))
        tk.Label(
            adv_frame, text="Puerto local (cámbialo si otro programa ya usa el 8765):",
            font=("Segoe UI", 8), bg="#F8FAFC", fg="#475569"
        ).pack(side=tk.LEFT)
        tk.Entry(adv_frame, textvariable=port_var, width=7, font=("Segoe UI", 8), relief="solid", bd=1).pack(side=tk.LEFT, padx=6)
        tk.Button(
            adv_frame, text="Guardar puerto", font=("Segoe UI", 8, "bold"),
            bg="#3671C6", fg="#FFFFFF", relief="solid", bd=1, padx=8, pady=1,
            cursor="hand2", command=apply_server
        ).pack(side=tk.LEFT)

        update_status_label()

        # Lista de reglas
        rules_sf = ScrollableFrame(dlg, bg="#DFE5EE")
        rules_sf.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)
        rules_body = rules_sf.content

        def get_char_names(p_val):
            if str(p_val) == "2":
                return sorted(self.profiles.get("player2", {}).keys())
            return sorted(self.profiles.get("player1", {}).keys())

        def render_rules():
            for w in rules_body.winfo_children():
                w.destroy()
            rules = cfg.get("rules", [])
            if not rules:
                tk.Label(
                    rules_body,
                    text="No hay reglas todavía. Pulsa '+ Añadir regla' para crear tu primera alerta.",
                    font=("Segoe UI", 9), bg="#DFE5EE", fg="#475569", pady=24
                ).pack()
                return

            ACTION_LABELS = {
                "character": "Cambiar personaje",
                "random_character": "Personaje aleatorio",
                "scream": "Grito temporal",
                "mute": "Silenciar (Mute)",
                "flip_x": "Voltear (Espejo X)",
            }
            LABEL_TO_ACTION = {v: k for k, v in ACTION_LABELS.items()}

            for idx, rule in enumerate(rules):
                is_active = bool(rule.get("enabled", True))
                card = tk.Frame(
                    rules_body,
                    bg="#FFFFFF" if is_active else "#F1F5F9",
                    highlightthickness=2 if is_active else 1,
                    highlightbackground="#94A3B8" if is_active else "#CBD5E1",
                    padx=14, pady=10
                )
                card.pack(fill=tk.X, pady=(0, 10))

                r_enabled = tk.BooleanVar(value=is_active)
                raw_ev = str(rule.get("event", "")).strip()
                r_event = tk.StringVar(value=raw_ev if raw_ev else EVENT_PLACEHOLDER)
                r_player = tk.StringVar(value="Ambos" if str(rule.get("player")) == "both" else ("2P" if str(rule.get("player")) == "2" else "1P"))
                r_action = tk.StringVar(value=ACTION_LABELS.get(rule.get("action", "character"), "Cambiar personaje"))
                r_char = tk.StringVar(value=str(rule.get("character", "")))
                r_dur = tk.StringVar(value=str(rule.get("duration", 8.0)))

                def save_rule(r=rule, ev_v=r_enabled, e_v=r_event, p_v=r_player, a_v=r_action, c_v=r_char, d_v=r_dur):
                    r["enabled"] = bool(ev_v.get())
                    ev_txt = e_v.get().strip()
                    if not ev_txt or ev_txt == EVENT_PLACEHOLDER:
                        r["event"] = ""
                    else:
                        r["event"] = ev_txt.lower()
                    pv = p_v.get()
                    r["player"] = "both" if pv == "Ambos" else (2 if pv == "2P" else 1)
                    r["action"] = LABEL_TO_ACTION.get(a_v.get(), "character")
                    r["character"] = c_v.get()
                    try:
                        r["duration"] = max(0.0, float(d_v.get().strip()))
                    except Exception:
                        r["duration"] = 8.0
                    self.save_global_config()

                # --- FILA 1: Checkbox + Cuando pase + Jugador + Que haga + Eliminar separado ---
                row1 = tk.Frame(card, bg=card["bg"])
                row1.pack(fill=tk.X)

                chk = tk.Checkbutton(row1, variable=r_enabled, bg=card["bg"], activebackground=card["bg"], cursor="hand2")
                chk.pack(side=tk.LEFT, padx=(0, 6))

                lbl_ev = tk.Label(row1, text="Cuando pase:", font=("Segoe UI", 8, "bold"), bg=card["bg"])
                lbl_ev.pack(side=tk.LEFT, padx=(0, 6))

                ev_cb = ttk.Combobox(
                    row1, textvariable=r_event,
                    values=["follow", "sub", "bits", "raid", "canje"],
                    width=24, font=("Segoe UI", 8)
                )
                ev_cb.pack(side=tk.LEFT, padx=(0, 14))
                if not raw_ev:
                    ev_cb.configure(foreground="#94A3B8")

                def on_ev_focus_in(_e, cb=ev_cb, v=r_event):
                    if v.get() == EVENT_PLACEHOLDER:
                        v.set("")
                    cb.configure(foreground="#1E293B")

                def on_ev_focus_out(_e, cb=ev_cb, v=r_event, fn=save_rule):
                    if not v.get().strip():
                        v.set(EVENT_PLACEHOLDER)
                        cb.configure(foreground="#94A3B8")
                    else:
                        cb.configure(foreground="#1E293B")
                    fn()

                ev_cb.bind("<FocusIn>", on_ev_focus_in)
                ev_cb.bind("<FocusOut>", on_ev_focus_out)
                ev_cb.bind("<<ComboboxSelected>>", lambda _e, cb=ev_cb, fn=save_rule: (cb.configure(foreground="#1E293B"), fn()))

                lbl_pl = tk.Label(row1, text="Jugador:", font=("Segoe UI", 8, "bold"), bg=card["bg"])
                lbl_pl.pack(side=tk.LEFT, padx=(0, 6))
                pl_cb = ttk.Combobox(row1, textvariable=r_player, values=["1P", "2P", "Ambos"], width=7, state="readonly", font=("Segoe UI", 8))
                pl_cb.pack(side=tk.LEFT, padx=(0, 14))

                lbl_ac = tk.Label(row1, text="Que haga:", font=("Segoe UI", 8, "bold"), bg=card["bg"])
                lbl_ac.pack(side=tk.LEFT, padx=(0, 6))
                ac_cb = ttk.Combobox(row1, textvariable=r_action, values=list(ACTION_LABELS.values()), width=19, state="readonly", font=("Segoe UI", 8))
                ac_cb.pack(side=tk.LEFT, padx=(0, 10))

                def del_rule(i=idx):
                    cfg["rules"].pop(i)
                    self.save_global_config()
                    render_rules()

                del_btn = tk.Button(
                    row1, text="🗑️", font=("Segoe UI", 9),
                    bg="#FEF2F2", fg="#B91C1C", activebackground="#FEE2E2",
                    relief="solid", bd=1, width=3, cursor="hand2",
                    command=del_rule
                )
                del_btn.pack(side=tk.RIGHT, padx=(18, 0))

                state_badge = tk.Button(
                    row1, text="PAUSADA" if not is_active else "ACTIVA",
                    font=("Segoe UI", 7, "bold"), relief="solid", bd=1,
                    padx=8, pady=1, cursor="hand2"
                )
                state_badge.pack(side=tk.RIGHT, padx=(8, 0))

                # --- FILA 2: Parámetros dependientes (Personaje + Duración) + Acciones (Probar + Copiar enlace) ---
                row2 = tk.Frame(card, bg=card["bg"])
                row2.pack(fill=tk.X, pady=(10, 0))

                lbl_ch = tk.Label(row2, text="Personaje al que cambia:", font=("Segoe UI", 8), bg=card["bg"])
                lbl_ch.pack(side=tk.LEFT, padx=(28, 6))
                p_val = "2" if r_player.get() == "2P" else "1"
                ch_cb = ttk.Combobox(row2, textvariable=r_char, values=get_char_names(p_val), width=24, state="readonly", font=("Segoe UI", 8))
                ch_cb.pack(side=tk.LEFT, padx=(0, 14))
                ch_cb.bind("<<ComboboxSelected>>", lambda _e, fn=save_rule: fn())

                lbl_dur = tk.Label(row2, text="Duración:", font=("Segoe UI", 8), bg=card["bg"])
                lbl_dur.pack(side=tk.LEFT, padx=(0, 6))
                dur_ent = tk.Entry(row2, textvariable=r_dur, width=5, font=("Segoe UI", 8), relief="solid", bd=1, justify=tk.CENTER)
                dur_ent.pack(side=tk.LEFT, padx=(0, 4))
                dur_ent.bind("<FocusOut>", lambda _e, fn=save_rule: fn())
                lbl_seg = tk.Label(row2, text="seg.", font=("Segoe UI", 8), bg=card["bg"])
                lbl_seg.pack(side=tk.LEFT, padx=(0, 16))

                copy_rule_btn = tk.Button(
                    row2, text="📋 Copiar enlace de esta alerta", font=("Segoe UI", 8, "bold"),
                    bg="#E0F2FE", fg="#0369A1", activebackground="#BAE6FD",
                    relief="solid", bd=1, padx=10, pady=2, cursor="hand2"
                )
                copy_rule_btn.pack(side=tk.RIGHT)

                def test_this(fn=save_rule, r=rule):
                    fn()
                    self._trigger_twitch_rule(r, {"event": r.get("event", "test")})

                test_btn = tk.Button(
                    row2, text="▶ Probar", font=("Segoe UI", 8, "bold"),
                    bg="#EDE9FE", fg="#6D28D9", activebackground="#DDD6FE",
                    relief="solid", bd=1, width=10, pady=2, cursor="hand2",
                    command=test_this
                )
                test_btn.pack(side=tk.RIGHT, padx=(0, 10))

                def copy_rule_link(fn=save_rule, r=rule, btn=copy_rule_btn):
                    fn()
                    ev_name = r.get("event") or "sub"
                    port_num = cfg.get("port", 8765)
                    link = f"http://127.0.0.1:{port_num}/trigger?event={ev_name}"
                    dlg.clipboard_clear()
                    dlg.clipboard_append(link)
                    btn.config(text="✅ ¡Enlace copiado!")
                    dlg.after(1400, lambda b=btn: b.config(text="📋 Copiar enlace de esta alerta") if b.winfo_exists() else None)

                copy_rule_btn.config(command=copy_rule_link)

                def apply_card_visual_state(
                    active_flag,
                    c_frame=card, r1=row1, r2=row2, cb_chk=chk,
                    labels=(lbl_ev, lbl_pl, lbl_ac, lbl_ch, lbl_dur, lbl_seg),
                    badge=state_badge, t_btn=test_btn, c_btn=copy_rule_btn,
                    d_ent=dur_ent
                ):
                    bg_c = "#FFFFFF" if active_flag else "#F1F5F9"
                    fg_main = "#334155" if active_flag else "#94A3B8"
                    c_frame.config(
                        bg=bg_c,
                        highlightthickness=2 if active_flag else 1,
                        highlightbackground="#94A3B8" if active_flag else "#CBD5E1"
                    )
                    r1.config(bg=bg_c)
                    r2.config(bg=bg_c)
                    cb_chk.config(bg=bg_c, activebackground=bg_c)
                    for lb in labels:
                        lb.config(bg=bg_c, fg=fg_main)
                    if active_flag:
                        badge.config(text="ACTIVA", bg="#DCFCE7", fg="#15803D")
                        t_btn.config(bg="#EDE9FE", fg="#6D28D9")
                        c_btn.config(bg="#E0F2FE", fg="#0369A1")
                        d_ent.config(fg="#0F172A", bg="#FFFFFF")
                    else:
                        badge.config(text="PAUSADA", bg="#E2E8F0", fg="#64748B")
                        t_btn.config(bg="#E2E8F0", fg="#94A3B8")
                        c_btn.config(bg="#E2E8F0", fg="#94A3B8")
                        d_ent.config(fg="#94A3B8", bg="#F8FAFC")

                def on_chk_toggle(fn=save_rule, ev_v=r_enabled, apply_fn=apply_card_visual_state):
                    fn()
                    apply_fn(bool(ev_v.get()))

                def on_badge_click(ev_v=r_enabled, toggle_fn=on_chk_toggle):
                    ev_v.set(not bool(ev_v.get()))
                    toggle_fn()

                chk.config(command=on_chk_toggle)
                state_badge.config(command=on_badge_click)
                apply_card_visual_state(is_active)

                def on_pl_or_ac(_e=None, fn=save_rule, p_v=r_player, a_v=r_action, c_box=ch_cb):
                    fn()
                    pv = "2" if p_v.get() == "2P" else "1"
                    c_box["values"] = get_char_names(pv)
                    c_box.config(state="readonly" if a_v.get() == "Cambiar personaje" else "disabled")

                pl_cb.bind("<<ComboboxSelected>>", on_pl_or_ac)
                ac_cb.bind("<<ComboboxSelected>>", on_pl_or_ac)
                if r_action.get() != "Cambiar personaje":
                    ch_cb.config(state="disabled")

        render_rules()

        ftr = tk.Frame(dlg, bg="#CBD5E1", padx=16, pady=10, relief="solid", bd=1)
        ftr.pack(fill=tk.X)

        def add_rule():
            p1_names = sorted(self.profiles.get("player1", {}).keys())
            cfg["rules"].append({
                "id": f"rule_{int(time.time() * 1000)}",
                "enabled": True,
                "event": "",
                "player": 1,
                "action": "character",
                "character": p1_names[0] if p1_names else "",
                "duration": 8.0,
            })
            self.save_global_config()
            render_rules()

        tk.Button(
            ftr, text="➕  Añadir regla",
            font=("Segoe UI", 9, "bold"),
            bg="#9146FF", fg="#FFFFFF", activebackground="#772CE8", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=14, pady=4, cursor="hand2",
            command=add_rule
        ).pack(side=tk.LEFT)

        tk.Label(
            ftr, text="💡 Puedes escribir el nombre de tu canje en 'Cuando pase'  •  Duración 0 = permanente",
            font=("Segoe UI", 8), bg="#CBD5E1", fg="#334155"
        ).pack(side=tk.LEFT, padx=(14, 0))

        tk.Button(
            ftr, text="✅  Listo",
            font=("Segoe UI", 10, "bold"),
            bg="#16A34A", fg="#FFFFFF", activebackground="#15803D", activeforeground="#FFFFFF",
            relief="solid", bd=2, padx=18, pady=4, cursor="hand2",
            command=dlg.destroy
        ).pack(side=tk.RIGHT)

    def _open_remote_control_placeholder(self):
        messagebox.showinfo(
            "📱 Control remoto (Experimental)",
            "Esta función está reservada para una próxima actualización.\n\n"
            "Permitirá controlar emociones, silencio y cambio de personajes desde tu celular o tablet en la red local."
        )

    def _open_4p_mode_placeholder(self):
        messagebox.showinfo(
            "👥 4 Players Mode (Experimental)",
            "Esta función está reservada para una próxima actualización.\n\n"
            "Permitirá ampliar la sala de 2 a 4 jugadores simultáneos con sus propias ventanas para OBS."
        )


    # =========================================================================
    # --- VENTANAS DE OBS ---
    # =========================================================================
    def toggle_avatar_windows(self):
        a1_open = self.avatar1_window and self.avatar1_window.winfo_exists()
        a2_open = self.avatar2_window and self.avatar2_window.winfo_exists()

        if a1_open or a2_open:
            log_debug("[OBS] ❌ Cerrando ventanas flotantes de OBS...")
            if a1_open:
                try:
                    self.avatar1_window.destroy()
                except Exception:
                    pass
                self.avatar1_window = None
            if a2_open:
                try:
                    self.avatar2_window.destroy()
                except Exception:
                    pass
                self.avatar2_window = None
            self.btn_open.config(text="🚀 ENVIAR A OBS (Abrir Avatares)", style="DSSend.TButton")
        else:
            log_debug("[OBS] 🚀 Abriendo ventanas flotantes de OBS...")
            self.open_avatar_windows()

    def open_avatar_windows(self):
        # Determinar qué personajes están activos / seleccionados en las tarjetas
        p1_active = self.card_has_selected.get(1, False)
        p2_active = self.card_has_selected.get(2, False)

        # Si el usuario está en el Taller de edición y ninguna tarjeta estaba seleccionada,
        # abrir el personaje que está editando en ese momento
        if not p1_active and not p2_active:
            if self.current_screen == "workshop":
                if self.workshop_player == 1:
                    p1_active = True
                else:
                    p2_active = True
            else:
                messagebox.showinfo(
                    "Selecciona un Personaje",
                    "Por favor selecciona un personaje en la tarjeta del Jugador 1 o del Jugador 2 antes de abrir OBS."
                )
                return

        opened_any = False
        if p1_active:
            self._open_avatar1_window_only()
            opened_any = True

        if p2_active:
            self._open_avatar2_window_only()
            opened_any = True

        if opened_any and self.btn_open:
            self.btn_open.config(text="❌ CERRAR VENTANAS OBS", style="DSBlue.TButton")

    def _get_images_dict(self, player_num):
        target = self.p1_data if player_num == 1 else self.p2_data
        pref = "a1" if player_num == 1 else "a2"
        imgs = {
            "idle": target.get(f"{pref}_idle"),
            "idle_blink": target.get(f"{pref}_idle_blink"),
            "talk": target.get(f"{pref}_talk"),
            "talk_blink": target.get(f"{pref}_talk_blink"),
            "scream": target.get(f"{pref}_scream"),
        }
        for ex in target.get("extra_expressions", []) or []:
            r_id = ex.get("role")
            if r_id:
                imgs[r_id] = target.get(f"{pref}_{r_id}") or ex.get("file")
        return imgs

    def _open_avatar1_window_only(self):
        if self.avatar1_window and self.avatar1_window.winfo_exists():
            return
        bg = self.global_config["bg_color"]
        bounce = self.global_config["bounce_enabled"]
        p1_mode_4 = (self.p1_data.get("image_mode") == "4_states")
        a1_images = self._get_images_dict(1)

        self.avatar1_window = AvatarWindow(
            self.root,
            title="Avatar 1 (Micrófono) - Croma OBS",
            image_dict=a1_images,
            mode_4_states=p1_mode_4,
            bg_color=bg,
            bounce_enabled=bounce,
            on_hotkey=lambda act: self._on_window_hotkey(1, act),
            props_list=self.p1_data.get("props", []),
            motions_map=self._get_motions_dict(1),
            motion_speeds_map=self._get_motion_speeds_dict(1),
            extra_expressions=self.p1_data.get("extra_expressions", []),
            flip_x=bool(self.p1_data.get("flip_x", False)),
            independent_mouth=self.p1_data.get("independent_mouth"),
            independent_eyes=self.p1_data.get("independent_eyes"),
            perf_mode=self.global_config.get("performance_mode", "performance"),
        )
        self.avatar1_window.squash_enabled = self.global_config.get("squash_enabled", True)
        self.avatar1_window.congruence_enabled = self.global_config.get("congruence_enabled", True)
        self.avatar1_window.mouth_flutter_enabled = self.global_config.get("mouth_flutter_enabled", False)
        self.avatar1_window.geometry("450x550+80+100")
        self.avatar1_window.protocol("WM_DELETE_WINDOW", lambda: self._on_avatar_window_closed(1))
        if self.btn_open:
            self.btn_open.config(text="❌ CERRAR VENTANAS OBS", style="DSBlue.TButton")
        self._refresh_eco_mode()
        log_debug("[OBS] ✅ Ventana de Avatar 1 (1P) abierta")

    def _open_avatar2_window_only(self):
        if self.avatar2_window and self.avatar2_window.winfo_exists():
            return
        bg = self.global_config["bg_color"]
        bounce = self.global_config["bounce_enabled"]
        p2_mode_4 = (self.p2_data.get("image_mode") == "4_states")
        a2_images = self._get_images_dict(2)

        self.avatar2_window = AvatarWindow(
            self.root,
            title="Avatar 2 (Discord) - Croma OBS",
            image_dict=a2_images,
            mode_4_states=p2_mode_4,
            bg_color=bg,
            bounce_enabled=bounce,
            on_hotkey=lambda act: self._on_window_hotkey(2, act),
            props_list=self.p2_data.get("props", []),
            motions_map=self._get_motions_dict(2),
            motion_speeds_map=self._get_motion_speeds_dict(2),
            extra_expressions=self.p2_data.get("extra_expressions", []),
            flip_x=bool(self.p2_data.get("flip_x", False)),
            independent_mouth=self.p2_data.get("independent_mouth"),
            independent_eyes=self.p2_data.get("independent_eyes"),
            perf_mode=self.global_config.get("performance_mode", "performance"),
        )
        self.avatar2_window.squash_enabled = self.global_config.get("squash_enabled", True)
        self.avatar2_window.congruence_enabled = self.global_config.get("congruence_enabled", True)
        self.avatar2_window.mouth_flutter_enabled = self.global_config.get("mouth_flutter_enabled", False)
        # Si Avatar 1 no está abierto, posicionar de forma cómoda
        x_pos = 80 if not (self.avatar1_window and self.avatar1_window.winfo_exists()) else 560
        self.avatar2_window.geometry(f"450x550+{x_pos}+100")
        self.avatar2_window.protocol("WM_DELETE_WINDOW", lambda: self._on_avatar_window_closed(2))
        if self.btn_open:
            self.btn_open.config(text="❌ CERRAR VENTANAS OBS", style="DSBlue.TButton")
        self._refresh_eco_mode()
        log_debug("[OBS] ✅ Ventana de Avatar 2 (2P) abierta")

    def _on_avatar_window_closed(self, avatar_num):
        log_debug(f"[OBS] ❌ Ventana de Avatar {avatar_num} cerrada manualmente.")
        if avatar_num == 1:
            if self.avatar1_window:
                try:
                    self.avatar1_window.destroy()
                except Exception:
                    pass
                self.avatar1_window = None
        elif avatar_num == 2:
            if self.avatar2_window:
                try:
                    self.avatar2_window.destroy()
                except Exception:
                    pass
                self.avatar2_window = None

        a1_open = self.avatar1_window and self.avatar1_window.winfo_exists()
        a2_open = self.avatar2_window and self.avatar2_window.winfo_exists()
        if not a1_open and not a2_open and self.btn_open:
            self.btn_open.config(text="🚀 ENVIAR A OBS (Abrir Avatares)", style="DSSend.TButton")
        self._refresh_eco_mode()

    def _get_motions_dict(self, player_num):
        target = self.p1_data if player_num == 1 else self.p2_data
        pref = "a1" if player_num == 1 else "a2"
        def _norm_motion(m):
            return "Respiración" if m == "Rebote" else m

        m_dict = {
            "idle": _norm_motion(target.get(f"{pref}_idle_motion", "Respiración")),
            "idle_blink": _norm_motion(target.get(f"{pref}_idle_blink_motion", "Ninguna")),
            "talk": _norm_motion(target.get(f"{pref}_talk_motion", "Respiración")),
            "talk_blink": _norm_motion(target.get(f"{pref}_talk_blink_motion", "Ninguna")),
            "scream": _norm_motion(target.get(f"{pref}_scream_motion", "Sacudida")),
        }
        for ex in target.get("extra_expressions", []) or []:
            r_id = ex.get("role")
            if r_id:
                m_dict[r_id] = _norm_motion(target.get(f"{pref}_{r_id}_motion") or ex.get("motion", "Ninguna"))
        return m_dict

    def _get_motion_speeds_dict(self, player_num):
        target = self.p1_data if player_num == 1 else self.p2_data
        pref = "a1" if player_num == 1 else "a2"
        s_dict = {}
        for r in ("idle", "idle_blink", "talk", "talk_blink", "scream"):
            try:
                s_dict[r] = float(target.get(f"{pref}_{r}_speed", 1.0))
            except Exception:
                s_dict[r] = 1.0
        for ex in target.get("extra_expressions", []) or []:
            r_id = ex.get("role")
            if r_id:
                try:
                    s_dict[r_id] = float(target.get(f"{pref}_{r_id}_speed", ex.get("speed", 1.0)))
                except Exception:
                    s_dict[r_id] = 1.0
        return s_dict

    def _sync_windows_images(self):
        if self.avatar1_window and self.avatar1_window.winfo_exists():
            p1_mode_4 = (self.p1_data.get("image_mode") == "4_states")
            self.avatar1_window.update_images(
                self._get_images_dict(1), p1_mode_4,
                props_list=self.p1_data.get("props", []),
                motions_map=self._get_motions_dict(1),
                motion_speeds_map=self._get_motion_speeds_dict(1),
                extra_expressions=self.p1_data.get("extra_expressions", []),
                flip_x=bool(self.p1_data.get("flip_x", False)),
                independent_mouth=self.p1_data.get("independent_mouth"),
                independent_eyes=self.p1_data.get("independent_eyes")
            )

        if self.avatar2_window and self.avatar2_window.winfo_exists():
            p2_mode_4 = (self.p2_data.get("image_mode") == "4_states")
            self.avatar2_window.update_images(
                self._get_images_dict(2), p2_mode_4,
                props_list=self.p2_data.get("props", []),
                motions_map=self._get_motions_dict(2),
                motion_speeds_map=self._get_motion_speeds_dict(2),
                extra_expressions=self.p2_data.get("extra_expressions", []),
                flip_x=bool(self.p2_data.get("flip_x", False)),
                independent_mouth=self.p2_data.get("independent_mouth"),
                independent_eyes=self.p2_data.get("independent_eyes")
            )

    def _on_window_hotkey(self, avatar_num, action):
        if action == "mute":
            if avatar_num == 1:
                self.audio_engine.toggle_mic_mute()
            elif avatar_num == 2:
                self.audio_engine.toggle_discord_mute()
            self._sync_mute_buttons()
        elif action == "scream_toggle":
            if avatar_num == 1:
                self.p1_is_screaming = not self.p1_is_screaming
            elif avatar_num == 2:
                self.p2_is_screaming = not self.p2_is_screaming
        elif isinstance(action, str) and action.startswith("emote:"):
            key_name = action.split(":", 1)[1]
            if avatar_num == 1:
                self.p1_live_avatar.trigger_hotkey_emote(key_name)
                if self.current_screen == "workshop" and self.workshop_player == 1:
                    self.w_live_avatar.trigger_hotkey_emote(key_name)
            elif avatar_num == 2:
                self.p2_live_avatar.trigger_hotkey_emote(key_name)
                if self.current_screen == "workshop" and self.workshop_player == 2:
                    self.w_live_avatar.trigger_hotkey_emote(key_name)

    def _on_global_key_press(self, event):
        w = event.widget
        if isinstance(w, (tk.Entry, ttk.Entry)):
            return
        keysym = str(getattr(event, "keysym", ""))
        if not keysym:
            return
        if keysym.lower() == "m":
            if self.current_screen == "workshop" and self.workshop_player == 2:
                muted = self.audio_engine.toggle_discord_mute()
                if self.avatar2_window and self.avatar2_window.winfo_exists():
                    self.avatar2_window.is_muted = muted
                    self.avatar2_window._update_display()
            else:
                muted = self.audio_engine.toggle_mic_mute()
                if self.avatar1_window and self.avatar1_window.winfo_exists():
                    self.avatar1_window.is_muted = muted
                    self.avatar1_window._update_display()
            self._sync_mute_buttons()
            return

        # Disparar emotes configurados por tecla rápida en 1P, 2P, Taller y Ventanas OBS
        self.p1_live_avatar.trigger_hotkey_emote(keysym)
        self.p2_live_avatar.trigger_hotkey_emote(keysym)
        self.w_live_avatar.trigger_hotkey_emote(keysym)
        if self.avatar1_window and self.avatar1_window.winfo_exists():
            self.avatar1_window.trigger_hotkey_emote(keysym)
        if self.avatar2_window and self.avatar2_window.winfo_exists():
            self.avatar2_window.trigger_hotkey_emote(keysym)
