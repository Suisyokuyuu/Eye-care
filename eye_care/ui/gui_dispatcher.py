"""
GUI 调度器：所有 pywebview/WebView2 窗口操作必须通过本模块投递到 GUI 线程执行。

硬规则：
- window.show()/hide()/destroy()、evaluate_js()、Win32 hwnd 操作、SetWindowPos、
  alpha/fade、acrylic、PrintWindow 等必须在 GUI 线程执行
- 后台线程（NotifierService、Controller tick、Flask）不得直接操作窗口
- **硬约束：不可在后台线程直接 evaluate_js，必须通过 dispatcher.post 投递到 GUI 线程**
- **硬约束：GUI 线程内 evaluate_js 应合并为单次调用，避免多次同步 round-trip（减少阻塞风险）**
- 由 pywebview 启动后的 GUI loop 持续消费队列

使用方式：
- 后台线程：dispatcher.post(callable, *args, **kwargs)
- 或使用类型化方法：post_notify_show、post_rest_show 等
- GUI 线程：run_pending() 在 webview.start 的 loop 中调用
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from eye_care.diagnostics import diag, log_exception_summary
from eye_care.ui.state_machines.recorder import record_reject

log = logging.getLogger(__name__)

# 当前是否在 GUI 线程（用于 debug 模式下检测非法调用）
_gui_thread_id: Optional[int] = None
# 指标：非 GUI 线程调用 window API 次数（DIAG_METRIC_DISPATCH illegal_count）
_metric_illegal_count: int = 0


def is_gui_thread() -> bool:
    """当前线程是否为 GUI 线程（即执行 run_pending 的线程）。"""
    if _gui_thread_id is None:
        return False
    return threading.current_thread().ident == _gui_thread_id


def _assert_gui_thread() -> None:
    """Debug 模式下：非 GUI 线程调用 window API 时 raise 并写日志。"""
    try:
        from eye_care.diagnostics.debug_switch import is_debug_enabled
        if not is_debug_enabled():
            return
        if not is_gui_thread():
            global _metric_illegal_count
            _metric_illegal_count += 1
            tid = threading.current_thread().ident
            diag.emit("DIAG_DISPATCH_ILLEGAL", log, "非法：在非GUI线程调用窗口API", level=logging.ERROR, tid=tid, gui_tid=_gui_thread_id)
            raise RuntimeError("ILLEGAL: window API called from non-GUI thread (tid=%s, gui_tid=%s)" % (tid, _gui_thread_id))
    except ImportError:
        return




@dataclass
class GuiTask:
    """通用 GUI 任务。"""
    fn: Callable[..., Any]
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)


@dataclass
class NotifyShowTask:
    """通知展示任务。"""
    extra: dict
    prompt_key: tuple[str, int]


@dataclass
class RestShowTask:
    """休息遮罩展示任务。"""
    pass


class GuiDispatcher:
    """
    统一 GUI 调度器：后台 post，GUI 线程 run_pending 消费。
    停止后拒绝新任务（stop gate），避免退出时 post 导致挂死。
    """

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._stopped_at: Optional[float] = None  # 停止时间戳，用于日志
        self._gui_thread_id: Optional[int] = None
        # 指标（DIAG_METRIC_DISPATCH）
        self._post_count: int = 0
        self._reject_count: int = 0
        self._max_queue_len: int = 0
        self._dispatch_durations_ms: deque = deque(maxlen=300)  # ~5min at ~1/s
        self._last_dispatch_ms: float = 0.0

    def set_gui_thread(self) -> None:
        """由 GUI loop 在启动时调用，标记当前线程为 GUI 线程。"""
        global _gui_thread_id
        self._gui_thread_id = threading.current_thread().ident
        _gui_thread_id = self._gui_thread_id

    def post(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """后台线程调用：投递任务到 GUI 队列。停止后拒绝入队。"""
        if self._stop.is_set():
            self._reject_count += 1
            diag.emit("DIAG_DISPATCH_REJECT", log, "已停止，拒绝投递", fn_name=getattr(fn, "__name__", "unknown"))
            return
        self._post_count += 1
        self._q.put(GuiTask(fn=fn, args=args, kwargs=kwargs))
        self._max_queue_len = max(self._max_queue_len, self._q.qsize())

    def post_notify_show(self, extra: dict, prompt_key: tuple[str, int]) -> None:
        """投递通知展示任务（类型化，便于消费端识别）。停止后拒绝入队。"""
        if self._stop.is_set():
            self._reject_count += 1
            diag.emit("DIAG_DISPATCH_REJECT", log, "已停止，拒绝投递", task="notify_show")
            record_reject(log, "notify", "dispatcher_stopped", task="notify_show")
            return
        self._post_count += 1
        self._q.put(NotifyShowTask(extra=extra, prompt_key=prompt_key))
        self._max_queue_len = max(self._max_queue_len, self._q.qsize())

    def post_rest_show(self) -> None:
        """投递休息遮罩展示任务。停止后拒绝入队。"""
        if self._stop.is_set():
            self._reject_count += 1
            diag.emit("DIAG_DISPATCH_REJECT", log, "已停止，拒绝投递", task="rest_show")
            record_reject(log, "rest", "dispatcher_stopped", task="rest_show")
            return
        self._post_count += 1
        self._q.put(RestShowTask())
        self._max_queue_len = max(self._max_queue_len, self._q.qsize())

    def ensure_gui(self, operation_name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """
        窗口操作统一入口：若当前在 GUI 线程则直接执行，否则投递到队列并打 HARD 日志。
        operation_name 用于日志，中文可读，如 "显示主窗口"。
        """
        if self._stop.is_set():
            self._reject_count += 1
            diag.emit("DIAG_DISPATCH_REJECT", log, "已停止，拒绝投递", operation=operation_name)
            return
        if is_gui_thread():
            try:
                fn(*args, **kwargs)
            except Exception:
                log_exception_summary(log, "DIAG_EXCEPTION", "GUI内执行窗口操作", "该操作失败", operation_name)
            return
        try:
            from eye_care.diagnostics.debug_switch import is_debug_enabled
        except ImportError:
            is_debug_enabled = lambda: False  # type: ignore[assignment]
        if is_debug_enabled():
            diag.emit(
                "DIAG_DISPATCH_POST", log, "非GUI线程窗口操作已投递到队列",
                operation=operation_name, thread=threading.current_thread().name or threading.current_thread().ident,
            )
        self.post(fn, *args, **kwargs)

    def get_task(self, timeout: float = 0.0) -> Any:
        """GUI 线程调用：获取待处理任务。timeout=0 非阻塞。"""
        try:
            return self._q.get(block=timeout > 0, timeout=timeout if timeout > 0 else None)
        except queue.Empty:
            return None

    def has_pending(self) -> bool:
        return not self._q.empty()

    def run_pending(
        self,
        *,
        notify_handler: Optional[Callable[[NotifyShowTask], None]] = None,
        rest_handler: Optional[Callable[[], None]] = None,
        max_per_cycle: int = 10,
    ) -> int:
        """
        GUI 线程调用：消费队列中的任务。
        - NotifyShowTask -> notify_handler(task)
        - RestShowTask -> rest_handler()
        - GuiTask -> task.fn(*task.args, **task.kwargs)
        返回本轮处理的任务数。
        """
        self.set_gui_thread()
        t0 = time.perf_counter()
        count = 0
        for _ in range(max_per_cycle):
            task = self.get_task(timeout=0)
            self._max_queue_len = max(self._max_queue_len, self._q.qsize())
            if task is None:
                break
            try:
                if isinstance(task, NotifyShowTask) and notify_handler:
                    notify_handler(task)
                elif isinstance(task, RestShowTask) and rest_handler:
                    rest_handler()
                elif isinstance(task, GuiTask):
                    task.fn(*task.args, **task.kwargs)
                else:
                    diag.emit("DIAG_DISPATCH_UNKNOWN", log, "未知调度任务类型", level=logging.WARNING, task_type=str(type(task)))
            except Exception:
                diag.emit("DIAG_DISPATCH_DRAIN", log, "停止后最后一轮消费任务异常", level=logging.DEBUG)
                log_exception_summary(log, "DIAG_EXCEPTION", "GUI调度任务执行", "该任务失败")
            count += 1
        dur_ms = (time.perf_counter() - t0) * 1000.0
        self._last_dispatch_ms = dur_ms
        self._dispatch_durations_ms.append(dur_ms)
        return count

    def get_metric(self) -> dict:
        """返回 DIAG_METRIC_DISPATCH 用字段（queue_len, post_count, reject_count, illegal_count, max_queue_len, dispatch_ms_last, dispatch_ms_p95_5m）。"""
        global _metric_illegal_count
        qlen = self._q.qsize()
        p95 = 0.0
        if self._dispatch_durations_ms:
            sorted_d = sorted(self._dispatch_durations_ms)
            idx = max(0, int(len(sorted_d) * 0.95) - 1)
            p95 = sorted_d[idx]
        return {
            "queue_len": qlen,
            "post_count": self._post_count,
            "reject_count": self._reject_count,
            "illegal_count": _metric_illegal_count,
            "max_queue_len": self._max_queue_len,
            "dispatch_ms_last": round(self._last_dispatch_ms, 2),
            "dispatch_ms_p95_5m": round(p95, 2),
        }

    def stop(self) -> None:
        """设置停止闸门；之后 post/post_notify_show/post_rest_show/ensure_gui 将拒绝新任务。"""
        if self._stop.is_set():
            return
        import time as _time
        self._stopped_at = _time.time()
        self._stop.set()
