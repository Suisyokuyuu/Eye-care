"""Open system URLs without leaking a frozen app's DLL paths to the browser."""
from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import sys
import threading

_launch_lock = threading.Lock()


@contextmanager
def system_launch_environment():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        yield
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_dir = kernel.GetDllDirectoryW
    get_dir.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
    get_dir.restype = ctypes.c_uint32
    set_dir = kernel.SetDllDirectoryW
    set_dir.argtypes = [ctypes.c_wchar_p]
    set_dir.restype = ctypes.c_int
    with _launch_lock:
        size = get_dir(0, None)
        buffer = ctypes.create_unicode_buffer(size + 1)
        get_dir(len(buffer), buffer)
        previous_dir = buffer.value or None
        previous_path = os.environ.get("PATH")
        if not set_dir(None):
            raise OSError("Could not restore system DLL search path")
        try:
            bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
            if previous_path is not None:
                entries = previous_path.split(os.pathsep)
                os.environ["PATH"] = os.pathsep.join(p for p in entries if not
                    Path(p.strip('"') or ".").resolve().is_relative_to(bundle))
            yield
        finally:
            set_dir(previous_dir)
            if previous_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = previous_path


def open_system_url(url):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    with system_launch_environment():
        return QDesktopServices.openUrl(QUrl(url))
