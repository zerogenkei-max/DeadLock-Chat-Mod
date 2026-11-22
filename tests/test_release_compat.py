import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _release_fixture import CRCS, ReleaseFixture, write
import check_compat
import release
import release_assets
from source2 import VPK, pack, resource

ROOT = Path(__file__).resolve().parents[1]


class CompatibilityRecordTest(ReleaseFixture):
    def test_matching_record_is_accepted(self):
        self.assertEqual(release_assets.load_compatibility(self.root)["result"], "unchanged from baseline")

    def test_missing_record_is_rejected(self):
        (self.root / "research/compatibility.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing or unreadable"):
            release_assets.load_compatibility(self.root)

    def test_crc_disagreement_is_rejected(self):
        self.write_compat(resources=dict(CRCS, **{"panorama/layout/chat.vxml_c": 5}))
        with self.assertRaisesRegex(ValueError, "do not match"):
            release_assets.load_compatibility(self.root)

    def test_changed_result_and_missing_fields_are_rejected(self):
        self.write_compat(result="changed: chat")
        with self.assertRaisesRegex(ValueError, "result"):
            release_assets.load_compatibility(self.root)
        write(self.root / "research/compatibility.json", json.dumps({"game": "9"}))
        with self.assertRaisesRegex(ValueError, "missing"):
            release_assets.load_compatibility(self.root)

    def test_real_project_record_agrees_with_its_baseline(self):
        record = release_assets.load_compatibility(ROOT)
        self.assertEqual((record["game"], record["steam"]), ("6861", "26546669"))


class CheckCompatTest(ReleaseFixture):
    def fake_game(self):
        game = self.root / "game-dir"
        pack({name: b"layout " + name.encode() for name in CRCS}, game / "game/citadel/pak01_dir.vpk")
        return game, VPK(game / "game/citadel/pak01_dir.vpk")

    def baseline_from(self, package):
        baseline = {"steam_build": "100", "game_version": "9",
                    "resource_crcs": {n: package.entries[n][0] for n in CRCS}}
        write(self.root / "research/baseline.json", json.dumps(baseline))
        return baseline

    def run_check(self, game, game_number="6861", steam="26546669"):
        return check_compat.main(["--game-dir", str(game), "--game", game_number, "--steam", steam], root=self.root)

    def test_unchanged_game_writes_an_unchanged_record(self):
        game, package = self.fake_game()
        self.baseline_from(package)
        record = self.run_check(game)
        self.assertEqual(record["result"], "unchanged from baseline")
        saved = json.loads((self.root / "research/compatibility.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["game"], "6861")
        self.assertEqual(release_assets.load_compatibility(self.root)["steam"], "26546669")

    def test_changed_layout_is_recorded_and_then_blocks_release(self):
        game, package = self.fake_game()
        baseline = self.baseline_from(package)
        baseline["resource_crcs"]["panorama/layout/chat.vxml_c"] ^= 1
        write(self.root / "research/baseline.json", json.dumps(baseline))
        record = self.run_check(game, "7000", "1")
        self.assertTrue(record["result"].startswith("changed:"))
        with self.assertRaises(ValueError):
            release_assets.load_compatibility(self.root)

    def test_missing_resource_counts_as_changed(self):
        game, package = self.fake_game()
        self.baseline_from(package)
        pack({"panorama/layout/chat.vxml_c": b"x"}, game / "game/citadel/pak01_dir.vpk")
        self.assertIn("changed", self.run_check(game)["result"])

    def test_game_package_is_not_modified(self):
        game, package = self.fake_game()
        self.baseline_from(package)
        before = (game / "game/citadel/pak01_dir.vpk").read_bytes()
        self.run_check(game)
        self.assertEqual((game / "game/citadel/pak01_dir.vpk").read_bytes(), before)


class BuiltLayoutTest(unittest.TestCase):
    def test_real_build_matches_baseline_sources(self):
        from build import build
        with tempfile.TemporaryDirectory() as temp:
            package = build(output=Path(temp) / "switchboard_dir.vpk", verify=False)
            release.check_built_layouts(ROOT, package)
            # A VPK whose chat layout is something else must be rejected.
            entries = {n: VPK(package).read(n) for n in VPK(package).entries}
            entries["panorama/layout/chat.vxml_c"] = resource("<root></root>", "xml")
            pack(entries, Path(temp) / "other.vpk")
            with self.assertRaisesRegex(ValueError, "baseline source plus hooks"):
                release.check_built_layouts(ROOT, Path(temp) / "other.vpk")


if __name__ == "__main__":
    unittest.main()
