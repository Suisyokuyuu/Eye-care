from __future__ import annotations

import os
import sys
import ctypes
from ctypes import wintypes


# =============================================================
# [State] Windows Probe：纯 ctypes 获取前台进程短名（更稳）
# - 不依赖 pywin32 / psutil，避免“抓不到进程导致永远无数据”
# =============================================================

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    GetForegroundWindow = user32.GetForegroundWindow
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId

    OpenProcess = kernel32.OpenProcess
    CloseHandle = kernel32.CloseHandle
    QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def get_foreground_app_short_name() -> str:
    """返回前台进程短名（不含 .exe），失败返回空字符串。"""
    if sys.platform != "win32":
        return ""

    hwnd = GetForegroundWindow()
    if not hwnd:
        return ""

    pid = wintypes.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""

    hproc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not hproc:
        return ""

    try:
        # 先用 260，若不够再扩
        size = 260
        while True:
            buf_len = wintypes.DWORD(size)
            buf = ctypes.create_unicode_buffer(size)
            ok = QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(buf_len))
            if ok:
                exe_path = buf.value
                name = os.path.splitext(os.path.basename(exe_path))[0]
                return name
            # 如果缓冲不够，尝试扩容
            if ctypes.get_last_error() == 122 and size < 4096:  # ERROR_INSUFFICIENT_BUFFER
                size *= 2
                continue
            return ""
    finally:
        CloseHandle(hproc)
