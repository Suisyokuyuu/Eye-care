from __future__ import annotations

from datetime import datetime, timedelta

from .context import ServiceContext


class SnapshotService:
    """Home for snapshot-related business logic extracted from Flask routes.

    Target routes:
    - GET /api/snapshot
    """

    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    def get_snapshot(self, *, query: dict) -> dict:
        """Build the snapshot payload for the main UI."""
        from eye_care.data.repository import DateRange
        from eye_care.diagnostics import diag
        from eye_care.api.common import _state_dict, _stats_for_date, _timebars_for_day, _timebars_for_range, API_VERSION

        controller = self.ctx.controller
        log = self.ctx.log

        try:
            from eye_care.diagnostics.debug_switch import is_debug_enabled as _is_debug_enabled

            if _is_debug_enabled():
                diag.emit("DIAG_SNAPSHOT_HIT", log, "snapshot hit", qs=dict(query or {}))
        except ImportError:
            log.debug("debug_switch not available for snapshot diagnostics")

        date_arg = query.get("date")
        range_arg = str(query.get("range", "day") or "day").strip().lower()
        if range_arg not in ("day", "week", "month", "custom"):
            range_arg = "day"

        if date_arg and isinstance(date_arg, str) and date_arg.strip():
            vm, extra = controller.snapshot_for_date(date_arg.strip())
        else:
            vm, extra = controller.snapshot_today()

        local_date = vm.local_date
        vm_dict = {"local_date": local_date, "daily_usage": vm.daily_usage}
        state = extra["state"]

        if bool((extra.get("debug") or {}).get("notify")):
            total = sum(int(v) for v in (vm.daily_usage or {}).values())
            log.info(
                "debug: snapshot range=%s date=%s total_s=%s idle_s=%s fg=%s rest=%s",
                range_arg,
                local_date,
                total,
                int(extra.get("idle_s", 0)),
                extra.get("fg") or "",
                extra.get("rest") or {},
            )

        dr = DateRange(start_local_date=local_date, end_local_date=local_date)
        usage_by_category = controller.repo.get_usage_range(dr, dim="category")
        stats = _stats_for_date(controller, local_date)

        range_start = range_end = local_date
        timebar_labels, timebar_keys, timebar_values = _timebars_for_day(controller, local_date)
        if range_arg == "week":
            dt = datetime.strptime(local_date, "%Y-%m-%d").date()
            start_d = dt - timedelta(days=dt.weekday())
            end_d = start_d + timedelta(days=6)
            range_start, range_end = start_d.isoformat(), end_d.isoformat()
            timebar_labels, timebar_keys, timebar_values = _timebars_for_range(controller, "week", range_start, range_end)
        elif range_arg == "month":
            from calendar import monthrange

            dt = datetime.strptime(local_date, "%Y-%m-%d").date()
            _, last = monthrange(dt.year, dt.month)
            range_start = dt.replace(day=1).isoformat()
            range_end = dt.replace(day=last).isoformat()
            timebar_labels, timebar_keys, timebar_values = _timebars_for_range(controller, "month", range_start, range_end)
        elif range_arg == "custom":
            from datetime import date as _date

            rs = query.get("range_start") or local_date
            re_ = query.get("range_end") or local_date
            try:
                _date.fromisoformat(rs)
                _date.fromisoformat(re_)
            except Exception:
                rs, re_ = local_date, local_date
            if re_ < rs:
                rs, re_ = re_, rs
            range_start, range_end = rs, re_
            timebar_labels, timebar_keys, timebar_values = _timebars_for_range(controller, "custom", range_start, range_end)

        range_usage_by_category = usage_by_category
        range_daily_usage = vm.daily_usage
        if range_arg in ("week", "month", "custom"):
            dr_range = DateRange(start_local_date=range_start, end_local_date=range_end)
            range_daily_usage = controller.repo.get_usage_range(dr_range, dim="app")
            range_usage_by_category = controller.repo.get_usage_range(dr_range, dim="category")

        blacklist = getattr(controller.cfg, "blacklist_apps", None) or []
        blacklist_set = set(blacklist) if isinstance(blacklist, (list, tuple)) else set()

        def _filter_usage(d, bl_set):
            if not isinstance(d, dict):
                return {}
            return {k: int(v or 0) for k, v in d.items() if k and k not in bl_set and int(v or 0) > 0}

        def _cat_agg(repo, app_usage):
            out = {}
            get_cat = getattr(repo, "get_app_category", lambda x: "其他")
            for app, sec in (app_usage or {}).items():
                cat = get_cat(app)
                out[cat] = int(out.get(cat, 0)) + int(sec)
            return out

        filtered_daily = _filter_usage(vm_dict.get("daily_usage") or {}, blacklist_set)
        filtered_range = _filter_usage(range_daily_usage or {}, blacklist_set)
        vm_dict["daily_usage"] = filtered_daily
        range_daily_usage = filtered_range
        usage_by_category = _cat_agg(controller.repo, filtered_daily)
        range_usage_by_category = _cat_agg(controller.repo, filtered_range)

        today_usage = controller.repo.get_daily_usage(local_date)
        today_total_seconds = sum(int(today_usage.get(k) or 0) for k in (today_usage or {}) if k not in blacklist_set)
        all_app_keys = set(range_daily_usage.keys()) if isinstance(range_daily_usage, dict) else set()
        all_app_keys.update(filtered_daily.keys())
        display_names = {k: controller.get_display_name(k) for k in all_app_keys} if hasattr(controller, "get_display_name") else {}

        payload = {
            "api_version": API_VERSION,
            "vm": vm_dict,
            "usage_by_category": usage_by_category,
            "range_daily_usage": range_daily_usage,
            "range_usage_by_category": range_usage_by_category,
            "app_paths": extra.get("app_paths") or {},
            "idle_s": int(extra.get("idle_s", 0)),
            "fg": extra.get("fg") or "",
            "state": _state_dict(state),
            "rest": extra.get("rest") or {},
            "hourly_usage": stats["stats_hourly"],
            "stats_total_seconds": stats["stats_total_seconds"],
            "stats_longest_focus_seconds": stats["stats_longest_focus_seconds"],
            "stats_rest_begin_count": stats["stats_rest_begin_count"],
            "stats_rest_complete_count": stats["stats_rest_complete_count"],
            "stats_rest_snooze_count": stats["stats_rest_snooze_count"],
            "stats_rest_rate_percent": stats["stats_rest_rate_percent"],
            "range_key": range_arg,
            "range_start": range_start,
            "range_end": range_end,
            "timebar_labels": timebar_labels,
            "timebar_keys": timebar_keys,
            "timebar_values": timebar_values,
            "today_total_seconds": today_total_seconds,
            "display_names": display_names,
        }

        rest = payload["rest"]
        if isinstance(rest, dict):
            payload["ui_should_prompt"] = bool(
                rest.get("due", False)
                and not rest.get("notified", False)
                and not bool(getattr(state, "is_paused", False))
                and not bool(getattr(state, "is_dnd", False))
            )

        if rest.get("due") and rest.get("work_s", 0) >= rest.get("threshold_s", 0):
            payload["rest"]["suggest_rest_text"] = "建议休息"
        else:
            payload["rest"]["suggest_rest_text"] = "暂无"

        return payload
