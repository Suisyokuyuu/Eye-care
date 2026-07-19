"""site_rules 纯函数测试：注册域 / 多段后缀 / 独立名单最长匹配 / IPv4 / 归并求和。"""
from __future__ import annotations

import unittest

from eye_care.utils.site_rules import (
    merge_domain_usage,
    registrable_domain,
    site_key,
)


class RegistrableDomainTests(unittest.TestCase):
    def test_basic_two_labels(self) -> None:
        self.assertEqual(registrable_domain("bilibili.com"), "bilibili.com")
        self.assertEqual(registrable_domain("space.bilibili.com"), "bilibili.com")
        self.assertEqual(registrable_domain("a.b.c.example.com"), "example.com")

    def test_multi_suffix(self) -> None:
        # 末两段命中多段后缀 → 取末三段
        self.assertEqual(registrable_domain("www.gov.cn"), "www.gov.cn")
        self.assertEqual(registrable_domain("foo.bar.gov.cn"), "bar.gov.cn")
        self.assertEqual(registrable_domain("user.github.io"), "user.github.io")
        self.assertEqual(registrable_domain("a.user.github.io"), "user.github.io")
        self.assertEqual(registrable_domain("shop.example.com.cn"), "example.com.cn")

    def test_multi_suffix_bare(self) -> None:
        # 恰好只有后缀本身（2 段）→ 原样返回
        self.assertEqual(registrable_domain("com.cn"), "com.cn")

    def test_ipv4_and_single_label(self) -> None:
        self.assertEqual(registrable_domain("127.0.0.1"), "127.0.0.1")
        self.assertEqual(registrable_domain("192.168.1.10"), "192.168.1.10")
        self.assertEqual(registrable_domain("localhost"), "localhost")

    def test_normalization(self) -> None:
        self.assertEqual(registrable_domain("Space.BiliBili.COM."), "bilibili.com")
        self.assertEqual(registrable_domain(""), "")
        self.assertEqual(registrable_domain(None), "")


class SiteKeyTests(unittest.TestCase):
    _IND = ["drive.google.com", "photos.google.com", "mail.google.com"]

    def test_default_merge_to_registrable(self) -> None:
        self.assertEqual(site_key("space.bilibili.com", []), "bilibili.com")
        self.assertEqual(site_key("www.baidu.com", self._IND), "baidu.com")
        # 未命中独立名单的 google 子域 → 并入 google.com
        self.assertEqual(site_key("accounts.google.com", self._IND), "google.com")
        self.assertEqual(site_key("google.com", self._IND), "google.com")

    def test_independent_exact_and_suffix(self) -> None:
        self.assertEqual(site_key("mail.google.com", self._IND), "mail.google.com")
        # 更深子域按最长后缀匹配归属该 rule
        self.assertEqual(site_key("foo.mail.google.com", self._IND), "mail.google.com")
        self.assertEqual(site_key("drive.google.com", self._IND), "drive.google.com")

    def test_longest_suffix_wins(self) -> None:
        ind = ["google.com", "mail.google.com"]
        # 同时命中 google.com 与 mail.google.com → 取最长
        self.assertEqual(site_key("x.mail.google.com", ind), "mail.google.com")
        self.assertEqual(site_key("news.google.com", ind), "google.com")

    def test_ipv4_site_key(self) -> None:
        self.assertEqual(site_key("10.0.0.2", self._IND), "10.0.0.2")


class MergeDomainUsageTests(unittest.TestCase):
    def test_merge_sums_by_site_key(self) -> None:
        usage = {
            "bilibili.com": 100,
            "space.bilibili.com": 50,
            "www.bilibili.com": 0,   # www 在采集层已剥；这里作原样键测试
            "google.com": 30,
            "mail.google.com": 40,
            "foo.mail.google.com": 5,
            "accounts.google.com": 7,
        }
        ind = ["mail.google.com"]
        out = merge_domain_usage(usage, ind)
        self.assertEqual(out["bilibili.com"], 150)
        self.assertEqual(out["google.com"], 37)          # google.com + accounts.google.com
        self.assertEqual(out["mail.google.com"], 45)     # mail + foo.mail
        self.assertNotIn("space.bilibili.com", out)
        self.assertNotIn("accounts.google.com", out)

    def test_empty(self) -> None:
        self.assertEqual(merge_domain_usage({}, []), {})
        self.assertEqual(merge_domain_usage(None, ["mail.google.com"]), {})


if __name__ == "__main__":
    unittest.main()
