"""Preserve runtime data and require actual-EXE startup before packaging."""
from __future__ import annotations
import shutil
import argparse
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build_environment():
    """Do not collect similarly named DLLs from unrelated tools on host PATH.

    Qt expects Windows ICU exports (ucnv_open); e.g. Poppler's icuuc.dll
    exports versioned symbols instead. Bundling it makes frozen QtCore fail.
    This only scopes the build subprocess; it never changes Windows settings.
    """
    env = os.environ.copy()
    windows = Path(env.get("SystemRoot", "C:/Windows"))
    paths = [Path(sys.executable).parent, Path(sys.base_prefix),
             Path(sys.base_prefix) / "Scripts", windows / "System32", windows,
             windows / "System32/Wbem"]
    env["PATH"] = os.pathsep.join(dict.fromkeys(str(p) for p in paths if p.is_dir()))
    for key in ("PYTHONPATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def main():
    package = (ROOT / "dist" / "EyE Care").resolve()
    if not package.is_relative_to(ROOT.resolve()):
        raise RuntimeError("Build target escaped the project")
    data = package / "user_data"
    backup = None
    if data.exists() and any(data.iterdir()):
        backup = ROOT / "outputs" / "build-user-data-backups" / str(uuid.uuid4())
        shutil.copytree(data, backup)
        print(f"Preserved user_data in {backup}", flush=True)

    def run(*args):
        subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True,
                       env=build_environment())

    try:
        run(ROOT / "scripts/sync_version.py")
        run("-m", "PyInstaller", ROOT / "EyE Care.spec", "--noconfirm")
    finally:
        if backup is not None:
            shutil.copytree(backup, data, dirs_exist_ok=True)
            print("Restored user_data; backup retained", flush=True)
    internal = package / "_internal"
    shutil.copytree(internal / "eye_care", package / "eye_care", dirs_exist_ok=True)
    for name in ("icon.ico", "icon.png", "README.md", "screenshot.png", "使用手册.md"):
        shutil.copy2(internal / name, package / name)
    (package / "docs").mkdir(exist_ok=True)
    shutil.copy2(internal / "docs" / "notion-guide.html", package / "docs" / "notion-guide.html")
    data.mkdir(exist_ok=True)
    duplicate = ROOT / "dist" / "EyE Care Updater.exe"
    if (package / duplicate.name).is_file():
        duplicate.unlink(missing_ok=True)
    run(ROOT / "scripts/check_packaged_startup.py", package)
    run(ROOT / "scripts/package_release.py", package, "--archive", "--output-dir", ROOT / "dist")
    run(ROOT / "scripts/verify_release.py", ROOT / "dist")
    print("Build and actual desktop startup verified", flush=True)
    return 0


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
