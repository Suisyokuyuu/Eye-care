"""
Notify 状态机：支持影子模式（只记录）和显式状态机模式（裁决 + 驱动行为）。
须在 GUI 线程写入 state；后台线程只发事件不入此地。
SM_NOTIFY_V2=False 时保持 legacy 行为（只记录）；SM_NOTIFY_V2=True 时由状态机裁决并驱动。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .types import NotifyState, NOTIFY_TRANSITIONS, is_valid_transition, TransitionResult
from .recorder import record_transition, record_reject, record_defer


class NotifyShadowMachine:
    """Notify 影子状态机：只记录，不驱动。非法转移发 DIAG_SM_REJECT。"""

    def __init__(self, logger: logging.Logger) -> None:
        self._log = logger
        self._state = NotifyState.IDLE
        self._session_id: Optional[str] = None
        self._prompt_key: Optional[str] = None

    @property
    def state(self) -> NotifyState:
        return self._state

    def record(
        self,
        to_state: NotifyState,
        event: str,
        result: str = "ok",
        reason_code: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """在现有链路旁路调用：记录一次迁移。非法转移显式 REJECT，不更新状态。"""
        from_s = self._state
        if not is_valid_transition(NOTIFY_TRANSITIONS, from_s.value, event, to_state.value):
            record_reject(
                self._log,
                "notify",
                "sm_transition_invalid",
                from_state=from_s.value,
                event=event,
                to_state=to_state.value,
            )
            return
        self._state = to_state
        record_transition(
            self._log,
            "notify",
            from_s.value,
            to_state.value,
            event,
            result=result,
            session_id=self._session_id,
            prompt_key=str(self._prompt_key)[:80] if self._prompt_key is not None else None,
            reason_code=reason_code,
            **kwargs,
        )

    def set_session(self, session_id: Optional[str] = None, prompt_key: Optional[str] = None) -> None:
        """设置当前会话标识（用于日志关联）。"""
        self._session_id = session_id
        self._prompt_key = prompt_key

    def record_reject(self, reason_code: str, task: Optional[str] = None) -> None:
        """显式记录 REJECT。"""
        record_reject(self._log, "notify", reason_code, task=task)

    def record_defer(self, reason_code: str) -> None:
        """显式记录 DEFER。"""
        record_defer(self._log, "notify", reason_code)

    # ---- 显式状态机裁决方法 ----
    # 返回 (TransitionResult, target_state_or_None)
    # 仅在 SM_NOTIFY_V2=True 时使用

    def accept(self, event: str, result: str = "ok", reason_code: Optional[str] = None, **kwargs: Any) -> tuple[TransitionResult, Optional[NotifyState]]:
        """请求接受一次状态转移。返回 (OK, target_state) 或 (REJECT, None)。"""
        from_s = self._state
        if not is_valid_transition(NOTIFY_TRANSITIONS, from_s.value, event, ""):
            # 目标状态为空，需要从转移表查
            key = (from_s.value, event)
            if key in NOTIFY_TRANSITIONS:
                to_state = NotifyState(NOTIFY_TRANSITIONS[key])
            else:
                wild = ("*", event)
                if wild in NOTIFY_TRANSITIONS:
                    to_state = NotifyState(NOTIFY_TRANSITIONS[wild])
                else:
                    # 非法转移
                    record_reject(
                        self._log,
                        "notify",
                        "sm_transition_invalid",
                        from_state=from_s.value,
                        event=event,
                    )
                    return TransitionResult.REJECT, None
        else:
            # 目标状态在调用时指定，验证是否一致
            to_state = kwargs.get("_to_state")
            if to_state is None:
                to_state = NotifyState.IDLE  # 默认
            key = (from_s.value, event)
            expected = NOTIFY_TRANSITIONS.get(key) or NOTIFY_TRANSITIONS.get(("*", event))
            if expected != to_state.value:
                record_reject(
                    self._log,
                    "notify",
                    "sm_transition_invalid",
                    from_state=from_s.value,
                    event=event,
                    to_state=to_state.value,
                    expected=expected,
                )
                return TransitionResult.REJECT, None

        # 验证通过，推进状态
        self._state = to_state
        record_transition(
            self._log,
            "notify",
            from_s.value,
            to_state.value,
            event,
            result=result,
            session_id=self._session_id,
            prompt_key=str(self._prompt_key)[:80] if self._prompt_key is not None else None,
            reason_code=reason_code,
            **kwargs,
        )
        return TransitionResult.OK, to_state

    def reject(self, reason_code: str, task: Optional[str] = None) -> tuple[TransitionResult, None]:
        """显式拒绝当前请求，不推进状态。"""
        record_reject(self._log, "notify", reason_code, task=task)
        return TransitionResult.REJECT, None

    def defer(self, reason_code: str) -> tuple[TransitionResult, None]:
        """显式延迟处理，不推进状态。"""
        record_defer(self._log, "notify", reason_code)
        return TransitionResult.DEFER, None

    def try_transition(
        self,
        *,
        event: str,
        to_state: NotifyState,
        result: str = "ok",
        reason_code: Optional[str] = None,
        **kwargs: Any,
    ) -> tuple[TransitionResult, Optional[NotifyState]]:
        """显式状态机驱动：尝试执行一次转移。非法转移走 DIAG_SM_REJECT 且不推进状态。

        必须使用关键字参数调用：
            self.try_transition(event="REQUEST_SHOW", to_state=NotifyState.SCHEDULED)
        """
        # 类型检查：防止 event 和 to_state 传反
        if not isinstance(event, str):
            raise TypeError(f"event must be str, got {type(event).__name__}")
        if not isinstance(to_state, NotifyState):
            raise TypeError(f"to_state must be NotifyState, got {type(to_state).__name__}")

        from_s = self._state
        # 转换为字符串，因为 is_valid_transition 需要字符串类型
        to_state_str = to_state.value if hasattr(to_state, 'value') else str(to_state)
        from_state_str = from_s.value if hasattr(from_s, 'value') else str(from_s)
        if not is_valid_transition(NOTIFY_TRANSITIONS, from_state_str, event, to_state_str):
            record_reject(
                self._log,
                "notify",
                "sm_transition_invalid",
                from_state=from_state_str,
                event=event,
                to_state=to_state_str,
            )
            return TransitionResult.REJECT, None
        self._state = to_state
        record_transition(
            self._log,
            "notify",
            from_state_str,
            to_state_str,
            event,
            result=result,
            session_id=self._session_id,
            prompt_key=str(self._prompt_key)[:80] if self._prompt_key is not None else None,
            reason_code=reason_code,
            **kwargs,
        )
        return TransitionResult.OK, to_state
