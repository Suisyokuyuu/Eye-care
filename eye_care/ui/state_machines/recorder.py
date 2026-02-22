"""
状态迁移诊断门面：所有状态机迁移/REJECT/DEFER 经此门面发射，禁止业务层直接打 DIAG_SM_*。
与 docs/STATE_MACHINE_UPGRADE_GUIDE.md 7 节一致。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from eye_care.diagnostics import diag


def record_transition(
    logger: logging.Logger,
    machine: str,
    from_state: str,
    to_state: str,
    event: str,
    result: str = "ok",
    session_id: Optional[str] = None,
    prompt_key: Optional[str] = None,
    reason_code: Optional[str] = None,
    **kwargs: Any,
) -> bool:
    """记录一次状态迁移（DEBUG_ONLY 策略，由 event_codes 控制）。"""
    payload = {
        "machine": machine,
        "from_state": from_state,
        "to_state": to_state,
        "event": event,
        "result": result,
    }
    if session_id is not None:
        payload["session_id"] = session_id
    if prompt_key is not None:
        payload["prompt_key"] = str(prompt_key)[:80]
    if reason_code is not None:
        payload["reason_code"] = reason_code
    payload.update(kwargs)
    return diag.emit(
        "DIAG_SM_TRANSITION",
        logger,
        "状态机迁移(影子)",
        **payload,
    )


def record_reject(
    logger: logging.Logger,
    machine: str,
    reason_code: str,
    task: Optional[str] = None,
    **kwargs: Any,
) -> bool:
    """记录 REJECT（ALWAYS_ON）。"""
    payload = {"machine": machine, "reason_code": reason_code}
    if task is not None:
        payload["task"] = task
    payload.update(kwargs)
    return diag.emit(
        "DIAG_SM_REJECT",
        logger,
        "状态机拒绝(已停止或非法)",
        level=logging.WARNING,
        **payload,
    )


def record_defer(
    logger: logging.Logger,
    machine: str,
    reason_code: str,
    **kwargs: Any,
) -> bool:
    """记录 DEFER（ALWAYS_ON）。最小字段：machine, reason_code。"""
    payload = {"machine": machine, "reason_code": reason_code}
    payload.update(kwargs)
    return diag.emit(
        "DIAG_SM_DEFER",
        logger,
        "状态机延后",
        **payload,
    )
