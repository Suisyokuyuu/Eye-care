"""Prepare Notion's daily calendar and weekly chart from device-level totals."""
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import unquote, urlencode

from .notion_client import NotionError, page_id, property_text, rich_text


DISPLAY_FIELDS = {
    "同日其他秒数": "number", "同周其他秒数": "number",
    "日历明细行": "checkbox", "周趋势汇总行": "checkbox",
}
READ_FIELDS = ("记录", "日期", "同步键", "总秒数", *DISPLAY_FIELDS)


def period_start(day):
    return day - timedelta(days=day.weekday())


def display_changes(rows):
    days, weeks = defaultdict(list), defaultdict(list)
    seen = set()
    for row in rows:
        props = row["properties"]
        key = property_text(row, "同步键")
        raw_date = (props["日期"].get("date") or {}).get("start")
        seconds = props["总秒数"].get("number")
        if not key or raw_date is None or seconds is None:
            continue
        if key in seen:
            raise NotionError("仓库里有重复的同步键，请先核对对应记录。")
        seen.add(key)
        day = date.fromisoformat(raw_date[:10])
        item = (day, key, int(seconds), row)
        days[day].append(item)
        weeks[period_start(day)].append(item)

    for items in weeks.values():
        week_total = sum(item[2] for item in items)
        # Keep the week anchored on its most recent day, including an ongoing day.
        latest = max(item[0] for item in items)
        week_anchor = min(days[latest], key=lambda item: item[1])[1]
        for day in sorted({item[0] for item in items}):
            by_device = sorted(days[day], key=lambda item: item[1])
            day_total = sum(item[2] for item in by_device)
            for index, (_, key, seconds, row) in enumerate(by_device):
                props = row["properties"]
                calendar = index == 0
                weekly = key == week_anchor
                desired = {
                    "同日其他秒数": day_total - seconds if calendar else None,
                    "同周其他秒数": week_total - seconds if weekly else None,
                    "日历明细行": not calendar, "周趋势汇总行": weekly,
                }
                updates = {}
                for name, value in desired.items():
                    kind = DISPLAY_FIELDS[name]
                    if props[name].get(kind) != value:
                        updates[name] = {kind: value}
                hours, minutes = divmod((day_total if calendar else seconds) // 60, 60)
                title = f"{hours}小时{minutes}分" if hours else f"{minutes}分"
                if property_text(row, "记录") != title:
                    updates["记录"] = {"title": rich_text(title)}
                if updates:
                    yield row["id"], updates


def refresh_calendar(client, source, schema, report_dates=(), changed_totals=None):
    """Only read aggregate fields, for complete weeks touched by this sync."""
    if any(schema.get(n, {}).get("type") != t for n, t in DISPLAY_FIELDS.items()):
        return 0
    filters = [{"property": "数据类型", "select": {"equals": "正式数据"}},
               {"property": "同步键", "rich_text": {"is_not_empty": True}}]
    if report_dates:
        first = period_start(date.fromisoformat(min(report_dates)))
        last = period_start(date.fromisoformat(max(report_dates))) + timedelta(days=6)
        filters.extend([{"property": "日期", "date": {"on_or_after": first.isoformat()}},
                        {"property": "日期", "date": {"on_or_before": last.isoformat()}}])
    fields = urlencode([("filter_properties", unquote(schema[n]["id"])) for n in READ_FIELDS])
    path = f"/data_sources/{page_id(source)}/query?{fields}"
    body = {"page_size": 100, "filter": {"and": filters}}
    rows = []
    seen = set()
    while True:
        result = client.request("POST", path, body)
        rows.extend(result["results"])
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
        if not cursor or cursor in seen:
            raise NotionError("看板汇总分页异常，请稍后再同步。")
        seen.add(cursor)
        body["start_cursor"] = cursor
    # Recently written pages can be missing or outdated in the query index.
    indexed = {row["id"]: row for row in rows}
    for target, seconds in (changed_totals or {}).items():
        row = indexed.get(target)
        if row is None or row["properties"]["总秒数"]["number"] != seconds:
            latest = client.request("GET", f"/pages/{page_id(target)}?{fields}")
            if (latest.get("in_trash") or latest.get("archived") or
                    latest.get("parent", {}).get("data_source_id") != page_id(source)):
                indexed.pop(target, None)
                continue
            indexed[target] = latest
    changes = list(display_changes(indexed.values()))
    for target, fields in changes:
        client.request("PATCH", f"/pages/{page_id(target)}", {"properties": fields})
    return len(changes)
