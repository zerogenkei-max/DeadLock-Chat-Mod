import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build
from source2 import VPK

LAYOUTS = ROOT / "research/vanilla/panorama/layout"


def source(name):
    return (LAYOUTS / name).read_text(encoding="utf-8")


class HookLayoutTest(unittest.TestCase):
    def test_real_layouts_are_hooked(self):
        chat = build.hook_layout(source("chat.xml"), "chat.xml")
        self.assertIn('class="SBColon"', chat)
        self.assertIn("switchboard_runtime.vts", chat)
        self.assertIn("switchboard.vcss", chat)
        popup = build.hook_layout(source("popups/popup_settings.xml"), "popups/popup_settings.xml")
        self.assertIn('id="SwitchboardFooterActions"', popup)
        footer = build.hook_layout(source("citadel_dashboard_footer_bar.xml"), "citadel_dashboard_footer_bar.xml")
        self.assertIn("switchboard_boot.vts", footer)

    def assert_loud(self, text, name, what):
        with self.assertRaisesRegex(ValueError, "Deadlock changed .*" + re.escape(what)):
            build.hook_layout(text, name)

    def test_each_missing_anchor_fails_the_build(self):
        chat = source("chat.xml")
        self.assert_loud(chat.replace("</styles>", ""), "chat.xml", "</styles>")
        self.assert_loud(chat.replace("<snippets>", "<snippet>"), "chat.xml", "<snippets>")
        self.assert_loud(chat.replace('class="SenderName"', 'class="Sender"'), "chat.xml", "SenderName")
        popup = source("popups/popup_settings.xml")
        self.assert_loud(popup.replace("SettingsFooterButtons", "FooterButtons"), "popups/popup_settings.xml",
                         "SettingsFooterButtons")
        self.assert_loud(popup.replace("</styles>", ""), "popups/popup_settings.xml", "</styles>")
        footer = source("citadel_dashboard_footer_bar.xml")
        self.assert_loud(footer.replace("<snippets>", ""), "citadel_dashboard_footer_bar.xml", "<snippets>")

    def test_unknown_layout_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown layout"):
            build.hook_layout("<root/>", "other.xml")


class BuildOutputTest(unittest.TestCase):
    def build(self, artwork=None, settings=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        out = build.build(settings, artwork=artwork, output=Path(temp.name) / "switchboard_dir.vpk", verify=False)
        package = VPK(out)
        boot = package.read("panorama/scripts/switchboard_boot.vts_c")
        config = json.loads(boot.split(b"var SwitchboardBoot = ", 1)[1].rsplit(b";", 1)[0])
        manifest = json.loads(out.with_suffix(".manifest.json").read_text(encoding="utf-8"))
        return config, manifest, package

    def test_has_artwork_is_false_without_an_image(self):
        config, _, package = self.build()
        self.assertIs(config["hasArtwork"], False)
        self.assertNotIn("panorama/images/switchboard/custom_background.vtex_c", package.entries)

    def test_has_artwork_is_true_only_when_artwork_is_compiled(self):
        sys.path.insert(0, str(ROOT / "tests"))
        from test_local_app import png
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        image = Path(temp.name) / "art.png"
        image.write_bytes(png())
        config, _, package = self.build(artwork=image, settings={"artwork": True})
        self.assertIs(config["hasArtwork"], True)
        self.assertIn("panorama/images/switchboard/custom_background.vtex_c", package.entries)
        missing = Path(temp.name) / "absent.png"
        config, _, _ = self.build(artwork=missing)
        self.assertIs(config["hasArtwork"], False)

    def test_manifest_game_build_comes_from_the_baseline(self):
        _, manifest, _ = self.build()
        baseline = json.loads((ROOT / "research/baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["game_build"], baseline["steam_build"])
        self.assertEqual(manifest["game_version"], baseline["game_version"])

    def test_default_output_is_the_build_folder_not_dist(self):
        source_text = (ROOT / "tools/build.py").read_text(encoding="utf-8")
        self.assertIn('ROOT / "build/switchboard_dir.vpk"', source_text)
        self.assertNotIn("dist/", source_text)
        self.assertNotIn("validate_settings", source_text)
        self.assertIn("build/", (ROOT / ".gitignore").read_text(encoding="utf-8").split())

    def test_syntax_check_failure_includes_nodes_stderr(self):
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="SyntaxError: Unexpected token ')'")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with patch.object(build.subprocess, "run", return_value=failed),                 self.assertRaisesRegex(ValueError, r"Syntax check failed for .*\.vts: SyntaxError: Unexpected token"):
            build.build(output=Path(temp.name) / "switchboard_dir.vpk", verify=True)

    def test_vanilla_layouts_are_not_gitignored(self):
        self.assertNotIn("research/vanilla/", (ROOT / ".gitignore").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
