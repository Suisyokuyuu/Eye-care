from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from eye_care.controller.app_controller import AppController
from eye_care.data.repository import DomainDelta
from eye_care.probes.browser_url import make_browser_watcher


_NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


class _RecordingWatcher:
    """Mock watcher：记录 set_active 调用，get_domain 返回预设 domain。"""

    def __init__(self, domain: str = "") -> None:
        self.active_calls: list[bool] = []
        self._domain = domain

    def start(self) -> None:  # pragma: no cover - trivial
        pass

    def stop(self, timeout_s: float = 2.0) -> None:  # pragma: no cover - trivial
        pass

    def set_active(self, active: bool) -> None:
        self.active_calls.append(bool(active))

    def get_domain(self, max_age_s: float = 6.0) -> str:
        return self._domain


class _RecordingRepo:
    def __init__(self) -> None:
        self.domain_deltas: list[DomainDelta] = []

    def add_domain_usage(self, delta: DomainDelta) -> None:
        self.domain_deltas.append(delta)


def _controller(*, record: bool, domain: str = "") -> AppController:
    """最小 controller：仅装配 _maybe_record_domain 需要的字段。"""
    c = AppController.__new__(AppController)
    c.cfg = SimpleNamespace(record_browser_enabled=record)
    c._browser_watcher = _RecordingWatcher(domain)
    c.repo = _RecordingRepo()
    return c


class BrowserTickTests(unittest.TestCase):
    def test_switch_off_default_does_not_activate_or_record(self) -> None:
        c = _controller(record=False, domain="bilibili.com")
        c._maybe_record_domain("chrome", 1, _NOW)

        # 开关关：set_active 只被置 False，且不写 repo
        self.assertNotIn(True, c._browser_watcher.active_calls)
        self.assertEqual(c._browser_watcher.active_calls, [False])
        self.assertEqual(c.repo.domain_deltas, [])

    def test_browser_foreground_records_domain(self) -> None:
        c = _controller(record=True, domain="bilibili.com")
        c._maybe_record_domain("chrome", 3, _NOW)

        self.assertEqual(c._browser_watcher.active_calls, [True])
        self.assertEqual(len(c.repo.domain_deltas), 1)
        delta = c.repo.domain_deltas[0]
        self.assertEqual(delta.domain, "bilibili.com")
        self.assertEqual(delta.seconds, 3)
        self.assertEqual(delta.utc_ts, _NOW)

    def test_non_browser_foreground_deactivates_and_skips(self) -> None:
        c = _controller(record=True, domain="bilibili.com")
        c._maybe_record_domain("editor", 1, _NOW)

        self.assertEqual(c._browser_watcher.active_calls, [False])
        self.assertEqual(c.repo.domain_deltas, [])

    def test_empty_domain_is_discarded(self) -> None:
        c = _controller(record=True, domain="")
        c._maybe_record_domain("chrome", 1, _NOW)

        # 前台是浏览器 → 仍激活探针，但 domain 为空 → 不写 repo
        self.assertEqual(c._browser_watcher.active_calls, [True])
        self.assertEqual(c.repo.domain_deltas, [])

    def test_make_browser_watcher_is_noop_on_non_windows(self) -> None:
        # 本机（Linux）应返回 no-op watcher：所有方法安全、get_domain 恒 ""
        w = make_browser_watcher(log=None)
        w.start()
        w.set_active(True)
        self.assertEqual(w.get_domain(), "")
        w.stop()


if __name__ == "__main__":
    unittest.main()
