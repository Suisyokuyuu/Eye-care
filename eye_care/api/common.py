"""
Shared helpers for API routes.
"""
from datetime import datetime, timedelta, timezone

API_VERSION = 1

# M5 检查更新：10 分钟内存缓存
_update_check_cache: dict = {}
_UPDATE_CACHE_TTL = 600


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _state_dict(state):
    return {
        "is_paused": bool(state.is_paused),
        "is_dnd": bool(state.is_dnd),
        "force_idle": bool(getattr(state, "force_idle", False)),
        "auto_idle": bool(getattr(state, "auto_idle", False)),
    }


def _parse_semver(s: str):
    s = (s or "").strip().lstrip("v")
    import re
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (0, 0, 0)


def _stats_for_date(controller, local_date: str):
    """从 repo 计算指定日期的屏幕时间统计与休息 KPI。"""
    from eye_care.data.repository import DateRange
    repo = controller.repo
    daily = repo.get_daily_usage(local_date)
    # 聚合保护: clamp 到 >= 0
    total_seconds = sum(max(0, int(v)) for v in daily.values())
    hourly = repo.get_hourly_usage(local_date)
    events = repo.get_events(local_date) if hasattr(repo, "get_events") else []
    longest_focus_s = 0
    rest_begin_count = 0
    rest_complete_count = 0
    rest_snooze_count = 0
    for ev in events:
        if getattr(ev, "kind", None) == "rest_begin":
            rest_begin_count += 1
            ack = (ev.payload or {}).get("ack_work_s")
            if ack is not None:
                longest_focus_s = max(longest_focus_s, int(ack))
        elif getattr(ev, "kind", None) == "rest_complete":
            rest_complete_count += 1
        elif getattr(ev, "kind", None) == "rest_snooze":
            rest_snooze_count += 1
            ack = (ev.payload or {}).get("ack_work_s")
            if ack is not None:
                longest_focus_s = max(longest_focus_s, int(ack))
    # 完成率 = done / (done + skip)，与 ui_adapter._calc_rest_kpis_for_range 口径一致；clamp 0~100；无事件时返回 None 供前端显示 —
    total_responded = rest_complete_count + rest_snooze_count
    if total_responded == 0:
        rest_rate_percent = None
    else:
        rate = rest_complete_count / total_responded
        rest_rate_percent = round(min(100.0, max(0.0, rate * 100.0)), 1)
    return {
        "stats_total_seconds": total_seconds,
        "stats_hourly": {int(h): int(s) for h, s in hourly.items()},
        "stats_longest_focus_seconds": longest_focus_s,
        "stats_rest_begin_count": rest_begin_count,
        "stats_rest_complete_count": rest_complete_count,
        "stats_rest_snooze_count": rest_snooze_count,
        "stats_rest_rate_percent": rest_rate_percent,
    }


def _timebars_for_day(controller, local_date: str):
    """按小时、按应用堆叠条数据：labels(0-23), keys(top5+其他), values(24 x 6)。"""
    repo = controller.repo
    daily = repo.get_daily_usage(local_date)
    top_items = sorted((daily or {}).items(), key=lambda x: int(x[1] or 0), reverse=True)[:5]
    keys = [k for k, _ in top_items if k] + ["其他"]
    if not keys:
        keys = ["其他"]
    bd = repo.get_hourly_breakdown(local_date, dim="app") if hasattr(repo, "get_hourly_breakdown") else {}
    rows = []
    for h in range(24):
        m = (bd.get(h) or bd.get(str(h)) or {})
        total = sum(int(v or 0) for v in m.values())
        vals = []
        top_sum = 0
        for k in keys:
            if k == "其他":
                vals.append(max(0, total - top_sum))
            else:
                s = int(m.get(k, 0) or 0)
                vals.append(s)
                top_sum += s
        rows.append(vals)
    return list(str(i) for i in range(24)), keys, rows


def _timebars_for_range(controller, range_key: str, start_day: str, end_day: str):
    """周/月：按天桶，keys 为范围内 top5+其他，values 为 days x keys。"""
    from datetime import datetime as dt_module, timedelta
    from eye_care.data.repository import DateRange
    repo = controller.repo
    dr = DateRange(start_local_date=start_day, end_local_date=end_day)
    usage = controller.repo.get_usage_range(dr, dim="app") or {}
    top_items = sorted(usage.items(), key=lambda x: int(x[1] or 0), reverse=True)[:5]
    keys = [k for k, _ in top_items if k] + ["其他"]
    if not keys:
        keys = ["其他"]
    days_list = []
    cur = dt_module.strptime(start_day, "%Y-%m-%d").date()
    end = dt_module.strptime(end_day, "%Y-%m-%d").date()
    while cur <= end:
        days_list.append(cur.isoformat())
        cur += timedelta(days=1)
    if range_key == "week":
        wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        labels = [wd[(dt_module.strptime(d, "%Y-%m-%d").weekday())] for d in days_list[:7]]
    else:
        labels = [str(dt_module.strptime(d, "%Y-%m-%d").day) + "日" for d in days_list]
    rows = []
    for d in days_list:
        day_usage = repo.get_daily_usage(d) if hasattr(repo, "get_daily_usage") else {}
        total = sum(int(day_usage.get(k, 0) or 0) for k in day_usage)
        vals = []
        top_sum = 0
        for k in keys:
            if k == "其他":
                vals.append(max(0, total - top_sum))
            else:
                s = int(day_usage.get(k, 0) or 0)
                vals.append(s)
                top_sum += s
        rows.append(vals)
    return labels, keys, rows
