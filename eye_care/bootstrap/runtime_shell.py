"""
Runtime shell for pywebview - contains run_pywebview_shell function.
"""
import logging
import os
import sys
import threading
import time
from pathlib import Path

from eye_care.diagnostics import diag, log_exception_summary
from .constants import (
    PROJECT_ROOT,
    UI_WEB_DIR,
    UI_INDEX_PATH,
    ENABLE_DRAG_REGION_INJECT,
)
from .bridge_inject import inject_bridge_script, inject_drag_region


def _play_notify_sound():
    """Play notification sound asynchronously if local asset exists."""
    try:
        import winsound
        sound_path = UI_WEB_DIR / "assets" / "notify_bubble_softer.wav"
        if sound_path.exists():
            winsound.PlaySound(str(sound_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
    except OSError as e:
        log_exception_summary(
            logging.getLogger(__name__),
            "DIAG_EXCEPTION",
            "notify sound os error",
            "degrade_continue",
            detail=str(e)[:200],
            reason_code="E_NOTIFY_SOUND_OSERROR",
        )
    except Exception as e:
        log_exception_summary(
            logging.getLogger(__name__),
            "DIAG_EXCEPTION",
            "notify sound unexpected error",
            "degrade_continue",
            detail=str(e)[:200],
            reason_code="E_NOTIFY_SOUND_UNKNOWN",
        )


def run_pywebview_shell(data_dir: Path, no_single: bool, api_port: int, debug_console: bool = False):
    # 统一工作目录：确保相对路径(eye_care/ui/web / data)稳定
    os.chdir(str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT))

    from eye_care.diagnostics.logging_setup import setup_logging
    from eye_care.controller.app_controller import AppController
    from eye_care.api.server import create_app
    from eye_care.ui.app_runtime import start_backend_services, wait_flask_ready
    from eye_care.ui.web_routes import build_ui_page_url, mount_ui_site_routes
    from eye_care.ui.window_runtime import NotifyOverlayRuntime
    from eye_care.ui.window_api import WindowApi
    from eye_care.ui.win_effects import WinEffects
    from eye_care.ui.gui_dispatcher import GuiDispatcher
    from eye_care.diagnostics.hwnd_dump import harden_hwnd_dump, rest_overlay_children_dump

    # 仅 --debug 时：控制台输出、rest URL 带 debug 参数等
    if debug_console or os.environ.get("EYECARE_DEBUG_CONSOLE", "0") == "1":
        os.environ["EYECARE_CONSOLE_LOG"] = "1"

    setup_logging(data_dir / "debug.log")
    log = logging.getLogger(__name__)
    window_runtime = NotifyOverlayRuntime(api_port=api_port, debug_console=debug_console, logger=log)
    win_effects = WinEffects(logger=log)

    def _dbg_main(message: str, data: dict, hypothesis_id: str) -> None:
        """仅 debug 开关打开时写诊断日志；默认关闭，不写固定路径。"""
        try:
            from eye_care.diagnostics.debug_switch import is_debug_enabled
            if not is_debug_enabled():
                return
            import json as _json
            diag_dir = data_dir / "diagnostics"
            diag_dir.mkdir(parents=True, exist_ok=True)
            out = diag_dir / "debug_session.log"
            payload = {
                "sessionId": "debug-session",
                "runId": "pre-fix",
                "hypothesisId": hypothesis_id,
                "location": "main.py:run_pywebview_shell",
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
            }
            with open(out, "a", encoding="utf-8") as f:
                f.write(_json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            log_exception_summary(
                log,
                "DIAG_EXCEPTION",
                "debug session log write",
                "degrade_continue",
                detail=str(e)[:200],
                reason_code="E_DEBUG_SESSION_WRITE",
            )

    # 单实例
    inst = None
    if not no_single:
        try:
            from eye_care.utils.single_instance import SingleInstance
            inst = SingleInstance("Global\\EyE_Care_SingleInstance_Mutex")
            if not inst.acquire():
                try:
                    import ctypes
                    from ctypes import wintypes
                    user32 = ctypes.WinDLL("user32", use_last_error=True)
                    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
                    user32.MessageBoxW.restype = wintypes.INT
                    user32.MessageBoxW(
                        None,
                        "EyE Care 已在运行中。",
                        "EyE Care",
                        0x00000000 | 0x00000040 | 0x00040000,  # MB_OK|MB_ICONINFORMATION|MB_TOPMOST
                    )
                except Exception as e:
                    log_exception_summary(
                        log,
                        "DIAG_EXCEPTION",
                        "single instance messagebox",
                        "degrade_continue",
                        detail=str(e)[:200],
                        reason_code="E_SINGLE_INSTANCE_MSGBOX",
                    )
                return
        except Exception:
            log_exception_summary(log, "DIAG_EXCEPTION", "单例检测", "可能无法保证单实例")
            log.exception("single instance init failed")

    diag.emit("DIAG_START", log, "应用启动准备")

    # 抑制Flask启动日志，避免退出时显示
    import logging as _logging
    _logging.getLogger('werkzeug').disabled = True

    # 快速启动：Flask和Controller在后台立即开始初始化，不等待
    controller = None
    controller_ready = {"value": False}
    flask_ready = {"value": False}

    def _set_controller(ctrl) -> None:
        nonlocal controller
        controller = ctrl

    services_thread = start_backend_services(
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
        on_controller_started_debug=lambda ctrl: _dbg_main("controller_started", {"startup_dnd": ctrl.state.is_dnd}, "H8"),
    )

    diag.emit("DIAG_FLASK_WAIT", log, "等待Flask启动")
    wait_flask_ready(api_port=api_port, flask_ready=flask_ready, timeout_s=2.0, logger=log)

    diag.emit("DIAG_WINDOW_CREATE", log, "创建主窗口", api_port=api_port)

    # 读取启动配置：决定是否在启动时显示主界面
    try:
        from eye_care.config.store import load_config

        cfg = load_config(data_dir / "config.json")
        startup_show_main = bool(getattr(cfg, "startup_show_main", True))
    except Exception:
        # 配置缺失或解析失败时，保持旧版行为：启动时显示主界面
        startup_show_main = True

    # 窗口控制 API：供前端通过 pywebview.api 调用(含导入/导出)
    CONTENT_WIDTH = 1400
    TOTAL_CONTENT_HEIGHT = 860

    tray_enabled = False

    close_rest_overlay_holder = {"fn": lambda: None}

    api = WindowApi(
        data_dir=data_dir,
        logger=log,
        controller_getter=lambda: controller,
        controller_ready_getter=lambda: bool(controller_ready["value"]),
        close_rest_overlay_cb=lambda: close_rest_overlay_holder["fn"](),
    )

    import webview
    import platform

    # 启动时一次性打印：系统透明效果、远程桌面、pywebview 版本（避免不同机器扯皮）
    def _log_sys_transparency():
        try:
            enable_transparency = -1
            import winreg
            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                0,
                winreg.KEY_READ,
            )
            enable_transparency = int(winreg.QueryValueEx(k, "EnableTransparency")[0])
            winreg.CloseKey(k)

            remote_session = -1
            import ctypes
            user32 = ctypes.windll.user32
            SM_REMOTESESSION = 0x1000
            remote_session = int(user32.GetSystemMetrics(SM_REMOTESESSION))
            try:
                pv_ver = __import__("importlib.metadata").version("pywebview")
            except Exception:
                pv_ver = getattr(webview, "__version__", "?")
            os_build = getattr(platform, "version", lambda: "")() or "?"
            diag.emit(
                "DIAG_SYS_TRANSPARENCY", log, "系统透明与环境信息",
                enable_transparency=enable_transparency, remote_session=remote_session,
                os_build=os_build, pywebview_version=pv_ver, platform=platform.platform(),
            )
        except Exception as e:
            log.warning("SYS_TRANSPARENCY log failed: %s", str(e)[:100])

    _log_sys_transparency()

    # ---- drag region settings (Windows/WebView2) ----
    # 只允许"直接点中拖拽区域"的元素触发拖动，避免吞掉按钮/日历等交互。
    try:
        webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
    except Exception as e:
        log_exception_summary(
            log,
            "DIAG_EXCEPTION",
            "set drag region direct target only",
            "degrade_continue",
            detail=str(e)[:200],
            reason_code="E_WEBVIEW_DRAG_REGION_SETTING",
        )

    window = webview.create_window(
        "EyE Care",
        build_ui_page_url(api_port, "main"),
        width=CONTENT_WIDTH,
        height=TOTAL_CONTENT_HEIGHT,
        min_size=(1280, 800),
        frameless=True,
        # IMPORTANT: easy_drag=True 会吞掉网页点击事件(日历/按钮等会"只能看不能点")。
        # 我们已经通过注入 pywebview-drag-region 只让标题栏可拖拽。
        easy_drag=False,
        js_api=api,
        resizable=True,
        background_color='#070D19',  # 深色背景避免白屏
        # 启动时是否显示主界面：未勾选时静默到托盘，由托盘菜单/图标再显示
        hidden=not startup_show_main,
    )
    api.set_window(window)
    # 设置 debug 路由的 window_api 引用（dispatcher 引用在创建后再注入）
    from eye_care.api.routes import debug as debug_routes
    debug_routes.set_debug_window_api(api)
    diag.emit("DIAG_WINDOW_CREATED", log, "主窗口已创建", api_port=api_port)
    _dbg_main("main_window_created", {"api_port": api_port}, "H8")

    # M5：唯一显隐入口，close_window(hide) 与托盘 toggle 均经此同步 window_visible
    # 按配置决定启动时是否视为“已显示主界面”
    window_visible = {"v": bool(startup_show_main)}

    # 置前警告去重（函数外部定义，跨调用去重）
    _fg_warn_once: set[str] = set()

    def _coerce_hwnd(raw) -> int | None:
        if raw is None:
            return None
        if isinstance(raw, int):
            return raw

        # pythonnet IntPtr 常见路径
        for attr in ("ToInt64", "ToInt32"):
            fn = getattr(raw, attr, None)
            if callable(fn):
                try:
                    return int(fn())
                except (TypeError, ValueError, OverflowError):
                    pass

        # ctypes / 自定义对象常见路径
        for attr in ("value", "handle", "Handle", "hwnd"):
            try:
                v = getattr(raw, attr, None)
                if v is not None:
                    return int(v)
            except (TypeError, ValueError, OverflowError):
                pass

        # 最后兜底
        try:
            return int(raw)
        except (TypeError, ValueError, OverflowError):
            return None

    def _set_window_visible(visible: bool) -> None:
        """必须在 GUI 线程执行。唯一更新 window 显隐与 window_visible 的地方。"""
        if visible:
            try:
                window.show()
                window.restore()
                # pywebview 部分版本/后端无 bring_to_front，有则调用，否则用 Win32 置前
                if getattr(window, "bring_to_front", None) is not None:
                    window.bring_to_front()
                elif sys.platform == "win32":
                    import ctypes
                    from ctypes import wintypes

                    user32 = ctypes.WinDLL("user32", use_last_error=True)
                    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
                    user32.SetForegroundWindow.restype = wintypes.BOOL
                    user32.IsWindow.argtypes = [wintypes.HWND]
                    user32.IsWindow.restype = wintypes.BOOL
                    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
                    user32.ShowWindow.restype = wintypes.BOOL

                    native = getattr(window, "native", None)
                    raw_h = getattr(native, "Handle", None) or getattr(native, "handle", None) or getattr(native, "hwnd", None)
                    hwnd = _coerce_hwnd(raw_h)

                    if hwnd is None:
                        key = f"bad_hwnd_type:{type(raw_h).__name__}"
                        if key not in _fg_warn_once:
                            _fg_warn_once.add(key)
                            log.warning("SetForegroundWindow skipped: bad handle type=%s raw=%r", type(raw_h).__name__, raw_h)
                    elif not bool(user32.IsWindow(hwnd)):
                        key = f"invalid_hwnd:{hwnd}"
                        if key not in _fg_warn_once:
                            _fg_warn_once.add(key)
                            log.warning("SetForegroundWindow skipped: hwnd not valid hwnd=%s", hwnd)
                    else:
                        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        ok = bool(user32.SetForegroundWindow(hwnd))
                        if not ok:
                            key = f"setfg_fail:{hwnd}"
                            if key not in _fg_warn_once:
                                _fg_warn_once.add(key)
                                log.warning("SetForegroundWindow returned false hwnd=%s", hwnd)
            except Exception:
                log_exception_summary(log, "DIAG_EXCEPTION", "主窗口显示", "show/restore/bring_to_front 失败")
            window_visible["v"] = True
        else:
            try:
                window.hide()
            except Exception:
                log_exception_summary(log, "DIAG_EXCEPTION", "主窗口隐藏", "hide 失败")
            window_visible["v"] = False

    set_visible_cb = getattr(api, "set_visible_cb", None)
    if callable(set_visible_cb):
        try:
            set_visible_cb(_set_window_visible)
        except Exception as e:
            log_exception_summary(
                log,
                "DIAG_EXCEPTION",
                "set visible callback",
                "degrade_continue",
                detail=str(e)[:200],
                reason_code="E_API_SET_VISIBLE_CB",
            )
    else:
        log_exception_summary(
            log,
            "DIAG_EXCEPTION",
            "set visible callback missing",
            "degrade_continue",
            detail="WindowApi.set_visible_cb not callable",
            reason_code="E_API_SET_VISIBLE_CB_MISSING",
        )

    # ----------------------------
    # GUI 调度器：所有 pywebview 窗口操作必须经此投递到 GUI 线程执行
    # ----------------------------
    dispatcher = GuiDispatcher()
    set_dispatcher = getattr(api, "set_dispatcher", None)
    if callable(set_dispatcher):
        try:
            set_dispatcher(dispatcher)
        except Exception as e:
            log_exception_summary(
                log,
                "DIAG_EXCEPTION",
                "set dispatcher",
                "degrade_continue",
                detail=str(e)[:200],
                reason_code="E_API_SET_DISPATCHER",
            )
    else:
        log_exception_summary(
            log,
            "DIAG_EXCEPTION",
            "set dispatcher missing",
            "degrade_continue",
            detail="WindowApi.set_dispatcher not callable",
            reason_code="E_API_SET_DISPATCHER_MISSING",
        )
    # 将 GUI dispatcher 引用注入 debug 路由，供调试接口使用
    try:
        debug_routes.set_debug_dispatcher(dispatcher)
    except Exception as e:
        log_exception_summary(
            log,
            "DIAG_EXCEPTION",
            "set debug dispatcher",
            "degrade_continue",
            detail=str(e)[:200],
            reason_code="E_API_SET_DISPATCHER",
        )

    debug_notify_only = {"v": False}

    # ----------------------------
    # 通知 / 休息 子系统（独立模块，由 dispatcher 投递到 GUI 执行）
    # ----------------------------
    gui_loop_ready = {"v": False}  # webview.start 进入 GUI loop 后置 True

    # ----------------------------
    # Rest 子系统：RestWindowController（所有 show/hide 经 dispatcher 投递到 GUI 线程）
    # ----------------------------
    from eye_care.rest.rest_window_controller import RestWindowController

    def _harden_hwnd_dump_wrapper(hwnd: int, where: str, logger: logging.Logger, log_prefix: str) -> None:
        harden_hwnd_dump(hwnd, where, logger, log_prefix)

    def _set_main_window_enabled(enabled: bool) -> None:
        """本函数暂时不做任何窗口操作，避免休息结束后窗口跳转问题。"""
        pass

    def _on_rest_closed_for_guard():
        """Rest 遮罩关闭完成，通知 controller 进入 2 秒冷却（与 RestEntryGuardMachine 5.5 一致）。"""
        try:
            if controller and getattr(controller, "notify_rest_closed", None):
                controller.notify_rest_closed()
        except Exception:
            log.exception("notify_rest_closed failed")

    rest_controller = RestWindowController(
        logger=log,
        win_effects=win_effects,
        window_runtime=window_runtime,
        window_api=api,
        controller_getter=lambda: controller,
        dispatcher=dispatcher,
        harden_hwnd_dump=_harden_hwnd_dump_wrapper,
        rest_overlay_children_dump=rest_overlay_children_dump,
        main_window_enabled_cb=_set_main_window_enabled,
        on_rest_closed_cb=_on_rest_closed_for_guard,
    )

    def _close_rest_overlay_then_refresh_main():
        rest_controller.close_overlay()

    close_rest_overlay_holder["fn"] = _close_rest_overlay_then_refresh_main
    api._rest_show_overlay_fn = lambda: dispatcher.post_rest_show()

    # ----------------------------
    # Notify 子系统：NotifyWindowController（所有 show/hide 经 dispatcher 投递到 GUI 线程）
    # ----------------------------
    from eye_care.notify.notify_window_controller import NotifyWindowController

    def _clear_prompt_dedupe():
        try:
            from eye_care.notify.notification_manager import NotificationManager
            NotificationManager.get_instance().clear_last_shown_key()
        except Exception as e:
            log_exception_summary(
                log,
                "DIAG_EXCEPTION",
                "clear notify dedupe",
                "degrade_continue",
                detail=str(e)[:200],
                reason_code="E_NOTIFY_CLEAR_LAST_SHOWN",
            )

    def _debug_notify_enabled() -> bool:
        try:
            return bool(controller and getattr(controller, "is_debug_notify", lambda: False)())
        except Exception:
            return False

    def _show_toast_fallback(extra: dict) -> None:
        """备用通知方式(系统Toast)"""
        try:
            from win10toast import ToastNotifier
            rest = extra.get("rest") or {}
            msg = rest.get("prompt_reason") or "该休息一下了(按 ESC 可跳过)"
            ToastNotifier().show_toast("EyE Care", msg, duration=5, threaded=True)
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "休息通知备用Toast", "Toast未弹出", str(e))
            log.warning("rest notification fallback (toast) failed: %s", e, exc_info=True)

    def _mark_notified():
        try:
            if controller:
                controller.mark_rest_notified()
        except Exception as e:
            log_exception_summary(
                log,
                "DIAG_EXCEPTION",
                "mark rest notified",
                "degrade_continue",
                detail=str(e)[:200],
                reason_code="E_MARK_REST_NOTIFIED",
            )

    from eye_care.notify.notification_manager import NotificationManager
    from eye_care.notify.notifier_service import NotifierService

    notification_manager = NotificationManager.get_instance(
        dispatcher=dispatcher,
        show_toast_fallback=_show_toast_fallback,
        min_interval_s=60,
        mark_notified=_mark_notified,
    )
    notifier_service = NotifierService(
        controller=controller,
        notification_manager=notification_manager,
        poll_interval_s=1.0,
    )
    notifier_service.start()

    # 用户点击 rest/snooze/dismiss 时再上报 on_notify_complete(True)，避免"出现又马上消失"
    def _on_user_action_complete(prompt_key, extra):
        notification_manager.on_notify_complete(prompt_key, True, extra)

    notify_controller = NotifyWindowController(
        logger=log,
        win_effects=win_effects,
        window_runtime=window_runtime,
        data_dir=data_dir,
        controller_getter=lambda: controller,
        dispatcher=dispatcher,
        clear_prompt_dedupe=_clear_prompt_dedupe,
        debug_notify_getter=_debug_notify_enabled,
        harden_hwnd_dump=_harden_hwnd_dump_wrapper,
        on_notify_shown=None,
        on_user_action_complete=_on_user_action_complete,
        sm_notify_v2_getter=lambda: bool(getattr(controller.cfg, "sm_notify_v2", False)),
    )

    exit_requested = {"v": False}
    stop_event = threading.Event()

    def _on_webview_start():
        """pywebview GUI loop：消费 dispatcher 队列，所有窗口操作在 GUI 线程执行。"""
        gui_loop_ready["v"] = True
        notify_controller.set_gui_loop_ready()
        diag.emit("DIAG_GUI_LOOP", log, "GUI消息循环已进入")
        diag.emit("DIAG_APP_START_OK", log, "启动成功")
        # Rest 静默加载：提前创建 overlay 窗口并加载 URL，首显时仅 ready 后再 show 避免黑屏
        try:
            rest_controller._lazy_init_overlays()
        except Exception as e:
            log_exception_summary(
                log,
                "DIAG_EXCEPTION",
                "rest lazy init overlays",
                "degrade_continue",
                detail=str(e)[:200],
                reason_code="E_REST_LAZY_INIT_OVERLAYS",
            )

        def _handle_notify_task(task):
            try:
                mode = controller._current_mode() if controller else ""
                is_paused = bool(controller.state.is_paused) if controller else False
                dnd = bool(controller.state.is_dnd) if controller else False
                rest = (task.extra.get("rest") or {}) if isinstance(task.extra, dict) else {}
                blocked_reason = "" if rest.get("should_prompt") else (rest.get("prompt_reason") or "suppressed")
                diag.emit("DIAG_NOTIFY_SHOW", log, "通知窗开始展示", mode=mode, is_paused=is_paused, dnd=dnd, blocked_reason=blocked_reason)
            except Exception:
                diag.emit("DIAG_NOTIFY_SHOW", log, "通知窗开始展示", mode="", is_paused=False, dnd=False, blocked_reason="")
            notify_controller.check_and_do_preload()
            result = notify_controller.show(task.extra, task.prompt_key)
            # result=True 表示已投递展示，此时才播放音效
            if result is True:
                _play_notify_sound()
            # on_notify_complete(True) 延后到用户点击时由 bridge 回调
            if result is not True:
                try:
                    notification_manager.on_notify_complete(task.prompt_key, result, task.extra)
                except Exception:
                    log_exception_summary(log, "DIAG_EXCEPTION", "通知完成回调", "可能影响去重/状态")
                    log.exception("on_notify_complete failed")

        def _handle_rest_task():
            try:
                mode = controller._current_mode() if controller else ""
                diag.emit("DIAG_REST_SHOW_ENTER", log, "休息遮罩任务开始执行(GUI)", mode=mode, source="gui", screen_count=len(rest_controller._overlays) if getattr(rest_controller, "_overlays", None) else 0)
            except Exception:
                diag.emit("DIAG_REST_SHOW_ENTER", log, "休息遮罩任务开始执行(GUI)", mode="", source="gui", screen_count=0)
            rest_controller.show_overlay()

        def _pump_during_rest_wait():
            """等待 rest 样式时消费队列，避免阻塞导致 _apply_style_step 不执行；rest 任务 no-op 防重入。"""
            dispatcher.run_pending(
                notify_handler=_handle_notify_task,
                rest_handler=lambda: None,
                max_per_cycle=200,
            )

        try:
            rest_controller.set_pump_fn(_pump_during_rest_wait)
        except Exception as e:
            log_exception_summary(
                log,
                "DIAG_EXCEPTION",
                "rest set pump function",
                "degrade_continue",
                detail=str(e)[:200],
                reason_code="E_REST_SET_PUMP_FN",
            )

        _metric_interval_s = 60
        _last_metric_ts = time.time()

        while not stop_event.is_set() and not exit_requested["v"]:
            try:
                notify_controller.check_and_do_preload()
                dispatcher.run_pending(
                    notify_handler=_handle_notify_task,
                    rest_handler=_handle_rest_task,
                    max_per_cycle=200,
                )
            except Exception:
                log_exception_summary(log, "DIAG_EXCEPTION", "GUI调度循环run_pending", "可能中断通知/休息展示")
                log.exception("dispatcher run_pending failed")
            try:
                now = time.time()
                if now - _last_metric_ts >= _metric_interval_s:
                    _last_metric_ts = now
                    try:
                        m = dispatcher.get_metric()
                        diag.emit("DIAG_METRIC_DISPATCH", log, "调度指标", **m)
                    except Exception as _e:
                        diag.emit("DIAG_METRIC_DISPATCH", log, "调度指标", _err=str(_e)[:80])
                    try:
                        m = notify_controller.get_metric()
                        diag.emit("DIAG_METRIC_NOTIFY", log, "通知指标", **m)
                    except Exception as _e:
                        diag.emit("DIAG_METRIC_NOTIFY", log, "通知指标", _err=str(_e)[:80])
                    try:
                        m = rest_controller.get_metric()
                        diag.emit("DIAG_METRIC_REST", log, "休息遮罩指标", **m)
                    except Exception as _e:
                        diag.emit("DIAG_METRIC_REST", log, "休息遮罩指标", _err=str(_e)[:80])
                    try:
                        if controller and getattr(controller, "repo", None):
                            m = controller.repo.get_metric()
                            diag.emit("DIAG_METRIC_REPO", log, "仓库指标", **m)
                    except Exception as _e:
                        diag.emit("DIAG_METRIC_REPO", log, "仓库指标", _err=str(_e)[:80])
            except Exception as e:
                log_exception_summary(
                    log,
                    "DIAG_EXCEPTION",
                    "metric emit loop",
                    "degrade_continue",
                    detail=str(e)[:200],
                    reason_code="E_METRIC_EMIT_LOOP",
                )
            try:
                stop_event.wait(0.016)
            except Exception:
                time.sleep(0.016)
        return

    def _request_exit(reason: str, destroy_window: bool = False) -> None:
        """请求退出（不强杀进程）：设退出标志、停调度闸门、按序停服务，让 webview.start() 自然返回。"""
        if exit_requested["v"]:
            diag.emit("DIAG_EXIT", log, "重复退出请求已忽略", reason=reason)
            return
        exit_requested["v"] = True
        diag.emit("DIAG_EXIT", log, "已请求退出", reason=reason)
        try:
            stop_event.set()
        except Exception as e:
            diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="stop_event.set", ok=False, err=str(e)[:80])
        # 停止调度闸门：之后任何 post 将被拒绝，避免退出时挂死
        try:
            dispatcher.stop()
            diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="dispatcher.stop", ok=True)
        except Exception as e:
            diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="dispatcher.stop", ok=False, err=str(e)[:80])
        # best-effort 顺序停服务（每步独立 try，不阻塞）
        try:
            notifier_service.stop(timeout_s=2.0)
            diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="notifier_service.stop", ok=True)
        except Exception as e:
            diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="notifier_service.stop", ok=False, err=str(e)[:80])
        try:
            if controller:
                controller.stop()
                diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="controller.stop", ok=True)
            else:
                diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="controller.stop", ok=True, skipped="no_controller")
        except Exception as e:
            diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="controller.stop", ok=False, err=str(e)[:80])
        try:
            if tray:
                tray.stop()
                diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="tray.stop", ok=True)
            else:
                diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="tray.stop", ok=True, skipped="no_tray")
        except Exception as e:
            diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="tray.stop", ok=False, err=str(e)[:80])
        # 以下必须在 GUI 线程执行（_request_exit 由 tray 投递或 on_closed 触发，均在 GUI 线程）
        try:
            rest_controller.destroy_overlays()
            diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="rest_controller.destroy_overlays", ok=True)
        except Exception as e:
            diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="rest_controller.destroy_overlays", ok=False, err=str(e)[:80])
        try:
            if getattr(notify_controller, "window", None):
                notify_controller.window.destroy()
                diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="notify_controller.window.destroy", ok=True)
            else:
                diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="notify_controller.window.destroy", ok=True, skipped="no_window")
        except Exception as e:
            diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="notify_controller.window.destroy", ok=False, err=str(e)[:80])
        try:
            if inst:
                inst.release()
                diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="inst.release", ok=True)
            else:
                diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="inst.release", ok=True, skipped="no_inst")
        except Exception as e:
            diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="inst.release", ok=False, err=str(e)[:80])
        diag.emit("DIAG_EXIT", log, "Flask在daemon线程，将随进程自然退出")
        if destroy_window:
            try:
                window.destroy()
                diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="window.destroy", ok=True)
            except Exception as e:
                diag.emit("DIAG_EXIT_STEP", log, "退出步骤", step="window.destroy", ok=False, err=str(e)[:80])
        diag.emit("DIAG_APP_EXIT_OK", log, "已成功退出")
        # 禁止 os._exit：让 webview.start() 自然返回，main() 结束，进程正常退出

    # NOTE: rest/notify 逻辑已迁移至 rest_controller、notify_controller
    diag.emit("DIAG_NOTIFY_MGR_READY", log, "通知管理器就绪(NotifierService已启动，窗口按需懒加载)")

    # ----------------------------
    # Tray(托盘)- 异步初始化，不阻塞主窗口显示
    # ----------------------------
    tray = None

    def _init_tray_async():
        """异步初始化托盘图标，避免阻塞主窗口启动"""
        nonlocal tray, tray_enabled
        try:
            from eye_care.tray.tray_icon import TrayCallbacks, PywebviewTrayIcon

            icon_path = PROJECT_ROOT / "icon.ico"

            def _is_window_visible() -> bool:
                return bool(window_visible["v"])

            def _show_main_window() -> None:
                """必须在 GUI 线程执行。只显示并强制前置，无 hide。"""
                _set_window_visible(True)  # 若已隐藏则 show，并始终 restore + bring_to_front

            def _on_open_settings() -> None:
                _set_window_visible(True)
                try:
                    window.evaluate_js("window.ui.openSettings()")
                except Exception:
                    log_exception_summary(log, "DIAG_EXCEPTION", "托盘打开设置", "evaluate_js 失败")

            def _on_rest_start() -> None:
                _set_window_visible(True)
                try:
                    window.evaluate_js("window.ui.restStart()")
                except Exception:
                    log_exception_summary(log, "DIAG_EXCEPTION", "托盘立即休息", "evaluate_js 失败")

            def _on_check_update() -> None:
                _set_window_visible(True)
                try:
                    window.evaluate_js("window.ui.checkUpdate()")
                except Exception:
                    log_exception_summary(log, "DIAG_EXCEPTION", "托盘检查更新", "evaluate_js 失败")

            def _on_open_data_dir() -> None:
                try:
                    os.startfile(str(data_dir))
                except Exception:
                    log_exception_summary(log, "DIAG_EXCEPTION", "托盘打开数据目录", "startfile 失败")

            def _on_dump_threads() -> None:
                """抓取线程栈：调用 hang_dump.dump_threads 并记录日志。"""
                try:
                    from eye_care.diagnostics.hang_dump import dump_threads
                    out_path = dump_threads(data_dir, reason="manual")
                    log.info("线程栈已抓取: %s", out_path)
                    diag.emit("DIAG_HANG_DUMP", log, "线程栈已抓取", path=str(out_path))
                except Exception as e:
                    log_exception_summary(
                        log,
                        "DIAG_EXCEPTION",
                        "托盘抓取线程栈",
                        "dump_threads 失败",
                        detail=str(e)[:200],
                        reason_code="E_HANG_DUMP_FAILED",
                    )

            def _set_run_mode(mode: str) -> None:
                if controller and controller_ready["value"]:
                    controller.set_run_mode(mode)

            def _quit() -> None:
                # 托盘退出：投递到 GUI 线程执行，避免在托盘线程里操作窗口
                dispatcher.post(lambda: _request_exit("tray_quit", destroy_window=True))
                diag.emit("DIAG_DISPATCH_TRAY_QUIT", log, "托盘退出已投递到GUI队列")

            def _run_on_main(fn) -> None:
                dispatcher.post(fn)
                diag.emit("DIAG_DISPATCH_TRAY_CALLBACK", log, "托盘回调已投递到GUI队列", fn_name=getattr(fn, "__name__", "unknown"))

            tray = PywebviewTrayIcon(
                icon_path=icon_path,
                callbacks=TrayCallbacks(
                    on_show_main=lambda: dispatcher.post(_show_main_window),
                    on_set_run_mode=_set_run_mode,
                    on_quit=_quit,
                    run_on_main=_run_on_main,
                    is_window_visible=_is_window_visible,
                    is_paused=lambda: bool(controller.state.is_paused) if controller and controller_ready["value"] else False,
                    is_dnd=lambda: bool(controller.state.is_dnd) if controller and controller_ready["value"] else False,
                    is_force_idle=lambda: bool(controller.state.force_idle) if controller and controller_ready["value"] else False,
                    is_auto_idle=lambda: bool(controller.state.auto_idle) if controller and controller_ready["value"] else False,
                    on_open_settings=_on_open_settings,
                    on_rest_start=_on_rest_start,
                    on_check_update=_on_check_update,
                    on_open_data_dir=_on_open_data_dir,
                    on_dump_threads=_on_dump_threads,
                ),
                title="EyE Care",
            )

            tray_enabled = tray.start()
            api.set_tray_enabled(tray_enabled)
            if tray_enabled:
                diag.emit("DIAG_TRAY_OK", log, "托盘已启用(异步)")
            else:
                diag.emit("DIAG_TRAY_UNAVAILABLE", log, "托盘不可用", level=logging.WARNING)
                # 托盘失败时显示主窗口作为兜底，确保用户能访问程序
                if not startup_show_main:
                    dispatcher.post(lambda: _set_window_visible(True))
                    diag.emit("DIAG_TRAY_FALLBACK", log, "托盘失败，已显示主窗口作为兜底")
        except Exception:
            log_exception_summary(log, "DIAG_EXCEPTION", "托盘异步初始化", "托盘不可用，主窗口正常")
            log.exception("tray async init failed")
            # 托盘初始化异常时，如果窗口隐藏则显示主窗口作为兜底
            if not startup_show_main:
                dispatcher.post(lambda: _set_window_visible(True))
                diag.emit("DIAG_TRAY_FALLBACK", log, "托盘初始化异常，已显示主窗口作为兜底")

    # 在后台线程初始化托盘，不阻塞窗口显示
    threading.Thread(target=_init_tray_async, daemon=True, name="tray_init").start()

    def on_closed():
        """窗口关闭事件：干净退出(正确注销窗口类)"""
        _request_exit("window_closed", destroy_window=False)

    window.events.closed += on_closed
    diag.emit("DIAG_PYWEBVIEW_START", log, "pywebview即将启动")
    try:
        webview.start(debug=False, func=_on_webview_start)
    except TypeError:
        webview.start(debug=False)
    diag.emit("DIAG_PYWEBVIEW_EXIT", log, "pywebview已退出")
