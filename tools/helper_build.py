"""Bind the portable helper to the reviewed runtime inputs used to build it."""
from __future__ import annotations

import hashlib
import json
import platform
from importlib import metadata
from pathlib import Path

from release_assets import reviewed_gallery
from switchboard_version import VERSION

BASELINES = (
    "research/vanilla/panorama/layout/chat.xml",
    "research/vanilla/panorama/layout/popups/popup_settings.xml",
    "research/vanilla/panorama/layout/citadel_dashboard_footer_bar.xml",
    "research/baseline.json",
)


def helper_inputs(root: Path) -> dict[str, str]:
    paths = [root / name for name in BASELINES]
    paths += [root / name for name in (
        "launcher.py", "tools/build.py", "tools/source2.py", "tools/settings.py",
        "tools/switchboard_version.py", "tools/package_exe.py",
    )]
    paths += [p for folder in ("web", "src", "themes")
              for p in (root / folder).rglob("*") if p.is_file()]
    paths += reviewed_gallery(root)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths))}


def toolchain() -> dict[str, str]:
    """Python and PyInstaller versions. Embedded code only compares equal under the same pair."""
    try:
        pyinstaller = metadata.version("pyinstaller")
    except metadata.PackageNotFoundError:
        pyinstaller = "not installed"
    return {"python": platform.python_version(), "pyinstaller": pyinstaller}


def toolchain_difference(root: Path) -> str:
    """Plain-language note when this machine's toolchain differs from the one that built the helper."""
    try:
        stamp = json.loads((root / "release/Switchboard.build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    built, current = {k: stamp.get(k) for k in ("python", "pyinstaller")}, toolchain()
    differences = [f"{name} {built[name] or 'unknown'} when built, {current[name]} now"
                   for name in ("python", "pyinstaller") if built[name] and built[name] != current[name]]
    if not differences:
        return ""
    return ("The helper was built with a different toolchain (" + "; ".join(differences) + "). "
            "Run the audit with the versions pinned in requirements-dev.txt, or rebuild the helper.")


def record_helper(root: Path) -> None:
    exe = root / "release/Switchboard.exe"
    stamp = {"format": 1, "version": VERSION, **toolchain(),
             "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
             "inputs": helper_inputs(root)}
    exe.with_suffix(".build.json").write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")


def verify_helper(root: Path) -> None:
    try:
        stamp = json.loads((root / "release/Switchboard.build.json").read_text(encoding="utf-8"))
        current_hash = hashlib.sha256((root / "release/Switchboard.exe").read_bytes()).hexdigest()
    except (OSError, ValueError) as exc:
        raise ValueError("Build the portable helper before packaging a release.") from exc
    if not isinstance(stamp, dict) or stamp.get("format") != 1 or stamp.get("version") != VERSION or stamp.get("sha256") != current_hash or stamp.get("inputs") != helper_inputs(root):
        raise ValueError("The portable helper or its inputs changed. Rebuild it before packaging.")
