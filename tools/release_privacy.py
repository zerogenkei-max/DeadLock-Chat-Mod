"""Release gate for private paths and words in public files.

Every file is scanned. Files that decode as UTF-8 without NUL bytes are read as
text, line by line. Everything else (VPK, images, executables, UTF-16 text) gets
a byte-level scan in ASCII and UTF-16-LE.

Set SWITCHBOARD_PRIVATE_WORDS to a comma-separated list (for example the
owner's Windows user name) to reject those words as well. The list is read from
the environment so nothing private is stored in the project.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

PRIVATE_WORDS_ENV = "SWITCHBOARD_PRIVATE_WORDS"

# Ordinary and source-escaped backslashes (up to four, as in JSON inside a
# string literal), with concrete path components so regex fragments and URL
# schemes are not treated as paths.
_SEP = r"(?:\\{1,4}|/)"
_COMPONENT = r"[A-Za-z0-9._ -]+"
_NAME = r"[A-Za-z0-9._-]+"
_ABSOLUTE_PATHS = (
    # drive paths, with single, escaped or forward slashes
    re.compile(rf"(?<![A-Za-z0-9])([A-Za-z]:){_SEP}{_COMPONENT}(?:{_SEP}{_COMPONENT})*"),
    # file URIs
    re.compile(r"(?i)\bfile:/{2,}[^\s\"'<>)/]+"),
    # Windows network shares
    re.compile(rf"(?<!\\)(?:\\{{2,4}}){_COMPONENT}{_SEP}{_COMPONENT}(?:{_SEP}{_COMPONENT})*"),
    # network shares with forward slashes
    re.compile(rf"(?<![A-Za-z0-9_:/\\.])//{_NAME}/{_NAME}"),
    re.compile(rf"(?<![A-Za-z0-9_:/])/{_SEP}?Users{_SEP}{_COMPONENT}(?:{_SEP}{_COMPONENT})*"),
    re.compile(rf"(?<![A-Za-z0-9_:/])/{_SEP}?home{_SEP}{_COMPONENT}(?:{_SEP}{_COMPONENT})*"),
    # WSL and Cygwin views of a drive
    re.compile(rf"(?<![A-Za-z0-9_:])/(?:mnt|cygdrive)/[A-Za-z]/{_NAME}"),
    # Home shorthand and profile variables
    re.compile(rf"(?<![A-Za-z0-9_.~])~{_SEP}{_NAME}"),
    re.compile(r"(?i)%(?:USERPROFILE|HOMEPATH|HOMEDRIVE)%"),
    re.compile(r"(?i)\$env:(?:USERPROFILE|HOMEPATH)\b"),
)

# Profile folders that exist on every Windows install and say nothing private.
_SHARED_PROFILES = {b"public", b"default", b"all users", b"default user"}

_STOP = b"\\\\/\\x00\\\"'"
_BYTE_PATHS = (
    re.compile(rb"(?i)(?<![A-Za-z0-9])[a-z]:[\\/]{1,4}users[\\/]{1,4}([^" + _STOP + rb"]{1,64})"),
    re.compile(rb"(?<![A-Za-z0-9_:/])/Users/([^" + _STOP + rb"]{1,64})"),
)


def private_words() -> list[str]:
    raw = os.environ.get(PRIVATE_WORDS_ENV, "")
    return [word.strip() for word in raw.split(",") if word.strip()]


def _binary_views(data: bytes) -> list[bytes]:
    """The raw bytes plus both byte lanes, which expose UTF-16-LE ASCII text."""
    return [data, data[0::2], data[1::2]]


def _binary_path_hit(data: bytes) -> bool:
    for view in _binary_views(data):
        for pattern in _BYTE_PATHS:
            for match in pattern.finditer(view):
                name = match.group(1).strip().lower()
                if name not in _SHARED_PROFILES and not name.startswith((b"%", b"{", b"<", b"*")):
                    return True
    return False


def _binary_word_hit(data: bytes, words: list[str]) -> bool:
    lowered = data.lower()
    for word in words:
        ascii_form = word.encode("utf-8").lower()
        wide = word.encode("utf-16-le").lower()
        if ascii_form in lowered or wide in lowered:
            return True
    return False


def _as_text(data: bytes) -> str | None:
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def assert_public_files(files: Iterable[tuple[Path, str]]) -> None:
    """Reject machine paths and private words in files destined for release.

    Errors identify only the archive-relative filename and line number, never
    the matched path, word or surrounding content.
    """
    words = private_words()
    for path, archive_name in files:
        data = Path(path).read_bytes()
        for word in words:
            if word.lower() in archive_name.lower():
                raise ValueError(f"{archive_name}: file name contains a private word")
        text = _as_text(data)
        if text is None:
            if _binary_path_hit(data):
                raise ValueError(f"{archive_name}: literal absolute machine path in binary data")
            if words and _binary_word_hit(data, words):
                raise ValueError(f"{archive_name}: private word in binary data")
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for pattern in _ABSOLUTE_PATHS:
                if pattern.search(line):
                    raise ValueError(f"{archive_name}:{line_number}: literal absolute machine path")
            lowered = line.lower()
            for word in words:
                if word.lower() in lowered:
                    raise ValueError(f"{archive_name}:{line_number}: private word")
