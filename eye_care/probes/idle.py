from __future__ import annotations
def get_idle_seconds() -> int:
    try:
        import sys
        if sys.platform.startswith("win"):
            from .win_idle import get_idle_seconds_win
            return int(get_idle_seconds_win())
    except (ImportError, OSError, AttributeError, TypeError, ValueError):
        return 0
    return 0
