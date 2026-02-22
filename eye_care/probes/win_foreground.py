from __future__ import annotations

"""Windows foreground-app probe.

Goal (new spec): return ONLY app_short (exe stem) + pid.
- no window title
- no process path stored

Implementation: GetForegroundWindow -> GetWindowThreadProcessId -> QueryFullProcessImageNameW
"""

import os
import ctypes
from ctypes import wintypes

from .foreground import ForegroundInfo


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GetForegroundWindow = user32.GetForegroundWindow
GetForegroundWindow.argtypes = []
GetForegroundWindow.restype = wintypes.HWND

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
GetWindowThreadProcessId.restype = wintypes.DWORD

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
QueryFullProcessImageNameW.restype = wintypes.BOOL

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # Windows API constant, not quota-related


def _clean_app_short(exe_path: str) -> str:
    """Normalize to 'app_short' per spec.

    - keep only basename
    - strip extension
    - lower-case
    """
    if not exe_path:
        return ""
    base = os.path.basename(exe_path)
    stem, _ = os.path.splitext(base)
    return (stem or "").strip().lower()


def _get_exe_path_by_pid(pid: int) -> str:
    h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return ""
    try:
        buf_len = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(buf_len.value)
        if QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(buf_len)):
            return buf.value
        # retry with larger buffer if needed
        buf_len = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(buf_len.value)
        if QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(buf_len)):
            return buf.value
        return ""
    finally:
        CloseHandle(h)


def get_foreground_win() -> ForegroundInfo:
    try:
        hwnd = GetForegroundWindow()
        if not hwnd:
            return ForegroundInfo(app_short="", pid=0)
        pid = wintypes.DWORD(0)
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        p = int(pid.value)
        if p <= 0:
            return ForegroundInfo(app_short="", pid=0)
        exe_path = _get_exe_path_by_pid(p)
        if not exe_path:
            # Fallback: psutil (name only). Avoid recording full path.
            try:
                import psutil  # type: ignore
                exe_path = str(psutil.Process(p).name() or "")
            except Exception:
                exe_path = ""
        app_short = _clean_app_short(exe_path)
        # exe_path is transient (for runtime icon extraction only)
        return ForegroundInfo(app_short=app_short, pid=p, exe_path=str(exe_path or ""))
    except Exception:
        return ForegroundInfo(app_short="", pid=0, exe_path="")
