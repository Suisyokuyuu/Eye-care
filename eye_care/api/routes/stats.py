"""
Stats routes for app usage data.
"""
from collections import OrderedDict
from datetime import datetime, timedelta

from flask import Flask, jsonify, request

from ...config.store import save_config
from ...diagnostics import log_exception_summary
from ...data.repository import DateRange
from ..common import API_VERSION

# LRU 缓存：app_details API 响应缓存，最大条目数 100
_app_details_cache: OrderedDict[tuple, dict] = OrderedDict()
_APP_DETAILS_CACHE_MAX_SIZE = 100


def _invalidate_app_details_cache(app_key: str = None, local_date: str = None) -> None:
    """失效 app_details 缓存。
    
    Args:
        app_key: 如果提供，只失效该 app 的缓存；否则失效所有缓存
        local_date: 如果提供，只失效涉及该日期的缓存
    """
    global _app_details_cache
    if app_key is None and local_date is None:
        # 失效所有缓存
        _app_details_cache.clear()
        return
    
    # 失效匹配的缓存条目
    keys_to_remove = []
    for key in _app_details_cache:
        key_app, key_range_start, key_range_end, key_date = key
        should_remove = False
        if app_key is not None and key_app == app_key:
            should_remove = True
        if local_date is not None:
            # 检查日期是否在范围内
            try:
                date_obj = datetime.strptime(local_date, "%Y-%m-%d").date()
                range_start = datetime.strptime(key_range_start, "%Y-%m-%d").date()
                range_end = datetime.strptime(key_range_end, "%Y-%m-%d").date()
                if range_start <= date_obj <= range_end:
                    should_remove = True
            except (ValueError, TypeError):
                pass
        if should_remove:
            keys_to_remove.append(key)
    
    for key in keys_to_remove:
        _app_details_cache.pop(key, None)


def register_stats_routes(app: Flask, controller, log):
    @app.route("/api/app_details", methods=["GET"])
    def app_details():
        """M1：app_short 入参；date 缺省=今天；days 默认 7。hourly/segments 仅单日 date。"""
        try:
            from ..common import _iso_z
            app_key = (request.args.get("app") or "").strip().lower()
            if not app_key:
                return jsonify({"error": "missing app", "code": "bad_request"}), 400
            date_arg = (request.args.get("date") or "").strip()
            if not date_arg:
                date_arg = datetime.now().astimezone().date().isoformat()
            try:
                end_d = datetime.strptime(date_arg, "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": "invalid date", "code": "bad_request"}), 400
            days = int(request.args.get("days") or 7)
            days = max(1, min(days, 90))  # 限制最大 90 天，提升性能
            range_start = (end_d - timedelta(days=days - 1)).isoformat()
            range_end = date_arg
            repo = controller.repo
            dr_range = DateRange(start_local_date=range_start, end_local_date=range_end)
            dr_day = DateRange(start_local_date=date_arg, end_local_date=date_arg)

            # LRU 缓存：检查缓存
            cache_key = (app_key, range_start, range_end, date_arg)
            if cache_key in _app_details_cache:
                # 命中缓存，移到末尾（LRU）
                _app_details_cache.move_to_end(cache_key)
                return jsonify(_app_details_cache[cache_key])

            daily_seconds = {}
            for d in range(days):
                cur = (end_d - timedelta(days=d)).isoformat()
                daily_seconds[cur] = int(repo.get_daily_usage(cur).get(app_key, 0) or 0)
            total_seconds = sum(daily_seconds.values())

            hourly_bd = repo.get_hourly_breakdown(date_arg, dim="app")
            hourly_seconds_for_date = {str(h): int((hourly_bd.get(h) or {}).get(app_key, 0) or 0) for h in range(24)}

            segments = repo.get_timeline_segments(app_key, dr_day)
            timeline_segments = [
                {"start_utc": _iso_z(s.start_utc), "end_utc": _iso_z(s.end_utc), "seconds": s.seconds, "local_date": s.local_date}
                for s in segments
            ]

            last_dt = repo.get_app_last_active_utc(app_key, dr_range)
            last_active_utc = _iso_z(last_dt) if last_dt else None

            # M4 详情页设置区块预填
            cfg = controller.cfg
            display_name = getattr(controller, "get_display_name", lambda x: (x or "").rstrip(".exe") or x)(app_key)
            overrides = getattr(cfg, "app_display_overrides", None) or {}
            display_name_override = overrides.get(app_key, "")
            category = getattr(repo, "get_app_category", lambda x: "")(app_key)
            auto_dnd = getattr(cfg, "app_auto_dnd_on_focus", None)
            auto_dnd_on_focus = (app_key in auto_dnd) if isinstance(auto_dnd, set) else bool((auto_dnd or {}).get(app_key))

            response_data = {
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

            # 写入缓存（LRU）
            _app_details_cache[cache_key] = response_data
            if len(_app_details_cache) > _APP_DETAILS_CACHE_MAX_SIZE:
                _app_details_cache.popitem(last=False)  # 移除最旧的条目

            return jsonify(response_data)
        except Exception as e:
            log.exception("app_details failed")
            return jsonify({"error": str(e), "code": "data_error"}), 500

    @app.route("/api/apps_list", methods=["GET"])
    def apps_list():
        """已记录应用列表：app_short, display_name, category（用于应用设置页卡片）。"""
        try:
            repo = controller.repo
            cfg = controller.cfg
            # 近期范围取 key 集合（90 天；若为空则兜底扫 30 天逐日 union）
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
            # 兜底：分类表 / overrides 里出现过的 app 也并入
            repo_categories = repo.get_app_categories() if hasattr(repo, "get_app_categories") else {}
            if isinstance(repo_categories, dict):
                app_keys.update(repo_categories.keys())

            category_overrides = getattr(cfg, "app_category_overrides", {}) or {}
            if isinstance(category_overrides, dict):
                app_keys.update(category_overrides.keys())

            display_overrides = getattr(cfg, "app_display_overrides", {}) or {}
            if isinstance(display_overrides, dict):
                app_keys.update(display_overrides.keys())
            # 排除黑名单
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
            return jsonify({"api_version": API_VERSION, "apps": items})
        except Exception as e:
            log.exception("apps_list failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/app_settings", methods=["POST"])
    def app_settings():
        """保存单应用：category / display_name / auto_dnd_on_focus。点"应用/保存"时调用。"""
        try:
            data = request.get_json() or {}
            app_short = (data.get("app_short") or "").strip()
            if not app_short:
                return jsonify({"error": "app_short required"}), 400
            cfg = controller.cfg
            if "category" in data and data.get("category") is not None:
                overrides = getattr(cfg, "app_category_overrides", None) or {}
                overrides = dict(overrides)
                overrides[app_short] = str(data.get("category", "")).strip()
                cfg.app_category_overrides = overrides
            if "display_name" in data:
                disp = getattr(cfg, "app_display_overrides", None) or {}
                disp = dict(disp)
                alias = (data.get("display_name") or "").strip()
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
            # 清除 app_details 缓存，确保重新打开时显示最新分类
            _invalidate_app_details_cache(app_key=app_short)
            return jsonify({"ok": True, "api_version": API_VERSION})
        except Exception as e:
            log.exception("app_settings failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/app_exclude", methods=["POST"])
    def app_exclude():
        """排除该应用计时：加入黑名单 + 删除历史数据。"""
        try:
            data = request.get_json() or {}
            app_short = (data.get("app_short") or "").strip()
            if not app_short:
                return jsonify({"error": "app_short required"}), 400
            cfg = controller.cfg
            blacklist = getattr(cfg, "blacklist_apps", None) or []
            blacklist = list(blacklist) if isinstance(blacklist, (list, tuple)) else []
            if app_short and app_short not in blacklist:
                blacklist.append(app_short)
            cfg.blacklist_apps = list(sorted(set(blacklist)))
            controller.repo.delete_app_data(app_short)
            log.info("blacklist persist: app_exclude app_short=%s, count=%d", app_short, len(cfg.blacklist_apps))
            save_config(controller.cfg_path, cfg)
            return jsonify({"ok": True, "api_version": API_VERSION})
        except Exception as e:
            log.exception("app_exclude failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/blacklist", methods=["GET"])
    def blacklist_get():
        """黑名单列表：app_short, display_name。"""
        try:
            cfg = controller.cfg
            blacklist = getattr(cfg, "blacklist_apps", None) or []
            blacklist = list(blacklist) if isinstance(blacklist, (list, tuple)) else []
            get_display = getattr(controller, "get_display_name", lambda x: (x or "").replace(".exe", "") or x)
            items = [{"app_short": a, "display_name": get_display(a)} for a in sorted(set(blacklist))]
            return jsonify({"api_version": API_VERSION, "apps": items})
        except Exception as e:
            log.exception("blacklist get failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/blacklist_remove", methods=["POST"])
    def blacklist_remove():
        """从黑名单移除某 app，恢复未来记录。"""
        try:
            data = request.get_json() or {}
            app_short = (data.get("app_short") or "").strip()
            if not app_short:
                return jsonify({"error": "app_short required"}), 400
            cfg = controller.cfg
            blacklist = getattr(cfg, "blacklist_apps", None) or []
            blacklist = list(blacklist) if isinstance(blacklist, (list, tuple)) else []
            if app_short in blacklist:
                blacklist.remove(app_short)
            cfg.blacklist_apps = list(sorted(set(blacklist)))
            log.info("blacklist persist: blacklist_remove app_short=%s, count=%d", app_short, len(cfg.blacklist_apps))
            save_config(controller.cfg_path, cfg)
            return jsonify({"ok": True, "api_version": API_VERSION})
        except Exception as e:
            log.exception("blacklist_remove failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/calendar_month", methods=["GET"])
    def calendar_month():
        try:
            year = int(request.args.get("year"))
            month = int(request.args.get("month"))  # 1..12

            from calendar import monthrange
            from datetime import date as _date

            _, last_day = monthrange(year, month)
            repo = controller.repo

            days_with_data = []
            for d in range(1, last_day + 1):
                ld = _date(year, month, d).isoformat()
                day_usage = repo.get_daily_usage(ld) if hasattr(repo, "get_daily_usage") else {}
                total = 0
                if day_usage:
                    for v in day_usage.values():
                        if v is None:
                            continue
                        if isinstance(v, bool):
                            total += int(v)
                            continue
                        if isinstance(v, int):
                            total += v
                            continue
                        if isinstance(v, float):
                            if v == v and v not in (float("inf"), float("-inf")):
                                total += int(v)
                            continue
                        if isinstance(v, str):
                            s = v.strip()
                            if s and s.lstrip("+-").isdigit():
                                total += int(s)
                if total > 0:
                    days_with_data.append(ld)

            return jsonify({
                "api_version": API_VERSION,
                "year": year,
                "month": month,
                "days_with_data": days_with_data,
            })
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "calendar_month接口", "前端日历置灰可能异常", str(e))
            return jsonify({"error": str(e)}), 500
