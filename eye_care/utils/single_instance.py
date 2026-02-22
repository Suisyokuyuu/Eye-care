from __future__ import annotations

"""Windows 单实例防撞（互斥量）。

目标：
- 第二次启动时，立即退出（不启动 controller / UI）。
- 不依赖第三方库（仅 ctypes）。

说明：
- 本模块仅做“防撞”互斥，不负责唤醒已运行实例并置顶。
"""

import ctypes
from ctypes import wintypes


class SingleInstance:
    def __init__(self, name: str) -> None:
        self.name = name
        self._handle: int | None = None

    def acquire(self) -> bool:
        """获取互斥量。

        Returns:
            True: 首实例，成功持有互斥量
            False: 已存在实例
        """

        # CreateMutexW returns a handle; if it already existed, GetLastError==ERROR_ALREADY_EXISTS
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE

        h = kernel32.CreateMutexW(None, True, self.name)
        if not h:
            return True  # fail-open: do not block startup

        self._handle = int(h)
        err = ctypes.get_last_error()
        ERROR_ALREADY_EXISTS = 183
        if err == ERROR_ALREADY_EXISTS:
            self.release()
            return False
        return True

    def release(self) -> None:
        if not self._handle:
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle(wintypes.HANDLE(self._handle))
        except (OSError, AttributeError, TypeError):
            self._handle = None
            return
        self._handle = None
