from __future__ import annotations

"""Windows idle-time probe.

Implementation: GetLastInputInfo + GetTickCount64.
Returns idle seconds as int. If any call fails, returns 0.
"""

import ctypes
from ctypes import wintypes


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GetLastInputInfo = user32.GetLastInputInfo
GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
GetLastInputInfo.restype = wintypes.BOOL

GetTickCount64 = kernel32.GetTickCount64
GetTickCount64.argtypes = []
GetTickCount64.restype = ctypes.c_ulonglong


def get_idle_seconds_win() -> int:
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not GetLastInputInfo(ctypes.byref(lii)):
            return 0
        now_ms = int(GetTickCount64())
        # lii.dwTime is a DWORD (wraps), but GetTickCount64 won't wrap in practice.
        last_ms = int(lii.dwTime)
        # Convert lii.dwTime into an equivalent value near now_ms.
        # dwTime uses GetTickCount (32-bit). Reconstruct by taking low 32 bits.
        now_low = now_ms & 0xFFFFFFFF
        # delta in unsigned 32-bit space
        delta = (now_low - last_ms) & 0xFFFFFFFF
        return int(delta // 1000)
    except Exception:
        return 0
