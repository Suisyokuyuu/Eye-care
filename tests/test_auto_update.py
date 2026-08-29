from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from eye_care.update_helper import ApplyError, apply_update
from eye_care.update_service import (
    LATEST_RELEASE_API_URL,
    MAIN_EXE_NAME,
    MANIFEST_NAME,
    UPDATER_EXE_NAME,
    UpdateError,
    UpdateService,
    _parse_latest_release,
    validate_staged_package,
)


def _write_manifest(root: Path, version: str, rel_paths: list[str]) -> None:
    files = []
    for rel in rel_paths:
        path = root / rel
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({"path": rel.replace("\\", "/"), "size": path.stat().st_size, "sha256": digest})
    (root / MANIFEST_NAME).write_text(json.dumps({
        "schema": 1, "product": "EyE Care", "version": version, "files": files,
    }), encoding="utf-8")


class UpdateFeedTests(unittest.TestCase):
    def test_update_check_uses_the_fixed_latest_release_api(self) -> None:
        self.assertEqual(
            LATEST_RELEASE_API_URL,
            "https://api.github.com/repos/Suisyokuyuu/Eye-care/releases/tags/latest",
        )

    @staticmethod
    def _asset(name: str, *, size: int = 1234, digest: str = "") -> dict:
        return {
            "name": name,
            "state": "uploaded",
            "size": size,
            "digest": digest,
            "browser_download_url": f"https://github.com/Suisyokuyuu/Eye-care/releases/download/latest/{name}",
        }

    def _release(self) -> dict:
        package = "EyE-Care-2.0.0-Windows-x64.zip"
        return {
            "tag_name": "latest",
            "draft": False,
            "html_url": "https://github.com/Suisyokuyuu/Eye-care/releases/tag/latest",
            "body": "test release",
            "published_at": "2026-08-29T00:00:00Z",
            "assets": [self._asset(package), self._asset(package + ".sha256", size=80)],
        }

    def test_package_filename_drives_update_without_version_tag(self) -> None:
        parsed = _parse_latest_release(self._release(), "1.3.2")
        self.assertTrue(parsed["has_update"])
        self.assertEqual(parsed["latest"], "2.0.0")
        self.assertIn("/download/latest/", parsed["asset_url"])
        self.assertTrue(parsed["checksum_url"].endswith(".zip.sha256"))

    def test_rejects_asset_that_uses_a_version_tag(self) -> None:
        release = self._release()
        release["assets"][0]["browser_download_url"] = release["assets"][0][
            "browser_download_url"
        ].replace("/latest/", "/v2.0.0/")
        with self.assertRaises(UpdateError):
            _parse_latest_release(release, "1.3.2")

    def test_incomplete_new_package_is_ignored(self) -> None:
        release = self._release()
        release["assets"] = [release["assets"][0]]
        parsed = _parse_latest_release(release, "1.3.2")
        self.assertFalse(parsed["has_update"])

    def test_incomplete_new_package_does_not_hide_an_older_complete_pair(self) -> None:
        release = self._release()
        newest_zip = release["assets"][0]
        old_name = "EyE-Care-1.5.0-Windows-x64.zip"
        release["assets"] = [
            self._asset(old_name),
            self._asset(old_name + ".sha256", size=80),
            newest_zip,
        ]
        parsed = _parse_latest_release(release, "1.3.2")
        self.assertEqual(parsed["latest"], "1.5.0")

    def test_check_update_reads_the_matching_checksum_sidecar(self) -> None:
        service = UpdateService(data_dir=Path("data"), install_dir=Path("app"), current_version="1.3.2")
        with (
            mock.patch.object(service, "_request_json", return_value=self._release()),
            mock.patch.object(service, "_request_checksum", return_value="a" * 64) as checksum,
        ):
            result = service.check_update(force=True)
        self.assertTrue(result["downloadable"])
        self.assertEqual(result["asset_sha256"], "a" * 64)
        checksum.assert_called_once()


class StagedPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _package(self, version: str = "2.0.0") -> Path:
        package = self.root / "package"
        package.mkdir()
        (package / MAIN_EXE_NAME).write_bytes(b"new-main")
        (package / UPDATER_EXE_NAME).write_bytes(b"new-updater")
        (package / "_internal").mkdir()
        (package / "_internal" / "runtime.dll").write_bytes(b"runtime")
        _write_manifest(package, version, [MAIN_EXE_NAME, UPDATER_EXE_NAME, "_internal/runtime.dll"])
        return package

    def test_validates_every_file_hash(self) -> None:
        package = self._package()
        manifest = validate_staged_package(package, "2.0.0")
        self.assertEqual(manifest["version"], "2.0.0")
        (package / "_internal" / "runtime.dll").write_bytes(b"tampered")
        with self.assertRaises(UpdateError):
            validate_staged_package(package, "2.0.0")

    def test_rejects_zip_slip_before_extraction(self) -> None:
        service = UpdateService(data_dir=self.root / "data", install_dir=self.root / "app")
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../escape.txt", "bad")
        destination = self.root / "extract"
        destination.mkdir()
        with self.assertRaises(UpdateError):
            service._extract_package(archive, destination)
        self.assertFalse((self.root / "escape.txt").exists())

    def test_interrupted_download_resumes_with_http_range(self) -> None:
        service = UpdateService(data_dir=self.root / "data", install_dir=self.root / "app")
        target = self.root / "partial.zip.part"
        target.write_bytes(b"abc")

        class Response:
            status = 206
            headers = {"Content-Length": "3", "Content-Range": "bytes 3-5/6"}
            chunks = [b"def", b""]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def getcode(self):
                return self.status

            def read(self, _size):
                return self.chunks.pop(0)

        with mock.patch("urllib.request.urlopen", return_value=Response()) as opener:
            digest = service._download_file(
                "https://github.com/Suisyokuyuu/Eye-care/releases/download/latest/test.zip",
                target,
                expected_size=6,
            )
        request = opener.call_args.args[0]
        self.assertEqual(request.headers.get("Range"), "bytes=3-")
        self.assertEqual(target.read_bytes(), b"abcdef")
        self.assertEqual(digest, hashlib.sha256(b"abcdef").hexdigest())

    def test_successful_update_cleanup_removes_completed_full_stage(self) -> None:
        service = UpdateService(data_dir=self.root / "data", install_dir=self.root / "app")
        stage = service.update_root / "stage-2.0.0"
        stage.mkdir(parents=True)
        (stage / "large.zip").write_bytes(b"payload")
        service.result_path.write_text(json.dumps({
            "ok": True, "status": "updated", "to_version": "2.0.0",
        }), encoding="utf-8")
        service.cleanup_runtime_helpers()
        self.assertFalse(stage.exists())


class ApplyUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = self.root / "app"
        self.source = self.target / "user_data" / "updates" / "stage" / "package"
        self.data = self.target / "user_data"
        self.source.mkdir(parents=True)
        (self.target / "_internal").mkdir()
        (self.target / MAIN_EXE_NAME).write_bytes(b"old-main")
        (self.target / UPDATER_EXE_NAME).write_bytes(b"old-updater")
        (self.target / "_internal" / "old.dll").write_bytes(b"old-library")
        (self.data / "history.json").write_text("keep-me", encoding="utf-8")
        _write_manifest(self.target, "1.0.0", [MAIN_EXE_NAME, UPDATER_EXE_NAME, "_internal/old.dll"])

        (self.source / "_internal").mkdir()
        (self.source / MAIN_EXE_NAME).write_bytes(b"new-main")
        (self.source / UPDATER_EXE_NAME).write_bytes(b"new-updater")
        (self.source / "_internal" / "new.dll").write_bytes(b"new-library")
        _write_manifest(self.source, "2.0.0", [MAIN_EXE_NAME, UPDATER_EXE_NAME, "_internal/new.dll"])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_replaces_program_removes_stale_file_and_preserves_user_data(self) -> None:
        result = apply_update(self.source, self.target, self.data, "1.0.0", "2.0.0")
        self.assertTrue(result["ok"])
        self.assertEqual((self.target / MAIN_EXE_NAME).read_bytes(), b"new-main")
        self.assertTrue((self.target / "_internal" / "new.dll").is_file())
        self.assertFalse((self.target / "_internal" / "old.dll").exists())
        self.assertEqual((self.data / "history.json").read_text(encoding="utf-8"), "keep-me")

    def test_copy_failure_rolls_back_all_changed_files(self) -> None:
        from eye_care import update_helper

        original_copy = update_helper._atomic_copy
        failed = {"once": False}

        def fail_once(source: Path, target: Path) -> None:
            # apply_update() resolves its directories first.  On Windows runners a
            # temporary path may therefore change case or expand from an 8.3 form,
            # so comparing it with the unresolved fixture path is not reliable.
            if target.name.casefold() == MAIN_EXE_NAME.casefold() and not failed["once"]:
                failed["once"] = True
                raise OSError("simulated locked file")
            original_copy(source, target)

        with mock.patch.object(update_helper, "_atomic_copy", side_effect=fail_once):
            with self.assertRaises(ApplyError):
                apply_update(self.source, self.target, self.data, "1.0.0", "2.0.0")
        self.assertTrue(failed["once"], "the simulated copy failure was not injected")
        self.assertEqual((self.target / MAIN_EXE_NAME).read_bytes(), b"old-main")
        self.assertEqual((self.target / UPDATER_EXE_NAME).read_bytes(), b"old-updater")
        self.assertTrue((self.target / "_internal" / "old.dll").is_file())
        self.assertFalse((self.target / "_internal" / "new.dll").exists())

    def test_rejects_tampered_stage_before_touching_installation(self) -> None:
        (self.source / MAIN_EXE_NAME).write_bytes(b"tampered")
        with self.assertRaises(ApplyError):
            apply_update(self.source, self.target, self.data, "1.0.0", "2.0.0")
        self.assertEqual((self.target / MAIN_EXE_NAME).read_bytes(), b"old-main")


if __name__ == "__main__":
    unittest.main()
