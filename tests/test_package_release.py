from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from eye_care.update_service import MAIN_EXE_NAME, MANIFEST_NAME, UPDATER_EXE_NAME
from scripts.package_release import create_archive, main as package_main, package_name
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

    def test_archive_command_creates_only_zip_and_checksum(self) -> None:
        output = self.root / "release"
        self.assertEqual(package_main([
            str(self.package), "--archive", "--version", "2.4.1", "--output-dir", str(output),
        ]), 0)
        archive = output / package_name("2.4.1")
        self.assertTrue(archive.is_file())
        self.assertTrue(archive.with_name(archive.name + ".sha256").is_file())
        self.assertFalse((output / "latest.json").exists())


if __name__ == "__main__":
    unittest.main()
