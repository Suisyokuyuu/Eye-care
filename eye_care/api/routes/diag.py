"""
Diag log route - Front-end sends breadcrumb logs.
"""
import json
from flask import Flask, jsonify, request
from ...diagnostics import diag, log_exception_summary


def register_diag_routes(app: Flask, controller, log):
    @app.route("/api/diag/log", methods=["POST"])
    def diag_log():
        """Front-end sends breadcrumb logs here.

        This is intentionally low-level and best-effort: it must never break UI.
        """
        try:
            data = request.get_json(silent=True) or {}
            # Avoid huge logs
            try:
                msg = str(data.get("msg", ""))
                if len(msg) > 800:
                    msg = msg[:800] + "..."
            except Exception:
                msg = ""
            meta = {
                "src": data.get("src"),
                "stage": data.get("stage"),
                "ts": data.get("ts"),
                "href": data.get("href"),
                "extra": data.get("extra"),
            }
            ua = request.headers.get("User-Agent", "")
            ip = request.headers.get("X-Forwarded-For") or request.remote_addr
            extra = meta.get("extra")
            extra_s = ""
            try:
                if extra is not None:
                    extra_s = json.dumps(extra, ensure_ascii=False)
                    if len(extra_s) > 400:
                        extra_s = extra_s[:400] + "..."
            except Exception:
                extra_s = str(extra)[:400] if extra is not None else ""
            diag.emit(
                "DIAG_UI_LOG", log, "前端埋点日志",
                msg=msg[:200],
                src=meta.get("src"),
                stage=meta.get("stage"),
                ip=ip,
                ua=ua[:120],
                extra=extra_s,
            )
            return jsonify({"ok": True})
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "前端diag_log接口", "仅记录失败，不影响功能")
            return jsonify({"ok": False, "error": str(e)}), 200
