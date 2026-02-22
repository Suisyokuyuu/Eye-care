"""
关键链路异常防护：safe_call 执行 fn，异常时经诊断层打 DIAG_EXCEPTION（reason_code + 节流），
返回 default，不改变业务降级行为。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional, TypeVar

from .diag_events import log_exception_summary

T = TypeVar("T")


def safe_call(
    fn: Callable[[], T],
    reason_code: str,
    module: str,
    default: T,
    log: Optional[logging.Logger] = None,
    phase_cn: str = "safe_call",
    impact_cn: str = "降级继续",
    log_exc: bool = True,
) -> T:
    """
    执行 fn()；异常时打 DIAG_EXCEPTION（经路由器 + reason_code 节流），返回 default。
    不改变业务语义：仍返回 default，不重新抛出。
    """
    if log is None:
        log = logging.getLogger(__name__)
    try:
        return fn()
    except Exception as e:
        if log_exc:
            log_exception_summary(
                log,
                "DIAG_EXCEPTION",
                phase_cn,
                impact_cn,
                detail=str(e)[:200],
                reason_code=reason_code,
                module=module,
            )
            # 堆栈由 log_exception_summary 内部按 reason_code 30s 节流决定是否输出
        return default
