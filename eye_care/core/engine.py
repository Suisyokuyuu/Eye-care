from __future__ import annotations

import time
from typing import List

from .models import CoreConfig, CoreEvent, CoreSnapshot, RunMode


class CoreEngine:
    def __init__(self, cfg: CoreConfig):
        self.cfg = cfg

        self._front_app: str = ""
        self._run_mode: RunMode = RunMode.ACTIVE

        self._dnd = False
        self._watching = False

        self._continuous_work_s: int = 0

        now = time.time()
        self._last_input_ts: float = now
        self._last_tick_ts: float = now

        self._idle_elapsed_s: int = 0
        self._rest_remaining_s: int = 0
        self._rest_done_in_idle: bool = False

        # 提醒逻辑
        self._need_break: bool = False
        self._remind_seq: int = 0
        self._next_remind_at: int = int(getattr(cfg, "work_threshold_s", 45 * 60))

        self._events: List[CoreEvent] = []
        self._prev_idle: bool = False

    # ---------------- 手动模式 ----------------

    def toggle_dnd(self) -> None:
        self._dnd = not self._dnd
        # 开启勿扰：立刻静默（不保留提醒态），并把下一次提醒推迟到再工作一个阈值
        if self._dnd:
            self._need_break = False
            self._next_remind_at = self._continuous_work_s + int(getattr(self.cfg, "work_threshold_s", 45 * 60))

    def toggle_watching(self) -> None:
        self._watching = not self._watching
        # 开启观影：同样静默（但不影响 idle 判定）
        if self._watching:
            self._need_break = False
            self._next_remind_at = self._continuous_work_s + int(getattr(self.cfg, "work_threshold_s", 45 * 60))

    def notify_user_input(self, ts: float) -> None:
        self._last_input_ts = float(ts)

    def mark_rest_completed(self) -> None:
        # 主动休息完成：开始新一轮
        self._start_new_round()
        self._rest_done_in_idle = False

    # ---------------- Tick ----------------

    def tick(self, now: float, front_app: str) -> CoreSnapshot:
        self._events = []
        now = float(now)
        self._front_app = front_app or ""

        dt = int(now - self._last_tick_ts)
        if dt <= 0:
            dt = 1
        if dt > 3:
            dt = 1
        self._last_tick_ts = now

        idle_elapsed = int(now - self._last_input_ts)
        idle_threshold = int(getattr(self.cfg, "idle_threshold_s", 60))

        is_idle = idle_elapsed >= idle_threshold
        rest_time = int(getattr(self.cfg, "rest_time_s", 300))

        # ---------- IDLE ----------
        if is_idle:
            self._run_mode = RunMode.IDLE
            self._idle_elapsed_s = idle_elapsed
            self._rest_remaining_s = max(rest_time - idle_elapsed, 0)

            # 刚进入 idle：解除提醒（用户已开始休息/离开）
            if not self._prev_idle:
                self._need_break = False
                # 下一次气泡推迟到再次工作一个阈值
                self._next_remind_at = self._continuous_work_s + int(getattr(self.cfg, "work_threshold_s", 45 * 60))

            # idle 满足 rest_time：算本轮休息完成 -> 新一轮
            if (idle_elapsed >= rest_time) and (not self._rest_done_in_idle):
                self._rest_done_in_idle = True
                self._start_new_round()
                # 注意：仍处于 idle，直到用户输入恢复

            self._prev_idle = True

        # ---------- ACTIVE ----------
        else:
            # 从 idle 回来
            if self._prev_idle:
                self._prev_idle = False
                # 如果上一段 idle 已完成休息，rest_done 标记在返回后清掉
                if self._rest_done_in_idle:
                    self._rest_done_in_idle = False

            self._run_mode = RunMode.ACTIVE
            self._idle_elapsed_s = idle_elapsed
            self._rest_remaining_s = 0

            # 连续工作只在 ACTIVE 且有 app 时累加
            if self._front_app:
                self._continuous_work_s += dt

            # 需要气泡的条件：非勿扰/非观影
            suppressed = self._dnd or self._watching

            if not suppressed:
                # 每过一个 work_threshold，弹一次气泡（need_break 会保持直到 idle/休息）
                if self._continuous_work_s >= self._next_remind_at:
                    self._need_break = True
                    self._remind_seq += 1
                    self._events.append(CoreEvent.NEED_BREAK)
                    self._next_remind_at += int(getattr(self.cfg, "work_threshold_s", 45 * 60))
            else:
                # 模式开启时不提醒
                pass

        return CoreSnapshot(
            run_mode=self._run_mode,
            front_app=self._front_app,
            dnd=self._dnd,
            watching=self._watching,
            continuous_work_s=self._continuous_work_s,
            idle_elapsed_s=self._idle_elapsed_s,
            rest_remaining_s=self._rest_remaining_s,
            rest_done_in_idle=self._rest_done_in_idle,
            need_break=self._need_break,
            remind_seq=self._remind_seq,
            events=list(self._events),
        )

    def _start_new_round(self) -> None:
        self._continuous_work_s = 0
        self._need_break = False
        self._next_remind_at = int(getattr(self.cfg, "work_threshold_s", 45 * 60))
