from __future__ import annotations
from datetime import datetime, timezone

def format_seconds(sec: int) -> str:
    """User-facing duration text (Chinese, no h/m/s)."""
    sec = int(sec or 0)
    if sec < 0:
        sec = 0
    h = sec // 3600
    m = (sec % 3600) // 60
    if h > 0:
        return f"{h}小时{m}分钟"
    return f"{m}分钟"

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def local_date_today() -> str:
    # local date as YYYY-MM-DD
    return datetime.now().astimezone().date().isoformat()


def normalize_local_date(s: str) -> str:
    """将前端可能传来的错误格式（如 2026-0204）规范为 YYYY-MM-DD。"""
    s = (s or "").strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s  # 已是 YYYY-MM-DD
    # 2026-0204 -> 2026-02-04（缺月日间连字符）
    if len(s) == 9 and s[4] == "-" and s[5:7].isdigit() and s[7:9].isdigit():
        return f"{s[:5]}{s[5:7]}-{s[7:9]}"
    return s


def week_range_to_today() -> tuple[str, str]:
    """Return (monday, today) in local timezone as YYYY-MM-DD."""
    now = datetime.now().astimezone()
    today = now.date()
    monday = today.fromordinal(today.toordinal() - today.weekday())
    return monday.isoformat(), today.isoformat()
