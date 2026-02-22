"""
诊断日志事件：统一格式「事件码 | 中文说明 | key=value ...」。
业务层只调用 emit() 或 log_exception_summary()，由本模块经 policy_engine 决定是否落盘。
6.1：DIAG_EXCEPTION 必带 phase, impact, reason_code；同一 reason_code 30s 内仅 1 条 exc_info。
"""
from __future__ import annotations

import logging
import re
import sys
import time
from typing import Any, Dict, Optional, Tuple

_EXC_THROTTLE: Dict[str, Tuple[float, int]] = {}  # reason_code -> (last_full_ts, count)
_EXC_WINDOW_S = 30


def _fmt_kv(**kwargs: Any) -> str:
    parts = []
    for k, v in kwargs.items():
        if v is None:
            continue
        parts.append("%s=%s" % (k, v))
    return " ".join(parts)


def _write_log(
    logger: logging.Logger,
    code: str,
    msg_cn: str,
    level: int = logging.INFO,
    **kwargs: Any,
) -> None:
    """仅 diagnostics 层使用：直接写 log，不经策略。"""
    extra = _fmt_kv(**kwargs)
    line = "%s | %s" % (code, msg_cn)
    if extra:
        line += " | " + extra
    logger.log(level, line)


def emit(
    event_code: str,
    logger: logging.Logger,
    msg_cn: str,
    level: int = logging.INFO,
    **kwargs: Any,
) -> bool:
    """
    诊断门面：经策略引擎决定是否输出。返回 True 表示已落盘。
    业务层只调用此方法（或 log_exception_summary），不直接写 log。
    """
    from .policy_engine import emit as policy_emit
    if policy_emit(event_code, logger, msg_cn, level, **kwargs):
        _write_log(logger, event_code, msg_cn, level, **kwargs)
        return True
    return False


def log_diag(
    log: logging.Logger,
    code: str,
    msg_cn: str,
    level: int = logging.INFO,
    **kwargs: Any,
) -> None:
    """兼容入口：经 emit 门面输出。"""
    emit(code, log, msg_cn, level, **kwargs)


def _reason_code_from_detail(detail: Optional[str]) -> str:
    """从 detail 推导简短 reason_code（6.1 必带）。"""
    if not detail:
        return "unknown"
    s = str(detail).strip()[:80]
    if ":" in s:
        s = s.split(":")[-1].strip()
    s = re.sub(r"\s+", "_", s)
    return s or "unknown"


def _exception_throttle_allow(reason_code: str) -> bool:
    """同一 reason_code 30s 内仅允许一次完整堆栈；返回 True 表示可打 exc_info。"""
    global _EXC_THROTTLE
    now = time.monotonic()
    if reason_code not in _EXC_THROTTLE:
        _EXC_THROTTLE[reason_code] = (now, 1)
        return True
    last_ts, count = _EXC_THROTTLE[reason_code]
    if now - last_ts >= _EXC_WINDOW_S:
        _EXC_THROTTLE[reason_code] = (now, 1)
        return True
    _EXC_THROTTLE[reason_code] = (last_ts, count + 1)
    return False


def log_exception_summary(
    log: logging.Logger,
    code: str,
    phase_cn: str,
    impact_cn: str,
    detail: Optional[str] = None,
    reason_code: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """
    异常概述 + 可选堆栈。同一 reason_code 30s 内仅 1 条 exc_info，其余只打无栈计数行。
    本函数内部在未节流时调用 log.exception，调用方无需再调。
    """
    rc = reason_code if reason_code is not None else _reason_code_from_detail(detail)
    allow_stack = _exception_throttle_allow(rc)
    if allow_stack:
        msg = "异常概述（下方为英文堆栈）"
    else:
        cnt = _EXC_THROTTLE.get(rc, (0, 0))[1]
        msg = "异常概述（节流，同 reason_code 仅首条含堆栈）"
        kwargs = {**kwargs, "throttle_hit": True, "count": cnt}

    if emit(code, log, msg, level=logging.ERROR, phase=phase_cn, impact=impact_cn, reason_code=rc, detail=detail, **kwargs):
        if allow_stack:
            log.exception("DIAG_EXCEPTION")
