"""Require the reviewed capture set for public release packaging."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from switchboard_version import PUBLIC_NAME, VERSION, artifact_name

MEDIA = {'.png', '.jpg', '.jpeg', '.webp', '.svg', '.ico', '.gif', '.wav', '.mp3', '.ogg', '.mp4'}


def reviewed_gallery(root: Path) -> list[Path]:
    gallery = root / 'gallery'
    manifest = json.loads((gallery / 'manifest.json').read_text(encoding='utf-8'))
    lock = json.loads((gallery / 'asset-lock.json').read_text(encoding='utf-8'))
    names = list(dict.fromkeys([manifest['cover'], manifest['thumbnail']] +
                              [item['file'] for item in manifest['items']]))
    if set(names) != set(lock['sha256']):
        raise ValueError('Gallery changed: review media provenance and update asset-lock.json')
    actual = {p.name for p in gallery.iterdir() if p.is_file() and p.suffix.lower() in MEDIA}
    if actual != set(names):
        raise ValueError('Unreviewed or missing gallery media: ' + ', '.join(sorted(actual ^ set(names))))
    for name in names:
        if Path(name).name != name or hashlib.sha256((gallery / name).read_bytes()).hexdigest() != lock['sha256'][name]:
            raise ValueError('Reviewed media changed: ' + name)
    # These runtime folders contain interface code, not bundled decorative media.
    for folder in ('web', 'src', 'themes'):
        for path in (root / folder).rglob('*'):
            if path.is_file() and path.suffix.lower() in MEDIA:
                raise ValueError('Review new runtime media before release: ' + str(path.relative_to(root)))
    names += ['manifest.json', 'asset-lock.json', 'index.html', 'style.css', 'app.js', 'ASSETS.md']
    return [gallery / name for name in names]


# ---------------------------------------------------------------------------
# What goes in each release file. release.py builds from these lists and
# audit_release.py checks the archives against the same lists, so a missing or
# extra entry fails the audit.
# ---------------------------------------------------------------------------

PACKAGE = 'switchboard_dir.vpk'
PORTABLE = 'Switchboard.exe'
PORTABLE_STAMP = 'Switchboard.build.json'
KINDS = ('Mod', 'Source', 'Windows')

# The Mod ZIP is what Deadlock Mod Manager installs: the VPK and the short
# documents only. Gallery images stay on the listing page.
MOD_DOCUMENTS = ['README.md', 'LICENSE', 'THIRD_PARTY.md', 'CHANGELOG.md']
FULL_DOCUMENTS = ['README.md', 'LISTING.md', 'CHANGELOG.md', 'LICENSE', 'THIRD_PARTY.md',
                  'research/RESEARCH.md', 'research/VALIDATION.md']
SOURCE_FILES = ['launcher.py', 'Switchboard.cmd', '.gitignore', 'PUBLISHING.md', 'requirements-dev.txt',
                'research/baseline.json', 'research/compatibility.json']
SOURCE_FOLDERS = ['src', 'tools', 'tests', 'themes', 'web', 'licenses']
SOURCE_SUFFIXES = {'.py', '.vts', '.css', '.xml', '.json', '.md', '.js', '.html', '.cmd', '.txt'}
SOURCE_EXCLUDED = {'tools/probe.py'}
LAYOUTS = ['chat.xml', 'popups/popup_settings.xml', 'citadel_dashboard_footer_bar.xml']
COMPATIBILITY_RESULT = 'unchanged from baseline'
DISCLOSURE_NAMES = ('Codex', 'Claude')


def load_baseline(root: Path) -> dict:
    return json.loads((root / 'research/baseline.json').read_text(encoding='utf-8'))


def load_compatibility(root: Path) -> dict:
    """Read research/compatibility.json and require it to agree with baseline.json."""
    path = root / 'research/compatibility.json'
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('research/compatibility.json is missing or unreadable. '
                         'Run tools/check_compat.py against the current game build.') from exc
    if not isinstance(record, dict):
        raise ValueError('research/compatibility.json is not an object')
    for key in ('game', 'steam', 'checked', 'resources', 'result'):
        if not record.get(key):
            raise ValueError('research/compatibility.json is missing "' + key + '"')
    baseline = load_baseline(root)
    if record['resources'] != baseline['resource_crcs']:
        raise ValueError('Resource CRCs in compatibility.json do not match research/baseline.json. '
                         'Deadlock changed a replaced layout; rebuild against it before releasing.')
    if record['result'] != COMPATIBILITY_RESULT:
        raise ValueError('compatibility.json result is not "' + COMPATIBILITY_RESULT + '"')
    return record


def check_disclosure(root: Path) -> None:
    """LISTING.md and README.md must credit both AI assistants."""
    for name in ('LISTING.md', 'README.md'):
        text = (root / name).read_text(encoding='utf-8')
        missing = [word for word in DISCLOSURE_NAMES if word not in text]
        if missing:
            raise ValueError(f'{name} must mention {" and ".join(DISCLOSURE_NAMES)} in the AI disclosure '
                             f'(missing: {", ".join(missing)})')


def expected_mod_json(root: Path) -> dict:
    """mod.json for every archive: no gallery references."""
    baseline = load_baseline(root)
    compat = load_compatibility(root)
    return {'name': PUBLIC_NAME, 'author': 'Genkei', 'version': VERSION, 'category': 'UI / chat',
            'summary': "Choose how Deadlock's chat looks, what it shows and how long it stays.",
            'description': (root / 'LISTING.md').read_text(encoding='utf-8'),
            'built_against': {'steam': baseline['steam_build'], 'game': baseline['game_version']},
            'compatibility': {'steam': compat['steam'], 'game': compat['game'],
                              'checked': compat['checked'], 'result': compat['result']},
            'source_license': 'MIT; Valve layouts remain Valve assets'}


def archive_files(root: Path, release: Path, kind: str, gallery: list[Path]) -> list[tuple[Path, str]]:
    """The exact (path, archive name) list for one release ZIP, sorted by name."""
    if kind not in KINDS:
        raise ValueError('Unknown archive kind: ' + kind)
    mod_json = (release / 'mod.json', 'mod.json')
    gallery_files = [(path, 'gallery/' + path.name) for path in gallery]
    if kind == 'Mod':
        files = [(release / PACKAGE, PACKAGE)] + [(root / n, n) for n in MOD_DOCUMENTS] + [mod_json]
    elif kind == 'Windows':
        files = [(root / n, n) for n in FULL_DOCUMENTS]
        files += [(release / n, n) for n in (PORTABLE, PORTABLE_STAMP)]
        files += [(p, 'licenses/' + p.name) for p in (root / 'licenses').glob('*.txt')]
        files += gallery_files + [mod_json]
    else:
        files = [(root / n, n) for n in FULL_DOCUMENTS + SOURCE_FILES] + gallery_files + [mod_json]
        for folder in SOURCE_FOLDERS:
            for path in (root / folder).rglob('*'):
                name = path.relative_to(root).as_posix()
                if (path.is_file() and '__pycache__' not in path.parts
                        and path.suffix.lower() in SOURCE_SUFFIXES and name not in SOURCE_EXCLUDED):
                    files.append((path, name))
        files += [(root / 'research/vanilla/panorama/layout' / n, 'research/vanilla/panorama/layout/' + n)
                  for n in LAYOUTS]
    names = [name for _, name in files]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate archive entries planned for the ' + kind + ' ZIP')
    return sorted(files, key=lambda pair: pair[1])


def checksum_targets(release: Path) -> list[Path]:
    """Files listed in SHA256SUMS.txt, in order."""
    return [release / PORTABLE, release / PACKAGE, release / 'mod.json'] + [
        release / artifact_name(kind) for kind in KINDS]
