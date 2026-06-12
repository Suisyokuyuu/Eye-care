"""Windows 相关小工具，供 Qt runtime_shell、notify 等复用，避免循环依赖。"""
from __future__ import annotations

from typing import Any, Optional


def native_handle_to_int(h: Any) -> Optional[int]:
    """将 .NET IntPtr / 可转 int 的对象转为 Python int，避免 op_Equality 异常。"""
    if h is None:
        return None
    try:
        return int(h)
    except (TypeError, ValueError, OverflowError):
        fn = getattr(h, "ToInt64", None) or getattr(h, "ToInt32", None)
        if callable(fn):
            try:
                return int(fn())
            except (TypeError, ValueError, OverflowError):
                return None
    return None
