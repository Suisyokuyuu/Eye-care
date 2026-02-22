"""
Debug routes for notify and diagnostics.
"""
import json
from pathlib import Path

from flask import Flask, jsonify, request

from ...diagnostics import log_exception_summary

# 全局变量：存储 window_api 和 dispatcher 引用（在 runtime_shell.py 中设置）
_debug_window_api = None
_debug_dispatcher = None


def set_debug_window_api(window_api):
    """设置 window_api 引用，供 debug 路由使用。"""
    global _debug_window_api
    _debug_window_api = window_api


def set_debug_dispatcher(dispatcher):
    """设置 dispatcher 引用，供 debug 路由使用。"""
    global _debug_dispatcher
    _debug_dispatcher = dispatcher


def register_debug_routes(app: Flask, controller, log, window_api=None):
    @app.route("/api/debug/notify_log", methods=["POST"])
    def debug_notify_log():
        try:
            data = request.get_json(silent=True) or {}
            on = bool(data.get("on", True))
            if hasattr(controller, "set_debug_notify"):
                controller.set_debug_notify(on)  # type: ignore
            return jsonify({"ok": True, "notify_debug": on})
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "debug_notify_log接口", "调试开关可能未生效")
            return jsonify({"error": str(e), "code": "debug_notify_log_failed"}), 500

    @app.route("/api/debug/notify", methods=["POST"])
    def debug_notify():
        """强制触发一次提醒：从渐入接入弹窗链路（post_notify_show），走完整 show→渐入。"""
        try:
            if hasattr(controller, "set_debug_notify"):
                controller.set_debug_notify(True)  # type: ignore
            if hasattr(controller, "debug_trigger_notify_show"):
                controller.debug_trigger_notify_show()  # type: ignore
            return jsonify({"ok": True})
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "debug_notify接口", "强制通知可能未触发")
            return jsonify({"error": str(e), "code": "debug_notify_failed"}), 500

    @app.route("/api/debug/open_app_detail", methods=["POST"])
    def debug_open_app_detail():
        """调试接口：通过 evaluate_js 打开应用详情模态框。用于测试场景。"""
        try:
            data = request.get_json(silent=True) or {}
            app_key = data.get("app_key", "").strip()
            if not app_key:
                return jsonify({"error": "missing app_key", "code": "bad_request"}), 400
            
            # 使用全局变量或参数中的 window_api
            wa = window_api or _debug_window_api
            if wa is None or not hasattr(wa, "_window") or wa._window is None:
                return jsonify({"error": "window not available", "code": "window_unavailable"}), 503
            
            # 通过 evaluate_js 打开应用详情
            js_code = f"""
            (function() {{
                if (typeof window.openAppDetailByKey === 'function') {{
                    window.openAppDetailByKey({json.dumps(app_key)}, {json.dumps(app_key)});
                }} else {{
                    console.warn('openAppDetailByKey not available');
                }}
            }})();
            """
            
            # 通过 dispatcher 投递到 GUI 线程执行
            if hasattr(wa, "_dispatcher") and wa._dispatcher:
                def _eval_in_gui():
                    try:
                        if wa._window and hasattr(wa._window, "evaluate_js"):
                            wa._window.evaluate_js(js_code)
                    except Exception as e:
                        log.warning("debug_open_app_detail evaluate_js failed: %s", e)
                wa._dispatcher.post(_eval_in_gui)
            else:
                # 如果没有 dispatcher，直接执行（可能不在 GUI 线程，但测试场景可接受）
                if wa._window and hasattr(wa._window, "evaluate_js"):
                    wa._window.evaluate_js(js_code)
            
            return jsonify({"ok": True, "app_key": app_key})
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "debug_open_app_detail接口", "打开应用详情可能失败")
            return jsonify({"error": str(e), "code": "debug_open_app_detail_failed"}), 500

    @app.route("/api/debug/dispatcher_metric", methods=["GET"])
    def debug_dispatcher_metric():
        """调试接口：获取 dispatcher 指标（包括 illegal_count）。用于测试验证。"""
        try:
            # 使用全局变量中的 dispatcher
            disp = _debug_dispatcher
            if disp is None or not hasattr(disp, "get_metric"):
                return jsonify({"error": "dispatcher not available", "code": "dispatcher_unavailable"}), 503
            
            metric = disp.get_metric()
            return jsonify({"ok": True, "metric": metric})
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "debug_dispatcher_metric接口", "获取dispatcher指标可能失败")
            return jsonify({"error": str(e), "code": "debug_dispatcher_metric_failed"}), 500

    @app.route("/api/debug/dump_threads", methods=["POST"])
    def debug_dump_threads():
        """调试接口：可编程触发线程栈抓取，供黑盒脚本等自动化验证。等价于托盘「抓取线程栈」。"""
        try:
            data_dir = getattr(controller, "data_dir", None)
            if data_dir is None:
                return jsonify({"error": "data_dir not available", "code": "data_dir_unavailable"}), 503
            data_dir = Path(data_dir)
            from ...diagnostics.hang_dump import dump_threads
            out_path = dump_threads(data_dir, reason="api")
            return jsonify({"ok": True, "path": str(out_path)})
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "debug_dump_threads接口", "线程栈抓取可能失败")
            return jsonify({"error": str(e), "code": "debug_dump_threads_failed"}), 500
