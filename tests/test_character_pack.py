import json
import os
import stat
import tempfile
import unittest
import zipfile

from core.character_pack import export_character_zip, import_character_zip
from core.emotions import normalize_emotion_slots
from core.safe_paths import is_within, safe_join_within


class TestCharacterPackSecurity(unittest.TestCase):
    def test_safe_join_within_blocks_escapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            char_dir = os.path.join(tmp, "personajes", "Foo")
            sib_dir = os.path.join(tmp, "personajes", "Foo (2)")
            os.makedirs(os.path.join(char_dir, "props"))
            os.makedirs(sib_dir)
            ok = os.path.join(char_dir, "props", "a.png")
            with open(ok, "wb") as f:
                f.write(b"png")

            self.assertEqual(safe_join_within(char_dir, "props/a.png"), os.path.abspath(ok))
            self.assertIsNone(safe_join_within(char_dir, "../../secret.txt"))
            self.assertIsNone(safe_join_within(char_dir, "..\\..\\secret.txt"))
            self.assertIsNone(safe_join_within(char_dir, "../Foo (2)/x.png"))
            self.assertIsNone(safe_join_within(char_dir, ok))
            self.assertIsNone(safe_join_within(char_dir, "C:secret.txt"))
            self.assertFalse(is_within(char_dir, sib_dir))

    def test_export_character_zip_prevents_path_leak_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            char_dir = os.path.join(tmp, "personajes", "Foo")
            os.makedirs(os.path.join(char_dir, "props"))
            secret = os.path.join(tmp, "secreto.txt")
            with open(secret, "w", encoding="utf-8") as f:
                f.write("PRIVADO")
            with open(os.path.join(char_dir, "props", "a.png"), "wb") as f:
                f.write(b"img")
            for name in ("idle.png", "talk.png"):
                with open(os.path.join(char_dir, name), "wb") as f:
                    f.write(b"p")

            meta = {
                "name": "Foo",
                "extra_expressions": [
                    {"role": "leak", "file_rel": "../../secreto.txt"},
                    {"role": "dup", "file_rel": "props/a.png"},
                ],
                "emotion_slots": [
                    {"name": "1"},
                    {"name": "2", "images": {"idle": secret}, "images_rel": {"talk": "../../secreto.txt"}},
                ],
            }
            with open(os.path.join(char_dir, "character.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f)

            for slot_idx in (0, 1):
                out_zip = os.path.join(tmp, f"out_{slot_idx}.zip")
                export_character_zip(char_dir, "Foo", out_zip, slot_idx=slot_idx)
                with zipfile.ZipFile(out_zip, "r") as zf:
                    names = zf.namelist()
                    self.assertEqual(len(names), len(set(names)))
                    for n in names:
                        self.assertNotEqual(zf.read(n), b"PRIVADO")
                    self.assertIn("props/a.png", names)

    def test_import_character_zip_blocks_traversal_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            chars_dir = os.path.join(tmp, "personajes")
            zip_path = os.path.join(tmp, "malicious.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("character.json", json.dumps({"name": "Hero"}))
                zf.writestr("idle.png", b"ok")
                zf.writestr("../../evil.txt", b"pwn")
                zf.writestr("..\\..\\evil2.txt", b"pwn2")
                zi = zipfile.ZipInfo("symlink.txt")
                zi.create_system = 3
                zi.external_attr = (stat.S_IFLNK | 0o777) << 16
                zf.writestr(zi, "/etc/passwd")

            name, dest = import_character_zip(zip_path, chars_dir)
            self.assertEqual(name, "Hero")
            self.assertTrue(os.path.isfile(os.path.join(dest, "idle.png")))
            self.assertFalse(os.path.exists(os.path.join(dest, "symlink.txt")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "evil.txt")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "evil2.txt")))

    def test_import_character_zip_rejects_too_many_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            chars_dir = os.path.join(tmp, "personajes")
            zip_path = os.path.join(tmp, "many.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                for i in range(205):
                    zf.writestr(f"f_{i}.txt", b"x")
            with self.assertRaises(ValueError):
                import_character_zip(zip_path, chars_dir)

    def test_normalize_emotion_slots_ignores_rel_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            char_dir = os.path.join(tmp, "Foo")
            os.makedirs(char_dir)
            secret = os.path.join(tmp, "secreto.txt")
            with open(secret, "w", encoding="utf-8") as f:
                f.write("PRIVADO")
            slots = normalize_emotion_slots(
                [{"name": "1"}, {"name": "2", "images_rel": {"idle": "../secreto.txt"}}],
                folder_path=char_dir,
            )
            self.assertNotEqual(slots[1]["images"].get("idle", ""), os.path.abspath(secret))


if __name__ == "__main__":
    unittest.main()
