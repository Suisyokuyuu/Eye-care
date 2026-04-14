"""
Stats routes for app usage data.
"""
from collections import OrderedDict
from datetime import datetime, timedelta

from flask import Flask, jsonify, request

from ...diagnostics import log_exception_summary
from ...data.repository import DateRange
from ...services import ServiceContext, ServiceError, StatsService
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
    service = StatsService(ServiceContext(controller=controller, log=log))
    @app.route("/api/app_details", methods=["GET"])
    def app_details():
        """M1?app_short ???date ??=???days ?? 7?hourly/segments ??? date?"""
        try:
            app_key = (request.args.get("app") or "").strip().lower()
            date_arg = (request.args.get("date") or "").strip()
            if not date_arg:
                date_arg = datetime.now().astimezone().date().isoformat()
            try:
                end_date = datetime.strptime(date_arg, "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": "invalid date", "code": "bad_request"}), 400
            days = int(request.args.get("days") or 7)
            days = max(1, min(days, 90))
            range_start = (end_date - timedelta(days=days - 1)).isoformat()
            cache_key = (app_key, range_start, date_arg, date_arg)
            if cache_key in _app_details_cache:
                _app_details_cache.move_to_end(cache_key)
                return jsonify(_app_details_cache[cache_key])

            response_data = service.get_app_details(query(dict(request.args)))
            _app_details_cache[cache_key] = response_data
            if len(_app_details_cache) > _APP_DETAILS_CACHE_MAX_SIZE:
                _app_details_cache.popitem(last=False)
            return jsonify(response_data)
        except ServiceError as e:
            return jsonify({"error": e.message, "code": e.code, **e.payload}), e.http_status
        except Exception as e:
            log.exception("app_details failed")
            return jsonify({"error": str(e), "code": "data_error"}), 500

    @app.route("/api/apps_list", methods=["GET"])
    def apps_list():
        """????????app_short, display_name, category????????????"""
        try:
            return jsonify(service.get_apps_list())
        except Exception as e:
            log.exception("apps_list failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/app_settings", methods=["POST"])
    def app_settings():
        """??????category / display_name / auto_dnd_on_focus??"??/??"????"""
        try:
            result = service.update_app_settings(body=request.get_json() or {})
            _invalidate_app_details_cache(app_key=result.get("app_short"))
            return jsonify({"ok": True, "api_version": API_VERSION})
        except ServiceError as e:
            return jsonify({"error": e.message, "code": e.code, **e.payload}), e.http_status
        except Exception as e:
            log.exception("app_settings failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/app_exclude", methods=["POST"])
    def app_exclude():
        """????????????? + ???????"""
        try:
            service.exclude_app(app_short=(request.get_json() or {}).get("app_short"))
            return jsonify({"ok": True, "api_version": API_VERSION})
        except ServiceError as e:
            return jsonify({"error": e.message, "code": e.code, **e.payload}), e.http_status
        except Exception as e:
            log.exception("app_exclude failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/blacklist", methods=["GET"])
    def blacklist_get():
        """??????app_short, display_name?"""
        try:
            return jsonify(service.get_blacklist())
        except Exception as e:
            log.exception("blacklist get failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/blacklist_remove", methods=["POST"])
    def blacklist_remove():
        """??????? app????????"""
        try:
            service.remove_from_blacklist(app_short=(request.get_json() or {}).get("app_short"))
            return jsonify({"ok": True, "api_version": API_VERSION})
        except ServiceError as e:
            return jsonify({"error": e.message, "code": e.code, **e.payload}), e.http_status
        except Exception as e:
            log.exception("blacklist_remove failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/calendar_month", methods=["GET"])
    def calendar_month():
        try:
            year = int(request.args.get("year"))
            month = int(request.args.get("month"))  # 1..12
            return jsonify(service.get_calendar_month(year=year, month=month))
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "calendar_month??", "??????????", str(e))
            return jsonify({"error": str(e)}), 500
