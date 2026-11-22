"""Build Switchboard against the extracted layouts of the current Deadlock build."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from source2 import VPK, compile_tree, pack, png_texture, resource
from settings import normalize
from switchboard_version import VERSION

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
OVERRIDES = ["chat.xml", "popups/popup_settings.xml", "citadel_dashboard_footer_bar.xml"]


def _replace_once(text: str, needle: str, replacement: str, what: str, layout: str) -> str:
    if needle not in text:
        raise ValueError(f"Deadlock changed {layout}: {what} was not found. "
                         "Inspect the current layout before rebuilding.")
    return text.replace(needle, replacement, 1)


def hook_layout(text: str, name: str) -> str:
    """Add the Switchboard hooks to one Deadlock layout.

    Every replacement has to happen. If Valve changes the text a hook relies on,
    this raises instead of shipping a mod with no scripts or no Settings button.
    """
    if name not in OVERRIDES:
        raise ValueError("Unknown layout: " + str(name))
    css = '<include src="s2r://panorama/styles/switchboard.vcss" />'
    scripts = "<scripts>" + "".join('<include src="s2r://panorama/scripts/' + script + '.vts" />'
                                    for script in ("switchboard_shared", "switchboard_boot", "switchboard_runtime")) + "</scripts>"
    text = _replace_once(text, "</styles>", css + "\n</styles>", "the </styles> tag", name)
    text = _replace_once(text, "<snippets>", scripts + "\n<snippets>", "the <snippets> tag", name)
    if name == "chat.xml":
        needle = '<Label class="SenderName" text="{s:sender_name}" />'
        text = _replace_once(text, needle, needle + '\n<Label class="SBColon" text=":" />', "the SenderName label", name)
    elif name == "popups/popup_settings.xml":
        needle = '<Panel class="SettingsFooterButtons">'
        text = _replace_once(text, needle, '<Panel id="SwitchboardFooterActions" class="SettingsFooterButtons">',
                             "the SettingsFooterButtons panel", name)
    return text


def load_baseline() -> dict:
    return json.loads((ROOT / "research/baseline.json").read_text(encoding="utf-8"))


def build(settings: dict | None = None, token: str = "", artwork: Path | None = None,
          output: Path | None = None, verify: bool = True) -> Path:
    settings = normalize(settings or {})
    files = compile_tree(ROOT / "src")
    originals = ROOT / "research/vanilla/panorama/layout"
    originals_hashes = {}
    for name in OVERRIDES:
        source = originals / name
        original = source.read_text(encoding="utf-8")
        ET.fromstring(original)
        text = hook_layout(original, name)
        ET.fromstring(text)
        files["panorama/layout/" + name.removesuffix(".xml") + ".vxml_c"] = resource(text, "xml")
        originals_hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    has_artwork = bool(artwork and artwork.is_file())
    boot = "var SwitchboardBoot = " + json.dumps({"version": VERSION, "settings": settings, "token": token,
                                                  "hasArtwork": has_artwork}, ensure_ascii=True) + ";"
    files["panorama/scripts/switchboard_boot.vts_c"] = resource(boot, "vts")
    if has_artwork:
        files["panorama/images/switchboard/custom_background.vtex_c"] = png_texture(artwork.read_bytes())
    elif settings["artwork"]:
        raise ValueError("Upload artwork before enabling the custom background")
    # Check all script syntax, independently of the game renderer.
    if verify:
        for path in (ROOT / "src/panorama/scripts").glob("*.vts"):
            code = "new (require('vm').Script)(require('fs').readFileSync(process.argv[1], 'utf8'));"
            result = subprocess.run(["node", "-e", code, str(path)], capture_output=True, text=True)
            if result.returncode:
                raise ValueError(f"Syntax check failed for {path.name}: {result.stderr.strip()}")
    for path in (ROOT / "src/panorama/layout").glob("*.xml"):
        ET.parse(path)
    destination = output or ROOT / "build/switchboard_dir.vpk"
    pack(files, destination)
    package = VPK(destination)
    for name in package.entries:
        if package.read(name) != files[name]:
            raise ValueError(f"VPK round-trip mismatch: {name}")
    baseline = load_baseline()
    manifest = {"name": "Switchboard", "version": VERSION, "game_build": baseline["steam_build"],
                "game_version": baseline["game_version"],
                "source_layouts_sha256": originals_hashes, "files": sorted(files),
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                "settings": settings}
    destination.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--artwork", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = json.loads(args.settings.read_text(encoding="utf-8")) if args.settings else {}
    print(build(config, artwork=args.artwork, output=args.output))
