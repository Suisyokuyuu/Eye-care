from __future__ import annotations

import unittest

from eye_care.utils.url_domain import BROWSER_APP_SHORTS, extract_domain


class ExtractDomainTests(unittest.TestCase):
    def test_full_https_url(self) -> None:
        self.assertEqual(extract_domain("https://example.com/path?q=1"), "example.com")

    def test_http_with_userinfo_and_port(self) -> None:
        # userinfo + 端口都应被剥离
        self.assertEqual(extract_domain("http://user:pw@example.com:8080/x"), "example.com")

    def test_no_scheme_omnibox_form(self) -> None:
        # Chromium omnibox 常省略 scheme
        self.assertEqual(extract_domain("example.com/path"), "example.com")

    def test_bare_host_no_scheme(self) -> None:
        self.assertEqual(extract_domain("example.com"), "example.com")

    def test_host_port_no_scheme(self) -> None:
        # host:port（含点主机）无 scheme —— 补 // 后正确解析
        self.assertEqual(extract_domain("example.com:8080/path"), "example.com")

    def test_www_stripped_one_level(self) -> None:
        self.assertEqual(extract_domain("www.baidu.com"), "baidu.com")

    def test_www_only_one_level(self) -> None:
        # 仅剥一层 www.
        self.assertEqual(extract_domain("www.www.x.com"), "www.x.com")

    def test_subdomain_preserved(self) -> None:
        # 非 www 子域保留
        self.assertEqual(extract_domain("docs.google.com"), "docs.google.com")

    def test_case_folded(self) -> None:
        self.assertEqual(extract_domain("WWW.Baidu.COM"), "baidu.com")

    def test_trailing_dot_removed(self) -> None:
        self.assertEqual(extract_domain("example.com."), "example.com")

    def test_ipv4_allowed(self) -> None:
        self.assertEqual(extract_domain("192.168.1.1"), "192.168.1.1")

    def test_ipv4_with_port(self) -> None:
        self.assertEqual(extract_domain("192.168.1.1:8080"), "192.168.1.1")

    def test_ipv4_full_url(self) -> None:
        self.assertEqual(extract_domain("https://192.168.0.1:3000/"), "192.168.0.1")

    def test_idn_ascii_preserved(self) -> None:
        # IDN 中文域名按显示形态保留
        self.assertEqual(extract_domain("中文.com"), "中文.com")

    def test_idn_full_url(self) -> None:
        self.assertEqual(extract_domain("http://例え.jp/a"), "例え.jp")

    # ---- 拒收路径 ----
    def test_chrome_internal_rejected(self) -> None:
        self.assertEqual(extract_domain("chrome://settings"), "")

    def test_edge_internal_rejected(self) -> None:
        self.assertEqual(extract_domain("edge://flags"), "")

    def test_about_rejected(self) -> None:
        self.assertEqual(extract_domain("about:blank"), "")

    def test_file_rejected(self) -> None:
        self.assertEqual(extract_domain("file:///C:/foo"), "")

    def test_view_source_rejected(self) -> None:
        self.assertEqual(extract_domain("view-source:https://a.com"), "")

    def test_data_rejected(self) -> None:
        self.assertEqual(extract_domain("data:text/html,x"), "")

    def test_javascript_rejected(self) -> None:
        self.assertEqual(extract_domain("javascript:void(0)"), "")

    def test_bare_search_word_rejected(self) -> None:
        # 裸搜索词（无点）
        self.assertEqual(extract_domain("foo"), "")

    def test_whitespace_search_rejected(self) -> None:
        # 含空白 = 正在输入的搜索词
        self.assertEqual(extract_domain("how to code"), "")

    def test_localhost_rejected(self) -> None:
        # localhost 无点
        self.assertEqual(extract_domain("localhost"), "")

    def test_localhost_port_rejected(self) -> None:
        self.assertEqual(extract_domain("localhost:3000"), "")

    def test_empty_and_blank_rejected(self) -> None:
        self.assertEqual(extract_domain(""), "")
        self.assertEqual(extract_domain("   "), "")

    def test_none_rejected(self) -> None:
        self.assertEqual(extract_domain(None), "")  # type: ignore[arg-type]

    def test_browser_shorts_content(self) -> None:
        # 与 json_wal_repo._cat_of 浏览器口径对齐
        self.assertEqual(
            BROWSER_APP_SHORTS,
            frozenset({"chrome", "msedge", "firefox", "brave", "vivaldi", "opera", "chromium"}),
        )


if __name__ == "__main__":
    unittest.main()
