"""
Style 状态机影子：仅记录迁移，不驱动行为。
与 StyleCoordinator 现有 phase 旁路记录。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .types import StyleState, STYLE_TRANSITIONS, is_valid_transition
from .recorder import record_transition, record_reject, record_defer


class StyleShadowMachine:
    """Style 影子状态机：只记录，不驱动。非法转移发 DIAG_SM_REJECT。"""

    def __init__(self, logger: logging.Logger) -> None:
        self._log = logger
        self._state = StyleState.WAIT_TARGET
        self._overlay_id: Any = None

    @property
    def state(self) -> StyleState:
        return self._state

    def record(
        self,
        to_state: StyleState,
        event: str,
        result: str = "ok",
        reason_code: Optional[str] = None,
        kind: Optional[str] = None,
        overlay_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """在现有链路旁路调用：记录一次迁移。非法转移显式 REJECT，不更新状态。"""
        from_s = self._state
        if not is_valid_transition(STYLE_TRANSITIONS, from_s.value, event, to_state.value):
            record_reject(
                self._log,
                "style",
                "sm_transition_invalid",
                from_state=from_s.value,
                event=event,
                to_state=to_state.value,
                **(dict(kind=kind) if kind else {}),
                **(dict(overlay_id=str(overlay_id)[:40]) if overlay_id is not None else {}),
                **kwargs,
            )
            return
        self._state = to_state
        oid = overlay_id if overlay_id is not None else self._overlay_id
        payload = {}
        if kind is not None:
            payload["kind"] = kind
        if oid is not None:
            payload["overlay_id"] = str(oid)[:40]
        payload.update(kwargs)
        record_transition(
            self._log,
            "style",
            from_s.value,
            to_state.value,
            event,
            result=result,
            reason_code=reason_code,
            **payload,
        )

    def set_overlay(self, overlay_id: Any) -> None:
        self._overlay_id = overlay_id

    def record_reject(self, reason_code: str) -> None:
        record_reject(self._log, "style", reason_code)

    def record_defer(self, reason_code: str) -> None:
        record_defer(self._log, "style", reason_code)
