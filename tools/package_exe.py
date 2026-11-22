"""Build the optional portable Windows launcher using an isolated PyInstaller env."""
import subprocess
import sys
from pathlib import Path
from release_assets import reviewed_gallery
from release_privacy import assert_public_files
from helper_build import helper_inputs, record_helper

root = Path(__file__).resolve().parents[1]
gallery = reviewed_gallery(root)
inputs = helper_inputs(root)
assert_public_files([(root / name, name) for name in inputs])
command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
           "--name", "Switchboard", "--icon", "NONE",
           "--distpath", str(root / "release"), "--workpath", str(root / "artifacts/pyinstaller"),
           "--specpath", str(root / "artifacts"), "--paths", str(root / "tools")]
for source, destination in [
    ("web", "web"), ("src", "src"), ("themes", "themes"),
    ("research/vanilla/panorama/layout/chat.xml", "research/vanilla/panorama/layout"),
    ("research/vanilla/panorama/layout/popups/popup_settings.xml", "research/vanilla/panorama/layout/popups"),
    ("research/vanilla/panorama/layout/citadel_dashboard_footer_bar.xml", "research/vanilla/panorama/layout"),
    ("research/baseline.json", "research"),
]:
    command.extend(["--add-data", str(root / source) + ";" + destination])
for path in gallery:
    command.extend(["--add-data", str(path) + ";gallery"])
command.append(str(root / "launcher.py"))
subprocess.run(command, cwd=root, check=True)
if helper_inputs(root) != inputs:
    raise ValueError("Runtime inputs changed during the build. Rebuild the helper before release.")
record_helper(root)
