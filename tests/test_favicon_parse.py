from __future__ import annotations

import unittest

from eye_care.services.favicon_service import (
    parse_icon_links,
    _next_retry_delay_s,
    _should_retry,
)


class TestParseIconLinks(unittest.TestCase):
    def test_standard_icon_link(self):
        html = '<html><head><link rel="icon" href="/favicon.png"></head></html>'
        self.assertEqual(
            parse_icon_links(html, "https://example.com/"),
            ["https://example.com/favicon.png"],
        )

    def test_shortcut_icon(self):
        html = '<link rel="shortcut icon" href="/img/fav.ico">'
        self.assertEqual(
            parse_icon_links(html, "https://example.com/"),
            ["https://example.com/img/fav.ico"],
        )

    def test_apple_touch_icon(self):
        html = '<link rel="apple-touch-icon" href="/apple-touch.png">'
        self.assertEqual(
            parse_icon_links(html, "https://example.com/"),
            ["https://example.com/apple-touch.png"],
        )

    def test_relative_path_urljoin(self):
        html = '<link rel="icon" href="../assets/icon.png">'
        result = parse_icon_links(html, "https://example.com/sub/page/")
        self.assertEqual(result, ["https://example.com/sub/assets/icon.png"])

    def test_no_icon_tags_returns_empty(self):
        html = "<html><head><title>hi</title></head><body>hello</body></html>"
        self.assertEqual(parse_icon_links(html, "https://example.com/"), [])

    def test_empty_html_returns_empty(self):
        self.assertEqual(parse_icon_links("", "https://example.com/"), [])
        self.assertEqual(parse_icon_links(None, "https://example.com/"), [])

    def test_malformed_html_does_not_raise(self):
        html = '<link rel="icon" href="/a.png"<html><head><link rel=icon href=/b.png>'
        try:
            result = parse_icon_links(html, "https://example.com/")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"parse_icon_links raised on malformed HTML: {exc!r}")
        self.assertIsInstance(result, list)

    def test_rel_case_mixed(self):
        html = (
            '<link rel="Icon" href="/a.png">'
            '<link REL="SHORTCUT ICON" href="/b.png">'
            '<link rel="Apple-Touch-Icon" href="/c.png">'
        )
        result = parse_icon_links(html, "https://example.com/")
        self.assertEqual(
            result,
            [
                "https://example.com/a.png",
                "https://example.com/b.png",
                "https://example.com/c.png",
            ],
        )

    def test_multiple_links_preserve_order(self):
        html = (
            '<link rel="icon" href="/first.png">'
            '<link rel="stylesheet" href="/style.css">'
            '<link rel="icon" href="/second.png">'
        )
        result = parse_icon_links(html, "https://example.com/")
        self.assertEqual(
            result,
            ["https://example.com/first.png", "https://example.com/second.png"],
        )

    def test_non_icon_rel_ignored(self):
        html = '<link rel="stylesheet" href="/style.css"><link rel="canonical" href="/x">'
        self.assertEqual(parse_icon_links(html, "https://example.com/"), [])


class TestNegativeCacheRetry(unittest.TestCase):
    def test_next_retry_delay_grows_with_fail_count(self):
        self.assertEqual(_next_retry_delay_s(1), 6 * 3600)
        self.assertEqual(_next_retry_delay_s(2), 12 * 3600)
        self.assertEqual(_next_retry_delay_s(4), 24 * 3600)

    def test_next_retry_delay_caps_at_seven_days(self):
        seven_days = 7 * 24 * 3600
        # fail_count=28 -> 28*6h = 168h = 7 天，恰好触顶
        self.assertEqual(_next_retry_delay_s(28), seven_days)
        # 继续增大 fail_count 不应超过封顶
        self.assertEqual(_next_retry_delay_s(100), seven_days)
        self.assertEqual(_next_retry_delay_s(10_000), seven_days)

    def test_next_retry_delay_handles_zero_or_negative(self):
        # fail_count<=0 按至少 1 次处理，不应返回 0/负数
        self.assertEqual(_next_retry_delay_s(0), 6 * 3600)
        self.assertEqual(_next_retry_delay_s(-5), 6 * 3600)

    def test_should_retry_no_entry(self):
        self.assertTrue(_should_retry(None, now=1_000_000.0))
        self.assertTrue(_should_retry({}, now=1_000_000.0))

    def test_should_retry_not_yet_due(self):
        now = 1_000_000.0
        entry = {"ok": False, "fail_count": 1, "next_retry_ts": now + 100}
        self.assertFalse(_should_retry(entry, now))

    def test_should_retry_due(self):
        now = 1_000_000.0
        entry = {"ok": False, "fail_count": 1, "next_retry_ts": now - 1}
        self.assertTrue(_should_retry(entry, now))

    def test_should_retry_exactly_at_boundary(self):
        now = 1_000_000.0
        entry = {"ok": False, "fail_count": 1, "next_retry_ts": now}
        self.assertTrue(_should_retry(entry, now))

    def test_should_retry_missing_next_retry_ts(self):
        # 没有 next_retry_ts 字段（异常数据）视为可重试
        self.assertTrue(_should_retry({"ok": False, "fail_count": 1}, now=1_000_000.0))


class TestModuleImportWithoutPySide6(unittest.TestCase):
    def test_import_does_not_require_pyside6(self):
        # 本测试能跑到这里本身就证明模块级 import 没有硬依赖 PySide6
        # （本机 CI/开发环境无 PySide6）。再显式确认一次相关符号存在。
        import eye_care.services.favicon_service as mod

        self.assertTrue(hasattr(mod, "FaviconService"))
        self.assertTrue(hasattr(mod, "parse_icon_links"))
        self.assertTrue(callable(mod.parse_icon_links))

    def test_favicon_service_construction_does_not_touch_network_or_pyside6(self):
        import tempfile
        from pathlib import Path

        from eye_care.services.favicon_service import FaviconService

        with tempfile.TemporaryDirectory() as tmp:
            svc = FaviconService(Path(tmp))
            # 构造不应创建目录（惰性），也不应抛异常
            self.assertFalse((Path(tmp) / "domain_icons").exists())
            # 空/非法 domain 应安全返回空字符串，不发请求、不抛异常
            self.assertEqual(svc.get_icon(""), "")
            self.assertEqual(svc.get_icon(None), "")

    def test_get_icon_never_enqueues_a_fetch(self):
        """UI 渲染走 get_icon，必须只读本地缓存——打开统计页不产生任何网络请求。"""
        import tempfile
        from pathlib import Path

        from eye_care.services.favicon_service import FaviconService

        with tempfile.TemporaryDirectory() as tmp:
            svc = FaviconService(Path(tmp))
            for _ in range(10):
                self.assertEqual(svc.get_icon("never-fetched.com"), "")
            self.assertEqual(svc._queued, set())
            self.assertTrue(svc._queue.empty())
            self.assertIsNone(svc._worker)

    def test_prefetch_enqueues_once_then_skips_already_fetched(self):
        """prefetch 是唯一联网入口：没抓过才入队；已抓过（索引 ok + 文件在）直接跳过。"""
        import json
        import tempfile
        from pathlib import Path

        from eye_care.services.favicon_service import FaviconService

        with tempfile.TemporaryDirectory() as tmp:
            svc = FaviconService(Path(tmp))
            # 阻止真的起 worker 发请求：入队情况通过 _queued/_queue 观察
            svc._ensure_worker = lambda: None

            svc.prefetch("fresh.com")
            self.assertIn("fresh.com", svc._queued)
            # 已在队列里 → 重复调用不再入队
            svc.prefetch("fresh.com")
            self.assertEqual(list(svc._queue.queue).count("fresh.com"), 1)

            # 造一个「抓过并落盘」的域名：索引 ok + PNG 文件存在 → 永不再抓
            icons = Path(tmp) / "domain_icons"
            icons.mkdir(parents=True, exist_ok=True)
            (icons / "done.png").write_bytes(b"fake-png")
            (icons / "icon_index.json").write_text(json.dumps(
                {"done.com": {"file": "done.png", "ok": True, "ts": 1.0,
                              "fail_count": 0, "next_retry_ts": 0}}), encoding="utf-8")
            svc2 = FaviconService(Path(tmp))
            svc2._ensure_worker = lambda: None
            svc2.prefetch("done.com")
            self.assertEqual(svc2._queued, set())
            self.assertTrue(svc2._queue.empty())

    def test_prefetch_does_not_stat_disk_every_call(self):
        """prefetch 每拍（1s）被调用，已抓过的站点不得每次都 stat 磁盘。"""
        import json
        import pathlib
        import tempfile

        from eye_care.services.favicon_service import FaviconService

        with tempfile.TemporaryDirectory() as tmp:
            icons = pathlib.Path(tmp) / "domain_icons"
            icons.mkdir(parents=True, exist_ok=True)
            (icons / "a.png").write_bytes(b"fake-png")
            (icons / "icon_index.json").write_text(json.dumps(
                {"cached.com": {"file": "a.png", "ok": True, "ts": 1.0,
                                "fail_count": 0, "next_retry_ts": 0}}), encoding="utf-8")

            svc = FaviconService(pathlib.Path(tmp))
            svc._ensure_worker = lambda: None

            real_exists = pathlib.Path.exists
            calls = {"n": 0}

            def counting(self):
                calls["n"] += 1
                return real_exists(self)

            pathlib.Path.exists = counting
            try:
                for _ in range(60):
                    svc.prefetch("cached.com")
            finally:
                pathlib.Path.exists = real_exists

            # 索引惰性加载 1 次 + PNG 存在性校验 1 次，之后走 _verified 集合
            self.assertLessEqual(calls["n"], 2)
            self.assertEqual(svc._queued, set())

    def test_prefetch_respects_failure_backoff(self):
        """失败条目退避未到期 → 不重复抓；到期 → 允许再试一次。"""
        import json
        import tempfile
        import time
        from pathlib import Path

        from eye_care.services.favicon_service import FaviconService

        with tempfile.TemporaryDirectory() as tmp:
            icons = Path(tmp) / "domain_icons"
            icons.mkdir(parents=True, exist_ok=True)
            (icons / "icon_index.json").write_text(json.dumps({
                "cooling.com": {"file": "", "ok": False, "ts": 1.0, "fail_count": 1,
                                "next_retry_ts": time.time() + 3600},
                "expired.com": {"file": "", "ok": False, "ts": 1.0, "fail_count": 1,
                                "next_retry_ts": time.time() - 1},
            }), encoding="utf-8")
            svc = FaviconService(Path(tmp))
            svc._ensure_worker = lambda: None

            svc.prefetch("cooling.com")
            self.assertEqual(svc._queued, set())

            svc.prefetch("expired.com")
            self.assertIn("expired.com", svc._queued)

    def test_clear_removes_cache_and_allows_refetch(self):
        """清除图标缓存 → PNG/索引/内存全清，且该站点重新变成「可抓」。"""
        import json
        import pathlib
        import tempfile

        from eye_care.services.favicon_service import FaviconService

        with tempfile.TemporaryDirectory() as tmp:
            icons = pathlib.Path(tmp) / "domain_icons"
            icons.mkdir(parents=True, exist_ok=True)
            (icons / "a.png").write_bytes(b"fake-png")
            (icons / "icon_index.json").write_text(json.dumps(
                {"x.com": {"file": "a.png", "ok": True, "ts": 1.0,
                           "fail_count": 0, "next_retry_ts": 0}}), encoding="utf-8")

            svc = FaviconService(pathlib.Path(tmp))
            svc._ensure_worker = lambda: None
            svc.prefetch("x.com")
            self.assertEqual(svc._queued, set())          # 清除前：已抓过，不抓

            self.assertTrue(svc.clear("x.com"))
            self.assertFalse((icons / "a.png").exists())  # PNG 已删
            self.assertNotIn("x.com", json.loads(
                (icons / "icon_index.json").read_text(encoding="utf-8")))  # 索引条目已删
            self.assertEqual(svc.get_icon("x.com"), "")   # 读不到了，UI 走首字母兜底

            svc.prefetch("x.com")
            self.assertIn("x.com", svc._queued)           # 清除后：重新可抓

    def test_clear_resets_failure_backoff(self):
        """清除也能解掉负缓存——抓失败的站点可以立刻重试，不用等 6 小时。"""
        import json
        import pathlib
        import tempfile
        import time

        from eye_care.services.favicon_service import FaviconService

        with tempfile.TemporaryDirectory() as tmp:
            icons = pathlib.Path(tmp) / "domain_icons"
            icons.mkdir(parents=True, exist_ok=True)
            (icons / "icon_index.json").write_text(json.dumps(
                {"f.com": {"file": "", "ok": False, "ts": 1.0, "fail_count": 3,
                           "next_retry_ts": time.time() + 7 * 24 * 3600}}), encoding="utf-8")

            svc = FaviconService(pathlib.Path(tmp))
            svc._ensure_worker = lambda: None
            svc.prefetch("f.com")
            self.assertEqual(svc._queued, set())          # 退避中，不抓

            svc.clear("f.com")
            svc.prefetch("f.com")
            self.assertIn("f.com", svc._queued)           # 退避已解除

    def test_clear_unknown_domain_is_safe(self):
        import pathlib
        import tempfile

        from eye_care.services.favicon_service import FaviconService

        with tempfile.TemporaryDirectory() as tmp:
            svc = FaviconService(pathlib.Path(tmp))
            self.assertFalse(svc.clear("never-seen.com"))
            self.assertFalse(svc.clear(""))
            self.assertFalse(svc.clear(None))

    def test_stop_prevents_further_fetches(self):
        """stop() 后不得再入队/复活 worker。

        关闭时 controller 的 tick 线程可能还在预取，不封死就会在退出途中再发一次网络请求。
        """
        import tempfile
        from pathlib import Path

        from eye_care.services.favicon_service import FaviconService

        with tempfile.TemporaryDirectory() as tmp:
            svc = FaviconService(Path(tmp))
            svc.stop(timeout_s=0.1)

            svc.prefetch("example.com")
            self.assertNotIn("example.com", svc._queued)
            # 队列里只该有 stop() 自己放的唤醒哨兵 None，没有待抓 domain
            drained = []
            while not svc._queue.empty():
                drained.append(svc._queue.get_nowait())
            self.assertEqual(drained, [None])
            self.assertFalse(svc._worker is not None and svc._worker.is_alive())


if __name__ == "__main__":
    unittest.main()
