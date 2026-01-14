from __future__ import annotations

import time
from typing import List

from .models import CoreConfig, CoreEvent, CoreSnapshot, ManualMode, RunMode


class CoreEngine:
    """
    核心状态机（不关心 UI/托盘/图标）：

    - 运行态：ACTIVE / IDLE（由输入空闲判定）
    - 手动态：NORMAL / DND / WATCHING（三者互斥，独立于 IDLE）
    - 只有 ACTIVE + NORMAL 才触发提醒
    - need_break 维持到：休息完成 或 进入 idle 并完成休息 或 skip_break
    """

    def __init__(self, cfg: CoreConfig):
        self.cfg = cfg

        self._front_app: str = ""
        self._run_mode: RunMode = RunMode.ACTIVE
        self._manual_mode: ManualMode = ManualMode.NORMAL

        self._continuous_work_s: int = 0

        now = time.time()
        self._last_input_ts: float = now
        self._last_tick_ts: float = now

        self._idle_elapsed_s: int = 0
        self._rest_remaining_s: int = 0
        self._rest_done_in_idle: bool = False

        self._need_break: bool = False
        self._remind_seq: int = 0
        self._next_remind_at: int = int(self.cfg.work_threshold_s)

        self._events: List[CoreEvent] = []
        self._prev_idle: bool = False

    # ---------------- config hot update ----------------

    def update_config(self, cfg: CoreConfig) -> None:
        """
        热更新配置（尤其是 work_threshold_s），并重排下一次提醒。
        解决：用户在设置里把提醒分钟改小，但 engine 仍按旧 _next_remind_at 触发，导致“改了也不弹”。
        """
        self.cfg = cfg

        th = int(getattr(cfg, "work_threshold_s", 0) or 0)
        if th <= 0:
            th = 60  # 兜底：至少 60s

        # 非 NORMAL：保持静默语义（进入 DND/WATCHING 本来就取消提醒）
        if self._manual_mode != ManualMode.NORMAL:
            self._need_break = False
            self._next_remind_at = self._continuous_work_s + th
            return

        # NORMAL：如果当前连续工作已经超过新阈值 -> 立刻进入 need_break（下一次 UI tick 就会弹）
        if (not self._need_break) and (self._continuous_work_s >= th):
            self._need_break = True
            self._remind_seq += 1
            self._next_remind_at = self._continuous_work_s + th
            return

        # 还没到阈值：把下一次提醒点对齐到“下一个阈值倍数”
        if self._need_break:
            self._next_remind_at = self._continuous_work_s + th
        else:
            self._next_remind_at = ((self._continuous_work_s // th) + 1) * th

    # ---------------- 手动模式（互斥） ----------------

    def get_manual_mode(self) -> ManualMode:
        return self._manual_mode

    def set_manual_mode(self, mode: ManualMode) -> None:
        if mode == self._manual_mode:
            return
        self._manual_mode = mode

        # 进入静默：立刻取消当前提醒，并把下一次提醒推到“再工作一个阈值”
        if mode != ManualMode.NORMAL:
            self._need_break = False
            self._next_remind_at = self._continuous_work_s + int(self.cfg.work_threshold_s)

    # 兼容旧接口：点一次进入该模式，再点一次回 NORMAL
    def toggle_dnd(self) -> None:
        self.set_manual_mode(ManualMode.NORMAL if self._manual_mode == ManualMode.DND else ManualMode.DND)

    def toggle_watching(self) -> None:
        self.set_manual_mode(ManualMode.NORMAL if self._manual_mode == ManualMode.WATCHING else ManualMode.WATCHING)

    def set_normal(self) -> None:
        self.set_manual_mode(ManualMode.NORMAL)

    def set_dnd(self) -> None:
        self.set_manual_mode(ManualMode.DND)

    def set_watching(self) -> None:
        self.set_manual_mode(ManualMode.WATCHING)

    # ---------------- 输入/休息 ----------------

    def notify_user_input(self, ts: float) -> None:
        self._last_input_ts = float(ts)

    def mark_rest_completed(self) -> None:
        self._start_new_round()
        self._rest_done_in_idle = False

    def skip_break(self) -> None:
        """跳过本轮提醒：清 need_break，并推迟到下一轮阈值再提醒。"""
        self._need_break = False
        self._next_remind_at = self._continuous_work_s + int(self.cfg.work_threshold_s)

    # ---------------- Tick ----------------

    def tick(self, now: float, front_app: str) -> CoreSnapshot:
        self._events = []
        now = float(now)
        self._front_app = front_app or ""

        # dt：不要 dt>3 就强制=1；改为 clamp 到 max_tick_dt_s
        dt = int(now - self._last_tick_ts)
        if dt <= 0:
            dt = 1
        max_dt = int(getattr(self.cfg, "max_tick_dt_s", 5))
        if dt > max_dt:
            dt = max_dt
        self._last_tick_ts = now

        idle_elapsed = int(now - self._last_input_ts)
        idle_threshold = int(self.cfg.idle_threshold_s)
        rest_time = int(self.cfg.rest_time_s)

        is_idle = idle_elapsed >= idle_threshold

        # ---------- IDLE ----------
        if is_idle:
            self._run_mode = RunMode.IDLE
            self._idle_elapsed_s = idle_elapsed
            self._rest_remaining_s = max(rest_time - idle_elapsed, 0)

            # idle 满足 rest_time：算休息完成 -> 开新一轮
            if (idle_elapsed >= rest_time) and (not self._rest_done_in_idle):
                self._rest_done_in_idle = True
                self._start_new_round()

            self._prev_idle = True

        # ---------- ACTIVE ----------
        else:
            if self._prev_idle:
                self._prev_idle = False
                if self._rest_done_in_idle:
                    self._rest_done_in_idle = False

            self._run_mode = RunMode.ACTIVE
            self._idle_elapsed_s = idle_elapsed
            self._rest_remaining_s = 0

            if self._front_app:
                self._continuous_work_s += dt

            suppressed = (self._manual_mode != ManualMode.NORMAL)
            if not suppressed:
                if self._continuous_work_s >= self._next_remind_at:
                    self._need_break = True
                    self._remind_seq += 1
                    self._events.append(CoreEvent.NEED_BREAK)
                    self._next_remind_at += int(self.cfg.work_threshold_s)

        return CoreSnapshot(
            run_mode=self._run_mode,
            front_app=self._front_app,
            manual_mode=self._manual_mode,
            dnd=(self._manual_mode == ManualMode.DND),
            watching=(self._manual_mode == ManualMode.WATCHING),
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
        self._next_remind_at = int(self.cfg.work_threshold_s)
