import tkinter as tk
from tkinter import messagebox
import time
from datetime import datetime

from core.app_constants import log_debug
from core.audio_engine import AudioEngine


class AudioCalibrationMixin:
    # =========================================================================
    # --- EVENTOS DE CALIBRACIÓN Y AUDIO (LOBBY Y TALLER) ---
    # =========================================================================
    def _on_lobby_meter_press(self, player_num, event, force_mode=None):
        canvas = self.p1_mini_meter if player_num == 1 else self.p2_mini_meter
        w = max(10, canvas.winfo_width())
        pct = max(1, min(95, int(round((event.x / w) * 100.0))))

        data = self.p1_data if player_num == 1 else self.p2_data
        has_scream = self._character_has_scream(data)
        v_key = "mic_threshold" if player_num == 1 else "discord_threshold"
        voice_t = int(data.get(v_key, 20 if player_num == 1 else 25))
        scream_t = int(data.get("scream_threshold", 55))

        if not has_scream:
            self._dragging_meter_target[player_num] = "voice"
        elif force_mode in ("voice", "scream"):
            self._dragging_meter_target[player_num] = force_mode
        else:
            # Si hace clic más cerca de la línea de grito, arrastra grito; si no, arrastra voz
            dist_voice = abs(pct - voice_t)
            dist_scream = abs(pct - scream_t)
            self._dragging_meter_target[player_num] = "scream" if dist_scream < dist_voice else "voice"

        self._apply_lobby_meter_value(player_num, pct)

    def _on_lobby_meter_drag(self, player_num, event):
        canvas = self.p1_mini_meter if player_num == 1 else self.p2_mini_meter
        w = max(10, canvas.winfo_width())
        pct = max(1, min(95, int(round((event.x / w) * 100.0))))
        self._apply_lobby_meter_value(player_num, pct)

    def _on_lobby_meter_release(self, player_num, event):
        target = self._dragging_meter_target.get(player_num, "voice")
        if player_num == 1:
            self._save_p1_profile()
            val = self.p1_data["scream_threshold"] if target == "scream" else self.p1_data["mic_threshold"]
            log_debug(f"[CALIBRACION LOBBY] P1 Umbral ({target}) guardado en {val}%")
        else:
            self._save_p2_profile()
            val = self.p2_data["scream_threshold"] if target == "scream" else self.p2_data["discord_threshold"]
            log_debug(f"[CALIBRACION LOBBY] P2 Umbral ({target}) guardado en {val}%")

    def _apply_lobby_meter_value(self, player_num, pct):
        target = self._dragging_meter_target.get(player_num, "voice")
        if player_num == 1:
            has_scream = self._character_has_scream(self.p1_data)
            if target == "scream" and has_scream:
                min_s = max(20, int(self.p1_data.get("mic_threshold", 20)) + 5)
                val = max(min_s, min(95, pct))
                self.p1_data["scream_threshold"] = val
                self.audio_engine.mic_scream_threshold = float(val)
            else:
                max_v = min(80, int(self.p1_data.get("scream_threshold", 55)) - 5) if has_scream else 80
                val = max(1, min(max_v, pct))
                self.p1_data["mic_threshold"] = val
                self.audio_engine.mic_threshold = float(val)

            if hasattr(self, "p1_meter_info_lbl"):
                if has_scream:
                    self.p1_meter_info_lbl.config(
                        text=f"🤫 Voz: {int(self.p1_data['mic_threshold'])}%  |  💥 Grito: {int(self.p1_data.get('scream_threshold', 55))}%"
                    )
                else:
                    self.p1_meter_info_lbl.config(
                        text=f"🤫 Voz: {int(self.p1_data['mic_threshold'])}%"
                    )
        else:
            has_scream = self._character_has_scream(self.p2_data)
            if target == "scream" and has_scream:
                min_s = max(20, int(self.p2_data.get("discord_threshold", 25)) + 5)
                val = max(min_s, min(95, pct))
                self.p2_data["scream_threshold"] = val
                self.audio_engine.discord_scream_threshold = float(val)
            else:
                max_v = min(80, int(self.p2_data.get("scream_threshold", 55)) - 5) if has_scream else 80
                val = max(1, min(max_v, pct))
                self.p2_data["discord_threshold"] = val
                self.audio_engine.discord_threshold = float(val)

            if hasattr(self, "p2_meter_info_lbl"):
                if has_scream:
                    self.p2_meter_info_lbl.config(
                        text=f"🤫 Voz: {int(self.p2_data['discord_threshold'])}%  |  💥 Grito: {int(self.p2_data.get('scream_threshold', 55))}%"
                    )
                else:
                    self.p2_meter_info_lbl.config(
                        text=f"🤫 Voz: {int(self.p2_data['discord_threshold'])}%"
                    )

    def _on_p1_lobby_device_changed(self, event=None):
        if not hasattr(self, "p1_lobby_dev_combo"):
            return
        idx = self.p1_lobby_dev_combo.current()
        if 0 <= idx < len(self.mic_devices):
            dev = self.mic_devices[idx]
            self.p1_data["mic_device_name"] = dev["name"]
            log_debug(f"[AUDIO LOBBY] P1 Cambió micrófono a: '{dev['name']}'")
            self._start_audio_engine()
            self._save_p1_profile()
            self._sync_audio_combos_selection()

    def _on_p2_lobby_device_changed(self, event=None):
        if not hasattr(self, "p2_lobby_dev_combo"):
            return
        idx = self.p2_lobby_dev_combo.current()
        if 0 <= idx < len(self.discord_sources):
            src = self.discord_sources[idx]
            self.p2_data["discord_source_id"] = src["id"]
            log_debug(f"[AUDIO LOBBY] P2 Cambió fuente Discord a: '{src['name']}'")
            self._start_audio_engine()
            self._save_p2_profile()
            self._sync_audio_combos_selection()

    def _manual_refresh_devices(self):
        log_debug("[AUDIO] 🔄 Refrescando lista de micrófonos y fuentes de Discord...")
        self._refresh_audio_devices()
        self._start_audio_engine()

    # =========================================================================
    # --- AUTO-CALIBRACIÓN INTELIGENTE EN 3 SEGUNDOS (🪄 AUTO) ---
    # =========================================================================
    def _start_auto_calibration(self, player_num):
        if getattr(self, "_auto_cal_running", False):
            return
        self._auto_cal_running = True
        self._auto_cal_samples = []
        log_debug(f"[AUTO-CALIBRACION] 🪄 Iniciando medición de 3 segundos para Jugador {player_num}...")
        self._sample_auto_calibration(player_num, remaining_ticks=50)

    def _sample_auto_calibration(self, player_num, remaining_ticks):
        if not getattr(self, "_auto_cal_running", False):
            return

        lvl = float(self.mic_level if player_num == 1 else self.discord_level)
        self._auto_cal_samples.append(lvl)

        secs_left = max(1, (remaining_ticks * 50 + 999) // 1000)
        btn_lobby = getattr(self, "p1_auto_cal_btn" if player_num == 1 else "p2_auto_cal_btn", None)
        if btn_lobby and btn_lobby.winfo_exists():
            btn_lobby.config(text=f"⏳ {secs_left}s...", bg="#FDE047", fg="#0F172A")

        if hasattr(self, "w_auto_cal_btn") and self.w_auto_cal_btn.winfo_exists() and self.workshop_player == player_num:
            self.w_auto_cal_btn.config(text=f"⏳ Midiendo ({secs_left}s)...", bg="#FDE047", fg="#0F172A")

        if remaining_ticks > 0:
            self.root.after(50, lambda: self._sample_auto_calibration(player_num, remaining_ticks - 1))
        else:
            self._finish_auto_calibration(player_num)

    def _finish_auto_calibration(self, player_num):
        self._auto_cal_running = False
        samples = sorted(self._auto_cal_samples) if self._auto_cal_samples else [0.0]
        n = len(samples)

        # Percentil 30 = piso de ruido ambiental; Percentil 85 = voz media; Máximo = pico
        noise_floor = samples[min(n - 1, int(n * 0.30))]
        high_level = samples[min(n - 1, int(n * 0.85))]
        peak_level = samples[-1]

        # Si hubo voz clara durante la prueba (diferencia > 12% entre ruido y voz alta), calibrar entre ambos
        if (high_level - noise_floor) > 12.0:
            new_voice = int(round(noise_floor + (high_level - noise_floor) * 0.42))
            new_Voice_clamped = max(5, min(68, new_voice))
            new_scream = max(new_Voice_clamped + 24, min(92, int(round(max(high_level + 22, peak_level + 12)))))
        else:
            # Solo ruido ambiental de fondo: colocar el umbral justo por encima del ruido del cuarto
            new_Voice_clamped = max(6, min(65, int(round(noise_floor + 8.0))))
            new_scream = max(45, min(90, new_Voice_clamped + 36))

        if player_num == 1:
            self.p1_data["mic_threshold"] = new_Voice_clamped
            self.p1_data["scream_threshold"] = new_scream
            self.audio_engine.mic_threshold = float(new_Voice_clamped)
            self.audio_engine.mic_scream_threshold = float(new_scream)
            self._save_p1_profile()
            self._refresh_p1_card_roster()
            if hasattr(self, "p1_auto_cal_btn") and self.p1_auto_cal_btn.winfo_exists():
                self.p1_auto_cal_btn.config(text="✅ ¡Listo!", bg="#DCFCE7", fg="#15803D")
                self.root.after(
                    2000,
                    lambda: self.p1_auto_cal_btn.config(text="🪄 Auto (3s)", bg="#E0F2FE", fg="#0369A1")
                    if hasattr(self, "p1_auto_cal_btn") and self.p1_auto_cal_btn.winfo_exists() else None
                )
        else:
            self.p2_data["discord_threshold"] = new_Voice_clamped
            self.p2_data["scream_threshold"] = new_scream
            self.audio_engine.discord_threshold = float(new_Voice_clamped)
            self.audio_engine.discord_scream_threshold = float(new_scream)
            self._save_p2_profile()
            self._refresh_p2_card_roster()
            if hasattr(self, "p2_auto_cal_btn") and self.p2_auto_cal_btn.winfo_exists():
                self.p2_auto_cal_btn.config(text="✅ ¡Listo!", bg="#DCFCE7", fg="#15803D")
                self.root.after(
                    2000,
                    lambda: self.p2_auto_cal_btn.config(text="🪄 Auto (3s)", bg="#FFEDD5", fg="#C2410C")
                    if hasattr(self, "p2_auto_cal_btn") and self.p2_auto_cal_btn.winfo_exists() else None
                )

        if self.current_screen == "workshop" and self.workshop_player == player_num:
            self.w_thresh_scale.set(new_Voice_clamped)
            self.w_thresh_val_lbl.config(text=f"{new_Voice_clamped}%")
            self.w_scream_scale.set(new_scream)
            self.w_scream_val_lbl.config(text=f"{new_scream}%")
            if hasattr(self, "w_auto_cal_btn") and self.w_auto_cal_btn.winfo_exists():
                self.w_auto_cal_btn.config(text="✅ ¡Auto-Calibrado!", bg="#DCFCE7", fg="#15803D")
                self.root.after(
                    2000,
                    lambda: self.w_auto_cal_btn.config(text="🪄 Auto-Calibrar (3s)", bg="#E0F2FE", fg="#0369A1")
                    if hasattr(self, "w_auto_cal_btn") and self.w_auto_cal_btn.winfo_exists() else None
                )

        log_debug(
            f"[AUTO-CALIBRACION] ✅ {player_num}P completado -> Ruido base: {noise_floor:.1f}%, "
            f"Voz fijada en: {new_Voice_clamped}%, Grito fijado en: {new_scream}%"
        )

    def _on_workshop_thresh_slider(self, val):
        val_int = int(float(val))
        self.w_thresh_val_lbl.config(text=f"{val_int}%")
        if self.workshop_player == 1:
            self.p1_data["mic_threshold"] = val_int
            self.audio_engine.mic_threshold = float(val_int)
            self._save_p1_profile()
            log_debug(f"[CALIBRACION] P1 Sensibilidad de voz ajustada a {val_int}%")
        else:
            self.p2_data["discord_threshold"] = val_int
            self.audio_engine.discord_threshold = float(val_int)
            self._save_p2_profile()
            log_debug(f"[CALIBRACION] P2 Sensibilidad Discord ajustada a {val_int}%")

    def _on_workshop_scream_slider(self, val):
        val_int = int(float(val))
        self.w_scream_val_lbl.config(text=f"{val_int}%")
        if self.workshop_player == 1:
            self.p1_data["scream_threshold"] = val_int
            self.audio_engine.mic_scream_threshold = float(val_int)
            self._save_p1_profile()
            log_debug(f"[CALIBRACION] P1 Umbral de grito ajustado a {val_int}%")
        else:
            self.p2_data["scream_threshold"] = val_int
            self.audio_engine.discord_scream_threshold = float(val_int)
            self._save_p2_profile()
            log_debug(f"[CALIBRACION] P2 Umbral de grito ajustado a {val_int}%")

    def _on_workshop_device_changed(self, event=None):
        idx = self.w_audio_combo.current()
        if idx < 0:
            return

        if self.workshop_player == 1:
            if idx < len(self.mic_devices):
                dev = self.mic_devices[idx]
                self.p1_data["mic_device_name"] = dev["name"]
                log_debug(f"[AUDIO] P1 Cambió dispositivo de micrófono a: '{dev['name']}'")
                self._start_audio_engine()
                self._save_p1_profile()
                self._sync_audio_combos_selection()
        else:
            if idx < len(self.discord_sources):
                src = self.discord_sources[idx]
                self.p2_data["discord_source_id"] = src["id"]
                log_debug(f"[AUDIO] P2 Cambió fuente de Discord a: '{src['name']}'")
                self._start_audio_engine()
                self._save_p2_profile()
                self._sync_audio_combos_selection()


    # =========================================================================
    # --- CICLO DE ACTUALIZACIÓN VISUAL Y MEDIDORES ---
    # =========================================================================
    def _update_ui_loop(self):
        is_coop = (self.global_config.get("game_mode") != "single")
        p1_muted = getattr(self.audio_engine, "mic_muted", False)
        p2_muted = getattr(self.audio_engine, "discord_muted", False)
        p1_thresh = self.p1_data.get("mic_threshold", 20)
        p2_thresh = self.p2_data.get("discord_threshold", 25)
        p1_has_scream = self._character_has_scream(self.p1_data)
        p2_has_scream = self._character_has_scream(self.p2_data)
        p1_scream_active = (self.p1_is_screaming or getattr(self, "_forced_scream", {}).get(1, False)) and p1_has_scream
        p2_scream_active = (self.p2_is_screaming or getattr(self, "_forced_scream", {}).get(2, False)) and p2_has_scream
        p2_talk_ctx = self.discord_talking if is_coop else False
        p2_scream_ctx = p2_scream_active if is_coop else False

        if self.current_screen == "lobby" and not getattr(self, "_eco_mode", False):
            if self.card_view_state.get(1) == "active":
                self.p1_live_avatar.update_state(
                    self.mic_talking, p1_scream_active,
                    muted=p1_muted, audio_level=self.mic_level, talk_threshold=p1_thresh,
                    partner_talking=p2_talk_ctx, partner_screaming=p2_scream_ctx
                )
                self._draw_mini_meter(
                    self.p1_mini_meter,
                    self.mic_level,
                    p1_thresh,
                    self.p1_data.get("scream_threshold", 55),
                    self.mic_talking,
                    p1_scream_active,
                    show_scream=p1_has_scream
                )

                if p1_muted:
                    self.p1_voice_badge.config(text="🔇 Muteado", bg="#64748B", fg="#FFFFFF")
                elif p1_scream_active:
                    self.p1_voice_badge.config(text="💥 ¡GRITO!", bg="#DC2626", fg="#FFFFFF")
                elif self.mic_talking:
                    self.p1_voice_badge.config(text="💬 Hablando", bg="#16A34A", fg="#FFFFFF")
                else:
                    self.p1_voice_badge.config(text="🤫 En silencio", bg="#25559C", fg="#E2E8F0")

            if is_coop and self.card_view_state.get(2) == "active":
                self.p2_live_avatar.update_state(
                    self.discord_talking, p2_scream_active,
                    muted=p2_muted, audio_level=self.discord_level, talk_threshold=p2_thresh,
                    partner_talking=self.mic_talking, partner_screaming=p1_scream_active
                )
                self._draw_mini_meter(
                    self.p2_mini_meter,
                    self.discord_level,
                    p2_thresh,
                    self.p2_data.get("scream_threshold", 55),
                    self.discord_talking,
                    p2_scream_active,
                    show_scream=p2_has_scream
                )

                if p2_muted:
                    self.p2_voice_badge.config(text="🔇 Muteado", bg="#64748B", fg="#FFFFFF")
                elif p2_scream_active:
                    self.p2_voice_badge.config(text="💥 ¡GRITO!", bg="#DC2626", fg="#FFFFFF")
                elif self.discord_talking:
                    self.p2_voice_badge.config(text="💬 Hablando", bg="#16A34A", fg="#FFFFFF")
                else:
                    self.p2_voice_badge.config(text="🤫 En silencio", bg="#B83F2E", fg="#E2E8F0")

        elif self.current_screen == "workshop" and not getattr(self, "_eco_mode", False):
            if self.workshop_player == 1:
                self.w_live_avatar.update_state(
                    self.mic_talking, p1_scream_active,
                    muted=p1_muted, audio_level=self.mic_level, talk_threshold=p1_thresh,
                    partner_talking=p2_talk_ctx, partner_screaming=p2_scream_ctx
                )
                self._draw_workshop_meter(
                    self.mic_level, p1_thresh, self.mic_talking, p1_scream_active,
                    self.p1_data.get("scream_threshold", 55), show_scream=p1_has_scream
                )
            else:
                self.w_live_avatar.update_state(
                    self.discord_talking, p2_scream_active,
                    muted=p2_muted, audio_level=self.discord_level, talk_threshold=p2_thresh,
                    partner_talking=self.mic_talking, partner_screaming=p1_scream_active
                )
                self._draw_workshop_meter(
                    self.discord_level, p2_thresh, self.discord_talking, p2_scream_active,
                    self.p2_data.get("scream_threshold", 55), show_scream=p2_has_scream
                )

        a1_open = self.avatar1_window and self.avatar1_window.winfo_exists()
        a2_open = self.avatar2_window and self.avatar2_window.winfo_exists()
        if a1_open:
            self.avatar1_window.set_talking(self.mic_talking)
            self.avatar1_window.set_screaming(p1_scream_active)
            self.avatar1_window.update_extra_context(
                muted=p1_muted, audio_level=self.mic_level, talk_threshold=p1_thresh,
                partner_talking=p2_talk_ctx, partner_screaming=p2_scream_ctx
            )
        if a2_open:
            self.avatar2_window.set_talking(self.discord_talking)
            self.avatar2_window.set_screaming(p2_scream_active)
            self.avatar2_window.update_extra_context(
                muted=p2_muted, audio_level=self.discord_level, talk_threshold=p2_thresh,
                partner_talking=self.mic_talking, partner_screaming=p1_scream_active
            )
        if not a1_open and not a2_open and "CERRAR" in self.btn_open.cget("text"):
            self.btn_open.config(text="🚀 ENVIAR A OBS (Abrir Avatares)", style="DSSend.TButton")
            self._refresh_eco_mode()

        delay_ms = 60 if getattr(self, "_eco_mode", False) else 20
        self.root.after(delay_ms, self._update_ui_loop)

    def _draw_mini_meter(self, canvas, level, threshold, scream_threshold, is_talking, is_screaming, show_scream=False):
        w = max(10, canvas.winfo_width())
        h = max(10, canvas.winfo_height())
        canvas.delete("all")

        # Cuadrícula sutil en el medidor estilo DS
        for pct_tick in (20, 40, 60, 80):
            gx = int((pct_tick / 100.0) * w)
            canvas.create_line(gx, 0, gx, h, fill="#CBD5E1", width=1)

        fill_w = int((min(100.0, max(0.0, level)) / 100.0) * w)
        color = "#EF4444" if (is_screaming and show_scream) else ("#22C55E" if is_talking else "#38BDF8")
        if fill_w > 0:
            canvas.create_rectangle(0, 0, fill_w, h, fill=color, width=0)

        # Línea punteada de histéresis (cierre de voz)
        if self.global_config.get("hysteresis_enabled", False):
            hx = int(((threshold * 0.70) / 100.0) * w)
            canvas.create_line(hx, 0, hx, h, fill="#0284C7", width=1, dash=(2, 2))

        # Marcador interactivo de Umbral de Voz (Rojo brillante + pestaña superior)
        tx = int((threshold / 100.0) * w)
        canvas.create_line(tx, 0, tx, h, fill="#E11D48", width=2)
        canvas.create_polygon(tx - 5, 0, tx + 5, 0, tx, 6, fill="#E11D48", outline="")

        # Marcador interactivo de Umbral de Grito (solo si existe un fotograma de grito en el personaje)
        if show_scream:
            sx = int((scream_threshold / 100.0) * w)
            canvas.create_line(sx, 0, sx, h, fill="#991B1B", width=2)
            canvas.create_polygon(sx - 5, h, sx + 5, h, sx, h - 6, fill="#991B1B", outline="")

    def _draw_workshop_meter(self, level, threshold, is_talking, is_screaming, scream_threshold, show_scream=False):
        canvas = self.w_audio_meter
        w = max(10, canvas.winfo_width())
        h = max(10, canvas.winfo_height())
        canvas.delete("all")

        fill_w = int((min(100.0, max(0.0, level)) / 100.0) * w)
        color = "#DC2626" if (is_screaming and show_scream) else ("#16A34A" if is_talking else "#38BDF8")

        if fill_w > 0:
            canvas.create_rectangle(0, 0, fill_w, h, fill=color, width=0)

        tx = int((threshold / 100.0) * w)
        canvas.create_line(tx, 0, tx, h, fill="#E11D48", width=2)

        if self.global_config.get("hysteresis_enabled", False):
            hx = int(((threshold * 0.70) / 100.0) * w)
            canvas.create_line(hx, 0, hx, h, fill="#0284C7", width=1, dash=(2, 2))

        if show_scream:
            sx = int((scream_threshold / 100.0) * w)
            canvas.create_line(sx, 0, sx, h, fill="#991B1B", width=2)

        if is_screaming and show_scream:
            canvas.create_text(w // 2, h // 2, text="💥 ¡GRITO DETECTADO!", fill="#FFFFFF", font=("Segoe UI", 8, "bold"))
        elif is_talking:
            canvas.create_text(w // 2, h // 2, text="HABLANDO...", fill="#FFFFFF", font=("Segoe UI", 8, "bold"))

    def _update_clock(self):
        now_str = datetime.now().strftime("%H:%M")
        self.clock_lbl.config(text=f"🕒 {now_str}")
        self.root.after(1000, self._update_clock)

    # =========================================================================
    # --- DISPOSITIVOS DE AUDIO ---
    # =========================================================================
    def _refresh_audio_devices(self):
        self.mic_devices = self.audio_engine.get_input_devices()
        self.discord_sources = self.audio_engine.get_discord_sources()
        self._sync_audio_combos_selection()

    def _sync_audio_combos_selection(self):
        if not hasattr(self, "mic_devices") or not hasattr(self, "discord_sources"):
            return

        mic_names = [d["name"] for d in self.mic_devices]
        curr_mic = self.p1_data.get("mic_device_name", "")
        mic_idx = 0
        for i, d in enumerate(self.mic_devices):
            if d["name"] == curr_mic or d.get("raw_name") == curr_mic:
                mic_idx = i
                break

        disc_names = [s["name"] for s in self.discord_sources]
        curr_disc_id = self.p2_data.get("discord_source_id", "app:discord")
        disc_idx = 0
        for i, s in enumerate(self.discord_sources):
            if s.get("id") == curr_disc_id:
                disc_idx = i
                break

        # Actualizar selector rápido de Micrófono en el Lobby (1P)
        if hasattr(self, "p1_lobby_dev_combo"):
            self.p1_lobby_dev_combo["values"] = mic_names
            if mic_names:
                self.p1_lobby_dev_combo.current(mic_idx)

        # Actualizar selector rápido de Discord en el Lobby (2P)
        if hasattr(self, "p2_lobby_dev_combo"):
            self.p2_lobby_dev_combo["values"] = disc_names
            if disc_names:
                self.p2_lobby_dev_combo.current(disc_idx)

        # Actualizar selector del Taller (Workshop)
        if hasattr(self, "w_audio_combo"):
            if self.workshop_player == 1:
                self.w_audio_combo["values"] = mic_names
                if mic_names:
                    self.w_audio_combo.current(mic_idx)
            else:
                self.w_audio_combo["values"] = disc_names
                if disc_names:
                    self.w_audio_combo.current(disc_idx)

    def _start_audio_engine(self):
        mic_idx = None
        saved_mic = self.p1_data.get("mic_device_name", "")
        for d in self.mic_devices:
            if d["name"] == saved_mic or d.get("raw_name") == saved_mic:
                mic_idx = d["index"]
                break
        if mic_idx is None and self.mic_devices:
            mic_idx = self.mic_devices[0]["index"]
            self.p1_data["mic_device_name"] = self.mic_devices[0]["name"]

        discord_info = None
        saved_src = self.p2_data.get("discord_source_id", "app:discord")
        for s in self.discord_sources:
            if s.get("id") == saved_src:
                discord_info = s
                break
        if discord_info is None and self.discord_sources:
            discord_info = self.discord_sources[0]
            self.p2_data["discord_source_id"] = discord_info.get("id", "app:discord")

        is_single = (self.global_config.get("game_mode") == "single")

        self.audio_engine.start(
            mic_device_index=mic_idx,
            discord_source_info=discord_info,
            mic_threshold=self.p1_data["mic_threshold"],
            discord_threshold=self.p2_data["discord_threshold"],
            mic_scream_threshold=self.p1_data.get("scream_threshold", 55),
            discord_scream_threshold=self.p2_data.get("scream_threshold", 55),
            single_player=is_single
        )



    def _on_mic_level_thread(self, level):
        self.mic_level = level

    def _on_discord_level_thread(self, level):
        self.discord_level = level

    def _on_mic_state_thread(self, talking):
        self.mic_talking = talking

    def _on_discord_state_thread(self, talking):
        self.discord_talking = talking

    def _on_mic_scream_thread(self, screaming):
        self.p1_is_screaming = screaming

    def _on_discord_scream_thread(self, screaming):
        self.p2_is_screaming = screaming

    def _safe_set_avatar_talking(self, avatar_num, talking):
        try:
            if avatar_num == 1:
                if self.avatar1_window and self.avatar1_window.winfo_exists():
                    self.avatar1_window.set_talking(talking)
            elif avatar_num == 2:
                if self.avatar2_window and self.avatar2_window.winfo_exists():
                    self.avatar2_window.set_talking(talking)
        except Exception:
            pass

    def _safe_set_avatar_scream(self, avatar_num, screaming):
        try:
            if avatar_num == 1:
                if self.avatar1_window and self.avatar1_window.winfo_exists():
                    self.avatar1_window.set_screaming(screaming)
            elif avatar_num == 2:
                if self.avatar2_window and self.avatar2_window.winfo_exists():
                    self.avatar2_window.set_screaming(screaming)
        except Exception:
            pass

