from __future__ import annotations

import logging
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from eye_care.diagnostics import diag, log_exception_summary


class _FlaskStartupFilter:
    """过滤 stderr 中 Flask/Werkzeug 启动时的两行（Serving Flask app / Debug mode: off）。"""

    def __init__(self, stream):
        self._stream = stream

    def write(self, s):
        if s and ("Serving Flask" in s or "Debug mode:" in s):
            return
        self._stream.write(s)

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def start_backend_services(
    *,
    data_dir: Path,
    api_port: int,
    app_controller_cls,
    create_app_fn: Callable,
    mount_ui_site_routes_fn: Callable,
    ui_web_dir: Path,
    ui_index_path: Path,
    inject_bridge_script: Callable[[str], str],
    inject_drag_region: Callable[[str], str],
    enable_drag_region_inject: bool,
    controller_ready: dict,
    flask_ready: dict,
    logger: logging.Logger,
    on_controller_started: Optional[Callable[[object], None]] = None,
    on_controller_started_debug: Optional[Callable[[object], None]] = None,
    window_api: Optional[object] = None,
) -> threading.Thread:
    """Start controller + Flask site in background thread."""

    def _run():
        try:
            diag.emit("DIAG_CONTROLLER_INIT", logger, "初始化Controller")
            controller = app_controller_cls(data_dir=data_dir)
            controller.state.is_dnd = bool(getattr(controller.cfg, "startup_dnd", False))
            try:
                from eye_care.diagnostics.debug_switch import is_debug_enabled
                is_debug_enabled(config_enabled=getattr(controller.cfg, "debug_enabled", False))
            except Exception as e:
                logger.debug("debug_switch init skipped: %s", e)
            controller.start()

            if callable(on_controller_started):
                on_controller_started(controller)
            controller_ready["value"] = True
            diag.emit("DIAG_CONTROLLER_READY", logger, "Controller就绪")

            if callable(on_controller_started_debug):
                try:
                    on_controller_started_debug(controller)
                except Exception:
                    logger.exception("on_controller_started_debug failed")

            diag.emit("DIAG_FLASK_LISTEN", logger, "启动Flask API")
            # 完全关闭 Flask/werkzeug 控制台输出（避免 "Serving Flask app" / "Debug mode: off"）
            for _name in ("werkzeug", "werkzeug.serving", "flask", "flask.app"):
                _l = logging.getLogger(_name)
                _l.setLevel(logging.CRITICAL)
                _l.disabled = True
                _l.handlers.clear()
                _l.propagate = False

            app = create_app_fn(controller, window_api=window_api)
            mount_ui_site_routes_fn(
                app,
                ui_web_dir=ui_web_dir,
                index_path=ui_index_path,
                inject_bridge_script=inject_bridge_script,
                inject_drag_region=inject_drag_region,
                enable_drag_region_inject=enable_drag_region_inject,
            )

            flask_ready["value"] = True
            diag.emit("DIAG_FLASK_LISTEN", logger, "Flask开始监听")
            _orig_stderr = sys.stderr
            try:
                sys.stderr = _FlaskStartupFilter(_orig_stderr)
                app.run(host="127.0.0.1", port=int(api_port), threaded=True, use_reloader=False)
            finally:
                sys.stderr = _orig_stderr
        except Exception:
            log_exception_summary(logger, "DIAG_EXCEPTION", "后台服务初始化", "Controller/Flask可能未启动")
            logger.exception("Services init failed")

    # daemon=True：退出序列不等待 Flask 停止，进程退出时该线程随进程自然结束
    t = threading.Thread(target=_run, daemon=True, name="services_init")
    t.start()
    return t


def wait_flask_ready(*, api_port: int, flask_ready: dict, timeout_s: float = 2.0, logger: Optional[logging.Logger] = None) -> bool:
    """Wait for Flask '/' to become reachable within timeout."""
    t0 = time.time()
    while time.time() - t0 < float(timeout_s):
        if flask_ready.get("value"):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{int(api_port)}/", timeout=0.3) as r:
                    if r.getcode() == 200:
                        if logger:
                            diag.emit("DIAG_FLASK_READY", logger, "Flask已就绪", elapsed_s=round(time.time() - t0, 2))
                        return True
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                time.sleep(0.05)
                continue
        time.sleep(0.05)
    if logger:
        diag.emit("DIAG_FLASK_TIMEOUT", logger, "Flask启动超时，继续创建窗口", level=logging.WARNING)
    return False
