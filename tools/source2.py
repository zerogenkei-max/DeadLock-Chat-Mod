"""Small, dependency-free Panorama resource and single-file VPK tools.

The legacy text resource format is documented by ValveResourceFormat and
Vergir/deadlock-4x3-fix-hud-resize (MIT). No resourcecompiler installation needed.
"""
from __future__ import annotations

import struct
import zlib
from collections import defaultdict
from pathlib import Path


def resource(text: str, kind: str) -> bytes:
    raw = text.encode("utf-8")
    version = 2 if kind in ("vts", "svg") else 3
    payload = raw if kind == "vts" else struct.pack("<IH", zlib.crc32(raw), 0) + raw
    # Header v12, one DATA block at the next 16-byte boundary.
    return struct.pack("<IHHII4sII", 32 + len(payload), 12, version, 8, 1,
                       b"DATA", 12, len(payload)) + b"\0" * 4 + payload


def png_texture(png: bytes) -> bytes:
    """Wrap a bounded PNG in Source 2's documented PNG_RGBA8888 texture format."""
    if len(png) < 33 or png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR":
        raise ValueError("Artwork must be a PNG image")
    if struct.unpack_from(">I", png, 8)[0] != 13:
        raise ValueError("Artwork PNG contains an invalid header")
    width, height, depth, colour, compression, filtering, interlace = struct.unpack_from(">IIBBBBB", png, 16)
    if not (1 <= width <= 2048 and 1 <= height <= 2048) or len(png) > 4 * 1024 * 1024:
        raise ValueError("Artwork must be at most 2048 by 2048 and 4 MiB")
    if (depth, compression, filtering, interlace) != (8, 0, 0, 0) or colour not in (2, 6):
        raise ValueError("Use an 8-bit RGB or RGBA PNG without interlacing; the customizer converts other image formats")
    pos, ended, pixels_closed = 8, False, False
    pixels = []
    while pos + 12 <= len(png):
        length = struct.unpack_from(">I", png, pos)[0]
        kind = png[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(png):
            raise ValueError("Artwork PNG is incomplete")
        expected = struct.unpack_from(">I", png, end - 4)[0]
        if zlib.crc32(png[pos + 4:end - 4]) != expected:
            raise ValueError("Artwork PNG contains a damaged chunk")
        if kind == b"IHDR" and pos != 8:
            raise ValueError("Artwork PNG contains a repeated header")
        if kind not in (b"IHDR", b"PLTE", b"IDAT", b"IEND") and not kind[0] & 32:
            raise ValueError("Artwork PNG contains an unsupported critical chunk")
        if kind == b"IDAT":
            if pixels_closed:
                raise ValueError("Artwork PNG pixel chunks are out of order")
            pixels.append(png[pos + 8:end - 4])
        elif pixels:
            pixels_closed = True
        pos = end
        if kind == b"IEND":
            ended = length == 0 and pos == len(png)
            break
    if not ended or not pixels:
        raise ValueError("Artwork PNG is incomplete")
    row_bytes = width * (4 if colour == 6 else 3) + 1
    decoded_size = row_bytes * height
    try:
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(b"".join(pixels), decoded_size + 1)
    except zlib.error as exc:
        raise ValueError("Artwork PNG contains invalid compressed pixels") from exc
    if len(decoded) != decoded_size or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
        raise ValueError("Artwork PNG has an invalid decoded pixel size")
    if any(decoded[row] > 4 for row in range(0, decoded_size, row_bytes)):
        raise ValueError("Artwork PNG contains an invalid row filter")
    data = struct.pack("<HH4fHHHBBIII", 1, 15, 0.5, 0.5, 0.5, 0.5,
                       width, height, 1, 16, 1, 0, 0, 0)
    # Texture pixels follow DATA and are excluded from the resource's file_size.
    size = 32 + len(data)
    return struct.pack("<IHHII4sII", size, 12, 1, 8, 1, b"DATA", 12, len(data)) + b"\0" * 4 + data + png


def pack(files: dict[str, bytes], output: Path) -> None:
    groups = defaultdict(lambda: defaultdict(list))
    data = bytearray()
    for name, content in sorted(files.items()):
        p = Path(name)
        groups[p.suffix[1:]][p.parent.as_posix()].append(
            (p.stem, zlib.crc32(content), len(data), len(content)))
        data.extend(content)
    tree = bytearray()
    for ext, folders in sorted(groups.items()):
        tree.extend(ext.encode() + b"\0")
        for folder, entries in sorted(folders.items()):
            tree.extend((folder if folder != "." else " ").encode() + b"\0")
            for stem, crc, offset, size in entries:
                tree.extend(stem.encode() + b"\0")
                tree.extend(struct.pack("<IHHIIH", crc, 0, 0x7fff, offset, size, 0xffff))
            tree.extend(b"\0")
        tree.extend(b"\0")
    tree.extend(b"\0")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(struct.pack("<III", 0x55aa1234, 1, len(tree)) + tree + data)


class VPK:
    def __init__(self, path: Path, *, allow_duplicate_entries: bool = False):
        self.path = path
        with path.open("rb") as f:
            header = f.read(12)
            if len(header) != 12:
                raise ValueError("VPK header is incomplete")
            sig, version, tree_size = struct.unpack("<III", header)
            if sig != 0x55aa1234 or version not in (1, 2):
                raise ValueError("Not a supported VPK")
            header_size = 12 if version == 1 else 28
            file_size = path.stat().st_size
            if not 1 <= tree_size <= 64 * 1024 * 1024 or header_size + tree_size > file_size:
                raise ValueError("VPK directory bounds are invalid")
            f.seek(header_size)
            tree = f.read(tree_size)
            if len(tree) != tree_size:
                raise ValueError("VPK directory is incomplete")
        self.inline_start = header_size + tree_size
        self.entries = {}
        self.has_duplicate_entries = False
        pos = 0
        def string():
            nonlocal pos
            end = tree.find(0, pos)
            if end < 0:
                raise ValueError("VPK directory string is incomplete")
            try:
                value = tree[pos:end].decode("utf-8")
            except UnicodeError as exc:
                raise ValueError("VPK directory text is invalid") from exc
            pos = end + 1
            return value
        while ext := string():
            while folder := string():
                while stem := string():
                    if pos + 18 > len(tree):
                        raise ValueError("VPK directory entry is incomplete")
                    crc, pre, archive, offset, size, terminator = struct.unpack_from("<IHHIIH", tree, pos)
                    pos += 18
                    if terminator != 0xffff or pos + pre > len(tree):
                        raise ValueError("Invalid VPK entry")
                    preload = tree[pos:pos + pre]
                    pos += pre
                    name = ((folder + "/") if folder != " " else "") + stem + "." + ext
                    if name.startswith("/") or "\\" in name or any(p in ("", ".", "..") for p in name.split("/")):
                        raise ValueError("VPK resource name is invalid")
                    if name in self.entries:
                        if not allow_duplicate_entries:
                            raise ValueError("VPK resource name is repeated")
                        self.has_duplicate_entries = True
                    if archive == 0x7fff and self.inline_start + offset + size > file_size:
                        raise ValueError("VPK resource bounds are invalid")
                    self.entries[name] = (crc, archive, offset, size, preload)
        if pos != len(tree):
            raise ValueError("VPK directory has trailing data")

    def read(self, name: str) -> bytes:
        crc, archive, offset, size, pre = self.entries[name]
        if archive == 0x7fff:
            path, start = self.path, self.inline_start + offset
        else:
            if not self.path.name.endswith("_dir.vpk"):
                raise ValueError("VPK archive segments require a directory package")
            path = self.path.with_name(self.path.name.replace("_dir.vpk", f"_{archive:03d}.vpk"))
            start = offset
        with path.open("rb") as f:
            if start + size > path.stat().st_size:
                raise ValueError("VPK resource is incomplete")
            f.seek(start)
            content = f.read(size)
            if len(content) != size:
                raise ValueError("VPK resource is incomplete")
            data = pre + content
        if zlib.crc32(data) != crc:
            raise ValueError(f"CRC mismatch: {name}")
        return data


def compile_tree(src: Path) -> dict[str, bytes]:
    files = {}
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src).as_posix()
        ext = path.suffix[1:]
        if ext in ("xml", "css", "vts", "svg"):
            suffix = {"xml": "vxml_c", "css": "vcss_c", "vts": "vts_c", "svg": "vsvg_c"}[ext]
            files[rel.rsplit(".", 1)[0] + "." + suffix] = resource(path.read_text(encoding="utf-8"), ext)
        else:
            files[rel] = path.read_bytes()
    return files
