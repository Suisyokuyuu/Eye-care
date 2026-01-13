from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Dict


# =============================================================
# [State] Utils：日期聚合 & 时间格式化
# =============================================================

def seconds_to_hhmmss(seconds: int) -> str:
    s = max(int(seconds), 0)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


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
