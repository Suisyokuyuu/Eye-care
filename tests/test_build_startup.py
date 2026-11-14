from __future__ import annotations
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.build_exe import build_environment, main as build_main
from scripts.check_packaged_startup import verify_startup


class BuildStartupTests(unittest.TestCase):
    def test_build_does_not_resolve_dlls_from_unrelated_host_tools(self):
        with patch.dict(os.environ, {"PATH": "C:/unrelated-poppler;C:/unrelated-libheif", "PYTHONPATH": "C:/other-python", "QT_PLUGIN_PATH": "C:/other-qt"}):
            original = dict(os.environ)
            env = build_environment()
            self.assertNotIn("unrelated", env["PATH"])
            self.assertNotIn("PYTHONPATH", env)
            self.assertNotIn("QT_PLUGIN_PATH", env)
            self.assertEqual(dict(os.environ), original)

    def test_failed_rebuild_preserves_existing_user_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = root / "dist/EyE Care"
            data = package / "user_data"
            data.mkdir(parents=True)
            (data / "record.json").write_text('{"seconds": 42}', encoding="utf-8")

            def run(args, **kwargs):
                if "PyInstaller" in args:
                    assert package.resolve().is_relative_to(root)
                    shutil.rmtree(package)
                    raise subprocess.CalledProcessError(1, args)
                return SimpleNamespace(returncode=0)

            with patch("scripts.build_exe.ROOT", root), patch("scripts.build_exe.subprocess.run", side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):
                    build_main()
            self.assertEqual(json.loads((data / "record.json").read_text(encoding="utf-8")), {"seconds": 42})
            self.assertEqual(len(list((root / "outputs/build-user-data-backups").glob("*/record.json"))), 1)

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
                with patch("scripts.check_packaged_startup.subprocess.Popen", side_effect=launch):
                    with self.assertRaises(RuntimeError):
                        verify_startup(package, report_dir)


if __name__ == "__main__":
    unittest.main()
