import hashlib
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from _release_fixture import ReleaseFixture, write
import release
from switchboard_version import PUBLIC_NAME, VERSION, artifact_name


def names(path):
    with zipfile.ZipFile(path) as z:
        return z.namelist()


class ReleaseArchiveTest(ReleaseFixture):
    def test_mod_zip_holds_only_the_vpk_short_documents_and_mod_json(self):
        self.make_release()
        self.assertEqual(sorted(names(self.release / artifact_name("Mod"))),
                         ["CHANGELOG.md", "LICENSE", "README.md", "THIRD_PARTY.md", "mod.json", "switchboard_dir.vpk"])

    def test_mod_json_has_public_name_version_listing_and_no_gallery(self):
        self.make_release()
        with zipfile.ZipFile(self.release / artifact_name("Mod")) as z:
            meta = json.loads(z.read("mod.json"))
        self.assertEqual((meta["name"], meta["version"]), (PUBLIC_NAME, VERSION))
        self.assertEqual(meta["description"], (self.root / "LISTING.md").read_text(encoding="utf-8"))
        self.assertNotIn("images", meta)
        self.assertNotIn("thumbnail", meta)
        self.assertNotIn("gallery/", json.dumps(meta))
        self.assertEqual(meta["built_against"], {"steam": "100", "game": "9"})

    def test_windows_and_source_zips_keep_the_gallery(self):
        self.make_release()
        for kind in ("Windows", "Source"):
            listed = names(self.release / artifact_name(kind))
            self.assertIn("gallery/cover.png", listed, kind)
            self.assertIn("gallery/a.jpg", listed, kind)
        self.assertIn("Switchboard.exe", names(self.release / artifact_name("Windows")))

    def test_source_zip_uses_a_suffix_allowlist_and_leaves_out_probe_files(self):
        self.make_release()
        listed = names(self.release / artifact_name("Source"))
        self.assertIn("src/a.vts", listed)
        self.assertIn("tools/x.py", listed)
        self.assertIn("research/compatibility.json", listed)
        for left_out in ("src/b.png", "tools/probe.py", "tools/Switchboard.spec", "tests/__pycache__/t.pyc"):
            self.assertNotIn(left_out, listed)

    def test_archive_names_come_from_artifact_name(self):
        self.make_release()
        for kind in ("Mod", "Source", "Windows"):
            self.assertTrue((self.release / artifact_name(kind)).is_file())

    def test_zips_are_deterministic(self):
        self.make_release()
        first = {k: (self.release / artifact_name(k)).read_bytes() for k in ("Mod", "Source", "Windows")}
        for path in self.root.rglob("*"):
            if path.is_file():
                path.touch()  # new modification times must not change the archives
        self.make_release()
        second = {k: (self.release / artifact_name(k)).read_bytes() for k in ("Mod", "Source", "Windows")}
        self.assertEqual(first, second)
        with zipfile.ZipFile(self.release / artifact_name("Mod")) as z:
            self.assertTrue(all(i.date_time == release.ZIP_DATE for i in z.infolist()))
            self.assertEqual(z.namelist(), sorted(z.namelist()))

    def test_checksums_use_lf_and_list_exactly_the_release_files(self):
        self.make_release()
        data = (self.release / "SHA256SUMS.txt").read_bytes()
        self.assertNotIn(b"\r", data)
        self.assertTrue(data.endswith(b"\n"))
        listed = {line.split("  ")[1]: line.split("  ")[0] for line in data.decode().splitlines()}
        self.assertEqual(set(listed), {"Switchboard.exe", "switchboard_dir.vpk", "mod.json",
                                       *(artifact_name(k) for k in ("Mod", "Source", "Windows"))})
        for name, digest in listed.items():
            self.assertEqual(hashlib.sha256((self.release / name).read_bytes()).hexdigest(), digest)

    def test_archive_refuses_a_private_path_in_a_file(self):
        bad = write(self.root / "bad.md", "see C:" + chr(92) + "Users" + chr(92) + "someone" + chr(92) + "x\n")
        with self.assertRaisesRegex(ValueError, "bad.md:1"):
            release.archive(self.release / "x.zip", [(bad, "bad.md")])
        self.assertFalse((self.release / "x.zip").exists())

    def test_main_stops_before_building_when_compatibility_is_missing_or_disagrees(self):
        write(self.root / "gallery/manifest.json", json.dumps({"version": VERSION}))
        (self.root / "research/compatibility.json").unlink()
        with patch.object(release, "build") as build, self.assertRaisesRegex(ValueError, "compatibility.json"):
            release.main(self.root)
        build.assert_not_called()
        self.write_compat(resources={"panorama/layout/chat.vxml_c": 99})
        with patch.object(release, "build") as build, self.assertRaisesRegex(ValueError, "do not match"):
            release.main(self.root)
        build.assert_not_called()

    def test_main_rejects_a_gallery_manifest_for_another_version(self):
        write(self.root / "gallery/manifest.json", json.dumps({"version": "0.0.1"}))
        with self.assertRaisesRegex(ValueError, "gallery manifest version"):
            release.main(self.root)

    def test_main_does_not_read_a_version_from_web_index(self):
        # Contract 2: the page reads its version from /api/state, so index.html carries none.
        write(self.root / "gallery/manifest.json", json.dumps({"version": VERSION}))
        write(self.root / "web/index.html", "<html>no version here</html>")
        (self.root / "research/compatibility.json").unlink()
        with self.assertRaisesRegex(ValueError, "compatibility.json"):
            release.main(self.root)  # got past the version check without complaining about index.html


if __name__ == "__main__":
    unittest.main()
