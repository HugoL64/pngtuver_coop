"""Runtime seguro para invitados Co-op: GuestInbox (coalescencia) y GuestCommand (default-deny).

La capa de red escribe en GuestInbox sin tocar widgets de Tkinter.
El hilo principal de Tkinter hace polling con un único `root.after(33, ...)` y ejecuta
las acciones a través de GuestCommand, evaluando permisos locales en tiempo de ejecución.
"""

import math
import threading
import time
from collections import deque

from core.relay_schemas import (
    PERMISSION_KEYS,
    SchemaError,
    VALID_SLOTS,
    validate_guest_action,
    validate_guest_voice,
)

VOICE_EXPIRY_SEC = 0.40
ACTION_QUEUE_MAXLEN = 8
ACTION_COOLDOWN_SEC = {
    "set_emotion": 0.30,
    "set_prop": 0.30,
    "flip_x": 0.30,
    "scream": 0.30,
    "set_character": 3.00,
}
GUEST_WINDOW_SEC = 10.0
GUEST_WINDOW_MAX_ACTIONS = 15


def default_guest_permissions():
    """Permisos default-deny para un slot invitado."""
    return {k: False for k in PERMISSION_KEYS}


class GuestInbox:
    """Buzón thread-safe con coalescencia de voz ("último valor gana") y cola acotada de acciones."""

    def __init__(self):
        self._lock = threading.Lock()
        self._voice = {s: (0.0, 0.0) for s in VALID_SLOTS}
        self._actions = {s: deque(maxlen=ACTION_QUEUE_MAXLEN) for s in VALID_SLOTS}
        self._last_seq = {s: -1 for s in VALID_SLOTS}
        self._connected = {s: False for s in VALID_SLOTS}
        self._foreground = {s: True for s in VALID_SLOTS}
        self._meta = {s: {"display_name": "", "tag": ""} for s in VALID_SLOTS}
        self._panic_frozen = False

    def set_panic_freeze(self, frozen):
        with self._lock:
            self._panic_frozen = bool(frozen)
            if self._panic_frozen:
                for s in VALID_SLOTS:
                    self._voice[s] = (0.0, 0.0)
                    self._actions[s].clear()

    def is_panic_frozen(self):
        with self._lock:
            return self._panic_frozen

    def on_guest_joined(self, slot, display_name="", tag="", reconnected=False):
        if slot not in VALID_SLOTS:
            return
        with self._lock:
            self._connected[slot] = True
            self._last_seq[slot] = -1  # seq reinicia al reconectar
            self._foreground[slot] = True
            self._meta[slot] = {"display_name": str(display_name or ""), "tag": str(tag or "")}
            if not reconnected:
                self._voice[slot] = (0.0, 0.0)
                self._actions[slot].clear()

    def on_guest_left(self, slot):
        if slot not in VALID_SLOTS:
            return
        with self._lock:
            self._connected[slot] = False
            self._last_seq[slot] = -1
            self._voice[slot] = (0.0, 0.0)
            self._actions[slot].clear()

    def set_presence(self, slot, foreground):
        if slot not in VALID_SLOTS:
            return
        with self._lock:
            if self._connected.get(slot):
                self._foreground[slot] = bool(foreground)

    def push_voice(self, slot, msg):
        """Valida y guarda el último nivel de voz del slot si seq es estrictamente creciente."""
        if slot not in VALID_SLOTS:
            return False
        clean = validate_guest_voice(msg)
        with self._lock:
            if self._panic_frozen or not self._connected.get(slot):
                return False
            seq = clean["seq"]
            if seq <= self._last_seq[slot]:
                return False
            self._last_seq[slot] = seq
            self._voice[slot] = (clean["level"], time.monotonic())
            return True

    def push_action(self, slot, msg):
        """Valida y encola una acción del slot (descartando las más antiguas si supera maxlen=8)."""
        if slot not in VALID_SLOTS:
            return False
        clean = validate_guest_action(msg)
        with self._lock:
            if self._panic_frozen or not self._connected.get(slot):
                return False
            seq = clean["seq"]
            if seq <= self._last_seq[slot]:
                return False
            self._last_seq[slot] = seq
            self._actions[slot].append(clean)
            return True

    def voice_snapshot(self, now=None):
        """Devuelve {slot: level} aplicando expiración de 400 ms y bloqueo por pánico."""
        ts_now = time.monotonic() if now is None else float(now)
        with self._lock:
            if self._panic_frozen:
                return {s: 0.0 for s in VALID_SLOTS}
            out = {}
            for s in VALID_SLOTS:
                if not self._connected.get(s):
                    out[s] = 0.0
                    continue
                lvl, ts = self._voice[s]
                out[s] = lvl if (ts > 0.0 and (ts_now - ts) < VOICE_EXPIRY_SEC) else 0.0
            return out

    def drain_actions(self):
        """Extrae en bloque las acciones pendientes por slot para procesar en el hilo UI."""
        with self._lock:
            if self._panic_frozen:
                for s in VALID_SLOTS:
                    self._actions[s].clear()
                return []
            batch = []
            for s in VALID_SLOTS:
                q = self._actions[s]
                while q:
                    batch.append((s, q.popleft()))
            return batch

    def status_snapshot(self):
        with self._lock:
            return {
                "panic_frozen": self._panic_frozen,
                "slots": {
                    s: {
                        "connected": self._connected[s],
                        "foreground": self._foreground[s],
                        "display_name": self._meta[s]["display_name"],
                        "tag": self._meta[s]["tag"],
                    }
                    for s in VALID_SLOTS
                },
            }


class GuestCommandExecutor:
    """Capa independiente de comandos de invitado con permisos default-deny y cooldowns."""

    def __init__(self, app):
        self.app = app
        self.permissions = {s: default_guest_permissions() for s in VALID_SLOTS}
        self._last_action_ts = {}  # (slot, action) -> monotonic
        self._window_hits = {s: deque() for s in VALID_SLOTS}

    def set_permissions(self, slot, perms_dict):
        if slot not in VALID_SLOTS or not isinstance(perms_dict, dict):
            return
        cur = self.permissions[slot]
        for k in PERMISSION_KEYS:
            if k in perms_dict:
                cur[k] = bool(perms_dict[k])

    def get_permissions(self, slot):
        if slot not in VALID_SLOTS:
            return default_guest_permissions()
        return dict(self.permissions[slot])

    def _allow_cooldown(self, slot, action, now):
        cd = ACTION_COOLDOWN_SEC.get(action, 0.30)
        key = (slot, action)
        last = self._last_action_ts.get(key, 0.0)
        if (now - last) < cd:
            return False

        hits = self._window_hits[slot]
        cutoff = now - GUEST_WINDOW_SEC
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= GUEST_WINDOW_MAX_ACTIONS:
            return False

        self._last_action_ts[key] = now
        hits.append(now)
        return True

    def execute(self, slot, cmd, now=None):
        """Ejecuta un comando ya validado de invitado forzando `slot` y permisos locales."""
        if slot not in VALID_SLOTS:
            return {"ok": False, "reason": "invalid_slot"}
        if self.app.guest_inbox.is_panic_frozen():
            return {"ok": False, "reason": "panic_frozen"}

        try:
            clean = validate_guest_action(cmd)
        except SchemaError:
            return {"ok": False, "reason": "invalid_schema"}

        action = clean["action"]
        perm_key = {
            "set_emotion": "emotion",
            "set_prop": "prop",
            "flip_x": "flip_x",
            "scream": "scream",
            "set_character": "character",
        }.get(action)

        # Fuente de verdad: permisos locales del Host (default-deny)
        if not perm_key or not self.permissions.get(slot, {}).get(perm_key, False):
            return {"ok": False, "reason": "forbidden"}

        ts_now = time.monotonic() if now is None else float(now)
        if not self._allow_cooldown(slot, action, ts_now):
            return {"ok": False, "reason": "cooldown"}

        if slot == 2:
            return self._apply_to_player2(action, clean)
        return self._apply_to_extra_slot(slot, action, clean)

    def _apply_to_extra_slot(self, slot, action, clean):
        slot_data = self.app._get_guest_slot_data(slot)
        if not isinstance(slot_data, dict):
            return {"ok": False, "reason": "slot_uninitialized"}

        if action == "set_emotion":
            em_id = clean["id"]
            if not (1 <= em_id <= 5):
                return {"ok": False, "reason": "emotion_out_of_range"}
            slot_data["active_emotion"] = em_id - 1
            self.app._sync_remote_slot_window(slot)
            return {"ok": True}

        if action == "set_prop":
            props = slot_data.get("props") or []
            idx = clean["id"]
            if not (0 <= idx < len(props)):
                return {"ok": False, "reason": "prop_not_found"}
            props[idx]["enabled"] = bool(clean["enabled"])
            self.app._sync_remote_slot_window(slot)
            return {"ok": True}

        if action == "flip_x":
            slot_data["flip_x"] = bool(clean["enabled"])
            self.app._sync_remote_slot_window(slot)
            return {"ok": True}

        if action == "scream":
            slot_data["_forced_scream"] = bool(clean["enabled"])
            win = (getattr(self.app, "extra_avatar_windows", {}) or {}).get(slot)
            if win and win.winfo_exists():
                win._manual_scream = bool(clean["enabled"])
                win.set_screaming(bool(clean["enabled"]))
            return {"ok": True}

        if action == "set_character":
            names = list((self.app.profiles.get("player2") or {}).keys())
            idx = clean["id"]
            if not (0 <= idx < len(names)):
                return {"ok": False, "reason": "character_not_found"}
            self.app.set_remote_slot_character(slot, names[idx])
            return {"ok": True}

        return {"ok": False, "reason": "unknown_action"}

    def _apply_to_player2(self, action, clean):
        p2 = self.app.p2_data

        if action == "set_emotion":
            em_id = clean["id"]
            if not (1 <= em_id <= 5):
                return {"ok": False, "reason": "emotion_out_of_range"}
            self.app._set_player_forced_emotion_slot(2, em_id)
            return {"ok": True}

        if action == "set_prop":
            props = p2.get("props") or []
            idx = clean["id"]
            if not (0 <= idx < len(props)):
                return {"ok": False, "reason": "prop_not_found"}
            prop_obj = props[idx]
            target = prop_obj.get("id") or prop_obj.get("name")
            if not target:
                return {"ok": False, "reason": "prop_invalid"}
            self.app._set_player_forced_prop(2, target, clean["enabled"])
            return {"ok": True}

        if action == "flip_x":
            self.app._set_player_forced_flip_x(2, clean["enabled"])
            return {"ok": True}

        if action == "scream":
            self.app._set_player_forced_scream(2, clean["enabled"])
            return {"ok": True}

        if action == "set_character":
            names = list((self.app.profiles.get("player2") or {}).keys())
            idx = clean["id"]
            if not (0 <= idx < len(names)):
                return {"ok": False, "reason": "character_not_found"}
            self.app._choose_character_from_card_list(2, names[idx])
            return {"ok": True}

        return {"ok": False, "reason": "unknown_action"}
