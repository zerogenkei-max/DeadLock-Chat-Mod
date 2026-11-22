import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from _release_fixture import ReleaseFixture, boot_vpk, write
import audit_release
import helper_build
from switchboard_version import artifact_name

TOKEN = "a" * 43


class AuditArchiveTest(ReleaseFixture):
    def setUp(self):
        super().setUp()
        self.make_release()

    def test_a_consistent_release_passes(self):
        report = self.audit_archives()
        self.assertEqual(set(report), {"Mod", "Source", "Windows"})
        self.assertEqual(report["Mod"]["files"], 6)
        audit_release.audit_checksums(self.release)
        self.assertEqual(audit_release.audit_vpk(self.release)["token"], "empty")

    def test_missing_entry_is_reported(self):
        self.rewrite_zip("Mod", lambda entries: entries.pop("LICENSE"))
        with self.assertRaisesRegex(ValueError, "Missing: .*LICENSE"):
            self.audit_archives()

    def test_extra_entry_is_reported(self):
        self.rewrite_zip("Mod", lambda entries: entries.update({"gallery/cover.png": b"image"}))
        with self.assertRaisesRegex(ValueError, "Extra: .*gallery/cover.png"):
            self.audit_archives()

    def test_second_vpk_in_the_mod_zip_is_rejected(self):
        self.rewrite_zip("Mod", lambda entries: entries.update({"other_dir.vpk": b"x"}))
        with self.assertRaisesRegex(ValueError, "wrong contents"):
            self.audit_archives()

    def test_changed_file_content_is_rejected(self):
        self.rewrite_zip("Mod", lambda entries: entries.update({"README.md": b"edited after packaging"}))
        with self.assertRaisesRegex(ValueError, "differs from current release inputs"):
            self.audit_archives()

    def test_version_mismatch_in_mod_json_is_rejected(self):
        def change(entries):
            meta = json.loads(entries["mod.json"])
            meta["version"] = "0.0.1"
            entries["mod.json"] = (json.dumps(meta, indent=2) + "\n").encode()
        # Keep release/mod.json equal so only the identity check can fail.
        self.rewrite_zip("Mod", change)
        (self.release / "mod.json").write_bytes(
            __import__("zipfile").ZipFile(self.release / artifact_name("Mod")).read("mod.json"))
        with self.assertRaisesRegex(ValueError, "mod.json does not match"):
            self.audit_archives()

    def test_ai_disclosure_must_name_codex_and_claude(self):
        for name in ("README.md", "LISTING.md"):
            for dropped in ("Codex", "Claude"):
                with self.subTest(name=name, dropped=dropped):
                    original = (self.root / name).read_text(encoding="utf-8")
                    (self.root / name).write_text(original.replace(dropped, "tool"), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, f"{name} must mention.*{dropped}"):
                        self.audit_archives()
                    (self.root / name).write_text(original, encoding="utf-8")

    def test_supplied_token_in_either_encoding_is_found(self):
        for form in (TOKEN.encode(), TOKEN.encode("utf-16-le")):
            with self.subTest(form=len(form)):
                self.rewrite_zip("Mod", lambda entries, form=form: entries.update({"switchboard_dir.vpk": b"x" + form}))
                (self.release / "switchboard_dir.vpk").write_bytes(b"x" + form)
                with self.assertRaisesRegex(ValueError, "private token"):
                    self.audit_archives(audit_release.read_tokens(self.token_file()))

    def token_file(self, text=TOKEN):
        path = self.root / "token.txt"
        path.write_text(text, encoding="utf-8")
        return [path]


class AuditInputTest(ReleaseFixture):
    def test_token_files_must_exist_and_hold_a_token(self):
        path = self.root / "t.txt"
        with self.assertRaisesRegex(ValueError, "missing or unreadable"):
            audit_release.read_tokens([self.root / "absent.txt"])
        for content in ("", "\n", "short", "a" * 44, "a" * 42 + "!"):
            path.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, "empty or not a 43-character"):
                audit_release.read_tokens([path])
        path.write_text(TOKEN + "\n", encoding="utf-8")
        self.assertEqual(audit_release.read_tokens([path]), [TOKEN.encode(), TOKEN.encode("utf-16-le")])

    def test_no_token_files_is_fine(self):
        self.assertEqual(audit_release.read_tokens([]), [])


class AuditChecksumTest(ReleaseFixture):
    def setUp(self):
        super().setUp()
        self.make_release()
        self.sums = self.release / "SHA256SUMS.txt"

    def test_valid_file_passes(self):
        audit_release.audit_checksums(self.release)

    def test_empty_or_half_empty_file_is_rejected(self):
        self.sums.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            audit_release.audit_checksums(self.release)
        lines = self.sums.read_bytes()
        self.make_release()
        first = self.sums.read_bytes().split(b"\n")[0] + b"\n"
        self.sums.write_bytes(first)
        with self.assertRaisesRegex(ValueError, "exactly the release files.*Missing"):
            audit_release.audit_checksums(self.release)

    def test_extra_entry_is_rejected(self):
        self.sums.write_bytes(self.sums.read_bytes() + b"0" * 64 + b"  extra.zip\n")
        with self.assertRaisesRegex(ValueError, "Extra: .*extra.zip"):
            audit_release.audit_checksums(self.release)

    def test_crlf_and_wrong_hash_are_rejected(self):
        data = self.sums.read_bytes()
        self.sums.write_bytes(data.replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(ValueError, "LF"):
            audit_release.audit_checksums(self.release)
        self.sums.write_bytes(b"0" * 64 + data[64:])
        with self.assertRaisesRegex(ValueError, "mismatch"):
            audit_release.audit_checksums(self.release)


class AuditVpkTest(ReleaseFixture):
    def test_token_or_artwork_in_the_public_vpk_is_rejected(self):
        boot_vpk(self.release / "switchboard_dir.vpk", token="secret")
        with self.assertRaisesRegex(ValueError, "personal token"):
            audit_release.audit_vpk(self.release)
        boot_vpk(self.release / "switchboard_dir.vpk", has_artwork=True)
        with self.assertRaisesRegex(ValueError, "without artwork"):
            audit_release.audit_vpk(self.release)


class ToolchainMessageTest(ReleaseFixture):
    def test_different_python_or_pyinstaller_is_explained(self):
        stamp = {"python": "3.0.0", "pyinstaller": "1.0"}
        write(self.release / "Switchboard.build.json", json.dumps(stamp))
        message = helper_build.toolchain_difference(self.root)
        self.assertIn("python 3.0.0 when built", message)
        self.assertIn("requirements-dev.txt", message)
        current = helper_build.toolchain()
        write(self.release / "Switchboard.build.json", json.dumps(current))
        self.assertEqual(helper_build.toolchain_difference(self.root), "")
        write(self.release / "Switchboard.build.json", "{}")
        self.assertEqual(helper_build.toolchain_difference(self.root), "")

    def test_stamp_records_python_and_pyinstaller_versions(self):
        with patch.object(helper_build, "reviewed_gallery", return_value=[]), \
                patch.object(helper_build, "helper_inputs", return_value={}):
            helper_build.record_helper(self.root)
        stamp = json.loads((self.release / "Switchboard.build.json").read_text(encoding="utf-8"))
        self.assertEqual({k: stamp[k] for k in ("python", "pyinstaller")}, helper_build.toolchain())


if __name__ == "__main__":
    unittest.main()
