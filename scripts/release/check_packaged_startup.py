"""Verify the shipped executable, not the host Python's Qt installation."""
from __future__ import annotations
import argparse
import json
import subprocess
import uuid
from pathlib import Path


def verify_startup(package: Path, report_dir: Path | None = None) -> dict:
    package = package.resolve()
    exe = package / "EyE Care.exe"
    if not exe.is_file():
        raise RuntimeError(f"Executable missing: {exe}")
    root = Path(__file__).resolve().parents[2]
    report_dir = (report_dir or root / "build" / "startup-checks" / str(uuid.uuid4())).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    if (report_dir / "startup_check.json").exists():
        raise RuntimeError("Use a fresh report directory; stale startup evidence is not accepted")
    (report_dir / "config.json").write_text(json.dumps({
        "show_onboarding": False, "notify_enabled": False, "record_browser_enabled": False,
        "startup_show_main": True, "notion_sync_daily": False, "notion_sync_on_startup": False,
    }), encoding="utf-8")
    with (report_dir / "process.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(exe), "--startup-check", "--data-dir", str(report_dir)],
                                   cwd=package, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            code = process.wait(timeout=50)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)
            raise RuntimeError(f"Startup timed out; see {report_dir}") from None
    report_path = report_dir / "startup_check.json"
    if not report_path.exists():
        raise RuntimeError(f"No startup report (exit={code}); see {report_dir}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    captures_ok = all((report_dir / name).is_file() and (report_dir / name).stat().st_size > 0
                      for name in ("startup-main.png", "startup-notion.png", "startup-settings.png"))
    interpreter = Path(report.get("executable", "")).resolve()
    if (package / "current.txt").is_file():
        version = (package / "current.txt").read_text("ascii").strip()
        app = package / "versions" / version
        runtime = (app / "runtime-id.txt").read_text("ascii").strip()
        correct_exe = (interpreter == (package / "runtime" / runtime / "pythonw.exe").resolve()
                       and Path(report.get("source_root", "")).resolve() == app.resolve()
                       and report.get("app_version") == version)
    else:
        correct_exe = bool(report.get("frozen")) and interpreter == exe.resolve()
    if (code or not report.get("ok") or not correct_exe
            or not report.get("main_window") or not report.get("notion_panel") or not captures_ok):
        raise RuntimeError(f"Packaged startup failed: {report}; see {report_dir}")
    print(f"Actual EXE main window and Notion panel verified: {report_dir}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args()
    verify_startup(args.package, args.report_dir)
