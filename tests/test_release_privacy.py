import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from release_privacy import assert_public_files

WIN = chr(92)
SLASH = "/"


class ReleasePrivacyTest(unittest.TestCase):
    def scan(self, content, name="docs/readme.md", filename="fixture.md"):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / filename
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return assert_public_files([(path, name)])

    def test_rejects_literal_absolute_machine_paths_without_echoing_them(self):
        profile = "C:" + WIN + "Users" + WIN + "Alice" + WIN + "Documents" + WIN + "repo"
        game = "O:" + WIN + "SteamLibrary" + WIN + "steamapps" + WIN + "common" + WIN + "Deadlock"
        unc = WIN * 2 + "workstation" + WIN + "Users" + WIN + "Alice" + WIN + "repo"
        home = SLASH + "home" + SLASH + "alice" + SLASH + "project"
        escaped = "C:" + WIN * 2 + "Users" + WIN * 2 + "Alice" + WIN * 2 + "project"
        for value in (profile, game, unc, home, escaped):
            with self.subTest(kind="path"):
                with self.assertRaisesRegex(ValueError, r"docs/readme\.md:1: literal absolute machine path") as caught:
                    self.scan("Example: " + value)
                self.assertNotIn(value, str(caught.exception))

    def test_rejects_the_other_path_styles(self):
        values = {
            "double-escaped twice": "C:" + WIN * 4 + "Users" + WIN * 4 + "Alice",
            "wsl": "/mnt/c/" + "Users/Alice/repo",
            "cygwin": "/cygdrive/c/" + "Users/Alice/repo",
            "home shorthand": "~" + "/projects/switchboard",
            "profile variable": "%USER" + "PROFILE%" + WIN + "Documents",
            "powershell profile": "$env:USER" + "PROFILE/Documents",
            "network share": "/" + "/fileserver/share/mods",
            "file uri": "file:///" + "C:" + "/Us" + "ers/Alice/repo",
            "unc share": WIN * 2 + "fileserver" + WIN + "share",
        }
        for kind, value in values.items():
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, r"docs/readme\.md:2: literal absolute machine path") as caught:
                    self.scan("fine line\nSee " + value + " for details")
                self.assertNotIn(value, str(caught.exception))

    def test_allows_game_uris_urls_relative_paths_and_generic_environment_variables(self):
        self.scan("asset://panorama/images/icons/hero.svg\nhttps://example.test/help\n"
                  "game/citadel/addons\n%LOCALAPPDATA%/Switchboard\n// a comment\nand/or")

    def test_scans_text_files_whatever_their_suffix(self):
        with self.assertRaisesRegex(ValueError, r"notes\.dat:1"):
            self.scan("C:" + WIN + "Users" + WIN + "Alice", name="notes.dat", filename="notes.dat")
        with self.assertRaisesRegex(ValueError, r"vendor/README:1"):
            self.scan("/mnt/d/" + "Users/Alice", name="vendor/README", filename="README")

    def test_binary_files_are_scanned_in_ascii_and_utf16(self):
        path = "C:" + WIN + "Users" + WIN + "Alice" + WIN + "x"
        for kind, blob in {"ascii": b"\x89PNG\r\n\x1a\n\0\0" + path.encode(),
                           "utf16": b"MZ\0\0" + path.encode("utf-16-le"),
                           "mac": b"\0\1" + b"/Us" + b"ers/alice/Desktop",
                           "odd utf16 alignment": b"\0" + (SLASH + "Users" + SLASH + "alice").encode("utf-16-le")}.items():
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, r"gallery/fixture\.png: literal absolute machine path in binary") as caught:
                    self.scan(blob, name="gallery/fixture.png", filename="fixture.png")
                self.assertNotIn("Alice", str(caught.exception))

    def test_binary_files_without_private_paths_pass(self):
        public = "C:" + WIN + "Users" + WIN + "Public" + WIN + "Documents"
        self.scan(b"\x89PNG\r\n\x1a\n\0\0" + bytes(range(256)) * 4, name="a.png", filename="a.png")
        self.scan(b"MZ\0\0" + public.encode("utf-16-le"), name="Switchboard.exe", filename="a.exe")

    def test_private_words_come_from_the_environment(self):
        with patch.dict(os.environ, {"SWITCHBOARD_PRIVATE_WORDS": ""}):
            self.scan("a note from zorbak", name="n.md")
        with patch.dict(os.environ, {"SWITCHBOARD_PRIVATE_WORDS": "Qwerty, zorbak"}):
            with self.assertRaisesRegex(ValueError, r"n\.md:2: private word") as caught:
                self.scan("fine\nA note from ZORBAK", name="n.md")
            self.assertNotIn("zorbak", str(caught.exception).lower())
            with self.assertRaisesRegex(ValueError, "file name contains a private word"):
                self.scan("fine", name="qwerty/readme.md")
            for blob in (b"\0\0zorbak", "zorbak".encode("utf-16-le") + b"\0"):
                with self.assertRaisesRegex(ValueError, "private word in binary data"):
                    self.scan(blob, name="a.vpk", filename="a.vpk")
            self.scan("nothing private here", name="ok.md")


if __name__ == "__main__":
    unittest.main()
