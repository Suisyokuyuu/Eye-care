"""
状态机影子层：仅记录迁移与 REJECT/DEFER，不驱动行为。
"""
from __future__ import annotations

from .types import (
    NotifyState,
    RestState,
    RestEntryGuardState,
    StyleState,
    TransitionResult,
    NOTIFY_TRANSITIONS,
    REST_TRANSITIONS,
    REST_ENTRY_GUARD_TRANSITIONS,
    STYLE_TRANSITIONS,
)
from .notify_machine import NotifyShadowMachine
from .rest_machine import RestShadowMachine
from .rest_entry_guard_machine import RestEntryGuardMachine
from .style_machine import StyleShadowMachine
from .recorder import record_transition, record_reject, record_defer

__all__ = [
    "NotifyState",
    "RestState",
    "RestEntryGuardState",
    "StyleState",
    "TransitionResult",
    "NOTIFY_TRANSITIONS",
    "REST_TRANSITIONS",
    "REST_ENTRY_GUARD_TRANSITIONS",
    "STYLE_TRANSITIONS",
    "NotifyShadowMachine",
    "RestShadowMachine",
    "RestEntryGuardMachine",
    "StyleShadowMachine",
    "record_transition",
    "record_reject",
    "record_defer",
]
