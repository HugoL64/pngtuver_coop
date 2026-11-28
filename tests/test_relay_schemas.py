import hashlib
import secrets
import unittest

from core.relay_schemas import (
    PROTOCOL_VERSION,
    SchemaError,
    parse_json_strict,
    sanitize_label,
    validate_auth_host,
    validate_guest_action,
    validate_guest_voice,
    validate_join,
    validate_permissions,
    validate_pin_kdf,
    validate_state_sync,
)


class TestRelaySchemas(unittest.TestCase):
    def test_parse_json_strict_rejects_nan_infinity_and_oversize(self):
        with self.assertRaises(SchemaError):
            parse_json_strict('{"a": NaN}', 1024)
        with self.assertRaises(SchemaError):
            parse_json_strict('{"a": Infinity}', 1024)
        with self.assertRaises(SchemaError) as ctx:
            parse_json_strict('{"a": "hola"}', 5)
        self.assertEqual(ctx.exception.close_code, 1009)
        with self.assertRaises(SchemaError):
            parse_json_strict('[1, 2, 3]', 1024)

    def test_sanitize_label_strips_bidi_and_controls(self):
        dirty = "Alex\u202e\u200f\x07\nTest"
        self.assertEqual(sanitize_label(dirty, max_len=20), "AlexTest")
        with self.assertRaises(SchemaError):
            sanitize_label("\u202e\x00   ", allow_empty=False)

    def test_validate_guest_voice_rejects_bool_and_out_of_range(self):
        ok = validate_guest_voice({"v": PROTOCOL_VERSION, "t": "voice", "seq": 1, "level": 42.5})
        self.assertEqual(ok["level"], 42.5)
        with self.assertRaises(SchemaError):
            validate_guest_voice({"v": PROTOCOL_VERSION, "t": "voice", "seq": True, "level": 10})
        with self.assertRaises(SchemaError):
            validate_guest_voice({"v": PROTOCOL_VERSION, "t": "voice", "seq": 1, "level": 101.0})
        with self.assertRaises(SchemaError):
            validate_guest_voice({"v": PROTOCOL_VERSION, "t": "voice", "seq": 1, "level": 10, "extra": 1})

    def test_validate_guest_action_variants(self):
        a1 = validate_guest_action({"v": PROTOCOL_VERSION, "t": "action", "seq": 2, "action": "set_emotion", "id": 3})
        self.assertEqual(a1["id"], 3)
        a2 = validate_guest_action({"v": PROTOCOL_VERSION, "t": "action", "seq": 3, "action": "set_prop", "id": 0, "enabled": True})
        self.assertTrue(a2["enabled"])
        with self.assertRaises(SchemaError):
            validate_guest_action({"v": PROTOCOL_VERSION, "t": "action", "seq": 4, "action": "flip_x", "enabled": "yes"})
        with self.assertRaises(SchemaError):
            validate_guest_action({"v": PROTOCOL_VERSION, "t": "action", "seq": 5, "action": "exec_cmd", "id": 1})

    def test_validate_pin_kdf_and_auth_host(self):
        salt = secrets.token_hex(16)
        h = hashlib.scrypt(b"1234", salt=salt.encode(), n=16384, r=8, p=1, dklen=32).hex()
        kdf = {"alg": "scrypt", "salt": salt, "params": {"N": 16384, "r": 8, "p": 1}, "hash": h}
        self.assertEqual(validate_pin_kdf(kdf)["params"]["N"], 16384)
        bad = dict(kdf, params={"N": 16383, "r": 8, "p": 1})
        with self.assertRaises(SchemaError):
            validate_pin_kdf(bad)

        auth = validate_auth_host({
            "v": PROTOCOL_VERSION,
            "t": "auth_host",
            "host_secret": "a" * 32,
            "room_code": None,
            "invite_token_hash": "0" * 64,
            "pin_kdf": kdf,
        })
        self.assertIn("pin_kdf", auth)

    def test_validate_join_and_state_sync(self):
        j = validate_join({
            "v": PROTOCOL_VERSION,
            "t": "join",
            "room_code": "ABCDEFGH",
            "invite_token": "x" * 24,
            "display_name": "Invitado",
        })
        self.assertEqual(j["display_name"], "Invitado")

        perms = validate_permissions({"emotion": True, "prop": False, "flip_x": False, "scream": False, "character": False})
        st = validate_state_sync({
            "v": PROTOCOL_VERSION,
            "t": "state_sync",
            "to": 2,
            "state_version": 1,
            "state": {
                "slot": 2,
                "active_character_id": 0,
                "characters": [{"id": 0, "name": "Nara"}],
                "active_emotion": 1,
                "emotions": [{"id": 1, "name": "Normal"}],
                "props": [{"id": 0, "name": "Lentes", "enabled": True}],
                "flip_x": False,
                "screaming": False,
                "permissions": perms,
            },
        })
        self.assertEqual(st["to"], 2)


if __name__ == "__main__":
    unittest.main()
