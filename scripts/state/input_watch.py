from __future__ import annotations

import threading
from typing import Callable


# =============================================================
# [State] InputWatcher：监听键鼠输入 -> 通知 core（不做任何 UI）
# =============================================================

class InputWatcher:
    def __init__(self, on_any_input: Callable[[], None]):
        self.on_any_input = on_any_input
        self._started = False
        self._lock = threading.Lock()

        self._keyboard_listener = None
        self._mouse_listener = None

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True

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

    def stop(self) -> None:
        with self._lock:
            self._started = False

        for l in (self._keyboard_listener, self._mouse_listener):
            try:
                if l:
                    l.stop()
            except Exception:
                pass

        self._keyboard_listener = None
        self._mouse_listener = None
