"""
Rest 进入守卫状态机（指南 5.5）：控制「立即休息」按钮与 /api/rest/start 可用性。
单状态源，与 snapshot rest.start_enabled / API 409 共用。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from eye_care.diagnostics import diag

from .types import (
    RestEntryGuardState,
    REST_ENTRY_GUARD_TRANSITIONS,
    is_valid_transition,
)
from .recorder import record_transition, record_reject


class RestEntryGuardMachine:
    """Rest 进入守卫：UNLOCKED -> REST_ENTERED -> LOCKED_ACTIVE -> REST_CLOSED -> LOCKED_COOLDOWN -> COOLDOWN_EXPIRE -> UNLOCKED。"""

    def __init__(self, logger: logging.Logger) -> None:
        self._log = logger
        self._state = RestEntryGuardState.UNLOCKED
        self._cooldown_end_at: float = 0.0  # 冷却结束时间戳（time.time()）

    @property
    def state(self) -> RestEntryGuardState:
        return self._state

    @property
    def cooldown_end_at(self) -> float:
        return self._cooldown_end_at

    def record(
        self,
        to_state: RestEntryGuardState,
        event: str,
        result: str = "ok",
        cooldown_end_at: Optional[float] = None,
        **kwargs: Any,
    ) -> bool:
        """记录一次迁移；非法转移 REJECT 且不更新状态。返回是否成功迁移。"""
        from_s = self._state
        if not is_valid_transition(
            REST_ENTRY_GUARD_TRANSITIONS, from_s.value, event, to_state.value
        ):
            record_reject(
                self._log,
                "rest_entry_guard",
                "sm_transition_invalid",
                from_state=from_s.value,
                event=event,
                to_state=to_state.value,
                **kwargs,
            )
            return False
        self._state = to_state
        if cooldown_end_at is not None:
            self._cooldown_end_at = cooldown_end_at
        record_transition(
            self._log,
            "rest_entry_guard",
            from_s.value,
            to_state.value,
            event,
            result=result,
            **kwargs,
        )
        return True

    def record_rest_entered(self) -> bool:
        """REST_ENTERED: UNLOCKED -> LOCKED_ACTIVE。rest_start 成功后调用。"""
        ok = self.record(RestEntryGuardState.LOCKED_ACTIVE, "REST_ENTERED")
        if ok:
            diag.emit("DIAG_REST_GUARD_LOCK", self._log, "rest 进入，立即休息已锁")
        return ok

    def record_rest_closed(self, cooldown_end_at: float) -> bool:
        """REST_CLOSED: LOCKED_ACTIVE -> LOCKED_COOLDOWN。rest 遮罩关闭后调用，冷却从此时起 2 秒。"""
        ok = self.record(
            RestEntryGuardState.LOCKED_COOLDOWN,
            "REST_CLOSED",
            cooldown_end_at=cooldown_end_at,
        )
        if ok:
            diag.emit(
                "DIAG_REST_GUARD_COOLDOWN_START",
                self._log,
                "rest 已关，进入 2s 冷却",
                cooldown_end_at=cooldown_end_at,
            )
        return ok

    def record_cooldown_expire(self) -> bool:
        """COOLDOWN_EXPIRE: LOCKED_COOLDOWN -> UNLOCKED。2 秒定时器到期后调用。"""
        ok = self.record(RestEntryGuardState.UNLOCKED, "COOLDOWN_EXPIRE")
        if ok:
            diag.emit("DIAG_REST_GUARD_UNLOCK", self._log, "冷却结束，立即休息可点")
        return ok

    def is_start_allowed(self) -> bool:
        """是否允许发起 rest（按钮可点 / API 可接受）。"""
        return self._state == RestEntryGuardState.UNLOCKED

    def get_block_reason(self) -> str:
        """start_block_reason: '' | 'rest_active' | 'rest_cooldown'。"""
        if self._state == RestEntryGuardState.LOCKED_ACTIVE:
            return "rest_active"
        if self._state == RestEntryGuardState.LOCKED_COOLDOWN:
            return "rest_cooldown"
        return ""

    def unlock_in_ms(self, now: Optional[float] = None) -> int:
        """剩余冷却毫秒数；非冷却态返回 0。"""
        if self._state != RestEntryGuardState.LOCKED_COOLDOWN:
            return 0
        import time
        t = (now if now is not None else time.time())
        return max(0, int((self._cooldown_end_at - t) * 1000))
