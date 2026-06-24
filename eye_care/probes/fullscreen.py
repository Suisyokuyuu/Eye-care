from __future__ import annotations

"""前台「全屏」探测的跨平台入口。

Windows 走 win_fullscreen 的真实实现；其它平台暂无实现，恒返回 False（不触发全屏勿扰）。
"""


def is_foreground_fullscreen() -> bool:
    try:
        import sys
        if sys.platform.startswith("win"):
            from .win_fullscreen import is_foreground_fullscreen as _impl
            return bool(_impl())
    except (ImportError, OSError, AttributeError, TypeError, ValueError):
        return False
    return False
