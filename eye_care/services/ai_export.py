"""Stable AI report schema, shared by JSON export and Notion sync."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from eye_care.data.transfer import get_or_create_device_id
from eye_care.utils.site_rules import merge_domain_usage
from .device_identity import installation_id


def build_ai_export(controller, days: int, include_sites: bool, *, now=None) -> dict:
    now = now or datetime.now().astimezone()
    today = now.date()
    days = max(1, min(30, int(days)))
    dates = [(today - timedelta(days=i)).isoformat() for i in reversed(range(days))]
    snapshot = controller.repo.export_snapshot(dates)
    cfg = controller.cfg
    excluded = set(getattr(cfg, "blacklist_apps", []) or [])
    browser_enabled = bool(getattr(cfg, "record_browser_enabled", False))
    sites_allowed = bool(include_sites and browser_enabled)
    device = installation_id(controller.data_dir)
    source = get_or_create_device_id(controller.data_dir)
    device_name = str(getattr(cfg, "notion_device_name", "") or "").strip() or f"电脑 {device[:6]}"
    reports = []
    for day in dates:
        apps, sites, categories = Counter(), Counter(), Counter()
        for row in snapshot["minute_usage"].get(day, []):
            for app, seconds in row["apps"].items():
                if app not in excluded and int(seconds) > 0:
                    apps[app] += int(seconds)
        names = getattr(cfg, "app_display_overrides", {}) or {}
        app_rows = []
        for app, seconds in sorted(apps.items(), key=lambda item: (-item[1], item[0])):
            category = controller.repo.get_app_category(app)
            categories[category] += seconds
            app_rows.append({"app": app, "name": names.get(app, app), "category": category, "seconds": seconds})
        if sites_allowed:
            for row in snapshot["minute_domains"].get(day, []):
                sites.update({k: max(0, int(v)) for k, v in row["domains"].items()})
            sites = Counter(merge_domain_usage(dict(sites), getattr(cfg, "site_independent_hosts", []) or []))
        events = Counter(str(row.get("kind", "")) for row in snapshot["events"].get(day, []))
        reports.append({
            "schema": "eye_care_daily@2", "source": "EyE Care", "device_id": device,
            "device_name": device_name, "data_source_id": source, "local_date": day,
            "day_state": "today_so_far" if day == today.isoformat() else "past_date",
            "coverage": "recorded_activity_only; missing data does not mean zero computer use",
            "has_records": bool(apps or sites or events), "total_usage_seconds": sum(apps.values()),
            "apps": app_rows, "categories_seconds": dict(sorted(categories.items())),
            "sites_status": "included" if sites_allowed else ("not_requested" if browser_enabled else "recording_disabled"),
            "sites": [{"domain": k, "seconds": v} for k, v in sorted(sites.items(), key=lambda p: (-p[1], p[0]))],
            "rest_event_counts": {k: events[k] for k in ("rest_begin", "rest_complete", "rest_snooze")},
            "notes": ["Site time overlaps browser app time; do not add them together.",
                      "rest_complete includes automatic completion; it is not a reminder compliance score.",
                      "Different devices may overlap; their sum is not deduplicated personal screen time.",
                      "Copied historical data may exist on more than one device; filter by device when comparing."],
        })
    return {"schema": "eye_care_ai_export@2", "generated_at": now.astimezone(timezone.utc).isoformat(),
            "local_timezone": str(now.tzinfo), "range_start": dates[0], "range_end": dates[-1], "days": reports}
