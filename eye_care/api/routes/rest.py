"""
Rest and shutdown routes.
"""
from flask import Flask, jsonify, request
from ...diagnostics import log_exception_summary
from ...services import RestService, ServiceContext, ServiceError


def register_rest_routes(app: Flask, controller, log, *, allow_shutdown: bool = False):
    """Register rest routes. allow_shutdown: 按开关注册，仅 debug 模式启用（审计要求）。"""
    service = RestService(ServiceContext(controller=controller, log=log))

    if allow_shutdown:
        @app.route("/api/shutdown", methods=["POST"])
        def shutdown():
            try:
                return jsonify(service.shutdown())
            except Exception as e:
                log_exception_summary(log, "DIAG_EXCEPTION", "shutdown接口", "后端可能未正确停止")
                return jsonify({"error": str(e), "code": "shutdown_failed"}), 500

    @app.route("/api/rest/start", methods=["POST"])
    def rest_start():
        try:
            return jsonify(service.start_rest(headers=dict(request.headers), remote_addr=request.remote_addr))
        except ServiceError as e:
            return jsonify(e.payload or {"error": e.message, "code": e.code}), e.http_status
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "rest_start接口", "开始休息可能未生效", str(e))
            return jsonify({"error": str(e), "code": "busy"}), 500

    @app.route("/api/rest/complete", methods=["POST"])
    def rest_complete():
        try:
            return jsonify(service.complete_rest(headers=dict(request.headers), remote_addr=request.remote_addr))
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "rest_complete接口", "完成休息可能未生效", str(e))
            return jsonify({"error": str(e), "code": "busy"}), 500

    @app.route("/api/rest/snooze", methods=["POST"])
    def rest_snooze():
        try:
            return jsonify(service.snooze_rest(headers=dict(request.headers), remote_addr=request.remote_addr))
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "rest_snooze接口", "推迟可能未生效", str(e))
            return jsonify({"error": str(e), "code": "busy"}), 500

    @app.route("/api/dnd", methods=["POST"])
    def dnd():
        try:
            body = request.get_json(force=True, silent=True) or {}
            return jsonify(service.set_dnd(on=bool(body.get("on", False))))
        except Exception as e:
            log.exception("dnd failed")
            return jsonify({"error": str(e), "code": "invalid_params"}), 500
