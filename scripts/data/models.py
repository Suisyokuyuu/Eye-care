from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class RunMode(str, Enum):
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"


class CoreEvent(str, Enum):
    NEED_BREAK = "NEED_BREAK"


@dataclass(frozen=True)
class CoreConfig:
    idle_threshold_s: int = 60
    work_threshold_s: int = 45 * 60
    rest_time_s: int = 5 * 60


@dataclass
class CoreSnapshot:
    run_mode: RunMode = RunMode.ACTIVE
    front_app: str = ""

    # 手动模式（独立于 idle）
    dnd: bool = False        # 勿扰：禁用提醒
    watching: bool = False   # 观影：禁用提醒（但不影响 idle 判定）

    continuous_work_s: int = 0
    idle_elapsed_s: int = 0
    rest_remaining_s: int = 0
    rest_done_in_idle: bool = False

    # 提醒状态：need_break 会一直保持，直到 idle 或进入休息完成
    need_break: bool = False

    # 用于 UI 在主线程触发气泡：每次需要弹气泡时 +1
    remind_seq: int = 0

    events: List[CoreEvent] = field(default_factory=list)
