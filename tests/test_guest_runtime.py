import unittest
from types import SimpleNamespace

from core.guest_runtime import GuestCommandExecutor, GuestInbox, default_guest_permissions


class _FakeApp:
    def __init__(self):
        self.guest_inbox = GuestInbox()
        self.p2_data = {
            "props": [{"id": "p0", "name": "Gorra", "enabled": True}],
            "flip_x": False,
            "active_emotion": 0,
        }
        self.profiles = {"player2": {"Nara": {}, "Gatito": {}}}
        self.calls = []

    def _set_player_forced_emotion_slot(self, pnum, em_id):
        self.calls.append(("emotion", pnum, em_id))

    def _set_player_forced_prop(self, pnum, target, enabled):
        self.calls.append(("prop", pnum, target, enabled))

    def _set_player_forced_flip_x(self, pnum, enabled):
        self.calls.append(("flip_x", pnum, enabled))

    def _set_player_forced_scream(self, pnum, enabled):
        self.calls.append(("scream", pnum, enabled))

    def _choose_character_from_card_list(self, pnum, name):
        self.calls.append(("character", pnum, name))


class TestGuestRuntime(unittest.TestCase):
    def test_inbox_monotonic_seq_and_voice_expiry(self):
        inbox = GuestInbox()
        inbox.on_guest_joined(2, display_name="Amigo", tag="123")
        self.assertTrue(inbox.push_voice(2, {"v": 1, "t": "voice", "seq": 1, "level": 50.0}))
        # seq repetido o menor debe rechazarse
        self.assertFalse(inbox.push_voice(2, {"v": 1, "t": "voice", "seq": 1, "level": 80.0}))
        snap = inbox.voice_snapshot()
        self.assertEqual(snap[2], 50.0)
        # expirado tras > 400 ms
        snap_late = inbox.voice_snapshot(now=9999999999.0)
        self.assertEqual(snap_late[2], 0.0)

    def test_executor_default_deny_and_permissions(self):
        app = _FakeApp()
        ex = GuestCommandExecutor(app)
        self.assertFalse(any(default_guest_permissions().values()))

        cmd = {"v": 1, "t": "action", "seq": 1, "action": "set_emotion", "id": 2}
        res = ex.execute(2, cmd, now=100.0)
        self.assertEqual(res, {"ok": False, "reason": "forbidden"})

        ex.set_permissions(2, {"emotion": True})
        res2 = ex.execute(2, cmd, now=100.0)
        self.assertEqual(res2, {"ok": True})
        self.assertEqual(app.calls[-1], ("emotion", 2, 2))

        # Cooldown (< 0.30 s)
        res3 = ex.execute(2, cmd, now=100.1)
        self.assertEqual(res3, {"ok": False, "reason": "cooldown"})

    def test_panic_freeze_blocks_and_clears(self):
        app = _FakeApp()
        app.guest_inbox.on_guest_joined(2, display_name="Amigo", tag="123")
        app.guest_inbox.push_action(2, {"v": 1, "t": "action", "seq": 1, "action": "flip_x", "enabled": True})
        app.guest_inbox.set_panic_freeze(True)
        self.assertEqual(app.guest_inbox.drain_actions(), [])
        ex = GuestCommandExecutor(app)
        ex.set_permissions(2, {"flip_x": True})
        res = ex.execute(2, {"v": 1, "t": "action", "seq": 2, "action": "flip_x", "enabled": True}, now=10.0)
        self.assertEqual(res, {"ok": False, "reason": "panic_frozen"})


if __name__ == "__main__":
    unittest.main()
