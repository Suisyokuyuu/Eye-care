from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from eye_care.update_service import MAIN_EXE_NAME, MANIFEST_NAME, UPDATER_EXE_NAME, _parse_update_feed
from scripts.package_release import create_archive, package_name, write_update_feed
from scripts.verify_release import verify_archive


class PackageReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.package = self.root / "EyE Care"
        self.package.mkdir()
        (self.package / MAIN_EXE_NAME).write_bytes(b"main")
        (self.package / UPDATER_EXE_NAME).write_bytes(b"updater")
        (self.package / "_internal").mkdir()
        (self.package / "_internal" / "runtime.dll").write_bytes(b"runtime")
        (self.package / "user_data").mkdir()
        (self.package / "user_data" / "private.json").write_text("private", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_archive_is_versioned_and_excludes_user_data(self) -> None:
        archive, checksum = create_archive(self.package, self.root / "out", "2.4.1")
        self.assertEqual(archive.name, package_name("2.4.1"))
        self.assertTrue(checksum.is_file())
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
        self.assertIn(f"EyE Care/{MAIN_EXE_NAME}", names)
        self.assertIn(f"EyE Care/{MANIFEST_NAME}", names)
        self.assertFalse(any("user_data" in name for name in names))
        verification = verify_archive(archive)
        self.assertEqual(verification["version"], "2.4.1")

    def test_feed_contains_version_hash_size_and_only_rolling_tag(self) -> None:
        archive, _ = create_archive(self.package, self.root / "out", "2.4.1")
        feed_path = write_update_feed(
            archive, self.root / "updates" / "latest.json", version="2.4.1", notes="修复计时",
        )
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
        self.assertEqual(feed["version"], "2.4.1")
        self.assertIn("/releases/download/latest/", feed["package"]["url"])
        self.assertEqual(len(feed["package"]["sha256"]), 64)
        self.assertEqual(feed["package"]["size"], archive.stat().st_size)
        self.assertTrue(_parse_update_feed(feed, "2.4.0")["has_update"])


if __name__ == "__main__":
    unittest.main()
