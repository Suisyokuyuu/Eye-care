from __future__ import annotations


def get_idle_seconds_checked() -> int | None:
    """返回 idle 秒数；Windows API 失败时返回 None，而不是伪装成“刚有输入”。"""
    try:
        import sys
        if sys.platform.startswith("win"):
            from .win_idle import get_idle_seconds_win_checked
            return get_idle_seconds_win_checked()
    except (ImportError, OSError, AttributeError, TypeError, ValueError):
        return None
    return 0


def get_idle_seconds() -> int:
    value = get_idle_seconds_checked()
    if value is None:
        return 0
    return int(value)
