"""
小型 HTTP API，供本地前端（pywebview 页面）与调试工具调用。
绑定 127.0.0.1，仅本机访问。

本文件为 facade，路由逻辑已拆分至 routes/ 目录。
"""
from __future__ import annotations

import logging
import time as _time

from flask import Flask, jsonify, request

from ..controller.app_controller import AppController
from ..diagnostics import diag
from ..diagnostics.debug_switch import is_debug_enabled
from .auth import generate_token, validate_token
from .common import API_VERSION
from .routes import auth as auth_routes, config, debug, diag as diag_routes, health, rest, snapshot, stats

log = logging.getLogger(__name__)

# 写接口需校验 X-EYECare-Token（以路由实际注册为准，此为最小集合）
_WRITE_PATHS_PREFIX = ("/api/config", "/api/categories", "/api/open_url", "/api/shutdown",
                       "/api/rest/", "/api/dnd", "/api/app_settings", "/api/app_exclude",
                       "/api/blacklist_remove", "/api/debug/", "/api/diag/log")


def _is_write_path(path: str) -> bool:
    if not path or not path.startswith("/api/"):
        return False
    if path == "/api/auth/token" or path.startswith("/api/auth/"):
        return False
    return any(path.startswith(p) or path == p.rstrip("/") for p in _WRITE_PATHS_PREFIX)


def create_app(controller: AppController, window_api=None) -> Flask:
    app = Flask(__name__)
    generate_token()
    app.config["EYECARE_API_TOKEN"] = True  # 标记已启用鉴权

    # 写接口 token 校验
    @app.before_request
    def _require_token_for_write():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        path = (request.path or "").split("?")[0]
        if not _is_write_path(path):
            return None
        token = request.headers.get("X-EYECare-Token", "").strip()
        if not validate_token(token):
            log.warning("AUDIT api.auth_rejected: path=%s method=%s", path, request.method)
            return jsonify({"error": "unauthorized", "code": "token_required"}), 401

    # request tracing for transparency/static assets + rest actions
    @app.before_request
    def _hard_before_request():
        request._eyecare_t0 = _time.perf_counter()

    @app.after_request
    def _hard_after_request(resp):
        p = request.path or ""
        if (
            p.startswith("/assets/")
            or p.startswith("/api/rest/")
            or p.startswith("/api/diag/")
            or p.startswith("/api/debug/")
        ):
            t0 = getattr(request, "_eyecare_t0", None)
            dt_ms = None
            if t0 is not None:
                dt_ms = round((_time.perf_counter() - t0) * 1000, 1)
                if is_debug_enabled():
                    diag.emit(
                        "DIAG_HTTP",
                        log,
                        "HTTP请求",
                        path=p,
                        status=getattr(resp, "status_code", None),
                        ms=dt_ms,
                        len=resp.content_length,
                        ua=(request.headers.get("User-Agent", "") or "")[:120],
                    )
        return resp

    # ----------------------------
    # 注册各路由模块（保持原顺序）
    # ----------------------------
    auth_routes.register_auth_routes(app, controller, log)
    health.register_health_routes(app, controller, log)
    diag_routes.register_diag_routes(app, controller, log)
    debug_on = is_debug_enabled(config_enabled=getattr(controller.cfg, "debug_enabled", False))
    if debug_on:
        debug.register_debug_routes(app, controller, log, window_api=window_api)
    snapshot.register_snapshot_routes(app, controller, log)
    rest.register_rest_routes(app, controller, log, allow_shutdown=debug_on)
    config.register_config_routes(app, controller, log)
    stats.register_stats_routes(app, controller, log)

    return app


def run_server(controller: AppController, host: str = "127.0.0.1", port: int = 17992) -> None:
    app = create_app(controller)
    log.info("API server starting on %s:%s", host, port)
    app.run(host=host, port=port, threaded=True, use_reloader=False)
