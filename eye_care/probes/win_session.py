from __future__ import annotations

"""Windows 用户会话/输入桌面可用性探针。

同时检查：
- 当前进程所在 WTS 会话必须为 ``WTSActive``（远程桌面断开时会变为
  ``WTSDisconnected``）；
- 当前输入桌面必须允许切换（锁屏/安全桌面时 ``SwitchDesktop`` 会失败）。

任何 API 失败都按不可交互处理。这里采用 fail-closed 是有意的：误少记一秒远好于
在无人使用时持续累计数小时并触发错误的休息提醒。
"""

import ctypes
import os
from ctypes import wintypes


WTS_CURRENT_SERVER_HANDLE = wintypes.HANDLE(0)
WTS_CONNECT_STATE = 8
WTS_ACTIVE = 0
DESKTOP_SWITCHDESKTOP = 0x0100

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)

ProcessIdToSessionId = kernel32.ProcessIdToSessionId
ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
ProcessIdToSessionId.restype = wintypes.BOOL

WTSQuerySessionInformationW = wtsapi32.WTSQuerySessionInformationW
WTSQuerySessionInformationW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(wintypes.DWORD),
]
WTSQuerySessionInformationW.restype = wintypes.BOOL

WTSFreeMemory = wtsapi32.WTSFreeMemory
WTSFreeMemory.argtypes = [wintypes.LPVOID]
WTSFreeMemory.restype = None

OpenInputDesktop = user32.OpenInputDesktop
OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenInputDesktop.restype = wintypes.HANDLE

SwitchDesktop = user32.SwitchDesktop
SwitchDesktop.argtypes = [wintypes.HANDLE]
SwitchDesktop.restype = wintypes.BOOL

CloseDesktop = user32.CloseDesktop
CloseDesktop.argtypes = [wintypes.HANDLE]
CloseDesktop.restype = wintypes.BOOL


def _current_wts_state() -> int | None:
    session_id = wintypes.DWORD(0)
    if not ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id)):
        return None

    buffer = wintypes.LPWSTR()
    size = wintypes.DWORD(0)
    ok = WTSQuerySessionInformationW(
        WTS_CURRENT_SERVER_HANDLE,
        session_id.value,
        WTS_CONNECT_STATE,
        ctypes.byref(buffer),
        ctypes.byref(size),
    )
    if not ok or not buffer or size.value < ctypes.sizeof(wintypes.DWORD):
        if buffer:
            WTSFreeMemory(buffer)
        return None
    try:
        return int(ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value)
    finally:
        WTSFreeMemory(buffer)


def _input_desktop_available() -> bool:
    desktop = OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not desktop:
        return False
    try:
        return bool(SwitchDesktop(desktop))
    finally:
        CloseDesktop(desktop)


def is_user_session_interactive_win() -> bool:
    try:
        return _current_wts_state() == WTS_ACTIVE and _input_desktop_available()
    except Exception:
        return False
