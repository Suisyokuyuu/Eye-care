from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from eye_care.bootstrap.constants import DEFAULT_API_PORT, ENABLE_DRAG_REGION_INJECT, PROJECT_ROOT, UI_INDEX_PATH, UI_WEB_DIR
from eye_care.bootstrap.bridge_inject import inject_bridge_script, inject_drag_region
from eye_care.ui.app_runtime import start_backend_services, wait_flask_ready
from eye_care.ui.web_routes import build_ui_page_url


def run_qt_shell(data_dir: Path, no_single: bool, api_port: int, debug_console: bool = False) -> None:
    os.chdir(str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT))

    from eye_care.api.server import create_app
    from eye_care.controller.app_controller import AppController
    from eye_care.diagnostics.logging_setup import setup_logging
    from eye_care.ui.web_routes import mount_ui_site_routes
    from eye_care.services.registry import build_service_registry

    try:
        from PySide6.QtCore import QObject, QTimer, QUrl, Slot
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWidgets import QApplication, QMainWindow
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except Exception as exc:  # pragma: no cover - depends on local runtime
        raise RuntimeError("PySide6/QWebEngine is required for --host qt") from exc

    setup_logging(data_dir / "debug.log")
    log = logging.getLogger(__name__)
    log.info("host=qt startup: api_port=%s debug_console=%s", api_port, debug_console)

    controller = None
    controller_ready = {"value": False}
    flask_ready = {"value": False}
    services = {"value": None}

    def _set_controller(ctrl) -> None:
        nonlocal controller
        controller = ctrl
        services["value"] = build_service_registry(controller=ctrl, log=log)

    def _services():
        current = services.get("value")
        if current is None:
            raise RuntimeError("qt bridge services are not ready")
        return current

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
            window.qtBridge.getAppsList(function(appsData) {
              var apps = (appsData && appsData.apps) ? appsData.apps : [];
              var first = apps.length > 0 ? apps[0] : null;
              var appKey = first && (first.app_short || first.appShort || first.key || '');
              logInfo('qt.apps_list_probe_count=' + String(apps.length));
              logInfo('qt.apps_list_probe_first=' + JSON.stringify(first || null));
              if (appKey) {
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

    class LoggingWebPage(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line_number, source_id):
            level_name = getattr(level, "name", str(level))
            log.info(
                "qt.js_console level=%s line=%s source=%s message=%s",
                level_name,
                int(line_number),
                source_id or "",
                message,
            )

    auto_quit_ms = int(os.environ.get("EYECARE_QT_AUTO_QUIT_MS", "0") or "0")

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("EyE Care (Qt Host)")
            self.resize(1400, 860)
            self.view = QWebEngineView(self)
            self.page = LoggingWebPage(self.view)
            self.channel = QWebChannel(self.page)
            self.bridge = QtBridgeProbe()
            self.channel.registerObject("qtBridge", self.bridge)
            self.page.setWebChannel(self.channel)
            self.view.setPage(self.page)
            self.setCentralWidget(self.view)
            self.view.loadFinished.connect(self._on_load_finished)
            self.view.load(QUrl(build_ui_page_url(api_port=api_port, page="main")))

        def _on_load_finished(self, ok: bool) -> None:
            log.info("qt.main_page_load_finished ok=%s url=%s", bool(ok), self.view.url().toString())
            if ok:
                self.page.runJavaScript(probe_script)
            if auto_quit_ms > 0:
                QTimer.singleShot(auto_quit_ms, app.quit)

    app = QApplication.instance() or QApplication([sys.argv[0]])
    window = MainWindow()
    window.show()

    def _shutdown() -> None:
        if controller is not None:
            try:
                controller.stop()
            except Exception:
                log.exception("qt shutdown: controller.stop failed")

    app.aboutToQuit.connect(_shutdown)

    if no_single:
        log.info("qt host single-instance bypass enabled")

    app.exec()
