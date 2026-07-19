"""浏览器 domain 统计 —— URL → 注册域名 的纯函数提取（零依赖、纯标准库）。

隐私关键路径：**完整 URL 只应存在于本模块的函数调用栈内**，调用方拿到的永远是
剥离了 scheme/路径/查询串/userinfo/端口之后的主机名（domain），绝不落盘完整 URL。
"""

from __future__ import annotations

import re
import urllib.parse

# 浏览器 exe 主干名（小写，去 .exe）。与 json_wal_repo._cat_of 里"浏览器"启发式的
# 关键字口径对齐：chrome / msedge / firefox / brave / vivaldi / opera / chromium。
BROWSER_APP_SHORTS: frozenset = frozenset(
    {"chrome", "msedge", "firefox", "brave", "vivaldi", "opera", "chromium"}
)

# scheme 语法：字母开头，后跟 字母/数字/+/-/. ，直到冒号。
# 注意：主机名同样允许含点，故 `example.com:8080` 会被这条正则误当成 scheme。
# 下面用"scheme 名不含点"来区分真正的 scheme 与 host:port。
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")


def extract_domain(raw: str) -> str:
    """从浏览器地址栏/标题栏文本中提取注册域名（主机名），失败一律返回 ""。

    规则（详见项目说明）：
      - 拒收：空串 / None / 含空白（=正在输入的搜索词）/ scheme 非 http|https 的一切
        （chrome:// edge:// about: file:// view-source: data: javascript: 等）。
      - Chromium omnibox 常省略 scheme（显示 `example.com/path`）：无 scheme 时补 `//`
        前缀再 urlsplit，取 hostname（自动去 userinfo/端口、转小写）。
      - 去尾点；仅剥一层 `www.` 前缀。
      - hostname 必须含点且字符合法（ASCII 仅 字母/数字/连字符/点；非 ASCII 的 IDN 放行），
        借此拒掉裸搜索词；纯 IPv4 允许；localhost 无点→拒。
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s:
        return ""
    # 含任意空白字符 = 用户正在输入的搜索词，直接拒收
    if any(ch.isspace() for ch in s):
        return ""

    to_split = s
    m = _SCHEME_RE.match(s)
    if m:
        scheme = m.group(1)
        if "." not in scheme:
            # 真正的 scheme（scheme 名不含点）。只放行 http/https，其余内部协议全拒。
            if scheme.lower() not in ("http", "https"):
                return ""
            # http/https：直接交给 urlsplit（其自带 :// 或后续 netloc 解析）
        else:
            # 形如 example.com:8080 —— 这是省略了 scheme 的 host:port，补 // 再解析
            to_split = "//" + s
    else:
        # 无 scheme：补 // 让 urlsplit 走 netloc 解析
        to_split = "//" + s

    try:
        host = urllib.parse.urlsplit(to_split).hostname
    except Exception:
        return ""
    if not host:
        return ""

    host = host.strip()
    # 去尾点（FQDN 的规范尾点）
    while host.endswith("."):
        host = host[:-1]
    if not host:
        return ""

    # 仅剥一层 www. 前缀（www.baidu.com→baidu.com；www.www.x.com→www.x.com；docs.google.com 不动）
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""

    # 必须含点，否则是裸搜索词 / localhost 之类
    if "." not in host:
        return ""

    # 字符合法性：ASCII 段仅允许 字母/数字/连字符/点；非 ASCII（IDN 中文域名）按显示形态放行
    for ch in host:
        if ord(ch) < 128 and not (ch.isalnum() or ch in "-."):
            return ""

    return host
