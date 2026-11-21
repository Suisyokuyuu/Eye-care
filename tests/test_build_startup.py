from __future__ import annotations
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.release.portable_release import build_windows
from scripts.release.check_packaged_startup import verify_startup


class BuildStartupTests(unittest.TestCase):
    def test_failed_windows_build_leaves_previous_package_and_live_data_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "dist/EyE Care/user_data"
            data.mkdir(parents=True)
            history = data / "record.json"
            history.write_text('{"seconds":42}')
            previous = root / "dist/EyE-Care-1.4.0-Windows-x64.zip"
            previous.write_bytes(b"last good package")
            with patch("scripts.release.portable_release.DIST", root / "dist"), patch(
                    "scripts.release.portable_release.collect_source", side_effect=RuntimeError("simulated failure")):
                with self.assertRaises(RuntimeError):
                    build_windows("1.4.0")
            self.assertEqual(previous.read_bytes(), b"last good package")
            self.assertEqual(json.loads(history.read_text()), {"seconds":42})

    def test_source_or_wrong_executable_report_cannot_pass_release_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "package"
            package.mkdir()
            (package / "EyE Care.exe").write_bytes(b"fixture")
            for index, frozen in enumerate((False, True)):
                report_dir = root / f"report-{index}"
                def launch(*args, **kwargs):
                    (report_dir / "startup_check.json").write_text(json.dumps({
                        "ok": True, "frozen": frozen, "executable": "wrong.exe",
                        "main_window": True, "notion_panel": True,
                    }), encoding="utf-8")
                    return SimpleNamespace(wait=lambda timeout: 0)
                with patch("scripts.release.check_packaged_startup.subprocess.Popen", side_effect=launch):
                    with self.assertRaises(RuntimeError):
                        verify_startup(package, report_dir)


if __name__ == "__main__":
    unittest.main()
