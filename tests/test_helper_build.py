import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import helper_build


class HelperBuildTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in helper_build.BASELINES + (
            "launcher.py", "tools/build.py", "tools/source2.py", "tools/settings.py",
            "tools/switchboard_version.py", "tools/package_exe.py",
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture input: " + name, encoding="utf-8")
        for folder in ("web", "src", "themes"):
            path = self.root / folder / "fixture.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture input: " + folder, encoding="utf-8")
        exe = self.root / "release/Switchboard.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"fixture executable bytes; never executed")
        self.gallery_patch = patch.object(helper_build, "reviewed_gallery", return_value=[])
        self.gallery_patch.start()
        self.addCleanup(self.gallery_patch.stop)

    def stamp(self):
        helper_build.record_helper(self.root)
        return self.root / "release/Switchboard.build.json"

    def test_matching_executable_and_runtime_inputs_are_accepted(self):
        self.stamp()
        helper_build.verify_helper(self.root)

    def test_modified_runtime_input_or_executable_is_rejected(self):
        self.stamp()
        changed_input = self.root / "src/fixture.txt"
        changed_input.write_text("changed after build", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            helper_build.verify_helper(self.root)

        self.stamp()
        exe = self.root / "release/Switchboard.exe"
        exe.write_bytes(exe.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            helper_build.verify_helper(self.root)

    def test_missing_stamp_and_version_mismatch_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Build the portable helper"):
            helper_build.verify_helper(self.root)

        stamp_path = self.stamp()
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        stamp["version"] = "fixture-mismatch"
        stamp_path.write_text(json.dumps(stamp), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            helper_build.verify_helper(self.root)


if __name__ == "__main__":
    unittest.main()
