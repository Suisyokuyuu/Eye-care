from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class ForegroundInfo:
    app_short: str = ""
    pid: int = 0
    # NOTE: This field is **transient** and MUST NOT be persisted to disk.
    # It exists only to allow runtime features (e.g., icon extraction).
    exe_path: str = ""

def get_foreground() -> ForegroundInfo:
    # Windows implementation can be plugged later.
    try:
        import sys
        if sys.platform.startswith("win"):
            from .win_foreground import get_foreground_win
            return get_foreground_win()
    except (ImportError, OSError, AttributeError, TypeError, ValueError):
        return ForegroundInfo(app_short="", pid=0)
    return ForegroundInfo(app_short="", pid=0)
