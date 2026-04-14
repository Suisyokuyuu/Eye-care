from __future__ import annotations

from calendar import monthrange
from datetime import date as local_date
from datetime import datetime, timedelta

from eye_care.api.common import API_VERSION, _iso_z
from eye_care.config.store import save_config
from eye_care.data.repository import DateRange

from .context import ServiceContext, ServiceError


class StatsService:
    """Home for app-detail, app-list, blacklist, and calendar routes.

    Target routes:
    - GET /api/app_details
    - GET /api/apps_list
    - POST /api/app_settings
    - POST /api/app_exclude
    - GET /api/blacklist
    - POST /api/blacklist_remove
    - GET /api/calendar_month
    """

    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    def get_app_details(self, *, query: dict) -> dict:
        controller = self.ctx.controller
        repo = controller.repo
        cfg = controller.cfg

        app_key = str((query or {}).get("app") or "").strip().lower()
        if not app_key:
            raise ServiceError("missing app", code="bad_request", http_status=400)

        date_arg = str((query or {}).get("date") or "").strip()
        if not date_arg:
            date_arg = datetime.now().astimezone().date().isoformat()
        try:
            end_date = datetime.strptime(date_arg, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ServiceError("invalid date", code="bad_request", http_status=400) from exc

        days = int((query or {}).get("days") or 7)
        days = max(1, min(days, 90))
        range_start = (end_date - timedelta(days=days - 1)).isoformat()
        range_end = date_arg
        dr_range = DateRange(start_local_date=range_start, end_local_date=range_end)
        dr_day = DateRange(start_local_date=date_arg, end_local_date=date_arg)

        daily_seconds = {}
        for offset in range(days):
            current = (end_date - timedelta(days=offset)).isoformat()
            daily_usage = repo.get_daily_usage(current) or {}
            daily_seconds[current] = int(daily_usage.get(app_key, 0) or 0)
        total_seconds = sum(daily_seconds.values())

        hourly_bd = repo.get_hourly_breakdown(date_arg, dim="app")
        hourly_seconds_for_date = {str(hour): int((hourly_bd.get(hour) or {}).get(app_key, 0) or 0) for hour in range(24)}

        segments = repo.get_timeline_segments(app_key, dr_day)
        timeline_segments = [
            {"start_utc": _iso_z(segment.start_utc), "end_utc": _iso_z(segment.end_utc), "seconds": segment.seconds, "local_date": segment.local_date}
            for segment in segments
        ]

        last_dt = repo.get_app_last_active_utc(app_key, dr_range)
        last_active_utc = _iso_z(last_dt) if last_dt else None

        display_name = getattr(controller, "get_display_name", lambda x: (x or "").rstrip(".exe") or x)(app_key)
        overrides = getattr(cfg, "app_display_overrides", None) or {}
        display_name_override = overrides.get(app_key, "")
        category = getattr(repo, "get_app_category", lambda x: "")(app_key)
        auto_dnd = getattr(cfg, "app_auto_dnd_on_focus", None)
        auto_dnd_on_focus = (app_key in auto_dnd) if isinstance(auto_dnd, set) else bool((auto_dnd or {}).get(app_key))

        return {
            "api_version": API_VERSION,
            "app": app_key,
            "range_start": range_start,
            "range_end": range_end,
            "total_seconds": total_seconds,
            "daily_seconds": daily_seconds,
            "hourly_seconds_for_date": hourly_seconds_for_date,
            "timeline_segments": timeline_segments,
            "last_active_utc": last_active_utc,
            "special_settings": {},
            "display_name": display_name,
            "display_name_override": display_name_override,
            "category": category or "other",
            "auto_dnd_on_focus": auto_dnd_on_focus,
        }

    def get_apps_list(self) -> dict:
        controller = self.ctx.controller
        repo = controller.repo
        cfg = controller.cfg
        range_end = datetime.now().astimezone().date().isoformat()
        range_start = (datetime.now().astimezone() - timedelta(days=90)).strftime("%Y-%m-%d")
        dr = DateRange(start_local_date=range_start, end_local_date=range_end)
        by_app = repo.get_usage_range(dr, dim="app") if hasattr(repo, "get_usage_range") else {}
        app_keys = set(by_app.keys()) if isinstance(by_app, dict) else set()
        if not app_keys and hasattr(repo, "get_daily_usage"):
            for d in range(30):
                day = (datetime.now().astimezone() - timedelta(days=d)).strftime("%Y-%m-%d")
                day_usage = repo.get_daily_usage(day) or {}
                app_keys.update(day_usage.keys())
        repo_categories = repo.get_app_categories() if hasattr(repo, "get_app_categories") else {}
        if isinstance(repo_categories, dict):
            app_keys.update(repo_categories.keys())

        category_overrides = getattr(cfg, "app_category_overrides", {}) or {}
        if isinstance(category_overrides, dict):
            app_keys.update(category_overrides.keys())

        display_overrides = getattr(cfg, "app_display_overrides", {}) or {}
        if isinstance(display_overrides, dict):
            app_keys.update(display_overrides.keys())

        blacklist = getattr(cfg, "blacklist_apps", None) or []
        blacklist_set = set(blacklist) if isinstance(blacklist, (list, tuple)) else set()
        app_keys = {k for k in app_keys if k and k not in blacklist_set}
        items = []
        get_display = getattr(controller, "get_display_name", lambda x: (x or "").replace(".exe", "") or x)
        get_cat = getattr(repo, "get_app_category", lambda x: "")
        for app_short in sorted(app_keys):
            items.append({
                "app_short": app_short,
                "display_name": get_display(app_short),
                "category": get_cat(app_short),
            })
        return {"api_version": API_VERSION, "apps": items}

    def update_app_settings(self, *, body: dict) -> dict:
        controller = self.ctx.controller
        cfg = controller.cfg
        data = body or {}
        app_short = str(data.get("app_short") or "").strip()
        if not app_short:
            raise ServiceError("app_short required", code="bad_request", http_status=400)

        if "category" in data and data.get("category") is not None:
            overrides = getattr(cfg, "app_category_overrides", None) or {}
            overrides = dict(overrides)
            overrides[app_short] = str(data.get("category", "")).strip()
            cfg.app_category_overrides = overrides
        if "display_name" in data:
            disp = getattr(cfg, "app_display_overrides", None) or {}
            disp = dict(disp)
            alias = str(data.get("display_name") or "").strip()
            if alias:
                disp[app_short] = alias
            else:
                disp.pop(app_short, None)
            cfg.app_display_overrides = disp
        if "auto_dnd_on_focus" in data:
            auto_dnd = getattr(cfg, "app_auto_dnd_on_focus", None)
            if isinstance(auto_dnd, dict):
                auto_dnd = dict(auto_dnd)
                auto_dnd[app_short] = bool(data.get("auto_dnd_on_focus"))
                cfg.app_auto_dnd_on_focus = auto_dnd
            else:
                auto_dnd = set(auto_dnd) if auto_dnd else set()
                if data.get("auto_dnd_on_focus"):
                    auto_dnd.add(app_short)
                else:
                    auto_dnd.discard(app_short)
                cfg.app_auto_dnd_on_focus = auto_dnd

        save_config(controller.cfg_path, cfg)
        if hasattr(controller.repo, "set_category_overrides"):
            controller.repo.set_category_overrides(getattr(cfg, "app_category_overrides", {}) or {})
        return {"ok": True, "api_version": API_VERSION, "app_short": app_short}

    def exclude_app(self, *, app_short: str) -> dict:
        controller = self.ctx.controller
        cfg = controller.cfg
        app_short = str(app_short or "").strip()
        if not app_short:
            raise ServiceError("app_short required", code="bad_request", http_status=400)

        blacklist = getattr(cfg, "blacklist_apps", None) or []
        blacklist = list(blacklist) if isinstance(blacklist, (list, tuple)) else []
        if app_short not in blacklist:
            blacklist.append(app_short)
        cfg.blacklist_apps = list(sorted(set(blacklist)))

        controller.repo.delete_app_data(app_short)
        self.ctx.log.info("blacklist persist: app_exclude app_short=%s, count=%d", app_short, len(cfg.blacklist_apps))
        save_config(controller.cfg_path, cfg)
        return {"ok": True, "api_version": API_VERSION, "app_short": app_short}

    def get_blacklist(self) -> dict:
        controller = self.ctx.controller
        cfg = controller.cfg
        blacklist = getattr(cfg, "blacklist_apps", None) or []
        blacklist = list(blacklist) if isinstance(blacklist, (list, tuple)) else []
        get_display = getattr(controller, "get_display_name", lambda x: (x or "").replace(".exe", "") or x)
        items = [{"app_short": a, "display_name": get_display(a)} for a in sorted(set(blacklist))]
        return {"api_version": API_VERSION, "apps": items}

    def remove_from_blacklist(self, *, app_short: str) -> dict:
        controller = self.ctx.controller
        cfg = controller.cfg
        app_short = str(app_short or "").strip()
        if not app_short:
            raise ServiceError("app_short required", code="bad_request", http_status=400)

        blacklist = getattr(cfg, "blacklist_apps", None) or []
        blacklist = list(blacklist) if isinstance(blacklist, (list, tuple)) else []
        if app_short in blacklist:
            blacklist.remove(app_short)
        cfg.blacklist_apps = list(sorted(set(blacklist)))

        self.ctx.log.info("blacklist persist: blacklist_remove app_short=%s, count=%d", app_short, len(cfg.blacklist_apps))
        save_config(controller.cfg_path, cfg)
        return {"ok": True, "api_version": API_VERSION, "app_short": app_short}

    def get_calendar_month(self, *, year: int, month: int) -> dict:
        controller = self.ctx.controller
        _, last_day = monthrange(year, month)
        repo = controller.repo

        days_with_data = []
        for day in range(1, last_day + 1):
            ld = local_date(year, month, day).isoformat()
            day_usage = repo.get_daily_usage(ld) if hasattr(repo, "get_daily_usage") else {}
            total = 0
            if day_usage:
                for value in day_usage.values():
                    if value is None:
                        continue
                    if isinstance(value, bool):
                        total += int(value)
                        continue
                    if isinstance(value, int):
                        total += value
                        continue
                    if isinstance(value, float):
                        if value == value and value not in (float("inf"), float("-inf")):
                            total += int(value)
                        continue
                    if isinstance(value, str):
                        stripped = value.strip()
                        if stripped and stripped.lstrip("+-").isdigit():
                            total += int(stripped)
            if total > 0:
                days_with_data.append(ld)

        return {
            "api_version": API_VERSION,
            "year": year,
            "month": month,
            "days_with_data": days_with_data,
        }
