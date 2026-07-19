"""浏览器站点归并规则 —— host → 站点 key 的纯函数（零依赖、纯标准库）。

采集层存**完整子域名**（如 `space.bilibili.com`，仅剥一层 `www.`）。展示层默认把
子域名合并到**注册域名**（`space.bilibili.com` → `bilibili.com`），使规则变更可回溯
历史数据（合并只发生在读取展示，不改底层存储/采集）。

「独立统计名单」（`independent`）里的子站点不并入主域名，按**最长后缀**匹配归属
（`foo.mail.google.com` → `mail.google.com`）。

本模块只做纯字符串归并，不发网络、不访问文件系统，供 tests 直接测试。
"""
from __future__ import annotations

import re
from typing import Dict, Iterable

# 常见多段公共后缀（末两段命中 → 注册域取末三段）。非穷举，覆盖高频场景即可。
_MULTI_SUFFIXES: frozenset = frozenset(
    {
        "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn",
        "com.hk", "com.tw", "co.jp", "ne.jp", "or.jp",
        "co.uk", "org.uk", "ac.uk", "gov.uk",
        "com.au", "net.au", "org.au",
        "co.kr", "com.br", "com.mx", "co.in", "co.nz",
        "com.sg", "com.my",
        "github.io", "gitlab.io", "netlify.app", "vercel.app",
        "pages.dev", "web.app",
    }
)

_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def _norm(host: str) -> str:
    """归一化 host：去空白、转小写、去尾点。"""
    h = str(host or "").strip().lower()
    while h.endswith("."):
        h = h[:-1]
    return h


def registrable_domain(host: str) -> str:
    """host → 注册域名。

    - IPv4 / 单标签（无点）原样返回。
    - 末两标签命中多段公共后缀表 → 取末三标签；否则取末两标签。
    """
    h = _norm(host)
    if not h:
        return ""
    if _IPV4_RE.match(h):
        return h
    labels = h.split(".")
    if len(labels) <= 1:
        return h
    last2 = ".".join(labels[-2:])
    if last2 in _MULTI_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last2


def site_key(host: str, independent: Iterable[str]) -> str:
    """host → 站点 key。

    先在 `independent` 集合里做**最长后缀匹配**（`host == rule` 或
    `host.endswith("." + rule)`，多条命中取最长 rule），命中返回该 rule；
    否则返回 `registrable_domain(host)`。
    """
    h = _norm(host)
    if not h:
        return ""
    best = ""
    for rule in independent or ():
        r = _norm(rule)
        if not r:
            continue
        if h == r or h.endswith("." + r):
            if len(r) > len(best):
                best = r
    if best:
        return best
    return registrable_domain(h)


def merge_domain_usage(usage: Dict[str, int], independent) -> Dict[str, int]:
    """按 `site_key` 把 {host: 秒} 求和归并为 {site_key: 秒}。"""
    out: Dict[str, int] = {}
    for host, sec in (usage or {}).items():
        key = site_key(host, independent)
        if not key:
            continue
        out[key] = out.get(key, 0) + int(sec or 0)
    return out
