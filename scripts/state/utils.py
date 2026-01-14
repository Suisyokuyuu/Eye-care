from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Dict


# =============================================================
# [State] Utils：日期聚合 & 时间格式化
# =============================================================

def seconds_to_hhmmss(seconds: int) -> str:
    """
    统一时间显示：X小时Y分钟
    - 小时为0：只显示 Y分钟
    - 不显示秒（精简发布版）
    """
    s = max(int(seconds), 0)
    total_m = s // 60
    h = total_m // 60
    m = total_m % 60

    if h > 0:
        return f"{h}小时{m}分钟"
    return f"{m}分钟"

def seconds_to_mmss(seconds: int) -> str:
    """倒计时显示：X分X秒；小于1分钟只显示秒"""
    s = max(int(seconds), 0)
    m = s // 60
    sec = s % 60
    if m <= 0:
        return f"{sec}秒"
    return f"{m}分{sec}秒"

def seconds_to_hm(sec: int) -> str:
    m = sec // 60
    h = m // 60
    m = m % 60

    if h > 0:
        return f"{h}小时{m}分钟"
    else:
        return f"{m}分钟"

def aggregate_range(by_day: Dict[str, Dict[str, int]], start: date, end: date) -> Dict[str, int]:
    agg = defaultdict(int)
    cur = start
    while cur <= end:
        day_key = cur.isoformat()
        day = by_day.get(day_key, {})
        for app, sec in day.items():
            agg[app] += int(sec)
        cur += timedelta(days=1)
    return dict(agg)


# =============================================================
# [Optional] 简单分类（可随时调整/扩展）
# =============================================================

def app_to_category(app_short_name: str) -> str:
    name = (app_short_name or "").lower()

    browser = {"chrome", "msedge", "edge", "firefox", "brave", "opera", "opera_gx"}
    if name in browser:
        return "浏览器"

    ide = {"code", "pycharm64", "idea64", "clion64", "devenv"}
    if name in ide:
        return "开发/IDE"

    office = {"winword", "excel", "powerpnt", "wps"}
    if name in office:
        return "办公"

    chat = {"wechat", "qq", "telegram", "discord", "slack"}
    if name in chat:
        return "社交/聊天"

    return "其他"
