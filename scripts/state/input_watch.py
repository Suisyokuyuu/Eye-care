from __future__ import annotations

import sys
import threading
import time
import ctypes
from ctypes import wintypes
from typing import Callable, Optional


# =============================================================
# [State] InputWatcher：Windows 优先用 GetLastInputInfo 轮询
# - 不依赖 pynput（避免“监听失败 -> 永远空闲”）
# - 非 Windows：再尝试 pynput；失败则降级
# =============================================================

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    GetLastInputInfo = user32.GetLastInputInfo
    GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
    GetLastInputInfo.restype = wintypes.BOOL

    GetTickCount64 = kernel32.GetTickCount64
    GetTickCount64.argtypes = []
    GetTickCount64.restype = ctypes.c_ulonglong


def _win_last_input_tick() -> Optional[int]:
    """返回 Windows 最后一次输入的 tick（毫秒），失败返回 None。"""
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ok = GetLastInputInfo(ctypes.byref(lii))
    if not ok:
        return None
    # dwTime 是 32-bit tick（毫秒），会回绕，但用于“变化检测”足够
    return int(lii.dwTime)


class InputWatcher:
    def __init__(self, on_any_input: Callable[[], None]):
        self.on_any_input = on_any_input
        self._started = False
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # fallback（非 win）
        self._keyboard_listener = None
        self._mouse_listener = None

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._stop_evt.clear()

        if sys.platform == "win32":
            # Windows：用系统 API 轮询（稳定、无第三方依赖）
            self._thread = threading.Thread(target=self._win_poll_loop, daemon=True)
            self._thread.start()
            return

        # 其他平台：尽量用 pynput（可用则更灵敏）
        try:
            from pynput import keyboard, mouse

            def _hit(*_args, **_kwargs):
                try:
                    self.on_any_input()
                except Exception:
                    pass

            self._keyboard_listener = keyboard.Listener(on_press=_hit, on_release=_hit)
            self._mouse_listener = mouse.Listener(on_move=_hit, on_click=_hit, on_scroll=_hit)

            self._keyboard_listener.start()
            self._mouse_listener.start()
        except Exception:
            # 监听失败：不阻断程序（只是 idle 判定退化）
            pass

    def _win_poll_loop(self) -> None:
        prev = None
        # 启动时先打一发，避免刚启动就被判 idle（可选）
        try:
            self.on_any_input()
        except Exception:
            pass

        while not self._stop_evt.is_set():
            try:
                cur = _win_last_input_tick()
                if cur is not None and cur != prev:
                    prev = cur
                    try:
                        self.on_any_input()
                    except Exception:
                        pass
            except Exception:
                pass

            time.sleep(0.25)

    def stop(self) -> None:
        with self._lock:
            self._started = False
            self._stop_evt.set()

        # win polling thread ends by event
        self._thread = None

        # pynput listeners
        for l in (self._keyboard_listener, self._mouse_listener):
            try:
                if l:
                    l.stop()
            except Exception:
                pass

        self._keyboard_listener = None
        self._mouse_listener = None
