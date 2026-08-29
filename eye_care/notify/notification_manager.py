"""
通知调度器：去重、冷却、通道选择。将展示请求投递到 GUI dispatcher。
后台线程不入队以外操作；展示由 GUI 线程执行。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from ..utils.time_utils import local_date_today

log = logging.getLogger(__name__)

MIN_INTERVAL_S = 60
_MAX_PROMPT_KEYS = 128


class NotificationManager:
    """去重 + 冷却。展示请求投递到 dispatcher，GUI 线程执行后回调 on_notify_complete。"""

    _instance: Optional["NotificationManager"] = None

    def __init__(
        self,
        dispatcher,  # GuiDispatcher
        show_toast_fallback: Optional[Callable[[dict], None]] = None,
        min_interval_s: int = MIN_INTERVAL_S,
        mark_notified: Optional[Callable[[], None]] = None,
    ):
        self._dispatcher = dispatcher
        self._show_toast = show_toast_fallback or (lambda _: None)
        self._min_interval_s = max(1, int(min_interval_s))
        self._last_show_time: float = 0.0
        # prompt_key = (local_date, rest_cycle, work_bucket)
        self._shown_prompt_keys: set[tuple] = set()
        self._pending_prompt_keys: dict[tuple, dict] = {}
        self._mark_notified = mark_notified
        self._pending_lock = threading.Lock()

    @classmethod
    def get_instance(
        cls,
        dispatcher=None,
        show_toast_fallback: Optional[Callable[[dict], None]] = None,
        min_interval_s: int = MIN_INTERVAL_S,
        mark_notified: Optional[Callable[[], None]] = None,
    ) -> "NotificationManager":
        if cls._instance is None:
            if dispatcher is None:
                raise ValueError("NotificationManager.get_instance() requires dispatcher on first call")
            cls._instance = cls(
                dispatcher=dispatcher,
                show_toast_fallback=show_toast_fallback,
                min_interval_s=min_interval_s,
                mark_notified=mark_notified,
            )
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    def on_snapshot(self, snapshot_extra: dict) -> None:
        rest = snapshot_extra.get("rest") or {}
        if not rest.get("should_prompt"):
            return

        work_s = int(rest.get("work_s") or 0)
        threshold_s = max(1, int(rest.get("threshold_s") or 60))
        work_bucket = work_s // threshold_s
        # 休息轮次：连续用眼每被清零一次就 +1。带上它后，计时重置后重新爬过同一个 bucket
        # 不会再被当成重复吞掉（修复"通知第一次弹、后面不弹"）。
        cycle = int(rest.get("cycle") or 0)
        local_date = local_date_today()
        prompt_key = (local_date, cycle, work_bucket)
        now = time.monotonic()

        # 0 表示本进程尚未展示过提醒；不能拿系统启动后的 monotonic 秒数与 0 做冷却，
        # 否则开机不足 min_interval_s 时首条提醒会被误挡。
        if self._last_show_time > 0.0 and now - self._last_show_time < self._min_interval_s:
            return

        with self._pending_lock:
            if prompt_key in self._shown_prompt_keys:
                return
            if prompt_key in self._pending_prompt_keys:
                return
            # 已有任意待展示任务时不再入队，避免跨秒 (date,0)/(date,1) 或竞态导致两次 show、通知窗一闪即关
            if self._pending_prompt_keys:
                return

            try:
                from eye_care.diagnostics.debug_switch import is_debug_enabled
                if is_debug_enabled():
                    log.info("notify: should_prompt work_s=%s threshold_s=%s -> enqueue_show", work_s, threshold_s)
            except ImportError:
                log.debug("debug_switch not available; skip notify enqueue debug log")

            self._pending_prompt_keys[prompt_key] = snapshot_extra
            self._dispatcher.post_notify_show(snapshot_extra, prompt_key)

    def on_notify_complete(
        self,
        prompt_key: tuple[str, int],
        result: Optional[bool],
        extra: dict,
        *,
        mark_notified: bool = True,
    ) -> None:
        if prompt_key is None or extra is None:
            return
        extra = extra or {}
        with self._pending_lock:
            self._pending_prompt_keys.pop(prompt_key, None)
        try:
            from eye_care.diagnostics.debug_switch import is_debug_enabled
            dbg = is_debug_enabled() and bool((extra.get("debug") or {}).get("notify"))
        except ImportError:
            dbg = False

        if result is True:
            if dbg:
                log.info("notify: show_done(result=True)")
            try:
                if mark_notified and callable(self._mark_notified) and not extra.get("debug_only") and prompt_key[-1] >= 0:
                    self._mark_notified()
            except Exception:
                log.exception("notify: _mark_notified failed on result=True")
            # Controller 已自行安排 snooze/dismiss 时，不永久记住当前 bucket；否则短冷却后
            # 即使 controller 重新放行，也会被同一个 prompt_key 吞掉。
            if mark_notified:
                self._shown_prompt_keys.add(prompt_key)
                self._prune_shown_keys()
            self._last_show_time = time.monotonic()
            return

        if result is None:
            if dbg:
                log.info("notify: defer (window not ready), will retry next poll")
            return

        try:
            self._show_toast(extra)
            if dbg:
                log.info("notify: fallback toast ok")
            try:
                if callable(self._mark_notified):
                    self._mark_notified()
            except Exception:
                log.exception("notify: _mark_notified failed on fallback toast")
            self._shown_prompt_keys.add(prompt_key)
            self._prune_shown_keys()
            self._last_show_time = time.monotonic()
        except Exception as e:
            log.warning("rest notification fallback (toast) failed: %s", e, exc_info=True)

    def _prune_shown_keys(self) -> None:
        if len(self._shown_prompt_keys) <= _MAX_PROMPT_KEYS:
            return
        today = local_date_today()
        keep = {k for k in self._shown_prompt_keys if k[0] >= today}
        if len(keep) < len(self._shown_prompt_keys):
            self._shown_prompt_keys = keep
        if len(self._shown_prompt_keys) > _MAX_PROMPT_KEYS:
            self._shown_prompt_keys = set(list(self._shown_prompt_keys)[-_MAX_PROMPT_KEYS:])

    def clear_last_shown_key(self) -> None:
        today = local_date_today()
        before_count = len(self._shown_prompt_keys)
        self._shown_prompt_keys = {k for k in self._shown_prompt_keys if k[0] < today}
        after_count = len(self._shown_prompt_keys)
        if before_count != after_count:
            log.info("已清除今日通知去重标记: 清除前=%s, 清除后=%s", before_count, after_count)

    def reset_runtime_state(self) -> None:
        """重置运行时状态：清空待处理队列、重置最后显示时间、清理今日去重标记。
        
        用于通知功能被禁用时清理状态，确保重新启用时不会受到残留状态影响。
        线程安全：在内部锁保护下执行。
        """
        with self._pending_lock:
            self._pending_prompt_keys.clear()
            self._last_show_time = 0.0
            self.clear_last_shown_key()
        log.debug("NotificationManager runtime state reset")
