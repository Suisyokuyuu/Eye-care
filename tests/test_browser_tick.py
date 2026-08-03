from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from eye_care.controller.app_controller import (
    FAVICON_PREFETCH_MIN_SECONDS,
    AppController,
)
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
    """记录 domain 增量，并按原始 host 累计当天秒数（供 favicon 门槛播种读取）。

    `seed` 可预置「本进程启动前就已存在」的当天用量，用来验证重启后不被打回从零。
    """

    def __init__(self, seed: dict | None = None) -> None:
        self.domain_deltas: list[DomainDelta] = []
        self.daily: dict[str, int] = dict(seed or {})

    def add_domain_usage(self, delta: DomainDelta) -> None:
        self.domain_deltas.append(delta)
        self.daily[delta.domain] = self.daily.get(delta.domain, 0) + int(delta.seconds)

    def get_daily_domain_usage(self, _local_date: str) -> dict:
        # 忽略日期参数：单元测试里只有「今天」，避免与本机时区耦合
        return dict(self.daily)


def _controller(*, record: bool, domain: str = "", prefetch=None,
                independent=(), repo_seed: dict | None = None) -> AppController:
    """最小 controller：仅装配 _maybe_record_domain 需要的字段。"""
    c = AppController.__new__(AppController)
    c.cfg = SimpleNamespace(record_browser_enabled=record,
                            site_independent_hosts=list(independent))
    c._browser_watcher = _RecordingWatcher(domain)
    c.repo = _RecordingRepo(repo_seed)
    c._favicon_secs = {}
    c._favicon_secs_day = ""
    if prefetch is not None:
        c.set_favicon_prefetch(prefetch)
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

    def test_prefetch_waits_for_the_time_threshold(self) -> None:
        # 误点一下就关掉的站点不该产生任何请求；满 60s 才抓
        calls: list[str] = []
        c = _controller(record=True, domain="bilibili.com", prefetch=calls.append)

        for _ in range(FAVICON_PREFETCH_MIN_SECONDS - 1):
            c._maybe_record_domain("chrome", 1, _NOW)
        self.assertEqual(calls, [], "未满门槛就联网了")

        c._maybe_record_domain("chrome", 1, _NOW)
        self.assertEqual(calls, ["bilibili.com"])

    def test_prefetch_collapses_subdomains_to_the_parent_site(self) -> None:
        # 主域名抓过就够了：子域名不单独抓，且各子域名的时长合并计入同一门槛
        calls: list[str] = []
        c = _controller(record=True, prefetch=calls.append)

        half = FAVICON_PREFETCH_MIN_SECONDS // 2
        c._browser_watcher = _RecordingWatcher("space.bilibili.com")
        for _ in range(half):
            c._maybe_record_domain("chrome", 1, _NOW)
        c._browser_watcher = _RecordingWatcher("t.bilibili.com")
        for _ in range(FAVICON_PREFETCH_MIN_SECONDS - half):
            c._maybe_record_domain("chrome", 1, _NOW)

        # 抓的是注册域名一次，而不是两个子域名各一次
        self.assertEqual(calls, ["bilibili.com"])

    def test_prefetch_keeps_independent_hosts_separate(self) -> None:
        # 用户显式配成独立统计的子站点仍各抓各的（否则三个 Google 服务同一个图标）
        calls: list[str] = []
        c = _controller(record=True, domain="mail.google.com", prefetch=calls.append,
                        independent=["mail.google.com"])
        for _ in range(FAVICON_PREFETCH_MIN_SECONDS):
            c._maybe_record_domain("chrome", 1, _NOW)

        self.assertEqual(calls, ["mail.google.com"])

    def test_prefetch_threshold_seeds_from_repo_across_restart(self) -> None:
        # 进程重启不该把已经攒够时长的站点打回从零、白等一分钟
        calls: list[str] = []
        c = _controller(record=True, domain="bilibili.com", prefetch=calls.append,
                        repo_seed={"bilibili.com": FAVICON_PREFETCH_MIN_SECONDS * 10})
        c._maybe_record_domain("chrome", 1, _NOW)

        self.assertEqual(calls, ["bilibili.com"])

    def test_prefetch_not_called_when_nothing_recorded(self) -> None:
        # 开关关 / 非浏览器前台 / domain 为空：不记账也不应联网
        for kw, fg in (
            ({"record": False, "domain": "bilibili.com"}, "chrome"),
            ({"record": True, "domain": "bilibili.com"}, "editor"),
            ({"record": True, "domain": ""}, "chrome"),
        ):
            with self.subTest(kw=kw, fg=fg):
                calls: list[str] = []
                c = _controller(prefetch=calls.append, **kw)
                c._maybe_record_domain(fg, 1, _NOW)
                self.assertEqual(calls, [])

    def test_prefetch_failure_does_not_break_recording(self) -> None:
        # 预取在 tick 线程上跑，任何异常都不能影响计时
        def boom(_domain: str) -> None:
            raise RuntimeError("network down")

        c = _controller(record=True, domain="bilibili.com", prefetch=boom)
        for _ in range(FAVICON_PREFETCH_MIN_SECONDS):
            c._maybe_record_domain("chrome", 1, _NOW)

        self.assertEqual(len(c.repo.domain_deltas), FAVICON_PREFETCH_MIN_SECONDS)

    def test_make_browser_watcher_is_noop_on_non_windows(self) -> None:
        # 本机（Linux）应返回 no-op watcher：所有方法安全、get_domain 恒 ""
        w = make_browser_watcher(log=None)
        w.start()
        w.set_active(True)
        self.assertEqual(w.get_domain(), "")
        w.stop()


if __name__ == "__main__":
    unittest.main()
