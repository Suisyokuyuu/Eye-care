"""
Rest 状态机影子：仅维护当前状态并记录迁移，不驱动行为。
须在 GUI 线程写入 state。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .types import RestState, REST_TRANSITIONS, is_valid_transition
from .recorder import record_transition, record_reject, record_defer


class RestShadowMachine:
    """Rest 影子状态机：只记录，不驱动。非法转移发 DIAG_SM_REJECT。"""

    def __init__(self, logger: logging.Logger) -> None:
        self._log = logger
        self._state = RestState.IDLE
        self._session_id: Optional[str] = None

    @property
    def state(self) -> RestState:
        return self._state

    def record(
        self,
        to_state: RestState,
        event: str,
        result: str = "ok",
        reason_code: Optional[str] = None,
        screen_count: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """在现有链路旁路调用：记录一次迁移。非法转移显式 REJECT，不更新状态。"""
        from_s = self._state
        if not is_valid_transition(REST_TRANSITIONS, from_s.value, event, to_state.value):
            record_reject(
                self._log,
                "rest",
                "sm_transition_invalid",
                from_state=from_s.value,
                event=event,
                to_state=to_state.value,
                **kwargs,
            )
            return
        self._state = to_state
        payload = {}
        if screen_count is not None:
            payload["screen_count"] = screen_count
        payload.update(kwargs)
        record_transition(
            self._log,
            "rest",
            from_s.value,
            to_state.value,
            event,
            result=result,
            session_id=self._session_id,
            reason_code=reason_code,
            **payload,
        )

    def set_session(self, session_id: Optional[str] = None) -> None:
        self._session_id = session_id

    def record_reject(self, reason_code: str, task: Optional[str] = None) -> None:
        record_reject(self._log, "rest", reason_code, task=task)

    def record_defer(self, reason_code: str) -> None:
        record_defer(self._log, "rest", reason_code)
