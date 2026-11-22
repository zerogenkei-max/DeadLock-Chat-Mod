"""Inspect release files and embedded code without executing the portable helper."""
from __future__ import annotations

import argparse
import hashlib
import json
import marshal
import re
import sys
import tempfile
import types
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from helper_build import helper_inputs, toolchain_difference, verify_helper
from release_assets import (KINDS, PACKAGE, archive_files, check_disclosure, checksum_targets, expected_mod_json,
                            reviewed_gallery)
from release_privacy import assert_public_files
from source2 import VPK
from switchboard_version import PUBLIC_NAME, VERSION, artifact_name

TOKEN_PATTERN = re.compile(rb"[A-Za-z0-9_-]{43}")


def read_tokens(token_files: list[Path]) -> list[bytes]:
    """Return the byte forms to look for: each token as ASCII and as UTF-16-LE.

    A token file that is missing, empty or not a 43-character token is an error,
    so a mistyped --token-file can never produce a green run.
    """
    forms: list[bytes] = []
    for path in token_files:
        try:
            raw = Path(path).read_bytes().strip()
        except OSError as exc:
            raise ValueError("Token file is missing or unreadable: " + Path(path).name) from exc
        if not TOKEN_PATTERN.fullmatch(raw):
            raise ValueError("Token file is empty or not a 43-character token: " + Path(path).name)
        forms += [raw, raw.decode("ascii").encode("utf-16-le")]
    return forms


def has_token(data: bytes, tokens: list[bytes]) -> bool:
    return any(token in data for token in tokens)


def audit_archives(root: Path, tokens: list[bytes]) -> dict:
    release = root / "release"
    check_disclosure(root)
    gallery = reviewed_gallery(root)
    expected_mod = expected_mod_json(root)
    archives = {}
    for kind in KINDS:
        archive = release / artifact_name(kind)
        expected = {name: path for path, name in archive_files(root, release, kind, gallery)}
        with zipfile.ZipFile(archive) as z, tempfile.TemporaryDirectory() as temporary:
            names = z.namelist()
            if len(names) != len(set(names)) or z.testzip():
                raise ValueError("Duplicate or damaged archive entries: " + archive.name)
            missing, extra = sorted(set(expected) - set(names)), sorted(set(names) - set(expected))
            if missing or extra:
                raise ValueError(f"{archive.name} has the wrong contents. Missing: {missing or 'none'}. Extra: {extra or 'none'}.")
            if kind == "Mod":
                vpks = [name for name in names if name.endswith("_dir.vpk")]
                if vpks != [PACKAGE]:
                    raise ValueError(f"The Mod ZIP must hold exactly one *_dir.vpk ({PACKAGE}); found {vpks}")
            files = []
            for name in names:
                if PureWindowsPath(name).drive or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name.replace(chr(92), "/")).parts:
                    raise ValueError("Unsafe archive entry name")
                data = z.read(name)
                if not expected[name].is_file() or expected[name].read_bytes() != data:
                    raise ValueError("Archive differs from current release inputs: " + name)
                if has_token(data, tokens):
                    raise ValueError("A supplied private token is present in " + archive.name)
                path = Path(temporary) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                files.append((path, name))
            assert_public_files(files)
            metadata = json.loads(z.read("mod.json"))
            if metadata != expected_mod:
                raise ValueError("mod.json does not match the current version, listing text and compatibility record")
            if metadata["name"] != PUBLIC_NAME or metadata["version"] != VERSION or metadata["author"] != "Genkei":
                raise ValueError("Release identity mismatch")
            if "images" in metadata or "thumbnail" in metadata:
                raise ValueError("mod.json must not refer to gallery images")
            archives[kind] = {"files": len(names), "bytes": archive.stat().st_size,
                              "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "crc": "passed"}
    return archives


def audit_vpk(release: Path) -> dict:
    package = VPK(release / PACKAGE)
    for name in package.entries:
        package.read(name)
    boot = package.read("panorama/scripts/switchboard_boot.vts_c")
    config = json.loads(boot.split(b"var SwitchboardBoot = ", 1)[1].rsplit(b";", 1)[0])
    if config["token"] or config["version"] != VERSION:
        raise ValueError("The public VPK has a personal token or incorrect version")
    if config.get("hasArtwork") is not False:
        raise ValueError("The public VPK must be built without artwork (hasArtwork false)")
    return {"resources": len(package.entries), "token": "empty", "version": config["version"]}


def audit_checksums(release: Path) -> None:
    data = (release / "SHA256SUMS.txt").read_bytes()
    if not data.strip():
        raise ValueError("SHA256SUMS.txt is empty")
    if b"\r" in data or not data.endswith(b"\n"):
        raise ValueError("SHA256SUMS.txt must use LF line endings and end with a newline")
    listed = {}
    for line in data.decode("utf-8").split("\n")[:-1]:
        expected, separator, name = line.partition("  ")
        if not separator or not re.fullmatch(r"[0-9a-f]{64}", expected) or Path(name).name != name or name in listed:
            raise ValueError("Malformed or repeated line in SHA256SUMS.txt")
        listed[name] = expected
    wanted = {p.name: p for p in checksum_targets(release)}
    if set(listed) != set(wanted):
        raise ValueError(f"SHA256SUMS.txt must list exactly the release files. Missing: {sorted(set(wanted) - set(listed)) or 'none'}. "
                         f"Extra: {sorted(set(listed) - set(wanted)) or 'none'}.")
    for name, path in wanted.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != listed[name]:
            raise ValueError("Release checksum mismatch: " + name)


def audit_portable(root: Path, tokens: list[bytes]) -> dict:
    # PyInstaller is only needed to read the helper, so import it here.
    from PyInstaller.archive.readers import CArchiveReader

    release = root / "release"
    reader = CArchiveReader(str(release / "Switchboard.exe"))
    pyz = reader.open_embedded_archive("PYZ.pyz")
    code_count = 0

    def check_code(code):
        nonlocal code_count
        if not isinstance(code, types.CodeType):
            return
        code_count += 1
        if PureWindowsPath(code.co_filename).drive or code.co_filename.startswith("/"):
            raise ValueError("An absolute code filename is embedded in the portable helper")
        for constant in code.co_consts:
            if isinstance(constant, types.CodeType):
                check_code(constant)

    for name, entry in reader.toc.items():
        if entry[-1] == "s":
            check_code(marshal.loads(reader.extract(name)))
    for name in pyz.toc:
        check_code(pyz.extract(name))
    modules = {"launcher": "launcher.py", "build": "tools/build.py", "source2": "tools/source2.py",
               "settings": "tools/settings.py", "switchboard_version": "tools/switchboard_version.py"}
    for name, source in modules.items():
        code = marshal.loads(reader.extract(name)) if name == "launcher" else pyz.extract(name)
        expected = compile((root / source).read_text(encoding="utf-8"), code.co_filename, "exec", dont_inherit=True, optimize=0)
        if code != expected:
            note = toolchain_difference(root)
            raise ValueError("Embedded code differs from source: " + name
                             + (". " + note if note else ". The Python and PyInstaller versions match the build, so the source changed after packaging."))
    data_count = 0
    for name in helper_inputs(root):
        if name.endswith(".py"):
            continue
        if reader.extract(name.replace("/", chr(92))) != (root / name).read_bytes():
            raise ValueError("Embedded data differs from source: " + name)
        data_count += 1
    for name, entry in reader.toc.items():
        if entry[-1] == "b" and has_token(reader.extract(name), tokens):
            raise ValueError("A supplied private token is embedded in helper data")
    return {"code_objects_checked": code_count, "absolute_code_filenames": 0,
            "source_modules_match": list(modules), "data_files_match": data_count}


def audit(root: Path, token_files: list[Path]) -> dict:
    release = root / "release"
    tokens = read_tokens(token_files)
    note = toolchain_difference(root)
    if note:
        print("Note: " + note, file=sys.stderr)
    verify_helper(root)
    report = {"version": VERSION, "portable_executed": False}
    report["archives"] = audit_archives(root, tokens)
    report["vpk"] = audit_vpk(release)
    report["portable"] = audit_portable(root, tokens)
    report["gallery_images"] = len(reviewed_gallery(root)) - 6
    report["private_tokens_checked"] = len(token_files)
    audit_checksums(release)
    report["checksums"] = "passed"
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-file", type=Path, action="append", default=[])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = audit(Path(__file__).resolve().parents[1], args.token_file)
    text = json.dumps(result, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text)
