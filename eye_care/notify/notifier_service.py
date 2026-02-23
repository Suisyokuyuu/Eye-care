"""
NotifierService：后台轮询 controller 快照，驱动 NotificationManager。
不直接操作窗口。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

log = logging.getLogger(__name__)


class NotifierService:
    def __init__(
        self,
        *,
        controller,
        notification_manager,
        poll_interval_s: float = 1.0,
    ) -> None:
        self._controller = controller
        self._manager = notification_manager
        self._poll_interval_s = max(0.1, float(poll_interval_s))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="notifier_service")
        self._thread.start()
        log.info("notifier service started poll_interval_s=%s", self._poll_interval_s)

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=max(0.1, float(timeout_s)))
        log.info("notifier service stopped")

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                _, extra = self._controller.snapshot_today(mark_prompted=False)
                if extra:
                    self._manager.on_snapshot(extra)
            except Exception:
                log.exception("notifier service loop crashed")
            self._stop.wait(self._poll_interval_s)
