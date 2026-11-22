"""Compare the installed game's replaced layouts with research/baseline.json.

Reads pak01_dir.vpk read-only and rewrites research/compatibility.json. Run it
after each Deadlock update, with the build numbers from Steam:

    python tools/check_compat.py --game-dir <Deadlock folder> --game 6861 --steam 26546669

release.py refuses to package unless the record says "unchanged from baseline"
and its CRCs equal the ones in baseline.json.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from source2 import VPK

ROOT = Path(__file__).resolve().parents[1]
UNCHANGED = "unchanged from baseline"


def pak_path(game_dir: Path) -> Path:
    return game_dir / "game/citadel/pak01_dir.vpk"


def read_crcs(vpk_path: Path, names) -> dict:
    """CRC of each named resource in the game package, None when absent. Reads only the directory."""
    entries = VPK(vpk_path, allow_duplicate_entries=True).entries
    return {name: entries[name][0] if name in entries else None for name in names}


def make_record(baseline: dict, actual: dict, game: str, steam: str, checked: str) -> dict:
    changed = sorted(name for name, crc in baseline["resource_crcs"].items() if actual.get(name) != crc)
    return {"game": game, "steam": steam, "checked": checked, "resources": actual,
            "result": UNCHANGED if not changed else "changed: " + ", ".join(changed)}


def main(argv=None, root: Path = ROOT) -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--game", required=True, help="game build number, for example 6861")
    parser.add_argument("--steam", required=True, help="Steam build id, for example 26546669")
    args = parser.parse_args(argv)
    baseline = json.loads((root / "research/baseline.json").read_text(encoding="utf-8"))
    actual = read_crcs(pak_path(args.game_dir), baseline["resource_crcs"])
    record = make_record(baseline, actual, args.game, args.steam, time.strftime("%Y-%m-%d"))
    (root / "research/compatibility.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(record["result"])
    return record


if __name__ == "__main__":
    main()
