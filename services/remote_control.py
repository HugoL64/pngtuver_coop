"""Bus unificado de acciones y snapshot de estado para control remoto (API local, LAN y Co-op)."""

import math
import random
import threading

from urllib.parse import urlparse

from core.app_constants import log_debug
from core.coop_relay_client import CoopRelayClient
from core.emotions import get_effective_pose_data, normalize_emotion_slots
from core.guest_runtime import GuestCommandExecutor, GuestInbox
from core.relay_schemas import PROTOCOL_VERSION, sanitize_label
from services.local_coop_host import LocalCoopHost

MAX_ACTION_DURATION_SEC = 10.0
MAX_ACTIVE_TIMERS_PER_PLAYER = 10


def _sanitize_log(val, max_len=80):
    return str(val or "").replace("\r", " ").replace("\n", " ").replace("\t", " ")[:max_len]


def _parse_optional_bool(val):
    """Convierte valores JSON en bool o devuelve None si se omitió."""
    if val is None or val == "":
        return None
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "si", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return None


def _parse_duration(raw_val):
    """Valida duration evitando bool/NaN/Infinity y acota entre 0.0 y MAX_ACTION_DURATION_SEC."""
    if raw_val is None or raw_val == "":
        return 0.0
    if isinstance(raw_val, bool):
        return 0.0
    try:
        num = float(raw_val)
    except Exception:
        return 0.0
    if not math.isfinite(num):
        return 0.0
    return max(0.0, min(MAX_ACTION_DURATION_SEC, num))


class RemoteControlMixin:
    """Provee la API interna unificada para consultar estado y ejecutar acciones remotas."""

    def _init_guest_runtime(self):
        """Inicializa GuestInbox, GuestCommandExecutor, CoopRelayClient y el loop `root.after(33, ...)`."""
        if hasattr(self, "guest_inbox"):
            return
        self.guest_inbox = GuestInbox()
        self.guest_executor = GuestCommandExecutor(self)
        self.extra_avatar_windows = {3: None, 4: None}
        self.remote_players = {3: self._make_default_remote_slot_data(3), 4: self._make_default_remote_slot_data(4)}
        self._pending_join_requests = []
        self._state_versions = {2: 0, 3: 0, 4: 0}
        self.coop_relay_client = CoopRelayClient(
            self,
            on_join_request=lambda req: self.root.after(0, lambda r=req: self._on_relay_join_request(r)),
            on_status_change=lambda ok, rc: None,
        )
        self.local_coop_host = LocalCoopHost()
        self._guest_tick_id = None
        self._start_guest_tick()

    def start_coop_relay(self, relay_url, allow_insecure_local=False, web_url="", use_tunnel=False):
        self._pending_join_requests.clear()
        if hasattr(self, "local_coop_host"):
            self.local_coop_host.ensure_local_services(relay_url, web_url)
            if use_tunnel:
                r_port = urlparse(str(relay_url or "").strip()).port or 8766
                self.local_coop_host.start_tunnel_async(local_port=r_port, auto_download=True)
        self.coop_relay_client.start(relay_url, allow_insecure_local=allow_insecure_local)

    def stop_coop_relay(self):
        self._pending_join_requests.clear()
        if hasattr(self, "coop_relay_client"):
            self.coop_relay_client.stop()
        if hasattr(self, "local_coop_host"):
            self.local_coop_host.stop_all()

    def _on_relay_join_request(self, req):
        req_id = req.get("req_id")
        if not req_id:
            return
        self._pending_join_requests = [r for r in self._pending_join_requests if r.get("req_id") != req_id]
        self._pending_join_requests.append(
            {
                "req_id": req_id,
                "display_name": sanitize_label(str(req.get("display_name") or "Invitado"), max_len=24, allow_empty=True) or "Invitado",
                "tag": sanitize_label(str(req.get("tag") or "000"), max_len=6, allow_empty=True) or "000",
                "suggested_slot": req.get("suggested_slot"),
            }
        )
        log_debug(f"[REMOTE] Solicitud añadida al lobby (pendientes={len(self._pending_join_requests)})")

    def decide_join_request(self, req_id, allow, slot):
        self._pending_join_requests = [r for r in self._pending_join_requests if r.get("req_id") != req_id]
        perms = self.guest_executor.get_permissions(slot)
        self.coop_relay_client.send_join_decision(req_id, allow, slot, perms)
        if allow:
            self.root.after(150, lambda s=slot: self.push_guest_state_sync(s))

    def update_guest_slot_permissions(self, slot, perms_dict):
        self.guest_executor.set_permissions(slot, perms_dict)
        if getattr(self, "coop_relay_client", None) and self.coop_relay_client.connected:
            self.coop_relay_client.send_control(
                {"v": PROTOCOL_VERSION, "t": "permissions", "slot": int(slot), "permissions": self.guest_executor.get_permissions(slot)}
            )
            self.push_guest_state_sync(slot)

    def kick_coop_guest(self, slot, ban=False):
        if getattr(self, "coop_relay_client", None) and self.coop_relay_client.connected:
            self.coop_relay_client.send_kick(slot, ban=ban)
        self.guest_inbox.on_guest_left(slot)

    def push_guest_state_sync(self, slot):
        if not (getattr(self, "coop_relay_client", None) and self.coop_relay_client.connected):
            return
        slot = int(slot)
        self._state_versions[slot] = self._state_versions.get(slot, 0) + 1
        pkt = self.build_guest_state_sync(slot, state_version=self._state_versions[slot])
        self.coop_relay_client.send_control(pkt)

    def _make_default_remote_slot_data(self, slot):
        prof_names = list((self.profiles.get("player2") or {}).keys())
        base_name = prof_names[0] if prof_names else ""
        base_prof = dict((self.profiles.get("player2") or {}).get(base_name, {}))
        return {
            "character_name": base_name,
            "talk_threshold": int(base_prof.get("discord_threshold", 20) or 20),
            "scream_threshold": int(base_prof.get("scream_threshold", 55) or 55),
            "image_mode": base_prof.get("image_mode", "4_states"),
            "props": [dict(p) for p in (base_prof.get("props") or []) if isinstance(p, dict)],
            "emotion_slots": base_prof.get("emotion_slots"),
            "active_emotion": 0,
            "flip_x": bool(base_prof.get("flip_x", False)),
            "_forced_scream": False,
            "a2_idle": base_prof.get("a2_idle", self.default_assets.get("a2_idle", "")),
            "a2_idle_blink": base_prof.get("a2_idle_blink", self.default_assets.get("a2_idle_blink", "")),
            "a2_talk": base_prof.get("a2_talk", self.default_assets.get("a2_talk", "")),
            "a2_talk_blink": base_prof.get("a2_talk_blink", self.default_assets.get("a2_talk_blink", "")),
            "a2_scream": base_prof.get("a2_scream", self.default_assets.get("a2_scream", "")),
        }

    def _get_guest_slot_data(self, slot):
        if int(slot) == 2:
            return self.p2_data
        return getattr(self, "remote_players", {}).get(int(slot))

    def set_remote_slot_character(self, slot, char_name):
        slot = int(slot)
        if slot == 2:
            self._choose_character_from_card_list(2, char_name)
            return
        prof = (self.profiles.get("player2") or {}).get(char_name)
        if not isinstance(prof, dict):
            return
        d = self.remote_players.get(slot)
        if d is None:
            return
        d["character_name"] = char_name
        d["image_mode"] = prof.get("image_mode", "4_states")
        d["props"] = [dict(p) for p in (prof.get("props") or []) if isinstance(p, dict)]
        d["emotion_slots"] = prof.get("emotion_slots")
        d["active_emotion"] = 0
        d["flip_x"] = bool(prof.get("flip_x", False))
        for role in ("idle", "idle_blink", "talk", "talk_blink", "scream"):
            d[f"a2_{role}"] = prof.get(f"a2_{role}", self.default_assets.get(f"a2_{role}", ""))
        self._sync_remote_slot_window(slot)

    def _sync_remote_slot_window(self, slot):
        slot = int(slot)
        win = getattr(self, "extra_avatar_windows", {}).get(slot)
        if not (win and win.winfo_exists()):
            return
        d = self._get_guest_slot_data(slot)
        if not isinstance(d, dict):
            return
        imgs, motions, speeds = get_effective_pose_data(d, prefix="a2")
        win.flip_x = bool(d.get("flip_x", False))
        win.update_images(imgs, mode_4_states=(d.get("image_mode") == "4_states"), motions_map=motions, motion_speeds_map=speeds)
        win.update_props_fast(d.get("props") or [])

    def open_remote_avatar_window(self, slot):
        """Abre una ventana OBS independiente para el jugador remoto 3P o 4P."""
        from ui.avatar_window import AvatarWindow

        slot = int(slot)
        if slot not in (3, 4):
            return None
        existing = self.extra_avatar_windows.get(slot)
        if existing and existing.winfo_exists():
            existing.lift()
            return existing
        d = self._get_guest_slot_data(slot)
        imgs, motions, speeds = get_effective_pose_data(d, prefix="a2")
        win = AvatarWindow(
            self.root,
            f"Avatar {slot}P (Co-op Remoto)",
            imgs,
            mode_4_states=(d.get("image_mode") == "4_states"),
            bg_color=self.global_config.get("bg_color", "#00FF00"),
            bounce_enabled=self.global_config.get("bounce_enabled", True),
            props_list=d.get("props") or [],
            motions_map=motions,
            motion_speeds_map=speeds,
            flip_x=bool(d.get("flip_x", False)),
            perf_mode=self.global_config.get("performance_mode", "performance"),
            dim_on_silence=self.global_config.get("dim_on_silence", False),
        )
        self.extra_avatar_windows[slot] = win
        return win

    def close_remote_avatar_window(self, slot):
        slot = int(slot)
        win = getattr(self, "extra_avatar_windows", {}).pop(slot, None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.on_close()
            except Exception:
                pass

    def build_guest_state_sync(self, slot, state_version=1):
        """Construye un paquete `state_sync` v1.3 sanitizado y sin rutas para el slot."""
        slot = int(slot)
        d = self._get_guest_slot_data(slot) or {}
        prof_names = list((self.profiles.get("player2") or {}).keys())[:64]
        curr_char = self.global_config.get("current_p2_profile", "") if slot == 2 else d.get("character_name", "")
        active_char_id = prof_names.index(curr_char) if curr_char in prof_names else 0

        characters = [
            {"id": idx, "name": sanitize_label(name, max_len=40, allow_empty=True) or f"Personaje {idx + 1}"}
            for idx, name in enumerate(prof_names)
        ]

        slots = normalize_emotion_slots(d.get("emotion_slots"))
        emotions = [
            {"id": idx + 1, "name": sanitize_label(str(sl.get("name") or (idx + 1)), max_len=40, allow_empty=True) or str(idx + 1)}
            for idx, sl in enumerate(slots[:5])
        ]

        raw_props = (d.get("props") or [])[:64]
        props = [
            {
                "id": idx,
                "name": sanitize_label(str(p.get("name") or f"Prop {idx + 1}"), max_len=40, allow_empty=True) or f"Prop {idx + 1}",
                "enabled": bool(p.get("enabled", True)),
            }
            for idx, p in enumerate(raw_props)
            if isinstance(p, dict)
        ]

        screaming = bool(self.p2_is_screaming) if slot == 2 else bool(d.get("_forced_scream", False))
        return {
            "v": PROTOCOL_VERSION,
            "t": "state_sync",
            "to": slot,
            "state_version": int(state_version),
            "state": {
                "slot": slot,
                "active_character_id": active_char_id,
                "characters": characters,
                "active_emotion": int(d.get("active_emotion", 0) or 0) + 1,
                "emotions": emotions,
                "props": props,
                "flip_x": bool(d.get("flip_x", False)),
                "screaming": screaming,
                "permissions": self.guest_executor.get_permissions(slot),
            },
        }

    def _start_guest_tick(self):
        if getattr(self, "_closing", False):
            return
        try:
            self._guest_tick()
        except Exception:
            pass

    def _guest_tick(self):
        if getattr(self, "_closing", False):
            return
        inbox = getattr(self, "guest_inbox", None)
        executor = getattr(self, "guest_executor", None)
        if inbox is not None and executor is not None:
            for slot, cmd in inbox.drain_actions():
                executor.execute(slot, cmd)

            status = inbox.status_snapshot()
            voice_snap = inbox.voice_snapshot()

            # Slot 2: inyectar voz remota al canal de 2P si está conectado
            if status["slots"][2]["connected"]:
                lvl2 = float(voice_snap.get(2, 0.0))
                t2 = float(self.p2_data.get("discord_threshold", 25) or 25)
                s2 = float(self.p2_data.get("scream_threshold", 55) or 55)
                self.discord_level = lvl2
                self.discord_talking = lvl2 >= t2
                self.p2_is_screaming = (lvl2 >= s2) or bool(getattr(self, "_forced_scream", {}).get(2, False))

            # Slots 3 y 4: actualizar ventanas OBS independientes
            for extra_slot in (3, 4):
                if not status["slots"][extra_slot]["connected"]:
                    continue
                win = getattr(self, "extra_avatar_windows", {}).get(extra_slot)
                if win and win.winfo_exists():
                    d = self.remote_players.get(extra_slot, {})
                    lvl = float(voice_snap.get(extra_slot, 0.0))
                    th = float(d.get("talk_threshold", 20) or 20)
                    sc = float(d.get("scream_threshold", 55) or 55)
                    win.set_talking(lvl >= th)
                    win.set_screaming((lvl >= sc) or bool(d.get("_forced_scream", False)))
        try:
            self._guest_tick_id = self.root.after(33, self._guest_tick)
        except Exception:
            self._guest_tick_id = None

    def _run_on_ui_sync(self, fn, timeout=2.5):
        """Ejecuta `fn()` en el hilo principal de Tkinter y espera su resultado."""
        if threading.current_thread() is threading.main_thread():
            return fn()

        done = threading.Event()
        box = {"result": None, "error": None}

        def _task():
            try:
                box["result"] = fn()
            except Exception as exc:
                box["error"] = str(exc)
            finally:
                done.set()

        try:
            self.root.after(0, _task)
        except Exception as exc:
            return {"ok": False, "error": f"UI no disponible: {exc}"}

        if not done.wait(timeout):
            return {"ok": False, "error": "Timeout esperando respuesta de la UI"}
        if box["error"] is not None:
            return {"ok": False, "error": box["error"]}
        return box["result"]

    def _build_player_remote_state(self, pnum):
        """Construye el estado serializable de un jugador (1 o 2)."""
        is_p1 = int(pnum) == 1
        data = self.p1_data if is_p1 else self.p2_data
        prof_key = "player1" if is_p1 else "player2"
        curr_key = "current_p1_profile" if is_p1 else "current_p2_profile"

        slots = normalize_emotion_slots(data.get("emotion_slots"))
        emotions = [
            {"slot": idx + 1, "name": str(sl.get("name") or (idx + 1))}
            for idx, sl in enumerate(slots)
        ]

        props = [
            {
                "id": str(p.get("id") or ""),
                "name": str(p.get("name") or ""),
                "enabled": bool(p.get("enabled", True)),
            }
            for p in (data.get("props") or [])
            if isinstance(p, dict)
        ]

        muted = bool(self.audio_engine.mic_muted if is_p1 else self.audio_engine.discord_muted)
        screaming = bool(self.p1_is_screaming if is_p1 else self.p2_is_screaming)

        return {
            "player": 1 if is_p1 else 2,
            "active_character": str(self.global_config.get(curr_key, "")),
            "characters": list(self.profiles.get(prof_key, {}).keys()),
            "active_emotion": int(data.get("active_emotion", 0) or 0) + 1,
            "emotions": emotions,
            "props": props,
            "muted": muted,
            "flip_x": bool(data.get("flip_x", False)),
            "screaming": screaming,
        }

    def get_remote_state(self):
        """Devuelve una instantánea completa del estado actual de la app."""
        return {
            "game_mode": str(self.global_config.get("game_mode", "single")),
            "players": {
                "1": self._build_player_remote_state(1),
                "2": self._build_player_remote_state(2),
            },
        }

    def _resolve_emotion_slot_number(self, data, raw_value):
        """Resuelve un número de slot (1..5) o nombre de emoción a entero 1..5."""
        if raw_value is None or raw_value == "":
            return None
        s = str(raw_value).strip()
        try:
            num = int(s.split(":")[0].strip())
            return max(1, min(5, num))
        except Exception:
            pass

        slots = normalize_emotion_slots(data.get("emotion_slots"))
        s_low = s.lower()
        for idx, sl in enumerate(slots):
            if str(sl.get("name", "")).strip().lower() == s_low:
                return idx + 1
        return None

    def _execute_player_action(self, pnum, action, value=None, enabled=None, duration=0.0):
        """Ejecuta una acción normalizada sobre un jugador concreto (en hilo UI)."""
        is_p1 = int(pnum) == 1
        target_data = self.p1_data if is_p1 else self.p2_data
        prof_key = "player1" if is_p1 else "player2"
        curr_key = "current_p1_profile" if is_p1 else "current_p2_profile"

        restore_fn = None

        if action in ("emotion", "emotion_slot"):
            slot_num = self._resolve_emotion_slot_number(target_data, value)
            if slot_num is None:
                return {"ok": False, "error": f"Emoción inválida: '{value}'"}
            prev_idx = self._set_player_forced_emotion_slot(pnum, slot_num)
            if duration > 0:
                restore_fn = lambda p=pnum, prev=prev_idx: self._set_player_forced_emotion_slot(p, int(prev) + 1)

        elif action == "character":
            target_char = str(value or "").strip()
            if not target_char or target_char not in self.profiles.get(prof_key, {}):
                return {"ok": False, "error": f"Personaje no encontrado para {pnum}P: '{target_char}'"}
            prev_char = self.global_config.get(curr_key, "")
            self._choose_character_from_card_list(pnum, target_char)
            if duration > 0 and prev_char and prev_char in self.profiles.get(prof_key, {}):
                restore_fn = lambda p=pnum, ch=prev_char: self._choose_character_from_card_list(p, ch)

        elif action == "random_character":
            names = list(self.profiles.get(prof_key, {}).keys())
            curr_name = self.global_config.get(curr_key, "")
            choices = [n for n in names if n != curr_name] or names
            if not choices:
                return {"ok": False, "error": f"No hay personajes disponibles para {pnum}P"}
            chosen = random.choice(choices)
            self._choose_character_from_card_list(pnum, chosen)
            if duration > 0 and curr_name and curr_name in self.profiles.get(prof_key, {}):
                restore_fn = lambda p=pnum, ch=curr_name: self._choose_character_from_card_list(p, ch)

        elif action == "prop":
            prop_target = str(value or "").strip()
            if not prop_target:
                return {"ok": False, "error": "Falta 'value' con el nombre o id del prop"}
            props_list = target_data.get("props") or []
            t_low = prop_target.lower()
            curr_prop = next(
                (p for p in props_list if str(p.get("name", "")).strip().lower() == t_low or str(p.get("id", "")).strip().lower() == t_low),
                None,
            )
            if curr_prop is None:
                return {"ok": False, "error": f"Prop no encontrado en {pnum}P: '{prop_target}'"}
            new_val = (not bool(curr_prop.get("enabled", True))) if enabled is None else bool(enabled)
            res = self._set_player_forced_prop(pnum, prop_target, new_val)
            if res is not None and duration > 0:
                p_id, prev_en = res
                restore_fn = lambda p=pnum, pid=p_id, pe=prev_en: self._set_player_forced_prop(p, pid, pe)

        elif action == "mute":
            prev_m = bool(self.audio_engine.mic_muted if is_p1 else self.audio_engine.discord_muted)
            new_m = (not prev_m) if enabled is None else bool(enabled)
            self._set_player_forced_mute(pnum, new_m)
            if duration > 0:
                restore_fn = lambda p=pnum, pm=prev_m: self._set_player_forced_mute(p, pm)

        elif action == "flip_x":
            prev_f = bool(target_data.get("flip_x", False))
            new_f = (not prev_f) if enabled is None else bool(enabled)
            self._set_player_forced_flip_x(pnum, new_f)
            if duration > 0:
                restore_fn = lambda p=pnum, pf=prev_f: self._set_player_forced_flip_x(p, pf)

        elif action == "scream":
            prev_s = bool(self.p1_is_screaming if is_p1 else self.p2_is_screaming)
            new_s = (not prev_s) if enabled is None else bool(enabled)
            self._set_player_forced_scream(pnum, new_s)
            if duration > 0:
                restore_fn = lambda p=pnum, ps=prev_s: self._set_player_forced_scream(p, ps)

        else:
            return {"ok": False, "error": f"Acción desconocida: '{action}'"}

        if restore_fn is not None and duration > 0:
            timers = getattr(self, "_remote_restore_timers", None)
            if timers is None:
                timers = {}
                self._remote_restore_timers = timers
            tkey = (int(pnum), str(action))
            existing = timers.get(tkey)
            if existing is not None:
                # Cancelar timer previo pero conservar el restore_fn original (evita estado intermedio pegado)
                try:
                    self.root.after_cancel(existing["tid"])
                except Exception:
                    pass
                orig_restore = existing["restore_fn"]
            else:
                orig_restore = restore_fn

            def _on_expire(k=tkey, fn=orig_restore):
                cur = timers.pop(k, None)
                fn()

            tid = self.root.after(int(duration * 1000), _on_expire)
            timers[tkey] = {"tid": tid, "restore_fn": orig_restore}

        return {"ok": True}

    def dispatch_remote_action(self, payload, source="api"):
        """Punto de entrada único para ejecutar acciones remotas y devolver respuesta JSON."""
        if not isinstance(payload, dict):
            return {"ok": False, "error": "Payload inválido"}

        action = str(payload.get("action", "")).strip().lower()
        if not action:
            return {"ok": False, "error": "Falta el campo 'action'"}

        value = payload.get("value")
        if value is None:
            # Compatibilidad con parámetros explícitos según tipo de acción
            value = payload.get("character") or payload.get("emotion") or payload.get("prop") or payload.get("slot")

        enabled = _parse_optional_bool(payload.get("enabled"))
        duration = _parse_duration(payload.get("duration"))

        log_debug(
            f"[REMOTE:{_sanitize_log(source, 20)}] action='{_sanitize_log(action, 32)}' "
            f"player='{_sanitize_log(payload.get('player', 1), 8)}' value='{_sanitize_log(value, 48)}' "
            f"enabled={enabled} dur={duration:.2f}s"
        )

        if action == "game_mode":
            mode = str(value or "").strip().lower()
            if mode not in ("single", "coop"):
                return {"ok": False, "error": "El modo debe ser 'single' o 'coop'"}
            self._set_game_mode(mode)
            return {"ok": True, "action": action, "state": self.get_remote_state()}

        raw_player = str(payload.get("player", "1")).strip().lower()
        if raw_player == "both":
            players = [1, 2]
        elif raw_player == "2":
            players = [2]
        else:
            players = [1]

        results = []
        for pnum in players:
            res = self._execute_player_action(pnum, action, value=value, enabled=enabled, duration=duration)
            if not res.get("ok"):
                return res
            results.append(pnum)

        return {
            "ok": True,
            "action": action,
            "players": results,
            "state": self.get_remote_state(),
        }
