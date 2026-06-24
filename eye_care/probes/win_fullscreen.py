from __future__ import annotations

"""Windows 前台窗口「全屏」探测。

判定口径：前台窗口的矩形完全覆盖其所在显示器（rcMonitor，含任务栏区域）即视为全屏，
典型场景=独占/无边框全屏游戏、全屏视频播放器。

刻意排除：
- 桌面 / 任务栏 / Shell 窗口（Progman/WorkerW/Shell_TrayWnd 等）——它们本就铺满屏幕。
- 本进程自身的窗口（如休息全屏遮罩、最大化主窗）——否则护眼应用自己的全屏遮罩会触发全屏勿扰。

注意「最大化 ≠ 全屏」：最大化窗口尊重工作区(rcWork)、不盖任务栏，故不会被判为全屏。
"""

import os
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

MONITOR_DEFAULTTONEAREST = 2

# 桌面/Shell 类名：这些窗口天生铺满屏，不能算作「应用全屏」
_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Button", "SysListView32"}


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
    ]


GetForegroundWindow = user32.GetForegroundWindow
GetForegroundWindow.argtypes = []
GetForegroundWindow.restype = wintypes.HWND

GetWindowRect = user32.GetWindowRect
GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
GetWindowRect.restype = wintypes.BOOL

MonitorFromWindow = user32.MonitorFromWindow
MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
MonitorFromWindow.restype = ctypes.c_void_p

GetMonitorInfoW = user32.GetMonitorInfoW
GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
GetMonitorInfoW.restype = wintypes.BOOL

GetClassNameW = user32.GetClassNameW
GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
GetClassNameW.restype = ctypes.c_int

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
GetWindowThreadProcessId.restype = wintypes.DWORD


def _class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    n = GetClassNameW(hwnd, buf, 256)
    return buf.value if n else ""


def is_foreground_fullscreen() -> bool:
    """前台窗口是否全屏覆盖其所在显示器。异常/非全屏一律返回 False。"""
    try:
        hwnd = GetForegroundWindow()
        if not hwnd:
            return False

        # 排除桌面/Shell 窗口
        if _class_name(hwnd) in _SHELL_CLASSES:
            return False

        # 排除本进程自身的窗口（休息全屏遮罩 / 最大化主窗等）
        pid = wintypes.DWORD(0)
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) == os.getpid():
            return False

        rc = _RECT()
        if not GetWindowRect(hwnd, ctypes.byref(rc)):
            return False

        mon = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not mon:
            return False
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if not GetMonitorInfoW(mon, ctypes.byref(mi)):
            return False

        m = mi.rcMonitor
        # 窗口矩形完整覆盖显示器（允许全屏窗口轻微越界为负边）
        return (
            rc.left <= m.left
            and rc.top <= m.top
            and rc.right >= m.right
            and rc.bottom >= m.bottom
        )
    except Exception:
        return False
