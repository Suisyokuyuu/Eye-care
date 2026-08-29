"""Qt 桌面宿主（QML 原生外壳）。

迁移完成后，主窗、休息全屏遮罩、通知气泡全部为 QML/Qt Quick 原生实现，
不再使用 QWebEngine / Flask / web SPA。后端 controller/services 经数据桥
（eye_care.qt_quick.*）直接喂给 QML，无 HTTP 中转。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from eye_care.bootstrap.constants import ASSETS_DIR, PROJECT_ROOT
from eye_care.ui.action_contracts import normalize_notify_window_action
from eye_care.ui.file_dialog import _create_file_dialog_safe


def run_qt_shell(data_dir: Path, no_single: bool, api_port: int = 0, debug_console: bool = False) -> None:
    os.chdir(str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT))

    # --debug 等价于 EYECARE_DEBUG=1（与 is_debug_enabled() 缓存一致，其首次调用在下方 setup_logging）。
    if debug_console:
        os.environ.setdefault("EYECARE_DEBUG", "1")

    from eye_care.controller.app_controller import AppController
    from eye_care.diagnostics import diag
    from eye_care.diagnostics.logging_setup import setup_logging
    from eye_care.services.registry import build_service_registry
    from eye_care.ui.win_effects import WinEffects

    try:
        from PySide6.QtCore import QMetaObject, QObject, QTimer, QUrl, Qt, Signal, Slot
        from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon
        from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
    except Exception as exc:  # pragma: no cover - depends on local runtime
        raise RuntimeError("PySide6 (QtQuick) is required for --host qt") from exc

    setup_logging(data_dir / "debug.log")
    log = logging.getLogger(__name__)

    debug_mode = (
        bool(debug_console)
        or os.environ.get("EYECARE_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
    )
    log.info("host=qt startup (qml shell): debug_mode=%s", debug_mode)

    win_effects = WinEffects(log)

    controller = None
    services = {"value": None}
    main_window_ref = {"value": None}
    rest_overlays = []
    rest_pending_show = {"value": False}
    notify_window_ref = {"value": None}
    notify_pending_payload = {"value": None}
    notification_manager_ref = {"value": None}
    notifier_service_ref = {"value": None}
    tray_ref = {"value": None}
    qt_bridge_ref = {"value": None}
    _qml_refs: dict = {}          # 持有 engine/bridges/poll/host_bridge 防 GC
    qml_root_ref = {"value": None}  # QML AppShell 根 Window

    def _qml_start_rest() -> None:
        """「立刻休息」：复用 host_bridge.startRest + showRestOverlay。"""
        hb = _qml_refs.get("host_bridge")
        if hb is None:
            log.warning("qt.qml_shell.rest: host_bridge 未就绪")
            return
        try:
            r = hb.startRest()
            log.info("qt.qml_shell.rest start_result=%s", r)
            hb.showRestOverlay()
        except Exception:
            log.exception("qt.qml_shell.rest failed")

    def _qml_invoke(method: str) -> None:
        """调用 QML 根上的无参函数（托盘→打开设置/更新页等）。"""
        root = qml_root_ref.get("value")
        if root is None:
            return
        try:
            QMetaObject.invokeMethod(root, method)
        except Exception:
            log.exception("qt.qml_shell.invoke %s failed", method)

    def _set_controller(ctrl) -> None:
        nonlocal controller
        controller = ctrl
        services["value"] = build_service_registry(controller=ctrl, log=log)

    def _services():
        current = services.get("value")
        if current is None:
            raise RuntimeError("qt bridge services are not ready")
        return current

    def _save_config() -> None:
        """Persist current controller config to disk."""
        ctrl = controller
        if ctrl is not None and hasattr(ctrl, "cfg") and hasattr(ctrl, "cfg_path"):
            try:
                from eye_care.config.store import save_config
                save_config(ctrl.cfg_path, ctrl.cfg)
                log.info("qt.config_saved")
            except Exception:
                log.exception("qt save config failed")

    def _controller():
        if controller is None:
            raise RuntimeError("qt controller is not ready")
        return controller

    def _refresh_dashboard() -> None:
        """立即刷新主界面左右栏（导入数据后调用，避免等最多 10s 轮询才看到新数据）。

        在 GUI 线程上调用（由 shellHost 槽触发的导入流程内），直接 refresh 两个数据桥即可。
        主界面没开/桥未就绪时静默跳过。
        """
        bridges = _qml_refs.get("bridges") or {}
        for key in ("leftPanelBridge", "rightPanelBridge"):
            b = bridges.get(key)
            if b is None:
                continue
            try:
                b.refresh()
            except Exception:
                log.exception("qt.refresh_dashboard %s failed", key)
        log.info("qt.refresh_dashboard done")

    def _main_window():
        current = main_window_ref.get("value")
        if current is None:
            raise RuntimeError("qt main window is not ready")
        return current

    def _show_main_window() -> None:
        window = _main_window()
        try:
            from PySide6.QtGui import QWindow as _QWindow
            if window.visibility() == _QWindow.Minimized:
                window.showNormal()
        except Exception:
            pass
        window.show()
        try:
            window.raise_()
        except Exception:
            pass
        try:
            window.requestActivate()
        except Exception:
            pass
        log.info("qt.tray.show_main_window")

    def _set_run_mode(mode: str) -> None:
        _controller().set_run_mode(mode)
        log.info("qt.tray.set_run_mode mode=%s", mode)
        tray = tray_ref.get("value")
        if tray is not None:
            try:
                tray._set_mode_icon(mode)
            except Exception:
                pass

    def _tray_mode_from_state() -> str:
        state = getattr(controller, "state", None) if controller is not None else None
        if state is None:
            return "normal"
        if bool(getattr(state, "is_dnd", False)):
            return "dnd"
        if bool(getattr(state, "force_idle", False)):
            return "leave"
        if bool(getattr(state, "auto_idle", False)):
            return "idle"
        return "normal"

    def _open_settings() -> None:
        _show_main_window()
        _qml_invoke("openSettings")

    def _start_rest_from_tray() -> None:
        _qml_start_rest()

    def _check_update_from_tray() -> None:
        _show_main_window()
        _qml_invoke("openUpdate")

    def _open_data_dir() -> None:
        os.startfile(str(data_dir))
        log.info("qt.tray.open_data_dir path=%s", data_dir)

    def _quit_from_tray() -> None:
        log.info("qt.tray.quit_requested")
        _shutdown()
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

    def _notify_auto_hide_seconds() -> int:
        try:
            cfg = getattr(_controller(), "cfg", None)
            if cfg is None:
                return 20
            value = getattr(cfg, "notify_auto_hide_seconds", 20)
            return max(0, min(600, int(20 if value is None else value)))
        except Exception:
            return 20

    def _play_rest_end_sound() -> dict:
        cfg = getattr(controller, "cfg", None) if controller is not None else None
        if cfg is not None and not bool(getattr(cfg, "rest_end_sound_enabled", True)):
            log.info("qt.rest_end_sound skipped (disabled)")
            return {"ok": False, "code": "disabled"}
        sound_path = ASSETS_DIR / "rest_end_refresh_soft.wav"
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

    def _play_notify_sound() -> None:
        """通知气泡提示音（gated by notify_sound_enabled）。"""
        cfg = getattr(controller, "cfg", None) if controller is not None else None
        if cfg is not None and not bool(getattr(cfg, "notify_sound_enabled", True)):
            log.info("qt.notify_sound skipped (disabled)")
            return
        sound_path = ASSETS_DIR / "notify_bubble_softer.wav"
        try:
            import winsound
            if not sound_path.exists():
                log.warning("qt.notify_sound missing path=%s", sound_path)
                return
            winsound.PlaySound(str(sound_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            log.info("qt.notify_sound_played path=%s", sound_path)
        except Exception:
            log.warning("qt.notify_sound failed", exc_info=True)

    def _try_show_pending_notify() -> dict:
        payload = notify_pending_payload.get("value")
        window = notify_window_ref.get("value")
        if not payload or window is None:
            return {"ok": False, "reason": "no_pending"}
        if not getattr(window, "notify_ready", False):
            return {"ok": False, "reason": "not_ready"}

        message = str(payload.get("message") or "Take a short break")
        raw_auto_hide = payload.get("auto_hide_s")
        auto_hide_s = int(_notify_auto_hide_seconds() if raw_auto_hide is None else raw_auto_hide)
        session = int(payload.get("session") or 0)
        if getattr(window, "notify_active_session", 0) == session and getattr(window, "notify_visible", False):
            return {"ok": True, "reason": "already_visible", "session": session}

        window.active_prompt_key = payload.get("prompt_key")
        window.active_extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        window.show_notify(message=message, auto_hide_s=auto_hide_s)
        window.notify_active_session = session
        _play_notify_sound()
        return {"ok": True, "reason": "shown", "session": session, "auto_hide_s": auto_hide_s}

    def _build_notify_message(extra: dict | None) -> str:
        payload = extra if isinstance(extra, dict) else {}
        rest = payload.get("rest") or {}
        message = str(rest.get("prompt_reason") or "您已连续用眼较长时间，建议稍作休息")
        return message.strip() or "您已连续用眼较长时间，建议稍作休息"

    def _queue_notify_payload(*, extra: dict | None, prompt_key=None, debug_only: bool = False, message: str | None = None) -> dict:
        window = notify_window_ref.get("value")
        session_seed = getattr(window, "notify_active_session", 0) if window is not None else 0
        session = int(session_seed or 0) + 1
        notify_pending_payload["value"] = {
            "message": str(message or _build_notify_message(extra)),
            "auto_hide_s": _notify_auto_hide_seconds(),
            "session": session,
            "extra": extra if isinstance(extra, dict) else {},
            "prompt_key": prompt_key,
            "debug_only": bool(debug_only),
        }
        return {"ok": True, "session": session, "ready": bool(getattr(window, "notify_ready", False) if window is not None else False)}

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

    # ───────────────────────── 通知气泡（QML 原生） ─────────────────────────
    class QmlNotifyAdapter:
        """QML 原生 notify 浮层适配器（QML 同步加载，notify_ready 恒 True）。

        actionTriggered("rest"/"snooze"/"dismiss") 走与原 notifyWindowAction
        相同的业务链：_notify_complete + （rest 时）showRestOverlay。
        """

        def __init__(self) -> None:
            from ..qt_quick.notify_overlay import QmlNotifyOverlay
            self.notify_ready = True
            self.notify_visible = False
            self.notify_active_session = 0
            self.active_prompt_key = None
            self.active_extra = {}
            self._overlay = QmlNotifyOverlay(on_action=self._on_action, win_effects=win_effects, log=log)
            log.info("qt.qml_notify_overlay_created")

        def show_notify(self, *, message: str, auto_hide_s: int) -> None:
            self._overlay.show_notify(message=message, auto_hide_s=int(auto_hide_s))
            self.notify_visible = True

        def hide_notify(self, *, reason: str = "dismiss") -> None:
            self._overlay.hide_notify(reason=reason)
            self.notify_visible = False

        def _on_action(self, name: str) -> None:
            # QML 已自渐隐（_handle_action 内部会调 hide_notify），此处只走业务。
            act = normalize_notify_window_action(name) or str(name or "")
            prompt_key = self.active_prompt_key
            extra = self.active_extra if isinstance(self.active_extra, dict) else {}
            self.notify_visible = False
            self.active_prompt_key = None
            self.active_extra = {}
            mark_notified = True
            is_natural_prompt = prompt_key is not None and not bool(extra.get("debug_only"))
            if act == "rest":
                bridge = qt_bridge_ref.get("value")
                if bridge is not None:
                    try:
                        start_result = bridge.startRest()
                        if bool((start_result or {}).get("ok")):
                            bridge.showRestOverlay()
                        else:
                            log.warning("qt.qml_notify_action rest start rejected result=%s", start_result)
                    except Exception:
                        log.exception("qt.qml_notify_action start/show rest failed")
            elif act == "snooze":
                # 通知上的「跳过本轮」是明确用户选择：等待一个完整提醒间隔后再提示下一轮。
                try:
                    if controller is not None and is_natural_prompt:
                        controller.rest_snooze()
                        mark_notified = False
                except Exception:
                    log.exception("qt.qml_notify_action snooze failed")
            elif act in ("dismiss", "auto-close"):
                # 关闭/自动消失也结束本轮提醒，等待一个完整提醒间隔后再提示下一轮。
                # 与「跳过本轮」分开记录，避免把自动消失计入用户主动跳过统计。
                try:
                    if controller is not None and is_natural_prompt:
                        controller.dismiss_rest_prompt()
                        mark_notified = False
                except Exception:
                    log.exception("qt.qml_notify_action dismiss failed")
            try:
                _notify_complete(prompt_key, extra, mark_notified=mark_notified)
            except Exception:
                log.exception("qt.qml_notify_action notify_complete failed name=%s", name)
            log.info("qt.qml_notify_action name=%s normalized=%s", name, act)

    def _ensure_notify_window(bridge: QObject = None):
        current = notify_window_ref.get("value")
        if current is not None:
            return current
        current = QmlNotifyAdapter()
        notify_window_ref["value"] = current
        return current

    # ───────────────────────── 休息全屏遮罩（QML 原生） ─────────────────────────
    def _qml_rest_finish(reason: str) -> None:
        """rest 业务收尾：complete=倒计时到点，snooze=点「跳过本轮」/Esc；随后关全部遮罩 + 释放守卫。"""
        try:
            if controller is not None:
                if reason == "complete":
                    controller.rest_complete()
                else:
                    controller.rest_snooze()
        except Exception:
            log.exception("qt.qml_rest_finish business failed reason=%s", reason)
        rest_pending_show["value"] = False
        for overlay in rest_overlays:
            try:
                if overlay.isVisible() or getattr(overlay, "rest_started", False):
                    overlay.hide_overlay()
            except Exception:
                log.exception("qt.qml_rest_finish hide failed")
        if controller is not None:
            try:
                controller.notify_rest_closed()
            except Exception:
                log.exception("qt.qml_rest_finish notify_rest_closed failed")
        log.info("qt.qml_rest_finish reason=%s", reason)

    def _on_qml_rest_complete() -> None:
        _play_rest_end_sound()
        _qml_rest_finish("complete")

    def _on_qml_rest_snooze() -> None:
        _qml_rest_finish("snooze")

    def _ensure_rest_overlays(bridge: QObject = None) -> None:
        screens = QGuiApplication.screens() or []
        wanted_names = [str(screen.name()) for screen in screens]
        current_names = [str(getattr(overlay, "screen_name", "")) for overlay in rest_overlays]
        if rest_overlays and current_names == wanted_names:
            for overlay in rest_overlays:
                overlay.sync_geometry()
            return
        # 屏幕拓扑发生变化时重建池；该函数只在准备显示新一轮休息时调用。
        for overlay in rest_overlays:
            try:
                overlay.hide_overlay()
            except Exception:
                pass
        rest_overlays.clear()
        from ..qt_quick.rest_overlay import QmlRestOverlay
        for idx, screen in enumerate(screens):
            rest_overlays.append(QmlRestOverlay(
                screen_idx=idx,
                screen=screen,
                on_snooze=_on_qml_rest_snooze,
                on_complete=_on_qml_rest_complete,
                win_effects=win_effects,
                log=log,
            ))
        log.info("qt.rest_overlay_pool_ready count=%s", len(rest_overlays))

    # ───────────────────────── 通知调度 ─────────────────────────
    class QtNotifyDispatcher(QObject):
        notifyShowRequested = Signal(object, object)

        def post_notify_show(self, extra: dict, prompt_key) -> None:
            self.notifyShowRequested.emit(extra, prompt_key)

    def _notify_complete(prompt_key, extra: dict | None, *, mark_notified: bool = True) -> None:
        manager = notification_manager_ref.get("value")
        if manager is None or prompt_key is None:
            return
        try:
            manager.on_notify_complete(prompt_key, True, extra or {}, mark_notified=mark_notified)
        except Exception:
            log.exception("qt notify complete callback failed")

    def _handle_notify_task(extra: dict, prompt_key) -> None:
        if notify_window_ref.get("value") is None:
            _ensure_notify_window()
        result = _queue_notify_payload(extra=extra, prompt_key=prompt_key, debug_only=bool((extra or {}).get("debug_only")), message=None)
        shown = _try_show_pending_notify()
        log.info("qt.notify_task_queued prompt_key=%s queue_result=%s show_result=%s", prompt_key, result, shown)

    # ───────────────────────── 宿主桥（QML 直接调用，不依赖 web view） ─────────────────────────
    class QtHostBridge(QObject):
        """QML 外壳的宿主桥：文件导入导出 / 关闭动作 / 休息。

        左右栏 + 设置 + 黑名单 + 应用 + 更新 + 日历各自有专用数据桥（eye_care.qt_quick.*），
        这里只承载与桌面宿主强耦合、QML 无法自办的几件事。
        """

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

        @Slot(str, result=bool)
        def setCloseAction(self, action: str) -> bool:
            """保存「关闭行为」偏好（关闭确认弹窗勾选"记住选择"）。

            做三件事，缺一不可：
              1) 写入 controller.cfg.close_action；
              2) **立即落盘**（save_config）——下次启动也记住；
              3) **同步设置页桥的内存 config**——否则同一次运行内 AppShell.requestClose() 读到的
                 还是旧 close_action（settingsBridge.config 是内存缓存，不刷新就一直是"ask"），
                 于是勾了记住、本次运行再点关闭仍弹确认（用户反馈：记不住）。
            """
            try:
                ctrl = controller
                if ctrl is None or not hasattr(ctrl, "cfg"):
                    return False
                val = str(action or "ask")
                if val not in ("ask", "minimize", "quit"):
                    val = "ask"
                ctrl.cfg.close_action = val
                _save_config()  # 立即落盘
                # 同步设置页桥内存 config（_qml_refs["bridges"] 在装配完成后即就绪；用户交互远晚于此）
                try:
                    sb = (_qml_refs.get("bridges") or {}).get("settingsBridge")
                    if sb is not None:
                        sb.reload()
                except Exception:
                    log.exception("qt.bridge.set_close_action sync settings bridge failed")
                log.info("qt.bridge.set_close_action action=%s saved+synced", val)
                return True
            except Exception:
                log.exception("qt bridge setCloseAction failed")
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
                _refresh_dashboard()  # 导入数据后立刻刷新主界面（若开着）
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
                    return {"status": "error", "error": "导入的数据格式不正确"}
                allowed = {f.name for f in fields(AppConfig)}
                export_excluded = {"sample_interval_s", "debug_enabled"}
                filtered = {k: v for k, v in data.items() if k in allowed and k not in export_excluded}
                current = asdict(ctrl.cfg) if hasattr(ctrl, "cfg") else {}
                merged = {**current, **filtered}
                merged = {k: merged[k] for k in allowed if k in merged}
                for key, default in (("app_category_overrides", {}), ("app_display_overrides", {}), ("app_auto_dnd_on_focus", {}), ("blacklist_apps", []), ("site_display_overrides", {})):
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
                # 导入设置会改黑名单/显示名/分类覆盖 → 主界面数据口径变；同步设置页内存 config 并刷新主界面
                try:
                    sb = (_qml_refs.get("bridges") or {}).get("settingsBridge")
                    if sb is not None:
                        sb.reload()
                except Exception:
                    log.exception("qt importSettings: sync settings bridge failed")
                _refresh_dashboard()
                return {"status": "ok", "path": str(in_path)}
            except Exception as exc:
                log.exception("qt bridge importSettings failed")
                return {"status": "error", "error": str(exc)}

    # ───────────────────────── 托盘 ─────────────────────────
    class QtTrayController(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.icon_path = PROJECT_ROOT / "icon.ico"
            self.tray = QSystemTrayIcon(self)
            self.menu = QMenu()
            self.menu.setStyleSheet("""
                QMenu{background:#000000;border:1px solid rgba(255,255,255,0.06);
                    border-radius:12px;padding:4px;}
                QMenu::item{padding:5px 22px 5px 12px;border-radius:4px;font-size:14px;color:rgba(255,255,255,0.80);}
                QMenu::item:selected{background:rgba(59,130,246,0.2);color:white;}
                QMenu::item:checked{background:rgba(59,130,246,0.12);color:white;}
                QMenu::separator{height:1px;background:rgba(255,255,255,0.04);margin:3px 8px;}
                QMenu::indicator{width:12px;height:12px;margin-left:2px;}
            """)
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
            self._add_action("show_main", "显示主界面", _show_main_window)
            self._add_action("rest_start", "立即休息", _start_rest_from_tray)
            self.menu.addSeparator()
            self._add_action("mode_normal", "正常", lambda: _set_run_mode("normal"), checkable=True)
            self._add_action("mode_dnd", "勿扰", lambda: _set_run_mode("dnd"), checkable=True)
            self._add_action("mode_leave", "离开", lambda: _set_run_mode("leave"), checkable=True)
            self.menu.addSeparator()
            self._add_action("open_settings", "打开设置", _open_settings)
            self._add_action("check_update", "检查更新", _check_update_from_tray)
            self._add_action("open_data_dir", "打开数据目录", _open_data_dir)
            self.menu.addSeparator()
            self._add_action("quit", "退出", _quit_from_tray)
            self.aboutToShow = self.menu.aboutToShow
            self.aboutToShow.connect(self._sync_menu_state)

        def _sync_menu_state(self) -> None:
            mode = _tray_mode_from_state()
            self.actions["mode_normal"].setChecked(mode == "normal")
            self.actions["mode_dnd"].setChecked(mode == "dnd")
            self.actions["mode_leave"].setChecked(mode == "leave")
            try:
                self._set_mode_icon(mode)
            except Exception:
                log.exception("qt tray set mode icon failed")
            log.info("qt.tray.menu_sync mode=%s", mode)

        def _set_mode_icon(self, mode: str) -> None:
            """Set tray icon with a mode indicator (colored dot, bottom-right)."""
            log.info("qt.tray.set_mode_icon mode=%s", mode)
            base = QIcon(str(self.icon_path))
            pixmap = base.pixmap(32, 32)
            if pixmap.isNull():
                return
            from PySide6.QtGui import QPainter
            p = QPainter(pixmap)
            p.setRenderHint(QPainter.Antialiasing)
            color_map = {"normal": "#22C55E", "dnd": "#EF4444", "leave": "#6B7280", "idle": "#94A3B8"}
            p.setBrush(QColor(color_map.get(mode, "#22C55E")))
            p.setPen(Qt.NoPen)
            p.drawEllipse(20, 20, 10, 10)
            p.end()
            self.tray.setIcon(QIcon(pixmap))
            tooltips = {
                "normal": "EyE Care - 正常",
                "dnd": "EyE Care - 勿扰",
                "leave": "EyE Care - 离开",
                "idle": "EyE Care - 暂离",
            }
            self.tray.setToolTip(tooltips.get(mode, "EyE Care"))

        def _on_activated(self, reason) -> None:
            trigger = getattr(QSystemTrayIcon, "Trigger", None)
            double_click = getattr(QSystemTrayIcon, "DoubleClick", None)
            if reason in (trigger, double_click):
                log.info("qt.tray.activated reason=%s", reason)
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

    def _apply_app_font() -> None:
        """统一应用字体，避免在日文/英文系统上因缺中文 UI 字体而 per-glyph 回退（字重不一/发虚）。

        QML 各处只设 pixelSize/weight、不指定 family → 继承应用默认字体。Windows 默认字体
        （Segoe UI / MS Shell Dlg）不含中文字形，渲染中文时按字形回退到不同字体，导致用户在
        日语系统上看到"字体变细、粗细不一"。这里显式选一个全 Windows 都自带的 CJK UI 字体，
        让所有语言环境下渲染一致。
        """
        try:
            from PySide6.QtGui import QFont, QFontDatabase
            candidates = ["Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑",
                          "Yu Gothic UI", "Meiryo", "Segoe UI"]
            try:
                families = set(QFontDatabase.families())
            except Exception:
                families = set()
            chosen = next((f for f in candidates if f in families), candidates[0])
            font = QFont(chosen)
            font.setStyleStrategy(QFont.PreferAntialias)
            app.setFont(font)
            log.info("qt.app_font family=%s available=%s", chosen, chosen in families)
        except Exception:
            log.exception("qt.app_font setup failed")

    # ───────────────────────── 启动序列 ─────────────────────────
    app = QApplication.instance() or QApplication([sys.argv[0]])
    _apply_app_font()

    # ── 单实例检测（QLocalServer/QLocalSocket，Qt 原生 IPC）──────
    # 第二个实例启动时：连上第一个实例发送 ACTIVATE、退出。
    # 第一个实例收到连接：调 _show_main_window() 把窗口拉到前台。
    _si_server = None
    _si_pending_activate = {"value": False}   # 窗口尚未就绪时收到激活请求的暂存标志

    if not no_single:
        try:
            from PySide6.QtNetwork import QLocalServer, QLocalSocket
            _SI_NAME = "EyECare_App_SingleInstance_v1"

            # 先探测：能连上说明已有实例在运行
            _probe = QLocalSocket()
            _probe.connectToServer(_SI_NAME)
            if _probe.waitForConnected(400):
                _probe.write(b"ACTIVATE\n")
                _probe.waitForBytesWritten(1000)
                _probe.disconnectFromServer()
                log.info("qt.single_instance: 检测到已运行实例，已发送激活信号，本次退出。")
                # 不能直接 return——QApplication 必须先 exec() 才能正常退出；
                # 用 processEvents 冲掉待处理事件后直接返回。
                app.processEvents()
                return
            _probe.deleteLater()

            # 成为主实例：创建服务端
            QLocalServer.removeServer(_SI_NAME)   # 清理上次崩溃留下的过期 socket
            _si_server = QLocalServer()
            if _si_server.listen(_SI_NAME):
                def _on_si_connection():
                    try:
                        client = _si_server.nextPendingConnection()
                        if client:
                            client.waitForReadyRead(400)
                            client.disconnectFromServer()
                    except Exception:
                        pass
                    if main_window_ref.get("value") is not None:
                        _show_main_window()
                    else:
                        _si_pending_activate["value"] = True
                _si_server.newConnection.connect(_on_si_connection)
                log.info("qt.single_instance: 主实例就绪，监听 %s", _SI_NAME)
            else:
                log.warning("qt.single_instance: 服务端监听失败(%s)，放行多实例",
                            _si_server.errorString())
                _si_server.deleteLater()
                _si_server = None
        except ImportError:
            log.warning("qt.single_instance: PySide6.QtNetwork 不可用，跳过单实例检测")
        except Exception:
            log.exception("qt.single_instance: 初始化失败，跳过单实例检测")

    # controller 同步创建（QML 外壳需要它；start() 自带后台线程，很快返回）
    diag.emit("DIAG_CONTROLLER_INIT", log, "初始化Controller")
    controller = AppController(data_dir=data_dir)
    controller.state.is_dnd = bool(getattr(controller.cfg, "startup_dnd", False))
    if controller.state.is_dnd:
        controller.state.dnd_reason = "manual"
    try:
        from eye_care.diagnostics.debug_switch import is_debug_enabled
        is_debug_enabled(config_enabled=getattr(controller.cfg, "debug_enabled", False))
    except Exception as e:
        log.debug("debug_switch init skipped: %s", e)
    controller.start()
    _set_controller(controller)
    diag.emit("DIAG_CONTROLLER_READY", log, "Controller就绪")

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
                        "prompt_reason": "调试触发：Qt notify 提示弹窗",
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

    def _fit_main_window_to_screen(window, screen=None) -> None:
        """把普通态主窗约束到当前屏幕的可用逻辑区域；Qt/PMv2 负责实际像素换算。"""
        try:
            from PySide6.QtGui import QWindow
            target = screen or window.screen() or QGuiApplication.primaryScreen()
            if target is None:
                return
            geo = target.availableGeometry()
            margin = 16
            max_w = max(320, geo.width() - margin * 2)
            max_h = max(240, geo.height() - margin * 2)
            min_w = min(980, max_w)
            min_h = min(620, max_h)
            window.setMinimumWidth(min_w)
            window.setMinimumHeight(min_h)
            if window.visibility() != QWindow.Windowed:
                return
            width = max(min_w, min(int(window.width()), max_w))
            height = max(min_h, min(int(window.height()), max_h))
            min_x = geo.x() + margin
            min_y = geo.y() + margin
            max_x = geo.x() + geo.width() - margin - width
            max_y = geo.y() + geo.height() - margin - height
            x = max(min_x, min(int(window.x()), max_x))
            y = max(min_y, min(int(window.y()), max_y))
            window.setGeometry(x, y, width, height)
            log.info(
                "qt.main_window.fit screen=%s geo=%sx%s%+d%+d window=%sx%s%+d%+d dpr=%.2f",
                target.name(), geo.width(), geo.height(), geo.x(), geo.y(),
                width, height, x, y, float(target.devicePixelRatio()),
            )
        except Exception:
            log.exception("qt main window fit failed")

    def _bind_main_window_screen(window, screen) -> None:
        if screen is None:
            return
        bound = _qml_refs.setdefault("main_window_bound_screens", set())
        key = id(screen)
        if key in bound:
            return
        bound.add(key)
        for signal_name in ("availableGeometryChanged", "geometryChanged", "logicalDotsPerInchChanged"):
            try:
                getattr(screen, signal_name).connect(
                    lambda *_args, w=window: QTimer.singleShot(0, lambda: _fit_main_window_to_screen(w))
                )
            except Exception:
                pass

    def _create_qml_shell():
        """构建 QML AppShell 主窗，并装配全部数据桥（persist=True 真落盘）。"""
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine
        from datetime import date as _date
        from eye_care.qt_quick.shell_integration import build_shell_bridges, CONTEXT_PROPERTY_NAMES

        qml_path = PROJECT_ROOT / "eye_care" / "qt_quick" / "qml" / "AppShell.qml"
        bridges = build_shell_bridges(controller, persist=True, log=log, today=_date.today().isoformat())
        try:
            bridges["updateBridge"].restartRequested.connect(_quit_from_tray)
        except Exception:
            log.exception("qt.qml_shell update restart binding failed")

        host_bridge = QtHostBridge()
        qt_bridge_ref["value"] = host_bridge
        _qml_refs["host_bridge"] = host_bridge

        def _on_toolbar_action(name):
            n = str(name or "")
            try:
                if n == "exportAll":
                    host_bridge.exportAll()
                elif n == "exportSettings":
                    host_bridge.exportSettings()
                elif n == "importAll":
                    host_bridge.importAll()
                elif n == "importSettings":
                    host_bridge.importSettings()
                elif n.startswith("closeAction:"):
                    host_bridge.setCloseAction(n.split(":", 1)[1])
                else:
                    log.info("qt.qml_shell.toolbar_action_unhandled name=%s", n)
            except Exception:
                log.exception("qt.qml_shell toolbar action failed name=%s", n)

        # shellHost：QML 直接调用的宿主桥（比 Python 连 QML 信号更可靠）。必须在 load 前 setContextProperty。
        class _ShellHost(QObject):
            @Slot(str)
            def doToolbarAction(self, name: str) -> None:
                _on_toolbar_action(name)

            @Slot()
            def requestRest(self) -> None:
                log.info("qt.qml_shell.shellHost.requestRest")
                _qml_start_rest()

            @Slot()
            def quitApp(self) -> None:
                log.info("qt.qml_shell.shellHost.quitApp")
                _quit_from_tray()

            @Slot()
            def demoNotify(self) -> None:
                """引导演示：直接弹出通知气泡，不走正常业务链。"""
                log.info("qt.qml_shell.shellHost.demoNotify")
                try:
                    # 首次调用时 notify 窗口尚未创建，需先初始化
                    if notify_window_ref.get("value") is None:
                        _ensure_notify_window(self)
                    _queue_notify_payload(message="示例：用眼提醒已到，建议稍作休息", extra={})
                    result = _try_show_pending_notify()
                    log.info("qt.qml_shell.shellHost.demoNotify result=%s", result)
                except Exception:
                    log.exception("qt.qml_shell shellHost.demoNotify failed")

            @Slot()
            def demoRest(self) -> None:
                """引导演示：直接显示休息倒计时界面，不通过业务守卫。"""
                log.info("qt.qml_shell.shellHost.demoRest")
                try:
                    _ensure_rest_overlays(self)
                    rest_pending_show["value"] = True
                    _show_ready_rest_overlays()
                except Exception:
                    log.exception("qt.qml_shell shellHost.demoRest failed")
        shell_host = _ShellHost()

        engine = QQmlApplicationEngine()
        # 显式声明 C++/Python 所有权，防止 QML 的 JS GC 误回收这些桥对象。
        for _b in list(bridges.values()) + [shell_host, host_bridge]:
            try:
                if isinstance(_b, QObject):
                    QQmlEngine.setObjectOwnership(_b, QQmlEngine.CppOwnership)
            except Exception:
                pass
        ctx = engine.rootContext()
        for name in CONTEXT_PROPERTY_NAMES:
            ctx.setContextProperty(name, bridges[name])
        ctx.setContextProperty("shellHost", shell_host)
        engine.load(QUrl.fromLocalFile(str(qml_path)))
        roots = engine.rootObjects()
        if not roots:
            raise RuntimeError("AppShell.qml 加载失败（rootObjects 空）")
        root = roots[0]
        qml_root_ref["value"] = root
        main_window_ref["value"] = root
        initial_screen = root.screen() or QGuiApplication.primaryScreen()
        _bind_main_window_screen(root, initial_screen)
        _fit_main_window_to_screen(root, initial_screen)
        try:
            def _on_main_screen_changed(screen):
                _bind_main_window_screen(root, screen)
                QTimer.singleShot(0, lambda: _fit_main_window_to_screen(root, screen))
            root.screenChanged.connect(_on_main_screen_changed)
        except Exception:
            log.exception("qt main window screenChanged binding failed")
        try:
            from eye_care.version import APP_VERSION
            root.setProperty("appVersion", ("v" + APP_VERSION) if APP_VERSION else "")
        except Exception:
            pass

        # 信号兜底（运行时 QML 优先 shellHost，不会重复触发）
        try:
            root.toolbarAction.connect(_on_toolbar_action)
            root.restRequested.connect(_qml_start_rest)
        except Exception:
            pass

        # 托盘应用：关最后一个窗口（休息覆盖层关闭 / 主窗最小化）不退进程；退出统一走 shellHost/托盘。
        app.setQuitOnLastWindowClosed(False)

        # 通知开关实时联动：设置页改 notify_enabled → 起/停 NotifierService。
        _qml_refs["notifier_running"] = bool(getattr(getattr(controller, "cfg", None), "notify_enabled", True))

        def _reconcile_notifier():
            try:
                want = bool(getattr(getattr(controller, "cfg", None), "notify_enabled", True))
                svc = notifier_service_ref.get("value")
                if svc is None:
                    return
                running = bool(_qml_refs.get("notifier_running"))
                if want and not running:
                    svc.start()
                    _qml_refs["notifier_running"] = True
                    log.info("qt.qml_shell.notifier started (settings toggle)")
                elif not want and running:
                    svc.stop(timeout_s=2.0)
                    _qml_refs["notifier_running"] = False
                    log.info("qt.qml_shell.notifier stopped (settings toggle)")
            except Exception:
                log.exception("qt.qml_shell.notifier reconcile failed")
        try:
            bridges["settingsBridge"].configChanged.connect(_reconcile_notifier)
        except Exception:
            pass
        # 设置点「应用」后 → 左栏立即重算（浏览器统计开关翻转 → browserEnabled 变 → 页签即时显隐）。
        try:
            bridges["settingsBridge"].configChanged.connect(bridges["leftPanelBridge"].refresh)
        except Exception:
            pass
        # 站点归并规则/显示名变更（站点详情页勾选独立统计、改显示名）→ 左右栏即时重算并回溯。
        try:
            bridges["sitesBridge"].configApplied.connect(bridges["leftPanelBridge"].refresh)
            bridges["sitesBridge"].configApplied.connect(bridges["rightPanelBridge"].refresh)
        except Exception:
            pass
        # 站点详情页「清除图标缓存」→ 左栏丢掉自己那份 data_url 缓存，否则卡片仍显示旧图标。
        try:
            bridges["sitesBridge"].iconCacheCleared.connect(
                bridges["leftPanelBridge"].clearDomainIconCache)
        except Exception:
            pass

        # 10s 轮询刷新左右栏
        poll = QTimer()
        poll.setInterval(10000)
        poll.timeout.connect(lambda: (bridges["leftPanelBridge"].refresh(), bridges["rightPanelBridge"].refresh()))
        poll.start()

        _qml_refs.update({"engine": engine, "bridges": bridges, "host_bridge": host_bridge,
                          "poll": poll, "shell_host": shell_host})
        log.info("qt.qml_shell: AppShell 已装配并显示（persist=True）")
        return root

    _create_qml_shell()

    # 窗口就绪：处理在 QML 创建前就收到的激活请求（极少见，保险起见）
    if _si_pending_activate.get("value"):
        _si_pending_activate["value"] = False
        _show_main_window()

    tray = QtTrayController()
    tray_ref["value"] = tray
    tray_started = tray.start()
    log.info("qt.tray.start_result ok=%s", tray_started)

    # 自动升级：启动后静默检查，此后每 6 小时检查一次。新版下载并校验完成后只提示，
    # 用户确认“立即重启升级”才退出当前进程，独立 updater 随后替换并重启。
    update_bridge = (_qml_refs.get("bridges") or {}).get("updateBridge")
    if update_bridge is not None:
        def _on_update_ready(version: str) -> None:
            try:
                tray.actions["check_update"].setText("安装已下载更新")
                tray.tray.showMessage(
                    "EyE Care 更新已准备好",
                    "v%s 已下载并校验完成，点击这里重启升级。" % version,
                )
            except Exception:
                log.exception("qt auto update ready notification failed")

        try:
            update_bridge.updateReady.connect(_on_update_ready)
            tray.tray.messageClicked.connect(_check_update_from_tray)
            if bool(getattr(update_bridge, "readyToInstall", False)):
                QTimer.singleShot(1500, lambda: _on_update_ready(update_bridge.latestVersion))
            QTimer.singleShot(5000, update_bridge.startAutomatic)
            update_poll = QTimer()
            update_poll.setInterval(6 * 60 * 60 * 1000)
            update_poll.timeout.connect(update_bridge.startAutomatic)
            update_poll.start()
            _qml_refs["update_poll"] = update_poll
        except Exception:
            log.exception("qt auto update scheduling failed")

    # Controller 的自动模式在后台线程变化；用 GUI 线程轻量轮询同步托盘，避免跨线程操作 Qt 对象。
    mode_poll = QTimer()
    mode_poll.setInterval(500)
    mode_cache = {"value": _tray_mode_from_state()}

    def _sync_tray_mode_if_changed() -> None:
        mode = _tray_mode_from_state()
        if mode == mode_cache.get("value"):
            return
        mode_cache["value"] = mode
        current_tray = tray_ref.get("value")
        if current_tray is not None:
            current_tray._set_mode_icon(mode)
        log.info("qt.tray.mode_changed mode=%s", mode)

    mode_poll.timeout.connect(_sync_tray_mode_if_changed)
    mode_poll.start()
    _qml_refs["mode_poll"] = mode_poll

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
        # 先停 controller 再停 favicon：controller 的 tick 线程是 favicon 预取的生产者，
        # 反过来会让关闭途中的预取又把 worker 唤起（FaviconService 侧另有 _stopped 兜底）。
        if controller is not None:
            try:
                controller.stop()
            except Exception:
                log.exception("qt shutdown: controller.stop failed")
        favicon = (_qml_refs.get("bridges") or {}).get("_faviconService")
        if favicon is not None:
            try:
                favicon.stop(timeout_s=2.0)
            except Exception:
                log.exception("qt shutdown: favicon.stop failed")

    app.aboutToQuit.connect(_shutdown)

    if no_single:
        log.info("qt host single-instance bypass enabled")

    app.exec()
