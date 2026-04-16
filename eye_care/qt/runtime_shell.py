from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from eye_care.bootstrap.constants import DEFAULT_API_PORT, ENABLE_DRAG_REGION_INJECT, PROJECT_ROOT, UI_INDEX_PATH, UI_WEB_DIR
from eye_care.bootstrap.bridge_inject import inject_bridge_script, inject_drag_region
from eye_care.ui.app_runtime import start_backend_services, wait_flask_ready
from eye_care.ui.action_contracts import normalize_notify_window_action
from eye_care.ui.web_routes import build_ui_page_url
from eye_care.ui.page_delivery import render_main_html, render_qt_subpage_html


def run_qt_shell(data_dir: Path, no_single: bool, api_port: int, debug_console: bool = False) -> None:
    os.chdir(str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT))

    from eye_care.api.server import create_app
    from eye_care.controller.app_controller import AppController
    from eye_care.diagnostics.logging_setup import setup_logging
    from eye_care.ui.web_routes import mount_ui_site_routes
    from eye_care.services.registry import build_service_registry
    from eye_care.ui.win_effects import WinEffects
    from eye_care.ui.window_api import _create_file_dialog_safe

    try:
        from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal, Slot
        from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except Exception as exc:  # pragma: no cover - depends on local runtime
        raise RuntimeError("PySide6/QWebEngine is required for --host qt") from exc

    setup_logging(data_dir / "debug.log")
    log = logging.getLogger(__name__)
    log.info("host=qt startup: api_port=%s debug_console=%s", api_port, debug_console)
    win_effects = WinEffects(log)

    controller = None
    controller_ready = {"value": False}
    flask_ready = {"value": False}
    services = {"value": None}
    main_window_ref = {"value": None}
    rest_overlays = []
    rest_pending_show = {"value": False}
    notify_window_ref = {"value": None}
    notify_pending_payload = {"value": None}
    notification_manager_ref = {"value": None}
    notifier_service_ref = {"value": None}
    tray_ref = {"value": None}

    def _set_controller(ctrl) -> None:
        nonlocal controller
        controller = ctrl
        services["value"] = build_service_registry(controller=ctrl, log=log)

    def _services():
        current = services.get("value")
        if current is None:
            raise RuntimeError("qt bridge services are not ready")
        return current

    def _controller():
        if controller is None:
            raise RuntimeError("qt controller is not ready")
        return controller

    def _main_window():
        current = main_window_ref.get("value")
        if current is None:
            raise RuntimeError("qt main window is not ready")
        return current

    def _show_main_window() -> None:
        window = _main_window()
        if window.isMinimized():
            window.showNormal()
        window.show()
        window.raise_()
        window.activateWindow()
        log.info("qt.tray.show_main_window")

    def _run_main_js(js: str, *, label: str) -> None:
        try:
            _show_main_window()
            _main_window().page.runJavaScript(js)
            log.info("qt.tray.main_js label=%s", label)
        except Exception:
            log.exception("qt tray main js failed label=%s", label)

    def _set_run_mode(mode: str) -> None:
        _controller().set_run_mode(mode)
        log.info("qt.tray.set_run_mode mode=%s", mode)

    def _open_settings() -> None:
        _run_main_js(
            """(function(){
  try {
    if (window.ui && typeof window.ui.openSettings === 'function') {
      window.ui.openSettings();
      return true;
    }
  } catch (e) {}
  return false;
})();""",
            label="open_settings",
        )

    def _start_rest_from_tray() -> None:
        _run_main_js(
            """(function(){
  try {
    if (window.ui && typeof window.ui.restStart === 'function') {
      window.ui.restStart();
      return true;
    }
  } catch (e) {}
  return false;
})();""",
            label="rest_start",
        )

    def _check_update_from_tray() -> None:
        _run_main_js(
            """(function(){
  try {
    if (window.ui && typeof window.ui.checkUpdate === 'function') {
      window.ui.checkUpdate();
      return true;
    }
  } catch (e) {}
  return false;
})();""",
            label="check_update",
        )

    def _open_data_dir() -> None:
        os.startfile(str(data_dir))
        log.info("qt.tray.open_data_dir path=%s", data_dir)

    def _quit_from_tray() -> None:
        log.info("qt.tray.quit_requested")
        app.quit()

    def _rest_duration_seconds() -> int:
        try:
            cfg = getattr(_controller(), "cfg", None)
            if cfg is None:
                return 20
            unit = getattr(cfg, "reminder_rest_unit", "sec")
            value = int(getattr(cfg, "reminder_rest_seconds", 20) or 20)
            raw = max(1, value) * (60 if unit == "min" else 1)
            return max(5, raw)
        except Exception:
            return 20

    def _rest_overlay_url(screen_idx: int) -> str:
        url = f"{build_ui_page_url(api_port=api_port, page='rest')}?screen={int(screen_idx)}"
        if debug_console or os.environ.get("EYECARE_DEBUG_CONSOLE", "0") == "1":
            url += "&debug=1"
        return url

    def _notify_auto_hide_seconds() -> int:
        try:
            cfg = getattr(_controller(), "cfg", None)
            if cfg is None:
                return 20
            return max(1, min(600, int(getattr(cfg, "notify_auto_hide_seconds", 20) or 20)))
        except Exception:
            return 20

    def _play_rest_end_sound() -> dict:
        sound_path = UI_WEB_DIR / "assets" / "rest_end_refresh_soft.wav"
        try:
            import winsound
        except Exception as exc:
            log.warning("qt.rest_end_sound unavailable: winsound import failed: %s", exc)
            return {"ok": False, "code": "winsound_unavailable", "path": str(sound_path)}
        try:
            if not sound_path.exists():
                log.warning("qt.rest_end_sound missing path=%s", sound_path)
                return {"ok": False, "code": "missing_asset", "path": str(sound_path)}
            winsound.PlaySound(str(sound_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            log.info("qt.rest_end_sound_played path=%s", sound_path)
            return {"ok": True, "path": str(sound_path)}
        except OSError as exc:
            log.warning("qt.rest_end_sound os error: %s", exc)
            return {"ok": False, "code": "os_error", "error": str(exc), "path": str(sound_path)}
        except Exception as exc:
            log.exception("qt.rest_end_sound unexpected error")
            return {"ok": False, "code": "unexpected_error", "error": str(exc), "path": str(sound_path)}

    def _try_show_pending_notify() -> dict:
        payload = notify_pending_payload.get("value")
        window = notify_window_ref.get("value")
        if not payload or window is None:
            return {"ok": False, "reason": "no_pending"}
        if not getattr(window, "notify_ready", False):
            return {"ok": False, "reason": "not_ready"}

        message = str(payload.get("message") or "Take a short break")
        auto_hide_s = int(payload.get("auto_hide_s") or _notify_auto_hide_seconds())
        session = int(payload.get("session") or 0)
        if getattr(window, "notify_active_session", 0) == session and getattr(window, "notify_visible", False):
            return {"ok": True, "reason": "already_visible", "session": session}

        window.active_prompt_key = payload.get("prompt_key")
        window.active_extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        window.show_notify(message=message, auto_hide_s=auto_hide_s)
        window.notify_active_session = session
        return {"ok": True, "reason": "shown", "session": session, "auto_hide_s": auto_hide_s}

    def _build_notify_message(extra: dict | None) -> str:
        payload = extra if isinstance(extra, dict) else {}
        rest = payload.get("rest") or {}
        message = str(rest.get("prompt_reason") or "???????????????????")
        return message.strip() or "???????????????????"

    def _queue_notify_payload(*, extra: dict | None, prompt_key=None, debug_only: bool = False, message: str | None = None) -> dict:
        session_seed = getattr(notify_window_ref.get("value"), "notify_active_session", 0) if notify_window_ref.get("value") is not None else 0
        session = int(session_seed or 0) + 1
        notify_pending_payload["value"] = {
            "message": str(message or _build_notify_message(extra)),
            "auto_hide_s": _notify_auto_hide_seconds(),
            "session": session,
            "extra": extra if isinstance(extra, dict) else {},
            "prompt_key": prompt_key,
            "debug_only": bool(debug_only),
        }
        return {"ok": True, "session": session, "ready": bool(getattr(notify_window_ref.get("value"), "notify_ready", False) if notify_window_ref.get("value") is not None else False)}

    def _show_ready_rest_overlays() -> None:
        shown = 0
        duration = _rest_duration_seconds()
        for overlay in rest_overlays:
            if not getattr(overlay, "rest_ready", False):
                continue
            if overlay.rest_started:
                continue
            overlay.show_overlay(duration_s=duration)
            shown += 1
        log.info("qt.rest_overlay_show_ready shown=%s total=%s", shown, len(rest_overlays))


    start_backend_services(
        data_dir=data_dir,
        api_port=api_port,
        app_controller_cls=AppController,
        create_app_fn=create_app,
        mount_ui_site_routes_fn=mount_ui_site_routes,
        ui_web_dir=UI_WEB_DIR,
        ui_index_path=UI_INDEX_PATH,
        inject_bridge_script=inject_bridge_script,
        inject_drag_region=inject_drag_region,
        enable_drag_region_inject=ENABLE_DRAG_REGION_INJECT,
        controller_ready=controller_ready,
        flask_ready=flask_ready,
        logger=log,
        on_controller_started=_set_controller,
    )
    wait_flask_ready(api_port=api_port, flask_ready=flask_ready, timeout_s=2.0, logger=log)

    class LoggingWebPage(QWebEnginePage):
        def __init__(self, *, page_role: str) -> None:
            super().__init__()
            self._page_role = str(page_role or "page")

        def javaScriptConsoleMessage(self, level, message, line_number, source_id):
            level_name = getattr(level, "name", str(level))
            log.info(
                "qt.js_console role=%s level=%s line=%s source=%s message=%s",
                self._page_role,
                level_name,
                int(line_number),
                source_id or "",
                message,
            )

    class RestOverlayWindow(QMainWindow):
        def __init__(self, *, screen_idx: int, screen, bridge: QObject) -> None:
            super().__init__()
            self.screen_idx = int(screen_idx)
            self.rest_ready = False
            self.rest_started = False
            self.setWindowTitle(f"EyE Care RestOverlay [{self.screen_idx}]")
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WA_NoSystemBackground, True)
            self.setAutoFillBackground(False)
            self.setStyleSheet("background: transparent;")

            geometry = screen.geometry()
            self.setGeometry(geometry)
            self.view = QWebEngineView(self)
            self.view.setAttribute(Qt.WA_TranslucentBackground, True)
            self.view.setAttribute(Qt.WA_NoSystemBackground, True)
            self.view.setAutoFillBackground(False)
            self.view.setStyleSheet("background: transparent; border: 0;")
            self.page = LoggingWebPage(page_role=f"rest[{self.screen_idx}]")
            self.page.setBackgroundColor(QColor(0, 0, 0, 0))
            self.channel = QWebChannel(self.page)
            self.channel.registerObject("qtBridge", bridge)
            self.page.setWebChannel(self.channel)
            self.view.setPage(self.page)
            self.setCentralWidget(self.view)
            self.centralWidget().setAttribute(Qt.WA_TranslucentBackground, True)
            self.centralWidget().setAttribute(Qt.WA_NoSystemBackground, True)
            self.centralWidget().setAutoFillBackground(False)
            self.centralWidget().setStyleSheet("background: transparent; border: 0;")
            self.view.loadFinished.connect(self._on_load_finished)
            self.view.load(QUrl(_rest_overlay_url(self.screen_idx)))
            log.info(
                "qt.rest_overlay_created screen=%s x=%s y=%s w=%s h=%s",
                self.screen_idx,
                geometry.x(),
                geometry.y(),
                geometry.width(),
                geometry.height(),
            )
            log.info("qt.rest_overlay_transparency_configured screen=%s page_bg=transparent widget_bg=transparent", self.screen_idx)

        def _on_load_finished(self, ok: bool) -> None:
            log.info(
                "qt.rest_page_load_finished screen=%s ok=%s url=%s",
                self.screen_idx,
                bool(ok),
                self.view.url().toString(),
            )
            if ok:
                self.page.runJavaScript(rest_bridge_script)

        def show_overlay(self, *, duration_s: int) -> None:
            self.rest_started = True
            self.show()
            self.raise_()
            self.activateWindow()
            try:
                hwnd = int(self.winId())
            except Exception:
                hwnd = 0
            acrylic_ok = False
            if hwnd:
                try:
                    acrylic_ok = bool(win_effects.enable_acrylic(hwnd, tint_color=0x33101826, blur=True, where=f"qt_rest_show screen={self.screen_idx}"))
                except Exception:
                    log.exception("qt rest acrylic apply failed screen=%s hwnd=%s", self.screen_idx, hwnd)
            log.info("qt.rest_overlay_acrylic screen=%s hwnd=%s ok=%s", self.screen_idx, hwnd, acrylic_ok)
            js = f"""(function(){{
  try {{ if (window.restFadeIn) window.restFadeIn(); }} catch (e) {{}}
  try {{ window.__rest_end_sound_enabled = true; }} catch (e) {{}}
  try {{ if (window.EyeCareRest && window.EyeCareRest.start) window.EyeCareRest.start({int(duration_s)}); }} catch (e) {{ console.error(e); }}
  try {{ console.info('qt.rest_overlay_started screen={self.screen_idx} duration={int(duration_s)}'); }} catch (e) {{}}
}})();"""
            self.page.runJavaScript(js)
            log.info("qt.rest_overlay_shown screen=%s duration_s=%s", self.screen_idx, int(duration_s))

        def hide_overlay(self) -> None:
            js = """(function(){
  try { if (window.EyeCareRest && window.EyeCareRest.stop) window.EyeCareRest.stop(); } catch (e) {}
  try { if (window.restFadeOut) window.restFadeOut(); } catch (e) {}
})();"""
            self.page.runJavaScript(js)
            self.rest_started = False
            self.hide()
            log.info("qt.rest_overlay_hidden screen=%s", self.screen_idx)

    rest_bridge_script = """
(function() {
  if (window.__EYECARE_QT_REST_BRIDGE_BOOTED__) return 'already-booted';
  window.__EYECARE_QT_REST_BRIDGE_BOOTED__ = true;

  function bootChannel() {
    if (!(window.qt && window.qt.webChannelTransport)) return;
    if (typeof window.QWebChannel !== 'function') return;
    new window.QWebChannel(window.qt.webChannelTransport, function(channel) {
      window.qtBridge = channel.objects.qtBridge || null;
      window.__EYECARE_QT_CHANNEL_READY__ = !!window.qtBridge;
      window.__EYECARE_QT_CALL__ = function(method, args) {
        args = Array.isArray(args) ? args.slice() : [];
        return new Promise(function(resolve, reject) {
          var target = window.qtBridge;
          if (!target || typeof target[method] !== 'function') {
            reject(new Error('qt bridge method unavailable: ' + method));
            return;
          }
          try {
            target[method].apply(target, args.concat([function(result) { resolve(result); }]));
          } catch (error) {
            reject(error);
          }
        });
      };
      window.pywebview = window.pywebview || {};
      window.pywebview.api = window.pywebview.api || {};
      window.pywebview.api.rest_ready_for_show = function(screenIdx) {
        return window.__EYECARE_QT_CALL__('restReadyForShow', [screenIdx]);
      };
      window.pywebview.api.close_rest_overlay = function() {
        return window.__EYECARE_QT_CALL__('closeRestOverlay', []);
      };
      window.pywebview.api.play_rest_end_sound = function() {
        return window.__EYECARE_QT_CALL__('playRestEndSound', []);
      };
      window.pywebview.api.rest_overlay_log = function(payload) {
        return window.__EYECARE_QT_CALL__('restOverlayLog', [payload || {}]);
      };
      try {
        var restLinks = Array.prototype.map.call(document.querySelectorAll('link[rel="stylesheet"]'), function(node) { return node.href || ''; });
        var restScripts = Array.prototype.map.call(document.querySelectorAll('script[src]'), function(node) { return node.src || ''; });
        console.info('qt.rest_static_probe=' + JSON.stringify({ href: window.location.href || '', links: restLinks, scripts: restScripts }));
      } catch (e) {}
      try { console.info('qt.rest_channel_ready=true'); } catch (e) {}
      try {
        var params = new URLSearchParams(window.location.search || '');
        var screenIdx = parseInt(params.get('screen') || '0', 10);
        window.pywebview.api.rest_ready_for_show(screenIdx).then(function(result) {
          try { console.info('qt.rest_ready_ack=' + JSON.stringify(result || {})); } catch (e) {}
        });
      } catch (e) {
        try { console.error(e); } catch (_) {}
      }
    });
  }

  if (typeof window.QWebChannel === 'function') {
    bootChannel();
    return 'channel-ready';
  }

  var script = document.createElement('script');
  script.src = 'qrc:///qtwebchannel/qwebchannel.js';
  script.onload = function() { bootChannel(); };
  script.onerror = function() {
    try { console.error('qt.rest_channel_script_load_failed'); } catch (e) {}
  };
  (document.head || document.documentElement).appendChild(script);
  return 'channel-loading';
})();
"""

    class NotifyOverlayWindow(QMainWindow):
        def __init__(self, *, bridge: QObject) -> None:
            super().__init__()
            self.notify_ready = False
            self.notify_visible = False
            self.notify_active_session = 0
            self.active_prompt_key = None
            self.active_extra = {}
            self.setWindowTitle("EyE Care Notify [qt]")
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WA_NoSystemBackground, True)
            self.setAutoFillBackground(False)
            self.setStyleSheet("background: transparent;")

            screen = QGuiApplication.primaryScreen()
            geometry = screen.availableGeometry() if screen is not None else QGuiApplication.primaryScreen().geometry()
            width, height = 400, 160
            x = geometry.x() + max(0, geometry.width() - width - 24)
            y = geometry.y() + max(0, geometry.height() - height - 24)
            self.setGeometry(x, y, width, height)
            self.view = QWebEngineView(self)
            self.view.setAttribute(Qt.WA_TranslucentBackground, True)
            self.view.setAttribute(Qt.WA_NoSystemBackground, True)
            self.view.setAutoFillBackground(False)
            self.view.setStyleSheet("background: transparent; border: 0;")
            self.page = LoggingWebPage(page_role="notify")
            self.page.setBackgroundColor(QColor(0, 0, 0, 0))
            self.channel = QWebChannel(self.page)
            self.channel.registerObject("qtBridge", bridge)
            self.page.setWebChannel(self.channel)
            self.view.setPage(self.page)
            self.setCentralWidget(self.view)
            self.centralWidget().setAttribute(Qt.WA_TranslucentBackground, True)
            self.centralWidget().setAttribute(Qt.WA_NoSystemBackground, True)
            self.centralWidget().setAutoFillBackground(False)
            self.centralWidget().setStyleSheet("background: transparent; border: 0;")
            self.view.loadFinished.connect(self._on_load_finished)
            notify_html = render_qt_subpage_html(page_path=UI_WEB_DIR / "notify" / "index.html", ui_web_dir=UI_WEB_DIR)
            self.view.setHtml(notify_html, QUrl(build_ui_page_url(api_port=api_port, page="notify")))
            log.info("qt.notify_overlay_created x=%s y=%s w=%s h=%s", x, y, width, height)

        def _on_load_finished(self, ok: bool) -> None:
            log.info("qt.notify_page_load_finished ok=%s url=%s", bool(ok), self.view.url().toString())
            if ok:
                self.page.runJavaScript(notify_bridge_script)

        def show_notify(self, *, message: str, auto_hide_s: int) -> None:
            self.show()
            self.raise_()
            self.activateWindow()
            try:
                hwnd = int(self.winId())
            except Exception:
                hwnd = 0
            acrylic_ok = False
            if hwnd:
                try:
                    acrylic_ok = bool(win_effects.enable_acrylic(hwnd, tint_color=0xBB101826, blur=True, where="qt_notify_show"))
                except Exception:
                    log.exception("qt notify acrylic apply failed hwnd=%s", hwnd)
            log.info("qt.notify_overlay_acrylic hwnd=%s ok=%s", hwnd, acrylic_ok)
            msg_json = json.dumps(str(message or ""), ensure_ascii=False)
            js = f"""(function(){{
  try {{ window.resetFade && window.resetFade(); }} catch (e) {{}}
  try {{ window.setMessage && window.setMessage({msg_json}); }} catch (e) {{}}
  try {{ window.notifyCardFadeIn && window.notifyCardFadeIn(); }} catch (e) {{}}
  try {{ window.autoHide && window.autoHide({int(auto_hide_s)}); }} catch (e) {{}}
  try {{ console.info('qt.notify_overlay_started autoHide={int(auto_hide_s)}'); }} catch (e) {{}}
}})();"""
            self.page.runJavaScript(js)
            self.notify_visible = True
            log.info("qt.notify_overlay_shown auto_hide_s=%s", int(auto_hide_s))

        def hide_notify(self, *, reason: str = "dismiss") -> None:
            self.page.runJavaScript("""(function(){ try { window.notifyCardFadeOut && window.notifyCardFadeOut(); } catch (e) {} })();""")
            self.notify_visible = False
            self.hide()
            log.info("qt.notify_overlay_hidden reason=%s", reason)

    notify_bridge_script = """
(function() {
  if (window.__EYECARE_QT_NOTIFY_BRIDGE_BOOTED__) return 'already-booted';
  window.__EYECARE_QT_NOTIFY_BRIDGE_BOOTED__ = true;

  function bootChannel() {
    if (!(window.qt && window.qt.webChannelTransport)) return;
    if (typeof window.QWebChannel !== 'function') return;
    new window.QWebChannel(window.qt.webChannelTransport, function(channel) {
      window.qtBridge = channel.objects.qtBridge || null;
      window.__EYECARE_QT_CHANNEL_READY__ = !!window.qtBridge;
      window.__EYECARE_QT_CALL__ = function(method, args) {
        args = Array.isArray(args) ? args.slice() : [];
        return new Promise(function(resolve, reject) {
          var target = window.qtBridge;
          if (!target || typeof target[method] !== 'function') {
            reject(new Error('qt bridge method unavailable: ' + method));
            return;
          }
          try {
            target[method].apply(target, args.concat([function(result) { resolve(result); }]));
          } catch (error) {
            reject(error);
          }
        });
      };
      window.pywebview = window.pywebview || {};
      window.pywebview.api = window.pywebview.api || {};
      window.pywebview.api.notify_log = function(payload) {
        return window.__EYECARE_QT_CALL__('notifyLog', [payload || {}]);
      };
      window.pywebview.api.notify_ready_for_show = function() {
        return window.__EYECARE_QT_CALL__('notifyReadyForShow', []);
      };
      window.pywebview.api.notify_window_action = function(action) {
        return window.__EYECARE_QT_CALL__('notifyWindowAction', [action || '']);
      };
      window.pywebview.api.notify_action = window.pywebview.api.notify_window_action;
      try {
        var notifyLinks = Array.prototype.map.call(document.querySelectorAll('link[rel="stylesheet"]'), function(node) { return node.href || ''; });
        var notifyScripts = Array.prototype.map.call(document.querySelectorAll('script[src]'), function(node) { return node.src || ''; });
        console.info('qt.notify_static_probe=' + JSON.stringify({ href: window.location.href || '', links: notifyLinks, scripts: notifyScripts }));
      } catch (e) {}
      try { console.info('qt.notify_channel_ready=true'); } catch (e) {}
    });
  }

  if (typeof window.QWebChannel === 'function') {
    bootChannel();
    return 'channel-ready';
  }

  var script = document.createElement('script');
  script.src = 'qrc:///qtwebchannel/qwebchannel.js';
  script.onload = function() { bootChannel(); };
  script.onerror = function() {
    try { console.error('qt.notify_channel_script_load_failed'); } catch (e) {}
  };
  (document.head || document.documentElement).appendChild(script);
  return 'channel-loading';
})();
"""

    def _ensure_notify_window(bridge: QObject):
        current = notify_window_ref.get("value")
        if current is not None:
            return current
        current = NotifyOverlayWindow(bridge=bridge)
        notify_window_ref["value"] = current
        return current

    def _ensure_rest_overlays(bridge: QObject) -> None:
        if rest_overlays:
            return
        screens = QGuiApplication.screens() or []
        for idx, screen in enumerate(screens):
            overlay = RestOverlayWindow(screen_idx=idx, screen=screen, bridge=bridge)
            rest_overlays.append(overlay)
        log.info("qt.rest_overlay_pool_ready count=%s", len(rest_overlays))

    class QtNotifyDispatcher(QObject):
        notifyShowRequested = Signal(object, object)

        def post_notify_show(self, extra: dict, prompt_key) -> None:
            self.notifyShowRequested.emit(extra, prompt_key)

    def _notify_complete(prompt_key, extra: dict | None) -> None:
        manager = notification_manager_ref.get("value")
        if manager is None or prompt_key is None:
            return
        try:
            manager.on_notify_complete(prompt_key, True, extra or {})
        except Exception:
            log.exception("qt notify complete callback failed")

    def _handle_notify_task(extra: dict, prompt_key) -> None:
        bridge = qt_bridge_ref.get("value")
        window = notify_window_ref.get("value")
        if window is None and bridge is not None:
            window = _ensure_notify_window(bridge)
        result = _queue_notify_payload(extra=extra, prompt_key=prompt_key, debug_only=bool((extra or {}).get("debug_only")), message=None)
        shown = _try_show_pending_notify()
        log.info("qt.notify_task_queued prompt_key=%s queue_result=%s show_result=%s", prompt_key, result, shown)

    qt_bridge_ref = {"value": None}

    class QtBridgeProbe(QObject):
        def __init__(self) -> None:
            super().__init__()

        @Slot(str, result="QVariantMap")
        def ping(self, payload: str = "") -> dict:
            data = {"ok": True, "payload": payload or "", "transport": "qwebchannel", "host": "qt"}
            log.info("qt.bridge.ping payload=%s", payload or "")
            return data

        @Slot(str, str, str, result=bool)
        def log(self, level: str, message: str, extra: str = "") -> bool:
            log.info(
                "qt.bridge.log level=%s message=%s extra=%s",
                (level or "info").strip().lower(),
                message or "",
                extra or "",
            )
            return True

        @Slot(result="QVariantMap")
        def getRuntimeInfo(self) -> dict:
            info = {
                "host": "qt",
                "transport": "qwebchannel",
                "apiPort": int(api_port),
                "controllerReady": bool(controller_ready.get("value")),
                "flaskReady": bool(flask_ready.get("value")),
            }
            log.info("qt.bridge.runtime_info %s", info)
            return info

        @Slot("QVariantMap", result="QVariantMap")
        def getSnapshot(self, query) -> dict:
            if not isinstance(query, dict):
                query = {}
            log.info("qt.bridge.get_snapshot query=%s", query)
            try:
                return _services().snapshot.get_snapshot(query=query)
            except Exception as exc:
                log.exception("qt bridge getSnapshot failed")
                return {"error": str(exc), "code": "bridge_error"}

        @Slot(int, int, result="QVariantMap")
        def getCalendarMonth(self, year: int, month: int) -> dict:
            log.info("qt.bridge.get_calendar_month year=%s month=%s", int(year), int(month))
            try:
                return _services().stats.get_calendar_month(year=int(year), month=int(month))
            except Exception as exc:
                log.exception("qt bridge getCalendarMonth failed")
                return {"error": str(exc), "code": "bridge_error", "days_with_data": []}

        @Slot(result="QVariantMap")
        def getConfig(self) -> dict:
            log.info("qt.bridge.get_config")
            try:
                return _services().config.get_config()
            except Exception as exc:
                log.exception("qt bridge getConfig failed")
                return {"error": str(exc), "code": "bridge_error", "config": {}}

        @Slot("QVariantMap", result="QVariantMap")
        def updateConfig(self, body) -> dict:
            if not isinstance(body, dict):
                body = {}
            log.info("qt.bridge.update_config body=%s", body)
            try:
                return _services().config.update_config(body=body)
            except Exception as exc:
                log.exception("qt bridge updateConfig failed")
                return {"error": str(exc), "code": "bridge_error"}

        @Slot(str, result="QVariantMap")
        def getIconDataUrl(self, app_short: str = "") -> dict:
            app_short = str(app_short or "").strip()
            log.info("qt.bridge.get_icon_data_url app_short=%s", app_short)
            try:
                return _services().config.get_icon(app_short=app_short)
            except Exception as exc:
                log.exception("qt bridge getIconDataUrl failed")
                return {"error": str(exc), "code": "bridge_error", "app_short": app_short}

        @Slot(result="QVariantMap")
        def getCategoryNames(self) -> dict:
            log.info("qt.bridge.get_category_names")
            try:
                return _services().config.get_category_names()
            except Exception as exc:
                log.exception("qt bridge getCategoryNames failed")
                return {"error": str(exc), "code": "bridge_error", "ok": False}

        @Slot(str, result="QVariantMap")
        def deleteCategory(self, name: str = "") -> dict:
            log.info("qt.bridge.delete_category name=%s", name)
            try:
                return _services().config.delete_category(name=name)
            except Exception as exc:
                if hasattr(exc, 'payload') and isinstance(exc.payload, dict) and exc.payload:
                    return exc.payload
                log.exception("qt bridge deleteCategory failed")
                code = getattr(exc, 'code', 'bridge_error')
                return {"error": str(exc), "code": code, "ok": False}

        @Slot(result="QVariantMap")
        def checkUpdate(self) -> dict:
            log.info("qt.bridge.check_update")
            try:
                return _services().config.check_update()
            except Exception as exc:
                log.exception("qt bridge checkUpdate failed")
                return {"error": str(exc), "code": "bridge_error", "ok": False}

        @Slot(str, result="QVariantMap")
        def openUrlAction(self, action: str = "") -> dict:
            log.info("qt.bridge.open_url_action action=%s", action)
            try:
                return _services().config.open_url_action(action=action)
            except Exception as exc:
                if hasattr(exc, 'payload') and isinstance(exc.payload, dict) and exc.payload:
                    return exc.payload
                log.exception("qt bridge openUrlAction failed")
                code = getattr(exc, 'code', 'bridge_error')
                return {"error": str(exc), "code": code, "ok": False}

        @Slot(bool, result="QVariantMap")
        def setDnd(self, on: bool) -> dict:
            log.info("qt.bridge.set_dnd on=%s", bool(on))
            try:
                return _services().rest.set_dnd(on=bool(on))
            except Exception as exc:
                log.exception("qt bridge setDnd failed")
                return {"error": str(exc), "code": "bridge_error", "dnd": bool(on)}

        @Slot(result="QVariantMap")
        def getAppsList(self) -> dict:
            log.info("qt.bridge.get_apps_list")
            try:
                return _services().stats.get_apps_list()
            except Exception as exc:
                log.exception("qt bridge getAppsList failed")
                return {"error": str(exc), "code": "bridge_error", "apps": []}

        @Slot("QVariantMap", result="QVariantMap")
        def getAppDetails(self, query) -> dict:
            if not isinstance(query, dict):
                query = {}
            log.info("qt.bridge.get_app_details query=%s", query)
            try:
                return _services().stats.get_app_details(query=query)
            except Exception as exc:
                log.exception("qt bridge getAppDetails failed")
                return {"error": str(exc), "code": "bridge_error"}

        @Slot(result="QVariantMap")
        def getBlacklist(self) -> dict:
            log.info("qt.bridge.get_blacklist")
            try:
                return _services().stats.get_blacklist()
            except Exception as exc:
                log.exception("qt bridge getBlacklist failed")
                return {"error": str(exc), "code": "bridge_error", "apps": []}

        @Slot(str, result="QVariantMap")
        def removeFromBlacklist(self, app_short: str = "") -> dict:
            app_short = str(app_short or "").strip()
            log.info("qt.bridge.remove_from_blacklist app_short=%s", app_short)
            try:
                return _services().stats.remove_from_blacklist(app_short=app_short)
            except Exception as exc:
                log.exception("qt bridge removeFromBlacklist failed")
                return {"error": str(exc), "code": "bridge_error", "app_short": app_short}

        @Slot("QVariantMap", result="QVariantMap")
        def updateAppSettings(self, body) -> dict:
            if not isinstance(body, dict):
                body = {}
            log.info("qt.bridge.update_app_settings body=%s", body)
            try:
                return _services().stats.update_app_settings(body=body)
            except Exception as exc:
                log.exception("qt bridge updateAppSettings failed")
                return {"error": str(exc), "code": "bridge_error"}

        @Slot(str, result="QVariantMap")
        def excludeApp(self, app_short: str = "") -> dict:
            app_short = str(app_short or "").strip()
            log.info("qt.bridge.exclude_app app_short=%s", app_short)
            try:
                return _services().stats.exclude_app(app_short=app_short)
            except Exception as exc:
                log.exception("qt bridge excludeApp failed")
                return {"error": str(exc), "code": "bridge_error", "app_short": app_short}

        @Slot(result="QVariantMap")
        def startRest(self) -> dict:
            log.info("qt.bridge.start_rest")
            try:
                return _services().rest.start_rest(headers={}, remote_addr=None)
            except Exception as exc:
                if hasattr(exc, 'payload') and isinstance(exc.payload, dict) and exc.payload:
                    return exc.payload
                log.exception("qt bridge startRest failed")
                return {"error": str(exc), "code": "bridge_error", "ok": False}

        @Slot(int, result="QVariantMap")
        def restReadyForShow(self, screen_idx: int = 0) -> dict:
            idx = int(screen_idx or 0)
            for overlay in rest_overlays:
                if overlay.screen_idx != idx:
                    continue
                overlay.rest_ready = True
                log.info("qt.bridge.rest_ready_for_show screen=%s", idx)
                if rest_pending_show.get("value") and not overlay.rest_started:
                    overlay.show_overlay(duration_s=_rest_duration_seconds())
                return {"ok": True, "screen": idx, "ready": True}
            log.warning("qt.bridge.rest_ready_for_show missing_overlay screen=%s", idx)
            return {"ok": False, "screen": idx, "code": "overlay_missing"}

        @Slot(result="QVariantMap")
        def closeRestOverlay(self) -> dict:
            rest_pending_show["value"] = False
            closed = 0
            for overlay in rest_overlays:
                if overlay.isVisible() or overlay.rest_started:
                    overlay.hide_overlay()
                    closed += 1
            log.info("qt.bridge.close_rest_overlay closed=%s", closed)
            return {"ok": True, "closed": closed}

        @Slot(result="QVariantMap")
        def playRestEndSound(self) -> dict:
            result = _play_rest_end_sound()
            log.info("qt.bridge.play_rest_end_sound result=%s", result)
            return result

        @Slot("QVariantMap", result="QVariantMap")
        def restOverlayLog(self, payload) -> dict:
            if not isinstance(payload, dict):
                payload = {}
            try:
                summary = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                summary = str(payload)
            log.info("qt.bridge.rest_overlay_log payload=%s", summary[:500])
            return {"ok": True}

        @Slot(result="QVariantMap")
        def showRestOverlay(self) -> dict:
            try:
                _ensure_rest_overlays(self)
                rest_pending_show["value"] = True
                _show_ready_rest_overlays()
                ready = sum(1 for overlay in rest_overlays if overlay.rest_ready)
                total = len(rest_overlays)
                log.info("qt.bridge.show_rest_overlay ready=%s total=%s", ready, total)
                return {"ok": True, "ready": ready, "total": total}
            except Exception as exc:
                log.exception("qt bridge showRestOverlay failed")
                return {"ok": False, "error": str(exc), "code": "bridge_error"}

        @Slot(result="QVariantMap")
        def notifyReadyForShow(self) -> dict:
            try:
                window = _ensure_notify_window(self)
                window.notify_ready = True
                result = _try_show_pending_notify()
                log.info("qt.bridge.notify_ready_for_show result=%s", result)
                return {"ok": True, "ready": True, "result": result}
            except Exception as exc:
                log.exception("qt bridge notifyReadyForShow failed")
                return {"ok": False, "error": str(exc), "code": "bridge_error"}

        @Slot(str, result="QVariantMap")
        def notifyWindowAction(self, action: str = "") -> dict:
            raw_action = str(action or "")
            act = normalize_notify_window_action(raw_action)
            log.info("qt.bridge.notify_window_action action=%s normalized=%s", raw_action, act)
            if not act:
                return {"ok": False, "code": "unknown_action", "action": raw_action}
            try:
                window = _ensure_notify_window(self)
                prompt_key = getattr(window, "active_prompt_key", None)
                extra = getattr(window, "active_extra", {}) if isinstance(getattr(window, "active_extra", {}), dict) else {}
                window.hide_notify(reason=act)
                _notify_complete(prompt_key, extra)
                window.active_prompt_key = None
                window.active_extra = {}
                if act == "rest":
                    rest_result = self.showRestOverlay()
                    return {"ok": True, "action": act, "rest_overlay": rest_result}
                return {"ok": True, "action": act}
            except Exception as exc:
                log.exception("qt bridge notifyWindowAction failed")
                return {"ok": False, "error": str(exc), "code": "bridge_error", "action": act}

        @Slot("QVariantMap", result="QVariantMap")
        def notifyLog(self, payload) -> dict:
            if not isinstance(payload, dict):
                payload = {}
            try:
                summary = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                summary = str(payload)
            stage = str(payload.get("stage") or "")
            if stage and not getattr(_ensure_notify_window(self), "notify_ready", False):
                notify_window_ref["value"].notify_ready = True
                result = _try_show_pending_notify()
                log.info("qt.bridge.notify_log marked_ready stage=%s result=%s", stage, result)
            log.info("qt.bridge.notify_log payload=%s", summary[:500])
            return {"ok": True}

        @Slot(result="QVariantMap")
        def showNotifyProbe(self) -> dict:
            try:
                window = _ensure_notify_window(self)
                queued = _queue_notify_payload(extra={"debug_only": True}, prompt_key=None, debug_only=True, message="Qt notify probe")
                notify_pending_payload["value"]["auto_hide_s"] = 2
                result = _try_show_pending_notify()
                log.info("qt.bridge.show_notify_probe session=%s result=%s", queued.get("session"), result)
                return {"ok": True, "session": queued.get("session"), "result": result, "ready": bool(window.notify_ready)}
            except Exception as exc:
                log.exception("qt bridge showNotifyProbe failed")
                return {"ok": False, "error": str(exc), "code": "bridge_error"}

        @Slot(result="QVariantMap")
        def triggerDebugNotify(self) -> dict:
            try:
                ctrl = _controller()
                if hasattr(ctrl, "set_debug_notify"):
                    ctrl.set_debug_notify(True)
                if hasattr(ctrl, "debug_trigger_notify_show"):
                    ctrl.debug_trigger_notify_show()
                log.info("qt.bridge.trigger_debug_notify ok=True")
                return {"ok": True}
            except Exception as exc:
                log.exception("qt bridge triggerDebugNotify failed")
                return {"ok": False, "error": str(exc), "code": "bridge_error"}

        @Slot(result="QVariantMap")
        def triggerNaturalNotify(self) -> dict:
            try:
                ctrl = _controller()
                manager = notification_manager_ref.get("value")
                if manager is None:
                    return {"ok": False, "code": "manager_unavailable"}
                if hasattr(ctrl, "debug_force_rest_due"):
                    ctrl.debug_force_rest_due()
                _vm, extra = ctrl.snapshot_today(mark_prompted=False)
                manager.on_snapshot(extra)
                rest = (extra or {}).get("rest") or {}
                log.info("qt.bridge.trigger_natural_notify rest=%s", rest)
                return {
                    "ok": True,
                    "due": bool(rest.get("due")),
                    "should_prompt": bool(rest.get("should_prompt")),
                    "work_s": int(rest.get("work_s") or 0),
                    "threshold_s": int(rest.get("threshold_s") or 0),
                }
            except Exception as exc:
                log.exception("qt bridge triggerNaturalNotify failed")
                return {"ok": False, "error": str(exc), "code": "bridge_error"}

        @Slot(result=bool)
        def closeWindow(self) -> bool:
            log.info("qt.bridge.close_window")
            try:
                _main_window().close()
                return True
            except Exception:
                log.exception("qt bridge closeWindow failed")
                return False

        @Slot(result=bool)
        def minimizeWindow(self) -> bool:
            log.info("qt.bridge.minimize_window")
            try:
                _main_window().showMinimized()
                return True
            except Exception:
                log.exception("qt bridge minimizeWindow failed")
                return False

        @Slot(result=bool)
        def maximizeToggle(self) -> bool:
            log.info("qt.bridge.maximize_toggle")
            try:
                w = _main_window()
                if w.isMaximized():
                    w.showNormal()
                else:
                    w.showMaximized()
                return True
            except Exception:
                log.exception("qt bridge maximizeToggle failed")
                return False

        @Slot(result="QVariantMap")
        def exportAll(self) -> dict:
            log.info("qt.bridge.export_all")
            try:
                from eye_care.data.transfer import export_all
                db_path = data_dir / "eyecare.db"
                if db_path.exists():
                    import sqlite3
                    conn = sqlite3.connect(str(db_path))
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.close()
                path = _create_file_dialog_safe(
                    "save",
                    save_filename="eye_care_export.zip",
                    file_types=("ZIP Files (*.zip)", "All files (*.*)"),
                )
                if not path:
                    return {"status": "cancel"}
                out_path = Path(path if isinstance(path, str) else path[0]).resolve()
                meta = export_all(data_dir, out_path)
                return {"status": "ok", "path": str(out_path), "meta": meta}
            except Exception as exc:
                log.exception("qt bridge exportAll failed")
                return {"status": "error", "error": str(exc)}

        @Slot(result="QVariantMap")
        def importAll(self) -> dict:
            log.info("qt.bridge.import_all")
            try:
                from eye_care.data.transfer import import_all
                ctrl = _controller()
                path = _create_file_dialog_safe(
                    "open",
                    allow_multiple=False,
                    file_types=("ZIP Files (*.zip)", "JSON Files (*.json)", "All files (*.*)"),
                )
                if not path:
                    return {"status": "cancel"}
                in_path = Path(path if isinstance(path, str) else path[0]).resolve()
                res = import_all(data_dir, in_path, repo=ctrl.repo)
                try:
                    ctrl.repo.merge()
                except Exception as merge_exc:
                    log.warning("qt importAll: repo.merge after import failed: %s", merge_exc)
                return {"status": "ok", "path": str(in_path), "result": res}
            except Exception as exc:
                log.exception("qt bridge importAll failed")
                return {"status": "error", "error": str(exc)}

        @Slot(result="QVariantMap")
        def exportSettings(self) -> dict:
            log.info("qt.bridge.export_settings")
            try:
                from dataclasses import asdict
                ctrl = _controller()
                path = _create_file_dialog_safe(
                    "save",
                    save_filename="eye_care_settings.json",
                    file_types=("JSON Files (*.json)", "All files (*.*)"),
                )
                if not path:
                    return {"status": "cancel"}
                out_path = Path(path if isinstance(path, str) else path[0]).resolve()
                raw = asdict(ctrl.cfg)
                raw.pop("sample_interval_s", None)
                raw.pop("debug_enabled", None)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
                return {"status": "ok", "path": str(out_path)}
            except Exception as exc:
                log.exception("qt bridge exportSettings failed")
                return {"status": "error", "error": str(exc)}

        @Slot(result="QVariantMap")
        def importSettings(self) -> dict:
            log.info("qt.bridge.import_settings")
            try:
                from dataclasses import asdict, fields
                from eye_care.config.models import AppConfig
                from eye_care.config.store import save_config
                ctrl = _controller()
                path = _create_file_dialog_safe(
                    "open",
                    allow_multiple=False,
                    file_types=("JSON Files (*.json)", "All files (*.*)"),
                )
                if not path:
                    return {"status": "cancel"}
                in_path = Path(path if isinstance(path, str) else path[0]).resolve()
                data = json.loads(in_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    return {"status": "error", "error": "?????????"}
                allowed = {f.name for f in fields(AppConfig)}
                export_excluded = {"sample_interval_s", "debug_enabled"}
                filtered = {k: v for k, v in data.items() if k in allowed and k not in export_excluded}
                current = asdict(ctrl.cfg) if hasattr(ctrl, "cfg") else {}
                merged = {**current, **filtered}
                merged = {k: merged[k] for k in allowed if k in merged}
                for key, default in (("app_category_overrides", {}), ("app_display_overrides", {}), ("app_auto_dnd_on_focus", {}), ("blacklist_apps", [])):
                    if key not in merged:
                        merged[key] = default
                    if key == "blacklist_apps" and isinstance(merged[key], list):
                        merged[key] = [str(x).strip() for x in merged[key] if x]
                new_cfg = AppConfig(**merged)
                ctrl.cfg = new_cfg
                save_config(ctrl.cfg_path, ctrl.cfg)
                ctrl.on_config_updated()
                if hasattr(ctrl.repo, 'set_category_overrides'):
                    ctrl.repo.set_category_overrides(getattr(new_cfg, 'app_category_overrides', None) or {})
                if hasattr(new_cfg, 'startup_launch_at_login'):
                    try:
                        from eye_care.utils.launch_at_login import set_launch_at_login
                        set_launch_at_login(bool(new_cfg.startup_launch_at_login))
                    except Exception as launch_exc:
                        log.warning("qt importSettings: launch_at_login apply failed: %s", launch_exc)
                return {"status": "ok", "path": str(in_path)}
            except Exception as exc:
                log.exception("qt bridge importSettings failed")
                return {"status": "error", "error": str(exc)}

    probe_script = """
(function() {
  if (window.__EYECARE_QT_PROBE_BOOTED__) return 'already-booted';
  window.__EYECARE_QT_PROBE_BOOTED__ = true;
  window.__EYECARE_QT_CHANNEL_PROMISE__ = new Promise(function(resolve) {
    window.__EYECARE_QT_CHANNEL_RESOLVE__ = resolve;
  });

  function logInfo(message) {
    try { console.info(message); } catch (e) {}
  }

  function logError(message) {
    try { console.error(message); } catch (e) {}
  }

  function bootChannel() {
    if (!(window.qt && window.qt.webChannelTransport)) {
      logError('qt.channel_transport_missing');
      return;
    }
    if (typeof window.QWebChannel !== 'function') {
      logError('qt.channel_constructor_missing');
      return;
    }
    new window.QWebChannel(window.qt.webChannelTransport, function(channel) {
      window.qtBridge = channel.objects.qtBridge || null;
      window.__EYECARE_QT_CHANNEL_READY__ = !!window.qtBridge;
      window.__EYECARE_QT_CALL__ = function(method, args) {
        args = Array.isArray(args) ? args.slice() : [];
        return new Promise(function(resolve, reject) {
          var target = window.qtBridge;
          if (!target || typeof target[method] !== 'function') {
            reject(new Error('qt bridge method unavailable: ' + method));
            return;
          }
          try {
            target[method].apply(target, args.concat([function(result) { resolve(result); }]));
          } catch (error) {
            reject(error);
          }
        });
      };
      if (typeof window.__EYECARE_QT_CHANNEL_RESOLVE__ === 'function') {
        window.__EYECARE_QT_CHANNEL_RESOLVE__(window.qtBridge);
        window.__EYECARE_QT_CHANNEL_RESOLVE__ = null;
      }
      logInfo('qt.channel_ready=' + String(window.__EYECARE_QT_CHANNEL_READY__));
      try {
        var mainLinks = Array.prototype.map.call(document.querySelectorAll('link[rel="stylesheet"]'), function(node) { return node.href || ''; });
        var mainScripts = Array.prototype.map.call(document.querySelectorAll('script[src]'), function(node) { return node.src || ''; });
        logInfo('qt.main_static_probe=' + JSON.stringify({ href: window.location.href || '', links: mainLinks, scripts: mainScripts }));
      } catch (e) {}
      if (!window.qtBridge) {
        logError('qt.bridge_missing');
        return;
      }
      window.qtBridge.getRuntimeInfo(function(info) {
        logInfo('qt.runtime_info=' + JSON.stringify(info || {}));
        window.qtBridge.ping('step4-probe', function(reply) {
          logInfo('qt.ping_reply=' + JSON.stringify(reply || {}));
          window.qtBridge.log('info', 'step4-probe', JSON.stringify(reply || {}), function(ack) {
            logInfo('qt.log_ack=' + JSON.stringify(ack));
            window.qtBridge.getConfig(function(configData) {
              var cfg = (configData && configData.config) ? configData.config : {};
              logInfo('qt.config_probe_keys=' + String(Object.keys(cfg).length));
            });
            window.qtBridge.getBlacklist(function(blacklistData) {
              var apps = (blacklistData && blacklistData.apps) ? blacklistData.apps : [];
              logInfo('qt.blacklist_probe_count=' + String(apps.length));
            });
            logInfo('qt.app_settings_bridge_ready=' + String(!!(window.qtBridge && typeof window.qtBridge.updateAppSettings === 'function' && typeof window.qtBridge.excludeApp === 'function')));
            logInfo('qt.category_bridge_ready=' + String(!!(window.qtBridge && typeof window.qtBridge.getCategoryNames === 'function' && typeof window.qtBridge.deleteCategory === 'function')));
            logInfo('qt.update_bridge_ready=' + String(!!(window.qtBridge && typeof window.qtBridge.checkUpdate === 'function' && typeof window.qtBridge.openUrlAction === 'function')));
            if (window.qtBridge && typeof window.qtBridge.getCategoryNames === 'function') {
              window.qtBridge.getCategoryNames(function(categoryData) {
                var categories = (categoryData && categoryData.categories) ? categoryData.categories : [];
                logInfo('qt.category_names_probe=' + JSON.stringify({ count: categories.length, first: categories.length ? categories[0] : null }));
              });
            }
            if (window.qtBridge && typeof window.qtBridge.checkUpdate === 'function') {
              window.qtBridge.checkUpdate(function(updateData) {
                logInfo('qt.update_check_probe=' + JSON.stringify({ ok: !!(updateData && updateData.ok), has_update: !!(updateData && updateData.has_update), error: updateData && updateData.error ? updateData.error : '' }));
              });
            }
            logInfo('qt.rest_start_bridge_ready=' + String(!!(window.qtBridge && typeof window.qtBridge.startRest === 'function' && typeof window.qtBridge.showRestOverlay === 'function')));
            logInfo('qt.rest_sound_bridge_ready=' + String(!!(window.qtBridge && typeof window.qtBridge.playRestEndSound === 'function')));
            logInfo('qt.notify_bridge_ready=' + String(!!(window.qtBridge && typeof window.qtBridge.showNotifyProbe === 'function' && typeof window.qtBridge.triggerDebugNotify === 'function' && typeof window.qtBridge.triggerNaturalNotify === 'function' && typeof window.qtBridge.notifyReadyForShow === 'function' && typeof window.qtBridge.notifyWindowAction === 'function' && typeof window.qtBridge.notifyLog === 'function')));
            logInfo('qt.desktop_bridge_ready=' + String(!!(window.qtBridge && typeof window.qtBridge.closeWindow === 'function' && typeof window.qtBridge.minimizeWindow === 'function' && typeof window.qtBridge.maximizeToggle === 'function' && typeof window.qtBridge.exportAll === 'function' && typeof window.qtBridge.importAll === 'function' && typeof window.qtBridge.exportSettings === 'function' && typeof window.qtBridge.importSettings === 'function')));
            if (window.qtBridge && typeof window.qtBridge.playRestEndSound === 'function') {
              window.qtBridge.playRestEndSound(function(soundResult) {
                logInfo('qt.rest_end_sound_probe=' + JSON.stringify(soundResult || {}));
              });
            }
            window.qtBridge.showNotifyProbe(function(notifyProbeResult) {
              logInfo('qt.show_notify_probe=' + JSON.stringify(notifyProbeResult || {}));
              if (window.qtBridge && typeof window.qtBridge.triggerDebugNotify === 'function') {
                setTimeout(function() {
                  window.qtBridge.triggerDebugNotify(function(debugNotifyResult) {
                    logInfo('qt.trigger_debug_notify=' + JSON.stringify(debugNotifyResult || {}));
                  });
                }, 400);
              }
              if (window.qtBridge && typeof window.qtBridge.triggerNaturalNotify === 'function') {
                setTimeout(function() {
                  window.qtBridge.triggerNaturalNotify(function(naturalNotifyResult) {
                    logInfo('qt.trigger_natural_notify=' + JSON.stringify(naturalNotifyResult || {}));
                  });
                }, 2600);
              }
            });
            window.qtBridge.showRestOverlay(function(restOverlayResult) {
              logInfo('qt.show_rest_overlay_probe=' + JSON.stringify(restOverlayResult || {}));
              if (restOverlayResult && restOverlayResult.ok && typeof window.qtBridge.closeRestOverlay === 'function') {
                setTimeout(function() {
                  window.qtBridge.closeRestOverlay(function(closeResult) {
                    logInfo('qt.close_rest_overlay_probe=' + JSON.stringify(closeResult || {}));
                  });
                }, 1200);
              }
            });
            window.qtBridge.getAppsList(function(appsData) {
              var apps = (appsData && appsData.apps) ? appsData.apps : [];
              var first = apps.length > 0 ? apps[0] : null;
              var appKey = first && (first.app_short || first.appShort || first.key || '');
              logInfo('qt.apps_list_probe_count=' + String(apps.length));
              logInfo('qt.apps_list_probe_first=' + JSON.stringify(first || null));
              if (appKey) {
                if (typeof window.qtBridge.getIconDataUrl === 'function') {
                  window.qtBridge.getIconDataUrl(appKey, function(iconData) {
                    var hasIcon = !!(iconData && iconData.data_url);
                    logInfo('qt.icon_probe=' + JSON.stringify({ app: appKey, ok: hasIcon, cache: iconData && iconData.cache ? iconData.cache : null }));
                  });
                }
                var now = new Date();
                var y = now.getFullYear();
                var m = now.getMonth() + 1;
                var d = now.getDate();
                var dateStr = y + '-' + (m < 10 ? '0' + m : String(m)) + '-' + (d < 10 ? '0' + d : String(d));
                var query = { app: appKey, days: 7, date: dateStr };
                logInfo('qt.app_details_probe_query=' + JSON.stringify(query));
                window.qtBridge.getAppDetails(query, function(detailData) {
                  var total = detailData && detailData.total_seconds ? detailData.total_seconds : 0;
                  logInfo('qt.app_details_probe_total=' + String(total));
                });
              }
            });
            var now = new Date();
            window.qtBridge.getCalendarMonth(now.getFullYear(), now.getMonth() + 1, function(monthData) {
              var days = (monthData && monthData.days_with_data) ? monthData.days_with_data.length : 0;
              logInfo('qt.calendar_month_probe_days=' + String(days));
            });
            window.qtBridge.getSnapshot({}, function(snapshotData) {
              var state = (snapshotData && snapshotData.state) ? snapshotData.state : {};
              var currentDnd = !!state.is_dnd;
              window.qtBridge.setDnd(currentDnd, function(dndData) {
                logInfo('qt.set_dnd_probe=' + JSON.stringify(dndData || {}));
              });
            });
          });
        });
      });
    });
  }

  if (typeof window.QWebChannel === 'function') {
    bootChannel();
    return 'channel-ready';
  }

  var script = document.createElement('script');
  script.src = 'qrc:///qtwebchannel/qwebchannel.js';
  script.onload = function() { bootChannel(); };
  script.onerror = function() {
    if (typeof window.__EYECARE_QT_CHANNEL_RESOLVE__ === 'function') {
      window.__EYECARE_QT_CHANNEL_RESOLVE__(null);
      window.__EYECARE_QT_CHANNEL_RESOLVE__ = null;
    }
    logError('qt.channel_script_load_failed');
  };
  (document.head || document.documentElement).appendChild(script);
  return 'channel-loading';
})();
"""

    auto_quit_ms = int(os.environ.get("EYECARE_QT_AUTO_QUIT_MS", "0") or "0")

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("EyE Care (Qt Host)")
            self.resize(1400, 860)
            self.view = QWebEngineView(self)
            self.page = LoggingWebPage(page_role="main")
            self.channel = QWebChannel(self.page)
            self.bridge = QtBridgeProbe()
            qt_bridge_ref["value"] = self.bridge
            self.channel.registerObject("qtBridge", self.bridge)
            self.page.setWebChannel(self.channel)
            self.view.setPage(self.page)
            self.setCentralWidget(self.view)
            self.view.loadFinished.connect(self._on_load_finished)
            main_html = render_main_html(
                index_path=UI_INDEX_PATH,
                inject_bridge_script=inject_bridge_script,
                inject_drag_region=inject_drag_region,
                enable_drag_region_inject=ENABLE_DRAG_REGION_INJECT,
            )
            self.view.setHtml(main_html, QUrl(build_ui_page_url(api_port=api_port, page="main")))

        def _on_load_finished(self, ok: bool) -> None:
            log.info("qt.main_page_load_finished ok=%s url=%s", bool(ok), self.view.url().toString())
            if ok:
                self.page.runJavaScript(probe_script)
            if auto_quit_ms > 0:
                QTimer.singleShot(auto_quit_ms, app.quit)

    class QtTrayController(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.icon_path = PROJECT_ROOT / "icon.ico"
            self.tray = QSystemTrayIcon(self)
            self.menu = QMenu()
            self.actions = {}
            icon = QIcon(str(self.icon_path))
            if icon.isNull():
                icon = QIcon()
                log.warning("qt.tray.icon_missing path=%s", self.icon_path)
            self.tray.setIcon(icon)
            self.tray.setToolTip("EyE Care")
            self._build_menu()
            self.tray.setContextMenu(self.menu)
            self.tray.activated.connect(self._on_activated)

        def _add_action(self, key: str, text: str, callback, *, checkable: bool = False) -> QAction:
            action = QAction(text, self.menu)
            action.setCheckable(checkable)
            action.triggered.connect(lambda checked=False, cb=callback: cb())
            self.menu.addAction(action)
            self.actions[key] = action
            return action

        def _build_menu(self) -> None:
            self._add_action("show_main", "?????", _show_main_window)
            self._add_action("rest_start", "????", _start_rest_from_tray)
            self.menu.addSeparator()
            self._add_action("mode_normal", "??", lambda: _set_run_mode("normal"), checkable=True)
            self._add_action("mode_dnd", "??", lambda: _set_run_mode("dnd"), checkable=True)
            self._add_action("mode_leave", "??", lambda: _set_run_mode("leave"), checkable=True)
            self.menu.addSeparator()
            self._add_action("open_settings", "????", _open_settings)
            self._add_action("check_update", "????", _check_update_from_tray)
            self._add_action("open_data_dir", "??????", _open_data_dir)
            self.menu.addSeparator()
            self._add_action("quit", "??", _quit_from_tray)
            self.aboutToShow = self.menu.aboutToShow
            self.aboutToShow.connect(self._sync_menu_state)

        def _sync_menu_state(self) -> None:
            state = getattr(controller, "state", None) if controller is not None else None
            mode = "normal"
            if state is not None:
                if bool(getattr(state, "force_idle", False)):
                    mode = "leave"
                elif bool(getattr(state, "is_dnd", False)):
                    mode = "dnd"
            self.actions["mode_normal"].setChecked(mode == "normal")
            self.actions["mode_dnd"].setChecked(mode == "dnd")
            self.actions["mode_leave"].setChecked(mode == "leave")
            log.info("qt.tray.menu_sync mode=%s", mode)

        def _on_activated(self, reason) -> None:
            trigger = getattr(QSystemTrayIcon, "Trigger", None)
            double_click = getattr(QSystemTrayIcon, "DoubleClick", None)
            if reason in (trigger, double_click):
                log.info("qt.tray.activated reason=%s", int(reason))
                _show_main_window()

        def start(self) -> bool:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                log.warning("qt.tray.unavailable")
                return False
            self._sync_menu_state()
            self.tray.show()
            log.info("qt.tray.started icon=%s", self.icon_path)
            return True

        def stop(self) -> None:
            try:
                self.tray.hide()
                log.info("qt.tray.stopped")
            except Exception:
                log.exception("qt tray stop failed")

        def run_probe(self) -> None:
            log.info("qt.tray.probe_start")
            QTimer.singleShot(500, lambda: self.actions["show_main"].trigger())
            QTimer.singleShot(900, lambda: self.actions["mode_dnd"].trigger())
            QTimer.singleShot(1300, lambda: self.actions["mode_normal"].trigger())
            QTimer.singleShot(1700, lambda: self.actions["rest_start"].trigger())
            QTimer.singleShot(2200, lambda: self.actions["open_settings"].trigger())
            QTimer.singleShot(2700, lambda: self.actions["check_update"].trigger())
            if os.environ.get("EYECARE_QT_TRAY_PROBE_QUIT", "0") == "1":
                QTimer.singleShot(3400, lambda: self.actions["quit"].trigger())

    app = QApplication.instance() or QApplication([sys.argv[0]])

    from eye_care.notify.notification_manager import NotificationManager
    from eye_care.notify.notifier_service import NotifierService

    notify_dispatcher = QtNotifyDispatcher()
    notify_dispatcher.notifyShowRequested.connect(_handle_notify_task)

    def _mark_notified() -> None:
        try:
            if controller is not None:
                controller.mark_rest_notified()
        except Exception:
            log.exception("qt mark_rest_notified failed")

    notification_manager_ref["value"] = NotificationManager.get_instance(
        dispatcher=notify_dispatcher,
        show_toast_fallback=lambda _extra: log.info("qt notify toast fallback suppressed"),
        min_interval_s=60,
        mark_notified=_mark_notified,
    )
    notifier_service_ref["value"] = NotifierService(
        controller_getter=lambda: controller,
        notification_manager=notification_manager_ref["value"],
        poll_interval_s=1.0,
    )

    try:
        if controller is not None and hasattr(controller, "set_debug_post_notify_show"):
            from eye_care.utils.time_utils import local_date_today

            def _debug_post_notify_show() -> None:
                extra = {
                    "rest": {
                        "should_prompt": True,
                        "prompt_reason": "?????Qt notify ????",
                    },
                    "debug": {"notify": True},
                    "debug_only": True,
                }
                notify_dispatcher.post_notify_show(extra, (local_date_today(), -1))

            controller.set_debug_post_notify_show(_debug_post_notify_show)
    except Exception:
        log.exception("qt set_debug_post_notify_show failed")

    try:
        notify_enabled = bool(getattr(getattr(controller, "cfg", None), "notify_enabled", True)) if controller is not None else True
        if notify_enabled:
            notifier_service_ref["value"].start()
    except Exception:
        log.exception("qt notifier_service start failed")

    window = MainWindow()
    main_window_ref["value"] = window
    window.show()

    tray = QtTrayController()
    tray_ref["value"] = tray
    tray_started = tray.start()
    log.info("qt.tray.start_result ok=%s", tray_started)
    if tray_started and os.environ.get("EYECARE_QT_TRAY_PROBE", "0") == "1":
        tray.run_probe()

    def _shutdown() -> None:
        tray = tray_ref.get("value")
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                log.exception("qt shutdown: tray.stop failed")
        notifier = notifier_service_ref.get("value")
        if notifier is not None:
            try:
                notifier.stop(timeout_s=2.0)
            except Exception:
                log.exception("qt shutdown: notifier.stop failed")
        if controller is not None:
            try:
                controller.stop()
            except Exception:
                log.exception("qt shutdown: controller.stop failed")

    app.aboutToQuit.connect(_shutdown)

    if no_single:
        log.info("qt host single-instance bypass enabled")

    app.exec()
