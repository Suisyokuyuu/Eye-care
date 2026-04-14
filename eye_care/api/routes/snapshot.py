"""
Snapshot route - main data endpoint.
"""
from flask import Flask, jsonify, request

from ...diagnostics import log_exception_summary
from ...services import ServiceContext, SnapshotService


def register_snapshot_routes(app: Flask, controller, log):
    service = SnapshotService(ServiceContext(controller=controller, log=log))

    @app.route("/api/snapshot", methods=["GET"])
    def snapshot():
        try:
            return jsonify(service.get_snapshot(query=dict(request.args)))
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "snapshot接口", "前端可能拿不到今日数据")
            return jsonify({"error": str(e), "code": "data_error"}), 500
