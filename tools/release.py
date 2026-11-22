"""Create the Mod Manager, Windows and editable-source release archives."""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build import OVERRIDES, build, hook_layout
from helper_build import verify_helper
from release_assets import (KINDS, PACKAGE, archive_files, check_disclosure, checksum_targets, expected_mod_json,
                            load_baseline, load_compatibility, reviewed_gallery)
from release_privacy import assert_public_files
from source2 import VPK, resource
from switchboard_version import VERSION, artifact_name

# A fixed timestamp and sorted entries make a rebuild byte-for-byte identical.
ZIP_DATE = (2020, 1, 1, 0, 0, 0)


def write_zip(destination: Path, files) -> None:
    """Write a deterministic ZIP: sorted entries, fixed dates, fixed permissions."""
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path, name in sorted(files, key=lambda pair: pair[1]):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3
            z.writestr(info, Path(path).read_bytes(), compresslevel=9)


def archive(destination: Path, files) -> None:
    assert_public_files(files)
    write_zip(destination, files)
    with zipfile.ZipFile(destination) as z:
        if z.testzip():
            raise ValueError('Archive verification failed: ' + str(destination))


def write_checksums(release: Path, targets) -> None:
    """SHA256SUMS.txt with LF line endings so `sha256sum -c` accepts it."""
    lines = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in targets)
    (release / 'SHA256SUMS.txt').write_bytes(lines.encode('utf-8'))


def check_built_layouts(root: Path, package: Path) -> None:
    """The VPK's three layouts must be the baseline sources plus the Switchboard hooks, nothing else."""
    baseline = load_baseline(root)
    entries = VPK(package)
    expected = {'panorama/layout/' + name.removesuffix('.xml') + '.vxml_c': name for name in OVERRIDES}
    if set(expected) != set(baseline['resource_crcs']):
        raise ValueError('The layouts this build replaces differ from the ones listed in research/baseline.json')
    for resource_name, name in expected.items():
        if resource_name not in entries.entries:
            raise ValueError('The built VPK is missing ' + resource_name)
        source = (root / 'research/vanilla/panorama/layout' / name).read_text(encoding='utf-8')
        if entries.read(resource_name) != resource(hook_layout(source, name), 'xml'):
            raise ValueError('The built VPK layout is not the baseline source plus hooks: ' + resource_name)


def make_archives(root: Path, release: Path, gallery: list[Path]) -> None:
    for kind in KINDS:
        archive(release / artifact_name(kind), archive_files(root, release, kind, gallery))


def main(root: Path = ROOT) -> None:
    release = root / 'release'
    release.mkdir(exist_ok=True)
    gallery_manifest = json.loads((root / 'gallery/manifest.json').read_text(encoding='utf-8'))
    if gallery_manifest.get('version') != VERSION:
        raise ValueError('Update the gallery manifest version before packaging.')
    check_disclosure(root)
    load_compatibility(root)
    reviewed = reviewed_gallery(root)
    verify_helper(root)
    package = build(output=release / PACKAGE)
    check_built_layouts(root, package)
    (release / 'mod.json').write_text(json.dumps(expected_mod_json(root), ensure_ascii=False, indent=2) + '\n',
                                      encoding='utf-8', newline='\n')
    make_archives(root, release, reviewed)
    targets = checksum_targets(release)
    write_checksums(release, targets)
    for p in targets:
        print(p.name, p.stat().st_size)


if __name__ == '__main__':
    main()
