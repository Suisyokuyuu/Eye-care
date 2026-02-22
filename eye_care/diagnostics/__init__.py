"""
诊断层门面：业务层只调用 emit() / safe_call()，不直接写 log 或做策略判断。
"""
from __future__ import annotations

from .diag_events import emit, log_diag, log_exception_summary
from .diag_guard import safe_call
from .debug_switch import is_debug_enabled, is_debug_module

__all__ = [
    "emit",
    "safe_call",
    "log_diag",
    "log_exception_summary",
    "is_debug_enabled",
    "is_debug_module",
    "diag",
]


class _Diag:
    """门面：业务层统一使用 diag.emit()、diag.safe_call()。"""
    emit = staticmethod(emit)
    safe_call = staticmethod(safe_call)


diag = _Diag()
