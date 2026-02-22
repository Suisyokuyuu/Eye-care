"""
Rest and shutdown routes.
"""
from flask import Flask, jsonify, request
from ...diagnostics import diag, log_exception_summary
from ..common import API_VERSION


def register_rest_routes(app: Flask, controller, log, *, allow_shutdown: bool = False):
    """Register rest routes. allow_shutdown: 按开关注册，仅 debug 模式启用（审计要求）。"""
    if allow_shutdown:
        @app.route("/api/shutdown", methods=["POST"])
        def shutdown():
            try:
                controller.stop()
                return jsonify({"ok": True, "api_version": API_VERSION})
            except Exception as e:
                log_exception_summary(log, "DIAG_EXCEPTION", "shutdown接口", "后端可能未正确停止")
                return jsonify({"error": str(e), "code": "shutdown_failed"}), 500

    @app.route("/api/rest/start", methods=["POST"])
    def rest_start():
        try:
            # 守卫：与 snapshot rest.start_enabled 共用同一状态源，被锁时 409
            guard = controller.get_rest_start_guard_status()
            if not guard.get("start_enabled", True):
                unlock_ms = int(guard.get("start_unlock_in_ms", 0))
                reason = str(guard.get("start_block_reason", "") or "rest_entry_locked")
                diag.emit(
                    "DIAG_REST_GUARD_BLOCK",
                    log,
                    "休息开始被拦截(守卫锁)",
                    reason_code=reason,
                    unlock_in_ms=unlock_ms,
                )
                return jsonify({
                    "ok": False,
                    "code": "rest_locked",
                    "unlock_in_ms": unlock_ms,
                    "api_version": API_VERSION,
                }), 409
            # entrypoint trace
            try:
                ip = request.headers.get("X-Forwarded-For") or request.remote_addr
                ua = request.headers.get("User-Agent", "")
                src = request.headers.get("X-Eyecare-Source", "")
                diag.emit("DIAG_REST_API_START", log, "休息开始请求入口", src=src, ip=ip, ua=ua[:120])
            except Exception as e:
                log_exception_summary(log, "DIAG_EXCEPTION", "rest_start 请求头/埋点", "仅记录", detail=str(e)[:200], reason_code="E_API_REST_EMIT")
            controller.rest_start()
            controller.notify_rest_entered()
            return jsonify({"ok": True, "api_version": API_VERSION})
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "rest_start接口", "开始休息可能未生效", str(e))
            return jsonify({"error": str(e), "code": "busy"}), 500

    @app.route("/api/rest/complete", methods=["POST"])
    def rest_complete():
        try:
            try:
                ip = request.headers.get("X-Forwarded-For") or request.remote_addr
                ua = request.headers.get("User-Agent", "")
                src = request.headers.get("X-Eyecare-Source", "")
                diag.emit("DIAG_REST_API_COMPLETE", log, "休息完成请求入口", src=src, ip=ip, ua=ua[:120])
            except Exception as e:
                log_exception_summary(log, "DIAG_EXCEPTION", "rest_complete 请求头/埋点", "仅记录", detail=str(e)[:200], reason_code="E_API_REST_EMIT")
            controller.rest_complete()
            return jsonify({"ok": True, "api_version": API_VERSION})
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "rest_complete接口", "完成休息可能未生效", str(e))
            return jsonify({"error": str(e), "code": "busy"}), 500

    @app.route("/api/rest/snooze", methods=["POST"])
    def rest_snooze():
        try:
            try:
                ip = request.headers.get("X-Forwarded-For") or request.remote_addr
                ua = request.headers.get("User-Agent", "")
                src = request.headers.get("X-Eyecare-Source", "")
                diag.emit("DIAG_REST_API_SNOOZE", log, "休息推迟请求入口", src=src, ip=ip, ua=ua[:120])
            except Exception as e:
                log_exception_summary(log, "DIAG_EXCEPTION", "rest_snooze 请求头/埋点", "仅记录", detail=str(e)[:200], reason_code="E_API_REST_EMIT")
            controller.rest_snooze()
            return jsonify({"ok": True, "api_version": API_VERSION})
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "rest_snooze接口", "推迟可能未生效", str(e))
            return jsonify({"error": str(e), "code": "busy"}), 500

    @app.route("/api/dnd", methods=["POST"])
    def dnd():
        try:
            body = request.get_json(force=True, silent=True) or {}
            on = bool(body.get("on", False))
            controller.set_dnd(on)
            return jsonify({"ok": True, "dnd": on, "api_version": API_VERSION})
        except Exception as e:
            log.exception("dnd failed")
            return jsonify({"error": str(e), "code": "invalid_params"}), 500
