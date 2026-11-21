"""Paths shared by the fixed launcher and the versioned application."""
from pathlib import Path
import os
import re
import sys
import uuid

VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
RUNTIME = re.compile(r"[0-9a-f]{16}")


def install_root(app):
    app = Path(app).resolve()
    if app.parent.name == "versions" and VERSION.fullmatch(app.name):
        root = app.parent.parent
        marker = app / "runtime-id.txt"
        if marker.is_file():
            runtime = marker.read_text(encoding="ascii").strip()
            if RUNTIME.fullmatch(runtime) and Path(sys.executable).resolve().parent == root / "runtime" / runtime:
                return root
    return app


def atomic_text(path, text):
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def signal_ready():
    marker = os.environ.pop("EYECARE_TRIAL_READY", "")
    if marker:
        from eye_care.version import APP_VERSION
        atomic_text(Path(marker), APP_VERSION)
