"""
Notify metrics maintenance and export.
"""
import logging
import time
from collections import deque
from typing import Any, Callable, Dict, Optional


def _calculate_p95(values: deque) -> float:
    """Calculate p95 from a deque of values."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    n = len(sorted_values)
    idx = int(n * 0.95) - 1
    if idx < 0:
        idx = 0
    if idx >= n:
        idx = n - 1
    return sorted_values[idx]


class NotifyMetrics:
    """Notify metrics tracker for DIAG_METRIC_NOTIFY."""

    def __init__(self):
        # Metric timestamps
        self._metric_last_show_ts: float = 0.0
        self._metric_last_style_ok_ts: float = 0.0
        self._metric_degraded_mode: bool = False
        self._metric_show_fail_count: int = 0
        self._metric_show_durations_ms: deque = deque(maxlen=300)
        self._metric_last_show_ms: float = 0.0
        self._metric_show_start: float = 0.0

    def record_show_start(self) -> None:
        """Record the start of a show operation."""
        self._metric_show_start = time.time() * 1000.0

    def record_show_end(self, success: bool = True) -> None:
        """Record the end of a show operation."""
        if self._metric_show_start > 0:
            duration_ms = (time.time() * 1000.0) - self._metric_show_start
            self._metric_show_durations_ms.append(duration_ms)
            self._metric_last_show_ms = duration_ms
            self._metric_show_start = 0.0
        if not success:
            self._metric_show_fail_count += 1
        self._metric_last_show_ts = time.time()

    def record_style_ok(self) -> None:
        """Record that style has been applied successfully."""
        self._metric_last_style_ok_ts = time.time()

    def set_degraded_mode(self, degraded: bool) -> None:
        """Set degraded mode flag."""
        self._metric_degraded_mode = degraded

    def get_metric(self) -> Dict[str, Any]:
        """Get current metrics as a dictionary."""
        return {
            "last_show_ts": self._metric_last_show_ts,
            "last_style_ok_ts": self._metric_last_style_ok_ts,
            "degraded_mode": self._metric_degraded_mode,
            "show_fail_count": self._metric_show_fail_count,
            "notify_show_ms_last": self._metric_last_show_ms,
            "notify_show_ms_p95_5m": _calculate_p95(self._metric_show_durations_ms),
        }

    def reset(self) -> None:
        """Reset all metrics."""
        self._metric_last_show_ts = 0.0
        self._metric_last_style_ok_ts = 0.0
        self._metric_degraded_mode = False
        self._metric_show_fail_count = 0
        self._metric_show_durations_ms.clear()
        self._metric_last_show_ms = 0.0
        self._metric_show_start = 0.0
