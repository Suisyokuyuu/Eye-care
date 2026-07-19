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


if __name__ == "__main__":
    unittest.main()
