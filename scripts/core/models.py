from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class RunMode(str, Enum):
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"


class ManualMode(str, Enum):
    NORMAL = "NORMAL"      # 正常
    DND = "DND"            # 勿扰
    WATCHING = "WATCHING"  # 观影


class CoreEvent(str, Enum):
    NEED_BREAK = "NEED_BREAK"


@dataclass
class CoreConfig:
    idle_threshold_s: int = 60
    work_threshold_s: int = 45 * 60
    rest_time_s: int = 5 * 60
    # tick 间隔过大时的上限（避免卡顿导致计时/提醒延后）
    max_tick_dt_s: int = 5


@dataclass
class CoreSnapshot:
    run_mode: RunMode = RunMode.ACTIVE
    front_app: str = ""

    # 互斥三态（与 idle 独立）
    manual_mode: ManualMode = ManualMode.NORMAL

    # 兼容旧 UI（由 manual_mode 派生）
    dnd: bool = False
    watching: bool = False

    continuous_work_s: int = 0
    idle_elapsed_s: int = 0
    rest_remaining_s: int = 0
    rest_done_in_idle: bool = False

    need_break: bool = False
    remind_seq: int = 0

    events: List[CoreEvent] = field(default_factory=list)
