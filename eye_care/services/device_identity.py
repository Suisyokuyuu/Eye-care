"""Local writer identity. A copied data directory must not impersonate its source."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

_identity_lock = threading.Lock()


def _machine_key():
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                return winreg.QueryValueEx(key, "MachineGuid")[0]
        except OSError:
            pass
    return platform.node()


def installation_id(data_dir, *, machine=None):
    directory = Path(data_dir).resolve()
    # Binding stays local: neither the host name nor the directory is exported.
    binding = hashlib.sha256((str(machine or _machine_key()) + "\0" +
                              os.path.normcase(str(directory))).encode("utf-8")).hexdigest()
    path = directory / "sync_device.json"
    with _identity_lock:
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("binding") == binding:
                return str(uuid.UUID(saved["id"]))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        directory.mkdir(parents=True, exist_ok=True)
        identity = str(uuid.uuid4())
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps({"id": identity, "binding": binding}), encoding="utf-8")
        temporary.replace(path)
        return identity


@contextmanager
def sync_directory_lock(data_dir):
    """Keep concurrent processes using the same local folder from racing on POST."""
    from .notion_client import NotionError
    path = Path(data_dir) / "notion_sync.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    locked = False
    try:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise NotionError("另一个软件实例正在同步同一数据目录，请稍后重试。") from None
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()
