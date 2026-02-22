"""
状态机公共类型。
与 docs/STATE_MACHINE_UPGRADE_GUIDE.md 5.1–5.4 对齐，仅用于旁路记录，不驱动行为。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class NotifyState(str, Enum):
    """NotifyWindowMachine 状态枚举（与指南 5.1 一致）。"""
    IDLE = "IDLE"
    SCHEDULED = "SCHEDULED"
    CREATING = "CREATING"
    CREATED = "CREATED"
    STYLING = "STYLING"
    SHOWING = "SHOWING"
    SHOWN = "SHOWN"
    HIDING = "HIDING"
    HIDDEN = "HIDDEN"
    FAILED = "FAILED"


class RestState(str, Enum):
    """RestOverlayMachine 状态枚举（与指南 5.2 一致）。"""
    IDLE = "IDLE"
    SCHEDULED = "SCHEDULED"
    CREATING = "CREATING"
    CREATED = "CREATED"
    SHOWING = "SHOWING"
    SHOWN = "SHOWN"
    COUNTDOWN = "COUNTDOWN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class StyleState(str, Enum):
    """StyleApplyMachine 状态枚举（与指南 5.3 一致）。"""
    WAIT_TARGET = "WAIT_TARGET"
    WAIT_HWND = "WAIT_HWND"
    APPLY_WIN32_STYLE = "APPLY_WIN32_STYLE"
    APPLY_WEBVIEW_BG = "APPLY_WEBVIEW_BG"
    VERIFY_FIRST_FRAME = "VERIFY_FIRST_FRAME"
    READY = "READY"
    DEGRADED = "DEGRADED"
    FAIL = "FAIL"


class TransitionResult(str, Enum):
    """迁移结果：ok / reject / defer（指南 5.4 不变量）。"""
    OK = "ok"
    REJECT = "reject"
    DEFER = "defer"


# 合法转移表（与 recorder 校验一致；实现口径见 STATE_MACHINE_UPGRADE_GUIDE.md）
NOTIFY_TRANSITIONS: dict[tuple[str, str], str] = {
    ("IDLE", "REQUEST_SHOW"): "SCHEDULED",
    ("HIDDEN", "REQUEST_SHOW"): "SCHEDULED",
    ("FAILED", "REQUEST_SHOW"): "SCHEDULED",
    ("SCHEDULED", "GUI_START"): "CREATING",
    ("SCHEDULED", "WINDOW_READY"): "CREATED",  # 已有窗口时跳过 CREATING
    ("CREATING", "CREATE_OK"): "CREATED",
    ("CREATING", "CREATE_FAIL"): "FAILED",
    ("CREATED", "STYLE_ENTER"): "STYLING",
    ("CREATED", "STYLE_READY"): "SHOWING",
    ("CREATED", "STYLE_DEGRADED"): "SHOWING",
    ("CREATED", "STYLE_FAIL"): "FAILED",
    ("STYLING", "STYLE_READY"): "SHOWING",
    ("STYLING", "STYLE_DEGRADED"): "SHOWING",
    ("STYLING", "STYLE_FAIL"): "FAILED",
    ("SHOWING", "FIRST_FRAME_OK"): "SHOWN",
    ("SHOWING", "FIRST_FRAME_TIMEOUT"): "SHOWN",
    ("SHOWN", "HIDE_REQ"): "HIDING",
    ("HIDING", "HIDE_DONE"): "HIDDEN",
    ("*", "ABORT"): "FAILED",
}

REST_TRANSITIONS: dict[tuple[str, str], str] = {
    ("IDLE", "REQUEST_SHOW"): "SCHEDULED",
    ("CLOSED", "REQUEST_SHOW"): "SCHEDULED",
    ("FAILED", "REQUEST_SHOW"): "SCHEDULED",
    ("SCHEDULED", "GUI_START"): "CREATING",
    ("CREATING", "OVERLAY_CREATE_PARTIAL"): "CREATED",
    ("CREATING", "OVERLAY_CREATE_NONE"): "FAILED",
    ("CREATED", "SHOW_OK"): "SHOWING",
    ("CREATED", "SHOW_NONE"): "FAILED",
    ("SHOWING", "SHOW_DONE"): "SHOWN",
    ("SHOWN", "COUNTDOWN_START"): "COUNTDOWN",
    ("SHOWN", "ABORT"): "CLOSING",
    ("COUNTDOWN", "COMPLETE"): "CLOSING",
    ("COUNTDOWN", "SNOOZE"): "CLOSING",
    ("COUNTDOWN", "ABORT"): "CLOSING",
    ("CLOSING", "CLOSE_DONE"): "CLOSED",
    ("CLOSING", "CLOSE_FAIL"): "FAILED",
}


class RestEntryGuardState(str, Enum):
    """Rest 进入守卫状态（指南 5.5）：控制「立即休息」按钮与 /api/rest/start 可用性。"""
    UNLOCKED = "UNLOCKED"
    LOCKED_ACTIVE = "LOCKED_ACTIVE"  # rest 进行中
    LOCKED_COOLDOWN = "LOCKED_COOLDOWN"  # rest 结束后 2 秒冷却


REST_ENTRY_GUARD_TRANSITIONS: dict[tuple[str, str], str] = {
    ("UNLOCKED", "REST_ENTERED"): "LOCKED_ACTIVE",
    ("LOCKED_ACTIVE", "REST_CLOSED"): "LOCKED_COOLDOWN",
    ("LOCKED_COOLDOWN", "COOLDOWN_EXPIRE"): "UNLOCKED",
}

STYLE_TRANSITIONS: dict[tuple[str, str], str] = {
    ("WAIT_TARGET", "TARGET_READY"): "WAIT_HWND",
    ("WAIT_HWND", "HWND_READY"): "APPLY_WIN32_STYLE",
    ("WAIT_HWND", "HWND_TIMEOUT"): "DEGRADED",
    ("APPLY_WIN32_STYLE", "WIN32_STYLE_OK"): "APPLY_WEBVIEW_BG",
    ("APPLY_WIN32_STYLE", "WIN32_STYLE_FAIL"): "DEGRADED",
    ("APPLY_WEBVIEW_BG", "WEBVIEW_BG_OK"): "VERIFY_FIRST_FRAME",
    ("APPLY_WEBVIEW_BG", "WEBVIEW_BG_FAIL"): "DEGRADED",
    ("VERIFY_FIRST_FRAME", "FIRST_FRAME_OK"): "READY",
    ("VERIFY_FIRST_FRAME", "FIRST_FRAME_TIMEOUT"): "DEGRADED",
}


def is_valid_transition(
    transitions: dict[tuple[str, str], str],
    from_state: str,
    event: str,
    to_state: str,
) -> bool:
    """转移是否在表内且目标状态一致；用于非法转移时发 DIAG_SM_REJECT。"""
    key = (from_state, event)
    if key in transitions:
        return transitions[key] == to_state
    wild = ("*", event)
    if wild in transitions:
        return transitions[wild] == to_state
    return False
