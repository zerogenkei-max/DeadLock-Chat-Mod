"""A small fake project root for the release and audit tests. Nothing here touches the real release/ folder."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import audit_release
import release
import release_assets
from source2 import pack, resource

CRCS = {
    "panorama/layout/chat.vxml_c": 1,
    "panorama/layout/popups/popup_settings.vxml_c": 2,
    "panorama/layout/citadel_dashboard_footer_bar.vxml_c": 3,
}
DISCLOSURE = "Written with OpenAI Codex and Claude."


def write(path: Path, content="fixture\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return path


def boot_vpk(path: Path, token="", has_artwork=False):
    from switchboard_version import VERSION
    boot = "var SwitchboardBoot = " + json.dumps({"version": VERSION, "settings": {}, "token": token,
                                                  "hasArtwork": has_artwork}) + ";"
    pack({"panorama/scripts/switchboard_boot.vts_c": resource(boot, "vts")}, path)


class ReleaseFixture(unittest.TestCase):
    """Builds a fake root with every release input, then real archives from it."""

    def setUp(self):
        from switchboard_version import VERSION
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = root = Path(self.temp.name)
        self.release = root / "release"
        for name in release_assets.FULL_DOCUMENTS + ["launcher.py", "Switchboard.cmd", ".gitignore",
                                                      "PUBLISHING.md", "requirements-dev.txt"]:
            write(root / name, f"{name} fixture\n")
        write(root / "README.md", "# Readme\n" + DISCLOSURE + "\n")
        write(root / "LISTING.md", "# Listing\n" + DISCLOSURE + "\n")
        write(root / "research/baseline.json", json.dumps({"steam_build": "100", "game_version": "9",
                                                           "resource_crcs": CRCS}))
        self.write_compat()
        for name, content in {"src/a.vts": "var a;", "src/b.png": b"\x89PNG not allowlisted",
                              "tools/x.py": "x = 1\n", "tools/probe.py": "probe\n", "tools/Switchboard.spec": "spec",
                              "tests/t.py": "t = 1\n", "tests/__pycache__/t.pyc": b"pyc",
                              "themes/t.json": "{}", "web/index.html": "<html></html>",
                              "licenses/L.txt": "licence"}.items():
            write(root / name, content)
        for name in release_assets.LAYOUTS:
            write(root / "research/vanilla/panorama/layout" / name, "<root><styles></styles><snippets></snippets></root>")
        self.gallery = [write(root / "gallery" / n, b"image " + n.encode()) for n in ("cover.png", "a.jpg")]
        self.release.mkdir()
        boot_vpk(self.release / release_assets.PACKAGE)
        write(self.release / "Switchboard.exe", b"MZ fixture exe")
        write(self.release / "Switchboard.build.json", "{}")
        (self.release / "mod.json").write_text(json.dumps(release_assets.expected_mod_json(root), indent=2) + "\n",
                                               encoding="utf-8", newline="\n")
        self.version = VERSION

    def write_compat(self, **changes):
        record = {"game": "9", "steam": "100", "checked": "2026-11-13", "resources": dict(CRCS),
                  "result": "unchanged from baseline"}
        record.update(changes)
        write(self.root / "research/compatibility.json", json.dumps(record))

    def make_release(self):
        release.make_archives(self.root, self.release, self.gallery)
        release.write_checksums(self.release, release_assets.checksum_targets(self.release))

    def audit_archives(self, tokens=()):
        with patch.object(audit_release, "reviewed_gallery", return_value=self.gallery):
            return audit_release.audit_archives(self.root, list(tokens))

    def rewrite_zip(self, kind, mutate):
        """Rewrite one archive after calling mutate(dict name -> bytes)."""
        import zipfile
        from switchboard_version import artifact_name
        path = self.release / artifact_name(kind)
        with zipfile.ZipFile(path) as z:
            entries = {n: z.read(n) for n in z.namelist()}
        mutate(entries)
        with zipfile.ZipFile(path, "w") as z:
            for name, data in entries.items():
                z.writestr(name, data)
