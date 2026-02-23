"""
NotifyWindowController：通知窗口生命周期（创建、show、hide、样式、效果）。
所有方法必须在 GUI 线程调用。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

from eye_care.diagnostics import diag, log_exception_summary
from eye_care.diagnostics.debug_switch import is_debug_enabled
from eye_care.diagnostics.hwnd_dump import dump_hwnd
from eye_care.ui.style_coordinator import StyleCoordinator, StylePhase, StyleState, StyleTarget
from eye_care.ui.state_machines import NotifyShadowMachine
from eye_care.ui.state_machines.types import NotifyState as NotifyMachineState, TransitionResult
from eye_care.ui.win_utils import native_handle_to_int

from .notify_hwnd_diag import diag_notify_hwnd_alpha, log_notify_ex_style, log_notify_window_class
from .notify_metrics import NotifyMetrics
from .notify_factory import calculate_notify_geometry, calculate_notify_init_position

log = logging.getLogger(__name__)


class NotifyWindowController:
    """通知窗口控制器。仅负责窗口 UI，不处理业务逻辑。"""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        win_effects,
        window_runtime,
        data_dir: Path,
        controller_getter: Callable[[], Any],
        dispatcher,
        clear_prompt_dedupe: Callable[[], None],
        debug_notify_getter: Callable[[], bool],
        harden_hwnd_dump: Optional[Callable[..., None]] = None,
        on_notify_shown: Optional[Callable[[], None]] = None,
        on_user_action_complete: Optional[Callable[[tuple, dict], None]] = None,
        sm_notify_v2_getter: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._log = logger
        self._on_notify_shown = on_notify_shown
        self._on_user_action_complete = on_user_action_complete or (lambda _pk, _ex: None)
        self._win_effects = win_effects
        self._window_runtime = window_runtime
        self._data_dir = Path(data_dir)
        self._controller_getter = controller_getter
        self._dispatcher = dispatcher
        self._clear_prompt_dedupe = clear_prompt_dedupe
        self._debug_notify_getter = debug_notify_getter
        self._harden_hwnd_dump = harden_hwnd_dump or (lambda *a, **k: None)
        # Notify 显式状态机开关（默认 False，legacy 行为）
        self._sm_notify_v2_getter = sm_notify_v2_getter or (lambda: False)

        def _dbg_log(msg: str, *args: Any, **kwargs: Any) -> None:
            if is_debug_enabled():
                self._log.info(msg, *args, **kwargs)
        self._dbg_log = _dbg_log

        self._window = None
        self._bridge = None
        self._title_token: Optional[str] = None
        self._initialized = False
        self._ready = False
        self._hwnd_cache: dict = {}
        self._geom = {"w": 400, "h": 160}
        self._preload_event = threading.Event()
        self._gui_loop_ready = False
        self._notify_ready_dict: dict = {"value": False}
        self._style_applied = False
        self._notify_init_xy: tuple = (0, 0)
        self._style_state: Optional[StyleState] = None
        self._style_target: Optional[StyleTarget] = None
        self._style_coordinator: Optional[StyleCoordinator] = None

        # fade/visibility guards（避免重复 hide / 多次 fade 叠加导致"一闪就没了"）
        self._fade_gen: int = 0
        self._hide_in_progress: bool = False
        self._hide_timeout_timer: Optional[threading.Timer] = None
        self._shown: bool = False
        self._alpha_cache: int = 255
        self._show_retry_count: int = 0
        # 方案2：前端 ACK + 50ms 最小延迟，再开始淡入
        self._notify_fade_started: bool = False
        self._notify_ack_received: bool = False
        self._notify_min_delay_elapsed: bool = False
        # show 互斥：同一时间只允许一次 show 在进行，避免重复触发踩到未就绪状态
        self._show_lock = threading.Lock()
        self._show_inflight: bool = False
        self._pending_payload: Optional[dict] = None
        # 当前展示的 prompt_key/extra，用户点击 rest/snooze/dismiss 时上报 on_notify_complete(True) 用
        self._current_prompt_key: Optional[tuple] = None
        self._current_extra: Optional[dict] = None
        # 就绪栅栏：show 前需 form_handle / webview_core / transparent / acrylic 四者就绪
        self._ready_evt = threading.Event()
        self._ready_flags: dict = {
            "form_handle": False,
            "webview_core": False,
            "transparent": False,
            "acrylic": False,
        }
        # 状态机影子：仅记录迁移，不驱动行为
        self._shadow = NotifyShadowMachine(self._log)
        # first_frame 去重：同一 session 仅接受首条 FIRST_FRAME_RENDERED（指南 5.3）
        self._show_session_counter: int = 0
        self._current_show_session_id: Optional[int] = None
        self._first_frame_received_session_id: Optional[int] = None
        self._first_frame_dup_count: int = 0
        # 指标模块
        self._metrics = NotifyMetrics()

    def _mark_ready(self, key: str, ok: bool = True) -> None:
        self._ready_flags[key] = bool(ok)
        if all(self._ready_flags.values()):
            self._ready_evt.set()

    def _reset_ready(self) -> None:
        self._ready_evt.clear()
        for k in self._ready_flags:
            self._ready_flags[k] = False

    def set_gui_loop_ready(self) -> None:
        self._gui_loop_ready = True

    def request_preload(self) -> None:
        """请求预加载（可由非 GUI 线程调用）。"""
        self._preload_event.set()

    def check_and_do_preload(self) -> bool:
        """GUI 线程调用：若预加载请求已设置，则执行 lazy_init 并返回 True。"""
        if not self._preload_event.is_set():
            return False
        try:
            self._preload_event.clear()
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
        self.lazy_init(force_in_gui=True)
        return True

    def lazy_init(self, force_in_gui: bool = False) -> None:
        """延迟初始化通知窗口。必须在 GUI 线程调用。"""
        if not self._gui_loop_ready and not force_in_gui:
            self._preload_event.set()
            diag.emit("DIAG_NOTIFY_PRELOAD_DEFER", self._log, "通知窗预加载推迟(GUI未就绪)", level=logging.WARNING)
            self._shadow.record_defer("preload_gui_not_ready")
            return
        if self._initialized:
            return

        diag.emit("DIAG_NOTIFY_PRELOAD_START", self._log, "开始懒加载通知窗口")
        self._reset_ready()
        try:
            from eye_care.ui.desktop_integrations import NotifyBridge
            import webview as _wv
            import uuid

            self._bridge = NotifyBridge()
            self._ready = False
            self._title_token = uuid.uuid4().hex
            title = f"EyE Care Notify [{self._title_token}]"
            # 使用工厂函数计算几何和初始位置
            w, h, scale = calculate_notify_geometry()
            self._geom["w"], self._geom["h"] = w, h
            x_init, y_init = calculate_notify_init_position()
            self._notify_init_xy = (x_init, y_init)

            notify_url = self._window_runtime.build_notify_url()
            diag.emit("DIAG_NOTIFY_CREATE_START", self._log, "notify window create 开始", url=notify_url[:80], transparent=True, background_color="#101826", frameless=True, hidden=True, title=title[:40])
            if is_debug_enabled():
                diag.emit("DIAG_NOTIFY_PIPE", self._log, "创建参数", step="create_params", transparent=True, background_color="#101826", title=title[:40])
            try:
                self._window = _wv.create_window(
                    title, notify_url,
                    width=w, height=h, x=x_init, y=y_init,
                    frameless=True, easy_drag=False, on_top=True,
                    resizable=False, transparent=True,
                    background_color="#101826",
                    js_api=self._bridge, minimized=False, hidden=True,
                )
                diag.emit("DIAG_NOTIFY_CREATE_OK", self._log, "notify window create 成功", transparent=True, background_color="#101826", hidden=True)
            except (TypeError, ValueError) as e:
                diag.emit("DIAG_NOTIFY_CREATE_OK", self._log, "notify window create 降级(无 background_color)", transparent=True, hidden=True, err=str(e)[:60])
                self._window = _wv.create_window(
                    title, notify_url,
                    width=w, height=h, x=x_init, y=y_init,
                    frameless=True, easy_drag=False, on_top=True,
                    resizable=False, transparent=True,
                    js_api=self._bridge, minimized=False, hidden=True,
                )
            self._initialized = True
            # 就绪栅栏：绑定 form_handle / webview_core 置位
            native = getattr(self._window, "native", None)
            if native is not None:
                def _on_handle_created(sender, args):
                    diag.emit("DIAG_NOTIFY_BARRIER", self._log, "form_handle ready")
                    self._mark_ready("form_handle", True)
                try:
                    native.HandleCreated += _on_handle_created
                    if getattr(native, "IsHandleCreated", False):
                        self._mark_ready("form_handle", True)
                except Exception as e:
                    diag.emit("DIAG_NOTIFY_BARRIER", self._log, "bind HandleCreated failed", err=str(e)[:80])
                browser = getattr(native, "browser", None)
                wv = getattr(browser, "webview", None) if browser else None
                if wv is not None:
                    def _on_core_init(sender, args):
                        try:
                            core = getattr(wv, "CoreWebView2", None)
                            h = getattr(native, "Handle", None)
                            native_hwnd = h() if callable(h) else h
                            diag.emit(
                                "DIAG_NOTIFY_BARRIER", self._log, "webview_core ready",
                                ok=getattr(args, "IsSuccess", None), wv_id=id(wv), core_id=id(core) if core is not None else None, native_hwnd=native_hwnd,
                            )
                        except Exception as e:
                            diag.emit("DIAG_NOTIFY_BARRIER", self._log, "webview_core ready id dump failed", ok=getattr(args, "IsSuccess", None), err=str(e)[:60])
                        self._mark_ready("webview_core", True)
                    try:
                        wv.CoreWebView2InitializationCompleted += _on_core_init
                        if getattr(wv, "CoreWebView2", None) is not None:
                            self._mark_ready("webview_core", True)
                    except Exception as e:
                        diag.emit("DIAG_NOTIFY_BARRIER", self._log, "bind Core init failed", err=str(e)[:80])
            try:
                hwnd_by_title = self._find_hwnd()
                native_handle_raw = None
                try:
                    n = getattr(self._window, "native", None)
                    if n is not None:
                        native_handle_raw = getattr(n, "Handle", None) or getattr(n, "handle", None)
                        if callable(native_handle_raw):
                            native_handle_raw = native_handle_raw()
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
                native_handle_int = native_handle_to_int(native_handle_raw)
                same = (hwnd_by_title == native_handle_int) if (hwnd_by_title is not None and native_handle_int is not None) else None
                if is_debug_enabled():
                    diag.emit("DIAG_NOTIFY_PIPE", self._log, "创建后hwnd来源", step="after_create", hwnd_by_title=hwnd_by_title, native_handle_int=native_handle_int, same=same)
            except Exception as e:
                diag.emit("DIAG_NOTIFY_PIPE", self._log, "创建后hwnd检查异常", step="after_create", err=str(e)[:80])
            debug_notify_only = {"v": False}

            def _on_loaded_inner():
                if is_debug_enabled():
                    diag.emit("DIAG_NOTIFY_PIPE", self._log, "loaded回调触发", step="loaded_fired")
                self._notify_ready_dict["value"] = True
                self._ready = True
                if self._debug_notify_getter():
                    diag.emit("DIAG_NOTIFY_READY", self._log, "通知窗口已加载就绪")
                # 就绪栅栏：loaded 时再绑 webview_core（create 时 browser 可能尚未创建）
                if not self._ready_flags.get("webview_core"):
                    native = getattr(self._window, "native", None) if self._window else None
                    browser = getattr(native, "browser", None) if native else None
                    wv = getattr(browser, "webview", None) if browser else None
                    if wv is not None:
                        def _on_core_init_loaded(sender, args):
                            try:
                                core = getattr(wv, "CoreWebView2", None)
                                h = getattr(native, "Handle", None)
                                native_hwnd = h() if callable(h) else h
                                diag.emit(
                                    "DIAG_NOTIFY_BARRIER", self._log, "webview_core ready (loaded)",
                                    ok=getattr(args, "IsSuccess", None), wv_id=id(wv), core_id=id(core) if core is not None else None, native_hwnd=native_hwnd,
                                )
                            except Exception as e:
                                diag.emit("DIAG_NOTIFY_BARRIER", self._log, "webview_core ready id dump failed", ok=getattr(args, "IsSuccess", None), err=str(e)[:60])
                            self._mark_ready("webview_core", True)
                        try:
                            wv.CoreWebView2InitializationCompleted += _on_core_init_loaded
                            if getattr(wv, "CoreWebView2", None) is not None:
                                self._mark_ready("webview_core", True)
                        except Exception as e:
                            diag.emit("DIAG_NOTIFY_BARRIER", self._log, "bind Core init (loaded) failed", err=str(e)[:80])
                # 修 race：loaded 可能先于 _style_target 构建触发
                if (self._style_target is None) or (self._style_coordinator is None):
                    try:
                        self._style_state = StyleState(mode="NOTIFY", overlay_id="notify")
                        self._style_target = StyleTarget(
                            kind="NOTIFY",
                            overlay_id="notify",
                            get_native=lambda: getattr(self._window, "native", None),
                            get_webview=lambda: (
                                getattr(getattr(getattr(self._window, "native", None), "browser", None), "webview", None)
                            ),
                            get_hwnd=self._find_hwnd,
                            get_bounds=None,
                            set_hwnd=None,
                            state=self._style_state,
                            on_ready=self._mark_ready,
                        )
                        self._style_coordinator = StyleCoordinator(self._log, self._win_effects)
                        if is_debug_enabled():
                            diag.emit("DIAG_NOTIFY_PIPE", self._log, "loaded内补建style_target", step="style_target_build_in_loaded", ok=True)
                    except Exception as e:
                        diag.emit("DIAG_NOTIFY_PIPE", self._log, "loaded内补建style_target失败", step="style_target_build_in_loaded", err=str(e)[:80])
                # loaded 兜底：late_set + 可选再 apply 一次（不依赖此为唯一启动点）
                try:
                    if self._style_target and self._style_coordinator:
                        self._style_coordinator.apply(self._style_target, self._dispatcher)
                    self._dispatcher.post(self._late_set_notify_transparent)
                    if is_debug_enabled():
                        diag.emit("DIAG_NOTIFY_PIPE", self._log, "loaded内late_set+apply兜底", step="loaded_fallback", ok=bool(self._style_target and self._style_coordinator))
                except Exception as e:
                    diag.emit("DIAG_NOTIFY_PIPE", self._log, "loaded内兜底异常", step="loaded_fallback", err=str(e)[:80])
                threading.Timer(0.2, lambda: self._dispatcher.post(self._late_set_notify_transparent)).start()
            try:
                if getattr(self._window, "events", None) and getattr(self._window.events, "loaded", None):
                    self._window.events.loaded += _on_loaded_inner
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")

            def _hide_notify(reason: str) -> None:
                # 必须投递到 GUI 线程执行，保证 fade_out 在 GUI 线程跑
                self._dispatcher.post(lambda r=reason: self.hide(r))

            def _flush_notify_complete() -> None:
                """用户点击 rest/snooze/dismiss 后调用：上报 on_notify_complete(True)，并清空当前 prompt。
                仅当 pk/ex 已设置时才上报，避免前端在 _do_show_ui 前误发 action 导致误 mark_rest_notified。
                """
                pk, ex = self._current_prompt_key, self._current_extra
                self._current_prompt_key = None
                self._current_extra = None
                if pk is not None and ex is not None:
                    try:
                        self._on_user_action_complete(pk, ex)
                    except Exception:
                        self._log.exception("notify: on_user_action_complete failed")
                elif pk is None and ex is None:
                    self._log.debug("notify: on_action_done skipped (no current prompt_key, possible early/lost action)")

            def _show_rest_via_dispatcher() -> None:
                self._dispatcher.post_rest_show()

            self._window_runtime.bind_notify_bridge(
                notify_bridge=self._bridge,
                notify_ready=self._notify_ready_dict,
                debug_notify_only=debug_notify_only,
                notify_title_token_getter=lambda: self._title_token,
                hide_notify_with_fade=_hide_notify,
                clear_prompt_dedupe=self._clear_prompt_dedupe,
                show_rest_overlay=_show_rest_via_dispatcher,
                on_ready_for_show=lambda: self._dispatcher.post(self._on_ready_for_show_ack),
                on_action_done=_flush_notify_complete,
            )

            self._style_state = StyleState(mode="NOTIFY", overlay_id="notify")
            self._style_target = StyleTarget(
                kind="NOTIFY",
                overlay_id="notify",
                get_native=lambda: getattr(self._window, "native", None),
                # WebView2 对象：用于 StyleCoordinator 判断 WebView 就绪并设置 DefaultBackgroundColor
                get_webview=lambda: (
                    getattr(getattr(getattr(self._window, "native", None), "browser", None), "webview", None)
                ),
                get_hwnd=self._find_hwnd,
                get_bounds=None,
                set_hwnd=None,
                state=self._style_state,
                on_ready=self._mark_ready,
            )
            self._style_coordinator = StyleCoordinator(self._log, self._win_effects)
            # 样式链尽早启动：create 后立即 post apply（不等 loaded）
            try:
                self._style_coordinator.apply(self._style_target, self._dispatcher)
                if is_debug_enabled():
                    diag.emit("DIAG_NOTIFY_PIPE", self._log, "create后post_apply", step="apply_post_create", ok=True)
            except Exception as e:
                diag.emit("DIAG_NOTIFY_PIPE", self._log, "create后post_apply失败", step="apply_post_create", err=str(e)[:120])
            try:
                self._window.hide()
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify window hide(create)", "仅记录", detail=str(e)[:200], reason_code="E_NOTIFY_WINDOW_HIDE")
        except Exception:
            self._initialized = False
            log_exception_summary(self._log, "DIAG_EXCEPTION", "通知窗懒加载", "通知窗可能不可用")

    def _has_webview_controller(self) -> bool:
        """Controller 未 ready 时 show 会导致首帧白底，caller 可据此 defer show。"""
        try:
            native = getattr(self._window, "native", None) if self._window else None
            browser = getattr(native, "browser", None) if native else None
            wv = getattr(browser, "webview", None) if browser else None
            core = getattr(wv, "CoreWebView2", None) if wv else None
            ctl = getattr(wv, "CoreWebView2Controller", None) if wv else None
            if ctl is None and core is not None:
                ctl = getattr(core, "Controller", None)
            return ctl is not None
        except Exception:
            return False

    def _post_js_update(self, js: str) -> None:
        """通过 dispatcher.post 投递到 GUI 线程执行 evaluate_js，避免在后台线程直接调用窗口 API。
        
        硬约束：不可在后台线程直接 evaluate_js，必须通过 dispatcher.post 投递到 GUI 线程。
        
        注意：evaluate_js 是同步调用，可能阻塞 GUI 线程。虽然无法真正中断阻塞的调用，
        但会记录执行时间，便于诊断问题。
        """
        def _eval_in_gui():
            try:
                if self._window and getattr(self._window, "evaluate_js", None):
                    start_time = time.perf_counter()
                    self._window.evaluate_js(js)
                    elapsed = time.perf_counter() - start_time
                    # 如果执行时间超过 100ms，记录警告日志
                    if elapsed > 0.1:
                        diag.emit("DIAG_NOTIFY_PIPE", self._log, f"evaluate_js 执行时间较长: {elapsed:.3f}s", step="eval_js_slow", js_snippet=js[:100])
                        self._log.warning(f"notify evaluate_js took {elapsed:.3f}s, may block GUI thread. JS: {js[:200]}")
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify evaluate_js", "降级", detail=str(e)[:200], reason_code="E_NOTIFY_M0_EVAL_JS")
        self._dispatcher.post(_eval_in_gui)

    def _post_gui(self, fn: Callable[[], None]) -> bool:
        """M0：仅异步投递到 GUI 线程（BeginInvoke），不等待，避免死锁。返回是否投递成功。"""
        native = getattr(self._window, "native", None) if self._window else None
        if not native:
            return False
        try:
            from System.Windows.Forms import MethodInvoker
            if getattr(native, "InvokeRequired", False):
                native.BeginInvoke(MethodInvoker(fn))
            else:
                fn()
            return True
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "notify post_gui", "降级", detail=str(e)[:200], reason_code="E_NOTIFY_M0_POST_GUI")
            return False

    def _has_webview_core_ui(self) -> bool:
        """仅在 UI 线程调用：CoreWebView2 是否已就绪。不吞异常，由调用方保证在 UI 线程执行。"""
        native = getattr(self._window, "native", None) if self._window else None
        browser = getattr(native, "browser", None) if native else None
        wv = getattr(browser, "webview", None) if browser else None
        core = getattr(wv, "CoreWebView2", None) if wv else None
        return core is not None

    def _has_webview_core(self) -> bool:
        """CoreWebView2 是否已就绪；透明判据以 Core 为准。仅在 UI 线程调用可靠；非 UI 线程可能误判为 False。"""
        try:
            native = getattr(self._window, "native", None) if self._window else None
            browser = getattr(native, "browser", None) if native else None
            wv = getattr(browser, "webview", None) if browser else None
            core = getattr(wv, "CoreWebView2", None) if wv else None
            return core is not None
        except Exception:
            return False

    def _post_to_native_ui(self, fn: Callable[[], None]) -> None:
        """将 fn 投递到 WinForms UI 线程执行（WebView2/CoreWebView2 必须在该线程访问）。无 native 时用 dispatcher 兜底。"""
        native = getattr(self._window, "native", None) if self._window else None
        if native is not None:
            try:
                from System import Action
                native.BeginInvoke(Action(fn))
                return
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify BeginInvoke late_set", "降级走dispatcher", detail=str(e)[:200], reason_code="E_NOTIFY_M0_BEGININVOKE")
        self._dispatcher.post(fn)

    def _retry_set_bg_until_controller_ready(self, max_ms: int = 1200, interval_ms: int = 50) -> None:
        """
        在 controller 就绪后再设置透明背景，避免设到非最终 controller 导致偶发白底。
        通过定时重试实现，成功一次即停止（幂等）；超时打 DIAG_NOTIFY_STYLE_APPLY_FAIL。
        重试必须在 WinForms UI 线程执行（CoreWebView2 仅可在该线程访问），故用 native.BeginInvoke 投递。
        """
        if getattr(self, "_notify_controller_bg_applied", False):
            return
        if getattr(self, "_controller_retry_in_progress", False):
            return
        native = getattr(self._window, "native", None) if self._window else None
        browser = getattr(native, "browser", None) if native else None
        wv = getattr(browser, "webview", None) if browser else None
        diag.emit("DIAG_NOTIFY_STYLE_APPLY_START", self._log, "late_set 透明样式开始（controller 就绪后 set）")
        diag.emit("DIAG_NOTIFY_LATE_SET", self._log, "late-set透明入口", has_native=native is not None, has_wv=wv is not None)
        if not native or not wv:
            diag.emit("DIAG_NOTIFY_STYLE_APPLY_FAIL", self._log, "late_set 缺少 native 或 webview", has_native=native is not None, has_wv=wv is not None)
            return
        self._controller_retry_in_progress = True
        self._post_to_native_ui(lambda: self._run_controller_ready_retry(time.time(), 0, max_ms, interval_ms))

    def _run_controller_ready_retry(
        self, start_ts: float, attempt: int, max_ms: int = 1200, interval_ms: int = 50
    ) -> None:
        """单次重试：若 controller 可用则设置并打 OK；否则打 CONTROLLER_WAIT 并继续或超时 FAIL。必须在 GUI 线程。"""
        elapsed_ms = int((time.time() - start_ts) * 1000)
        native = getattr(self._window, "native", None) if self._window else None
        browser = getattr(native, "browser", None) if native else None
        wv = getattr(browser, "webview", None) if browser else None
        core = getattr(wv, "CoreWebView2", None) if wv else None
        ctl = (
            getattr(wv, "CoreWebView2Controller", None)
            or (getattr(core, "Controller", None) if core else None)
        )
        has_controller = ctl is not None
        diag.emit(
            "DIAG_NOTIFY_CONTROLLER_WAIT", self._log, "controller 就绪等待/重试",
            attempt=attempt,
            elapsed_ms=elapsed_ms,
            has_native=native is not None,
            has_wv=wv is not None,
            has_controller=has_controller,
            controller_is_none=ctl is None,
        )
        if ctl is not None:
            try:
                import clr
                clr.AddReference("System.Drawing")
                clr.AddReference("System.Windows.Forms")
                from System.Drawing import Color
                trans = Color.FromArgb(0, 0, 0, 0)
            except Exception as e:
                diag.emit("DIAG_NOTIFY_STYLE_APPLY_FAIL", self._log, "late_set Color 失败", err=str(e)[:80])
                self._controller_retry_in_progress = False
                return
            try:
                wv.DefaultBackgroundColor = trans
                if core is not None:
                    core.DefaultBackgroundColor = trans
                ctl.DefaultBackgroundColor = trans
                native.BackColor = trans
                try:
                    native.Invalidate(True)
                    native.Refresh()
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
            except Exception as e:
                diag.emit("DIAG_NOTIFY_STYLE_APPLY_FAIL", self._log, "controller 就绪后设置异常", err=str(e)[:80])
                self._controller_retry_in_progress = False
                return
            # 读回并打 OK
            try:
                na_col = getattr(native, "BackColor", None)
                core_col = getattr(core, "DefaultBackgroundColor", None) if core else None
                ctl_col = getattr(ctl, "DefaultBackgroundColor", None)
                wv_col = getattr(wv, "DefaultBackgroundColor", None)
                native_BackColor_A = getattr(na_col, "A", None) if na_col is not None else None
                core_bg_A = getattr(core_col, "A", None) if core_col is not None else None
                ctl_bg_A = getattr(ctl_col, "A", None) if ctl_col is not None else None
                wv_bg_A = getattr(wv_col, "A", None) if wv_col is not None else None
                diag.emit(
                    "DIAG_NOTIFY_STYLE_APPLY_OK", self._log, "late_set 完成（controller 就绪后 set）",
                    controller_bg_A=ctl_bg_A,
                    core_bg_A=core_bg_A,
                    ctl_bg_A=ctl_bg_A,
                    native_BackColor_A=native_BackColor_A,
                    webview_bg_A=wv_bg_A,
                )
            except Exception as e:
                diag.emit("DIAG_NOTIFY_STYLE_APPLY_OK", self._log, "late_set 完成（读回失败）", err=str(e)[:60])
            self._notify_controller_bg_applied = True
            self._controller_retry_in_progress = False
            # 成功后允许下一轮 show 再次触发
            self._late_set_triggered_this_cycle = False
            return
        if elapsed_ms >= max_ms:
            diag.emit(
                "DIAG_NOTIFY_STYLE_APPLY_FAIL", self._log, "controller 未就绪超时",
                err="controller_not_ready_timeout",
                elapsed_ms=elapsed_ms,
                attempts=attempt,
            )
            self._controller_retry_in_progress = False
            # 超时后允许后续触发点再次尝试（重置本轮触发标志）
            self._late_set_triggered_this_cycle = False
            if self._debug_notify_getter():
                self._start_notify_frame_probe()
            return
        # 继续重试：必须投递到 WinForms UI 线程（Timer 在后台线程，不能直接访问 WebView2）
        next_attempt = attempt + 1
        threading.Timer(
            interval_ms / 1000.0,
            lambda: self._post_to_native_ui(
                lambda: self._run_controller_ready_retry(start_ts, next_attempt, max_ms, interval_ms)
            ),
        ).start()

    def _start_notify_frame_probe(self) -> None:
        """可选：debug 下、controller 超时后短时高频取证，1 秒内每 16ms 打 DIAG_NOTIFY_FRAME_PROBE（最多 60 条）。必须在 WinForms UI 线程执行。"""
        def _probe(probe_index: int, start_ts: float) -> None:
            if probe_index >= 60:
                return
            elapsed_ms = int((time.time() - start_ts) * 1000)
            native = getattr(self._window, "native", None) if self._window else None
            browser = getattr(native, "browser", None) if native else None
            wv = getattr(browser, "webview", None) if browser else None
            core = getattr(wv, "CoreWebView2", None) if wv else None
            ctl = (
                getattr(wv, "CoreWebView2Controller", None)
                or (getattr(core, "Controller", None) if core else None)
            )
            has_controller = ctl is not None
            native_a = None
            ctl_a = None
            ex_style_hex = None
            ws_ex_layered = None
            try:
                bc = getattr(native, "BackColor", None) if native else None
                native_a = getattr(bc, "A", None) if bc is not None else None
                if ctl is not None:
                    col = getattr(ctl, "DefaultBackgroundColor", None)
                    ctl_a = getattr(col, "A", None) if col is not None else None
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
            try:
                h = self._find_hwnd()
                if h:
                    import win32con
                    import win32gui
                    ex = win32gui.GetWindowLong(int(h), win32con.GWL_EXSTYLE)
                    ex_style_hex = hex(ex)
                    ws_ex_layered = bool(ex & 0x80000)
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
            diag.emit(
                "DIAG_NOTIFY_FRAME_PROBE", self._log, "notify 短时取证",
                elapsed_ms=elapsed_ms,
                has_controller=has_controller,
                native_BackColor_A=native_a,
                controller_DefaultBackgroundColor_A=ctl_a,
                ex_style_hex=ex_style_hex,
                ws_ex_layered=ws_ex_layered,
            )
            if probe_index + 1 < 60:
                threading.Timer(
                    0.016,
                    lambda: self._post_to_native_ui(lambda: _probe(probe_index + 1, start_ts)),
                ).start()
        self._post_to_native_ui(lambda: _probe(0, time.time()))

    def _late_set_notify_transparent(self) -> None:
        """
        NOTIFY 专用：在 controller 就绪后再设 WebView2 背景透明，避免设到非最终 controller 导致偶发白底。
        入口仅启动重试链 _retry_set_bg_until_controller_ready；真正设置以 controller-ready 为判据。
        必须在 GUI 线程调用（或由 dispatcher 投递到 GUI）。
        """
        # 防护：避免同一 show 周期内重复触发重试链
        if getattr(self, "_late_set_triggered_this_cycle", False):
            if is_debug_enabled():
                diag.emit("DIAG_NOTIFY_LATE_SET", self._log, "本轮已触发过，跳过", step="already_triggered")
            return
        if getattr(self, "_notify_controller_bg_applied", False):
            if is_debug_enabled():
                diag.emit("DIAG_NOTIFY_LATE_SET", self._log, "已设置过，跳过", step="already_applied")
            return
        self._late_set_triggered_this_cycle = True
        self._retry_set_bg_until_controller_ready(max_ms=1200, interval_ms=50)

    def _do_actual_show(self) -> None:
        """真正 Show 通知窗口（首帧 ready 后或 _show_step 末尾若已 ready 时调用）。必须在 GUI 线程。"""
        self._dbg_log("DIAG_NOTIFY_M0 | step=3_native_show")
        try:
            n = getattr(self._window, "native", None) if self._window else None
            if n is not None:
                n.Show()
                n.Visible = True
                try:
                    n.BringToFront()
                    n.Activate()
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
            else:
                self._window.show()
        except Exception:
            try:
                self._window.show()
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify show", "降级", detail=str(e)[:200], reason_code="E_NOTIFY_M0_SHOW")
        self._dbg_log("DIAG_NOTIFY_M0 | step=3_after_native_show")
        try:
            ctrl = self._controller_getter() if self._controller_getter else None
            mode = ctrl._current_mode() if ctrl else ""
            is_paused = bool(ctrl.state.is_paused) if ctrl else False
            dnd = bool(ctrl.state.is_dnd) if ctrl else False
        except Exception:
            mode, is_paused, dnd = "", False, False
        # DIAG_METRIC_NOTIFY 耗时与时间戳（record_show_start 已在 _do_show_ui 中调用）
        try:
            self._metrics.record_show_end(success=True)
            self._metrics.record_style_ok()
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
        # FIRST_FRAME_OK 已在 _on_ready_for_show_ack 中处理，这里跳过
        if not self._get_sm_notify_v2():
            if self._shadow.state == NotifyMachineState.SHOWING:
                self._shadow.record(NotifyMachineState.SHOWN, "FIRST_FRAME_OK")
        diag.emit("DIAG_NOTIFY_SHOWN", self._log, "notify 已 Show/Visible（首帧 ready 后）", mode=mode, is_paused=is_paused, dnd=dnd, blocked_reason="")
        self._dispatcher.post(self._late_set_notify_transparent)
        self._shown = True
        self._hide_in_progress = False
        if self._on_notify_shown:
            try:
                self._dispatcher.post(self._on_notify_shown)
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
        self._dbg_log("DIAG_NOTIFY_M0 | step=4_apply_acrylic")
        try:
            h = self._find_hwnd()
            if h:
                diag_notify_hwnd_alpha(self._log, int(h), "notify_show_before_restore")
                # 第二次及以后 show：去掉上次 fade-out 留下的 WS_EX_LAYERED+alpha=0，否则窗口不显示，只在渐出时闪一下
                self._win_effects.restore_exstyle_after_hide([int(h)])
                # 若从未保存过 ex_restore（首次 show 时已有 Layered），restore 无效；此处强制去掉 Layered 使窗口可见
                self._win_effects.ensure_notify_visible_before_show(int(h))
                diag_notify_hwnd_alpha(self._log, int(h), "notify_show_after_restore")
                self._win_effects.enable_acrylic(int(h), tint_color=0xBB101826, blur=True, where="notify_show")
                diag_notify_hwnd_alpha(self._log, int(h), "notify_show_after_acrylic")
            self._ensure_topmost_and_pos(h or 0)
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "notify acrylic/pos", "降级", detail=str(e)[:200], reason_code="E_NOTIFY_M0_ACRYLIC")
        self._dbg_log("DIAG_NOTIFY_M0 | step=5_setpos_done")
        # 渐入由 ACK + 最小延迟 50ms 驱动，不再用固定 0.05s 直接触发 fade-in
        threading.Timer(0.05, lambda: self._dispatcher.post(self._on_min_delay_elapsed)).start()
        threading.Timer(0.15, lambda: self._dispatcher.post(self._late_set_notify_transparent)).start()
        def _reapply():
            try:
                self._late_set_notify_transparent()
                h2 = self._find_hwnd()
                if h2:
                    self._win_effects.enable_acrylic(int(h2), tint_color=0xBB101826, blur=True, where="post_show_reapply_150ms")
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
        threading.Timer(0.15, lambda: self._dispatcher.post(_reapply)).start()

    # ------------------------------ notify fade helpers ------------------------------
    def _resolve_hwnd_for_alpha(self, hwnd: int) -> int:
        """
        解决“alpha 有日志但视觉不生效”的核心：确保对“可见的根窗口”设置 WS_EX_LAYERED + alpha。
        pywebview/WebView2 有时会把 native_handle 指向子窗口；对子窗口 SetLayeredWindowAttributes 可能不影响整体显示。
        """
        try:
            import win32gui
            import win32con
            if not hwnd:
                return hwnd
            h = int(hwnd)
            # 先向上找根窗口
            try:
                root = win32gui.GetAncestor(h, win32con.GA_ROOT)
                if root and win32gui.IsWindow(root):
                    h = int(root)
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
            # 再尝试 root owner（某些情况下 GA_ROOT 仍是 child）
            try:
                ro = win32gui.GetAncestor(h, win32con.GA_ROOTOWNER)
                if ro and win32gui.IsWindow(ro):
                    h = int(ro)
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
            return h
        except Exception:
            return int(hwnd) if hwnd else hwnd

    def _ensure_layered(self, hwnd: int) -> None:
        """确保 Notify 窗口具备 WS_EX_LAYERED（支持 SetLayeredWindowAttributes 渐变）。"""
        try:
            import win32gui
            import win32con
            ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            if not (ex & win32con.WS_EX_LAYERED):
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex | win32con.WS_EX_LAYERED)
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")

    def _set_alpha(self, hwnd: int, alpha: int, where: str) -> None:
        """
        Notify 宿主渐变统一走 win_effects.notify_set_alpha，避免直接调用 SetLayeredWindowAttributes 导致
        Layered + Acrylic 交互异常；where 建议使用 \"notify_fade_in\" / \"notify_fade_out\" 等前缀。
        """
        try:
            if not hwnd:
                return
            self._win_effects.notify_set_alpha(int(hwnd), int(alpha), where or "notify_fade")
        except Exception as e:
            log_exception_summary(
                self._log,
                "DIAG_EXCEPTION",
                "notify set_alpha",
                "degrade_continue",
                detail=str(e)[:200],
                reason_code="E_NOTIFY_SET_ALPHA",
            )

    def _hwnd_brief(self, tag: str, hwnd: int) -> None:
        """hwnd 简报：ex/layered/class/text，用于抓打错窗口或样式漂移。"""
        try:
            import win32con
            import win32gui
            h = int(hwnd) if hwnd else 0
            if not h or not win32gui.IsWindow(h):
                self._dbg_log("HARD_NOTIFY_HWND tag=%s hwnd=%s INVALID", tag, h)
                return
            ex = win32gui.GetWindowLong(h, win32con.GWL_EXSTYLE)
            cls = win32gui.GetClassName(h)
            txt = (win32gui.GetWindowText(h) or "")[:80]
            self._log.info(
                "HARD_NOTIFY_HWND tag=%s hwnd=%s ex=%s layered=%s class=%s text=%s",
                tag, h, hex(ex & 0xFFFFFFFF), bool(ex & win32con.WS_EX_LAYERED), cls, txt,
            )
        except Exception as e:
            self._dbg_log("HARD_NOTIFY_HWND_FAIL tag=%s hwnd=%s err=%r", tag, hwnd, e)

    def _fade_async(self, hwnd: int, a0: int, a1: int, duration_ms: int, where: str, on_done=None) -> None:
        """
        非阻塞淡入淡出（FN09口径）：
        - 用单线程时间循环（sleep对齐下一帧），避免 Timer 堆叠/挤在同一毫秒导致“卡顿台阶感”
        - 以 ~60fps 量化成固定 steps（约每16ms一步），日志频率与 FN09 接近
        """
        try:
            import time
            import math
            a0 = int(a0); a1 = int(a1)
            duration_ms = max(80, int(duration_ms))

            # FN09：200ms ~ 13 steps（约16ms/step）
            steps = max(6, min(30, int(round(duration_ms / 16.0)) + 1))
            step_dt = duration_ms / max(1, steps) / 1000.0

            self._fade_gen += 1
            gen = self._fade_gen

            # 关键：用“可见的根窗口”做 alpha（避免对子窗口 set_alpha 无效）
            alpha_hwnd = self._resolve_hwnd_for_alpha(hwnd)

            if is_debug_enabled():
                diag.emit("HARD_NOTIFY_FADE_BEGIN", self._log, "notify fade begin", where=where,
                         a0=a0, a1=a1, ms=duration_ms, steps=steps, hwnd=int(alpha_hwnd))

            def _runner():
                start = time.perf_counter()
                last_k = -1
                try:
                    for k in range(0, steps + 1):
                        if gen != self._fade_gen:
                            return
                        # 理论时间点
                        target = start + k * step_dt
                        now = time.perf_counter()
                        sleep_s = target - now
                        if sleep_s > 0:
                            time.sleep(sleep_s)

                        # ease-in-out（cosine），比线性更“顺”
                        t = k / float(steps)
                        ease = 0.5 - 0.5 * math.cos(math.pi * t)
                        a = int(round(a0 + (a1 - a0) * ease))
                        # 只在步进变化时写（避免重复）
                        if k != last_k:
                            last_k = k
                            self._dispatcher.post(lambda _a=a, _k=k: self._set_alpha(alpha_hwnd, _a, f"{where}:step{_k}"))

                    self._dispatcher.post(lambda: (diag.emit("HARD_NOTIFY_FADE_END", self._log, "notify fade end", where=where, hwnd=int(alpha_hwnd)) if is_debug_enabled() else None))
                    # 关键修复：layered alpha 可能会破坏 acrylic，淡入结束后重刷一次
                    if "fade_in:show" in str(where):
                        def _reapply_acrylic():
                            try:
                                self._win_effects.enable_acrylic(int(alpha_hwnd), tint_color=0xBB101826, blur=True, where="fade_in_end_reapply")
                            except Exception as e:
                                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
                            try:
                                if hasattr(self, "_late_set_notify_transparent"):
                                    self._late_set_notify_transparent()
                            except Exception as e:
                                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
                        self._dispatcher.post(_reapply_acrylic)
                except Exception as e:
                    self._dispatcher.post(lambda: (diag.emit("HARD_NOTIFY_FADE_FAIL", self._log, "notify fade step failed", where=where, err=str(e)[:80], hwnd=int(alpha_hwnd)) if is_debug_enabled() else None))
                finally:
                    if on_done:
                        try:
                            self._dispatcher.post(on_done)
                        except Exception as e:
                            log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")

            th = threading.Thread(target=_runner, name=f"notify_fade:{where}", daemon=True)
            th.start()
        except Exception as e:
            if is_debug_enabled():
                diag.emit("HARD_NOTIFY_FADE_FAIL", self._log, "notify fade begin failed", where=where, err=str(e)[:80], hwnd=int(hwnd) if hwnd else None)
            if on_done:
                try:
                    self._dispatcher.post(on_done)
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")

    def _on_ready_for_show_ack(self) -> None:
        """方案2：前端调用 notify_ready_for_show 后由 bridge 投递到 GUI 线程执行。first_frame 唯一来源，按 session 去重（指南 5.3）。

        状态机驱动 FIRST_FRAME_OK。
        """
        sid = self._current_show_session_id
        if sid is not None and self._first_frame_received_session_id == sid:
            self._first_frame_dup_count += 1
            if is_debug_enabled():
                diag.emit("DIAG_NOTIFY_STAGE", self._log, "first_frame 重复(已忽略)", stage="first_frame_duplicate", count=self._first_frame_dup_count)
            # 重复 ACK 只记 debug 事件，不驱动状态
            return
        if sid is not None:
            self._first_frame_received_session_id = sid
        diag.emit("DIAG_NOTIFY_FIRST_FRAME", self._log, "notify 首帧/DOM ready（前端已调用 notify_ready_for_show）")

        # 状态机驱动 FIRST_FRAME_OK
        if self._get_sm_notify_v2():
            result, _ = self._shadow.try_transition(event="FIRST_FRAME_OK", to_state=NotifyMachineState.SHOWN, result="ok")
            if result != TransitionResult.OK:
                self._dbg_log("DIAG_NOTIFY_M0 | sm_notify_v2 rejected at FIRST_FRAME_OK")
                return

        self._notify_ack_received = True
        if getattr(self, "_show_deferred_until_ready", False):
            self._show_deferred_until_ready = False
            try:
                self._do_actual_show()
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify do_actual_show ready_ack", "降级", detail=str(e)[:200], reason_code="E_NOTIFY_M0_DO_SHOW")
        self._try_start_notify_fade_in(force=False)

    def _on_min_delay_elapsed(self) -> None:
        """方案1：show 后 50ms 已过，允许在 ACK 到达时开始淡入。"""
        self._notify_min_delay_elapsed = True
        self._try_start_notify_fade_in(force=False)

    def _try_start_notify_fade_in(self, force: bool = False) -> None:
        """
        方案1+2：在「前端 ACK」且「至少 50ms 已过」时开始淡入，或 force 时强制淡入（500ms 超时兜底）。
        """
        if self._notify_fade_started:
            return
        if force or (self._notify_ack_received and self._notify_min_delay_elapsed):
            self._notify_fade_started = True
            self._start_notify_fade_in()

    def _start_notify_fade_in(self) -> None:
        """由 _try_start_notify_fade_in 在 ACK+最小延迟 满足后调用，触发前端 .card 渐入。"""
        self._trigger_notify_card_fade_in()

    def _trigger_notify_card_fade_in(self) -> None:
        """触发前端 .card 的 opacity 0→1 渐入（窗口已固定 alpha=255）。须在 GUI 线程调用。
        使用 _post_js_update 投递执行，避免同步 evaluate_js 在前端忙时阻塞 GUI 线程。"""
        self._post_js_update("window.notifyCardFadeIn && window.notifyCardFadeIn();")

    def _dump_notify_after_fade_end(self, hwnd: Optional[int]) -> None:
        """卡片 CSS 渐入结束后打 dump（约 show 后 250ms）。须在 GUI 线程调用。"""
        if hwnd:
            try:
                dump_hwnd(int(hwnd), where="notify_after_fade_end", logger=self._log, log_prefix="HARD_NOTIFY_HWND_DUMP")
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")

    def _ensure_topmost_and_pos(self, hwnd: int) -> None:
        """置顶并定位到主屏工作区右下角。须在 GUI 线程调用。"""
        if not hwnd:
            return
        try:
            import win32gui
            import win32con
            import win32api
            pt = win32api.GetCursorPos()
            hmon = win32api.MonitorFromPoint(pt, 1)
            mi = win32api.GetMonitorInfo(hmon)
            (l, t, r, b) = mi.get("Work") or mi.get("Monitor")
            x = int(r - self._geom.get("w", 400) - 20)
            y = int(b - self._geom.get("h", 160) - 60)
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, x, y,
                                  self._geom.get("w", 400), self._geom.get("h", 160),
                                  win32con.SWP_NOACTIVATE | win32con.SWP_NOSENDCHANGING)
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE | win32con.SWP_NOSENDCHANGING)
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")

    def _do_show_ui(self, payload: dict, prompt_key: Optional[tuple] = None) -> None:
        """
        M0 治本：GUI 线程只做 Win32/WinForms 显示与样式；禁止同步 evaluate_js（易在 GUI 线程自锁）。
        JS 更新通过 _post_js_update 投递到 GUI 线程执行。
        prompt_key: 本次展示的 prompt 键，用户点击时上报 on_notify_complete(True) 用。

        关键边统一由状态机推进。
        """
        self._current_show_session_id = self._show_session_counter
        self._show_session_counter += 1
        # 新 session 必须重置 ACK 状态，避免旧 session 的 ACK 让本 session 直接放行
        self._notify_ack_received = False

        # 状态机驱动（WINDOW_READY）
        if self._get_sm_notify_v2():
            result, _ = self._shadow.try_transition(event="WINDOW_READY", to_state=NotifyMachineState.CREATED)
            if result != TransitionResult.OK:
                self._dbg_log("DIAG_NOTIFY_M0 | sm_notify_v2 rejected at WINDOW_READY")
                return
            result, _ = self._shadow.try_transition(event="STYLE_ENTER", to_state=NotifyMachineState.STYLING)
            if result != TransitionResult.OK:
                self._dbg_log("DIAG_NOTIFY_M0 | sm_notify_v2 rejected at STYLE_ENTER")
                return
        else:
            # Legacy 行为
            if self._shadow.state == NotifyMachineState.SCHEDULED:
                self._shadow.record(NotifyMachineState.CREATED, "WINDOW_READY")
            if self._shadow.state == NotifyMachineState.CREATED:
                self._shadow.record(NotifyMachineState.STYLING, "STYLE_ENTER")

        if prompt_key is not None:
            self._current_prompt_key, self._current_extra = prompt_key, payload
        self._metrics.record_show_start()
        src = "rest" if payload.get("rest") else "app_details_or_other"
        self._dbg_log("DIAG_NOTIFY_M0 | _do_show_ui enter src=%s", src)
        try:
            self._dbg_log("DIAG_NOTIFY_M0 | step=1_parse_payload")
            if not self._window:
                return
            native = getattr(self._window, "native", None)
            hwnd = self._find_hwnd()
            rest = payload.get("rest") or {}
            msg = rest.get("prompt_reason") or "连续使用时间已达到提醒阈值，建议休息。"
            # 通知自动隐藏时长（秒）：默认 20s，可在设置页修改（点【应用】才生效）
            auto_hide = 20
            try:
                ctrl = self._controller_getter()
                if ctrl and hasattr(ctrl, "cfg"):
                    auto_hide = int(getattr(ctrl.cfg, "notify_auto_hide_seconds", 20) or 0)
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
            # 防呆：限制范围，避免 0 导致前端 1s 定时"马上执行"；避免极端值导致 UI 误行为
            if auto_hide < 1:
                auto_hide = 1
            if auto_hide > 600:
                auto_hide = 600
            import json as _json
            js_for_later = "window.resetFade && window.resetFade(); window.setMessage && window.setMessage(%s); window.autoHide && window.autoHide(%d);" % (_json.dumps(msg), int(auto_hide))

            self._dbg_log("DIAG_NOTIFY_M0 | step=2_before_native_show")

            # 状态机驱动（STYLE_READY）- 降级语义保留
            if self._get_sm_notify_v2():
                # STYLE_DEGRADED 仍允许展示，只有 STYLE_FAIL 才失败终止
                # 这里默认走 STYLE_READY（降级逻辑在样式应用中处理）
                result, _ = self._shadow.try_transition(event="STYLE_READY", to_state=NotifyMachineState.SHOWING, result="ok")
                if result != TransitionResult.OK:
                    # 尝试 STYLE_DEGRADED
                    result, _ = self._shadow.try_transition(event="STYLE_DEGRADED", to_state=NotifyMachineState.SHOWING, result="degraded")
                    if result != TransitionResult.OK:
                        self._dbg_log("DIAG_NOTIFY_M0 | sm_notify_v2 rejected at STYLE_*")
                        return
                    self._metrics.set_degraded_mode(True)
            else:
                # Legacy 行为
                if self._shadow.state == NotifyMachineState.STYLING:
                    self._shadow.record(NotifyMachineState.SHOWING, "STYLE_READY")
            # 先对仍隐藏的窗口做 late_set，再等前端 ready 后再 Show，避免首帧白底
            def _show_step():
                # 本次 show 重置 controller 透明重试状态，以 controller-ready 为"透明设置真正完成"的判据
                self._notify_controller_bg_applied = False
                self._controller_retry_in_progress = False
                self._late_set_triggered_this_cycle = False  # 重置本轮触发标志
                # 渐入由 ACK + 最小延迟驱动，每轮 show 重置以便 _try_start_notify_fade_in 能执行
                self._notify_min_delay_elapsed = False
                self._notify_fade_started = False
                # 1) 窗口仍隐藏时先做 late_set（内部为 controller 就绪重试），减少 Show 后闪白
                self._late_set_notify_transparent()
                self._show_deferred_until_ready = True
                if is_debug_enabled():
                    diag.emit("DIAG_NOTIFY_PIPE", self._log, "show 延后至首帧 ready", step="defer_show_until_ready")
                # 2) 若前端已 ready（如预加载后先 ACK），则立即 Show；否则等 _on_ready_for_show_ack
                if self._notify_ack_received:
                    self._show_deferred_until_ready = False
                    self._do_actual_show()
                else:
                    self._dbg_log("DIAG_NOTIFY_M0 | step=3_deferred (wait first frame)")

            if native is not None:
                try:
                    from System import Action
                    native.BeginInvoke(Action(_show_step))
                except Exception:
                    try:
                        _show_step()
                    except Exception as e:
                        log_exception_summary(self._log, "DIAG_EXCEPTION", "notify BeginInvoke Show fallback", "降级", detail=str(e)[:200], reason_code="E_NOTIFY_M0_SHOW_FALLBACK")
            else:
                try:
                    _show_step()
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "notify show_step", "降级", detail=str(e)[:200], reason_code="E_NOTIFY_M0_SHOW_STEP")

            self._dbg_log("DIAG_NOTIFY_M0 | step=6_post_js")
            self._post_js_update(js_for_later)
            self._dbg_log("DIAG_NOTIFY_M0 | step=7_done")
        finally:
            with self._show_lock:
                self._show_inflight = False
                pending = getattr(self, "_pending_payload", None)
                self._pending_payload = None
                if pending is not None:
                    self._show_inflight = True
                    self._dbg_log("DIAG_NOTIFY_M0 | had pending, post one more _do_show_ui")
                    # pending 为 (extra, prompt_key) 或仅 extra（兼容）
                    if isinstance(pending, (list, tuple)) and len(pending) >= 2:
                        self._post_gui(lambda: self._do_show_ui(pending[0], pending[1]))
                    else:
                        self._post_gui(lambda: self._do_show_ui(pending if isinstance(pending, dict) else pending[0]))

    def _get_sm_notify_v2(self) -> bool:
        """获取 sm_notify_v2 开关状态（从配置获取）。"""
        return self._sm_notify_v2_getter()

    def show(self, extra: dict, prompt_key: Optional[tuple] = None) -> Optional[bool]:
        """
        M0 治本：零阻塞。只做 inflight 防重入 + 投递 _do_show_ui，不 wait、不 ensure_ready、不 _ready_evt。
        返回 True 表示已投递或已合并；on_notify_complete(True) 延后到用户点击 rest/snooze/dismiss 时由 bridge 回调。
        prompt_key: 当前展示的 prompt 键，用于用户操作后上报 on_notify_complete(True)。

        先发 REQUEST_SHOW 事件，状态机 accept 后才投递 _do_show_ui。
        """
        if not self._initialized:
            self._preload_event.set()
            return None
        if not self._window:
            self._metrics.record_show_end(success=False)
            self._shadow.record(NotifyMachineState.FAILED, "CREATE_FAIL", reason_code="no_window")
            return False
        if not self._notify_ready_dict.get("value", False):
            return None
        if not self._style_target or not self._style_coordinator:
            self._metrics.record_show_end(success=False)
            return None

        # 状态机裁决（SM_NOTIFY_V2=True）
        if self._get_sm_notify_v2():
            # 设置 session 用于日志关联
            self._shadow.set_session(session_id=str(self._show_session_counter), prompt_key=prompt_key)
            # 尝试 REQUEST_SHOW 转移
            result, _ = self._shadow.try_transition(event="REQUEST_SHOW", to_state=NotifyMachineState.SCHEDULED, result="ok")
            if result != TransitionResult.OK:
                # 状态机拒绝，记录 reason 并返回
                self._dbg_log("DIAG_NOTIFY_M0 | sm_notify_v2 rejected at REQUEST_SHOW")
                return False
            # 状态机接受，继续后续流程

        if self._shadow.state in (NotifyMachineState.IDLE, NotifyMachineState.HIDDEN, NotifyMachineState.FAILED):
            self._shadow.record(NotifyMachineState.SCHEDULED, "REQUEST_SHOW")
        with self._show_lock:
            if self._show_inflight:
                self._pending_payload = (extra, prompt_key) if prompt_key is not None else extra
                self._dbg_log("DIAG_NOTIFY_M0 | inflight merge")
                return True
            self._show_inflight = True
            # 立即写入，避免 _do_show_ui 尚未在 GUI 跑时前端就发 action 导致 _flush_notify_complete(pk=None)
            if prompt_key is not None:
                self._current_prompt_key, self._current_extra = prompt_key, extra

        self._shadow.set_session(session_id=str(self._show_session_counter), prompt_key=prompt_key)
        self._post_gui(lambda: self._do_show_ui(extra, prompt_key))
        return True

    def get_metric(self) -> dict:
        """返回 DIAG_METRIC_NOTIFY 用字段（last_show_ts, last_style_ok_ts, degraded_mode, show_fail_count, notify_show_ms_last, notify_show_ms_p95_5m）。"""
        m = self._metrics.get_metric()
        return {
            "last_show_ts": m.get("last_show_ts", 0.0),
            "last_style_ok_ts": m.get("last_style_ok_ts", 0.0),
            "degraded_mode": m.get("degraded_mode", False),
            "show_fail_count": m.get("show_fail_count", 0),
            "notify_show_ms_last": m.get("notify_show_ms_last", 0.0),
            "notify_show_ms_p95_5m": m.get("notify_show_ms_p95_5m", 0.0),
        }

    def close_animated(self, reason: str = "dismiss") -> None:
        """关闭通知窗口：fade_out 后 hide。须在 GUI 线程调用，或经 dispatcher 投递。"""
        self.hide(reason)

    def hide(self, reason: str) -> None:
        """隐藏通知窗口。必须在 GUI 线程调用。使用 Layered 窗口级淡出（FN09 口径）。

        hide() 先尝试 HIDE_REQ，状态机 accept 后才执行 fade/hide。
        """
        try:
            # 避免：点击"稍后"后又触发 auto-hide，再次 hide 导致闪退/淡出被打断
            if self._hide_in_progress:
                diag.emit("DIAG_NOTIFY_PIPE", self._log, "hide已在进行，忽略重复调用", step="hide_guard", reason=reason)
                return
            # 状态机驱动 HIDE_REQ
            if self._get_sm_notify_v2():
                result, _ = self._shadow.try_transition(event="HIDE_REQ", to_state=NotifyMachineState.HIDING, result="ok")
                if result != TransitionResult.OK:
                    self._dbg_log("DIAG_NOTIFY_M0 | sm_notify_v2 rejected at HIDE_REQ")
                    return
            else:
                # Legacy 行为
                if self._shadow.state == NotifyMachineState.SHOWN:
                    self._shadow.record(NotifyMachineState.HIDING, "HIDE_REQ")

            hwnd = self._find_hwnd()

            def _do_hide():
                try:
                    if self._window:
                        self._window.hide()
                        self._shown = False
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
                try:
                    import win32gui
                    import win32con
                    if hwnd:
                        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
            # 新策略基础上微调：前端卡片做 CSS 渐出，同时宿主窗口做一次受控 alpha 渐出（通过 win_effects.notify_set_alpha），
            # 渐出结束后再 hide + 恢复 exstyle，既保证观感，又尽量规避 Layered + Acrylic 交互异常。
            self._hide_in_progress = True
            # 1) 触发前端卡片渐出动画
            self._post_js_update("window.notifyCardFadeOut && window.notifyCardFadeOut();")

            # 1.1) 同步触发宿主窗体 alpha 渐出（约 500ms，与前端 CSS fade-out 对齐）
            try:
                if hwnd:
                    # 这里使用内部 _fade_async，底层通过 _set_alpha → win_effects.notify_set_alpha 统一管理 Layered/exstyle。
                    self._fade_async(int(hwnd), 255, 0, 550, "notify_fade_out", on_done=None)
            except Exception as e:
                log_exception_summary(
                    self._log,
                    "DIAG_EXCEPTION",
                    "notify fade_out_host",
                    "degrade_continue",
                    detail=str(e)[:200],
                    reason_code="E_NOTIFY_HOST_FADE_OUT",
                )

            def _after_fade_simple(_hwnd=hwnd):
                """卡片渐出完成后的统一收尾：隐藏窗口 + 状态机 HIDE_DONE + 样式恢复。"""
                try:
                    # 取消可能存在的旧超时定时器
                    if self._hide_timeout_timer:
                        try:
                            self._hide_timeout_timer.cancel()
                        except Exception:
                            pass
                        self._hide_timeout_timer = None

                    self._hide_in_progress = False
                    _do_hide()
                    if self._shadow.state == NotifyMachineState.HIDING:
                        self._shadow.record(NotifyMachineState.HIDDEN, "HIDE_DONE")
                    if _hwnd:
                        try:
                            # 尝试恢复可能残留的 Layered 样式（幂等）
                            self._win_effects.restore_exstyle_after_hide([_hwnd])
                            diag_notify_hwnd_alpha(self._log, _hwnd, "notify_after_simple_hide")
                        except Exception as e:
                            log_exception_summary(self._log, "DIAG_EXCEPTION", "notify after_simple_hide", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_AFTER_SIMPLE_HIDE")
                    diag.emit("DIAG_NOTIFY_PIPE", self._log, "notify 简化淡出收尾完成", step="after_simple_fade", reason=reason)
                except Exception as e:
                    # 即便收尾失败，也要尽量保证状态复位，避免下一次 hide 被永远挡住
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "notify after_simple_fade", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_AFTER_SIMPLE_FADE")
                    self._hide_in_progress = False
                    try:
                        _do_hide()
                    except Exception:
                        pass

            # 2) 预计前端 CSS 渐出时间 ~500ms，Timer 在线程中仅负责投递到 GUI 线程执行收尾
            def _schedule_after_fade():
                try:
                    self._dispatcher.post(_after_fade_simple)
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "notify schedule_after_fade", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_SCHEDULE_AFTER_FADE")

            threading.Timer(0.55, _schedule_after_fade).start()

            # 3) 超时兜底：若 1.5 秒后仍未完成收尾，则再投递一次简单收尾，避免极端情况下卡在 HIDING
            def _timeout_fallback_simple():
                if self._hide_in_progress:
                    diag.emit("DIAG_NOTIFY_PIPE", self._log, "notify 简化淡出超时兜底触发", step="hide_timeout_simple", reason=reason, timeout_sec=1.5)
                    try:
                        self._dispatcher.post(_after_fade_simple)
                    except Exception as e:
                        log_exception_summary(self._log, "DIAG_EXCEPTION", "notify timeout_fallback_simple", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_TIMEOUT_SIMPLE")

            self._hide_timeout_timer = threading.Timer(1.5, _timeout_fallback_simple)
            self._hide_timeout_timer.daemon = True
            self._hide_timeout_timer.start()
        except Exception:
            self._log.exception("notify hide failed")

    def _find_hwnd(self) -> Optional[int]:
        """
        获取通知窗口句柄：
        1) 优先使用 pywebview 提供的 native_handle（最稳定）
        2) 兜底用 title token 查找
        返回值会被 _resolve_hwnd_for_alpha 规整为“可见根窗口”。
        """
        try:
            import win32gui
            # 1) native_handle 优先
            try:
                if self._window and getattr(self._window, "native_handle", None):
                    h = int(self._window.native_handle)
                    if h and win32gui.IsWindow(h):
                        h = self._resolve_hwnd_for_alpha(h)
                        self._hwnd_cache["hwnd"] = int(h)
                        return int(h)
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")

            # 2) cache
            if self._hwnd_cache.get("hwnd") and win32gui.IsWindow(self._hwnd_cache["hwnd"]):
                h = self._resolve_hwnd_for_alpha(int(self._hwnd_cache["hwnd"]))
                self._hwnd_cache["hwnd"] = int(h)
                return int(h)
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")

        # 3) title token 兜底
        try:
            import win32gui
            hwnd = None
            if self._title_token:
                title = f"EyE Care Notify [{self._title_token}]"
                hwnd = win32gui.FindWindow(None, title)
            if not hwnd and self._title_token:
                def _cb(h, _):
                    nonlocal hwnd
                    try:
                        if self._title_token in (win32gui.GetWindowText(h) or ""):
                            hwnd = h
                            return False
                    except Exception as e:
                        log_exception_summary(self._log, "DIAG_EXCEPTION", "notify fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_NOTIFY_FALLBACK")
                    return True
                win32gui.EnumWindows(_cb, None)
            if hwnd:
                h = self._resolve_hwnd_for_alpha(int(hwnd))
                self._hwnd_cache["hwnd"] = int(h)
                return int(h)
            return None
        except Exception:
            return None

    @property
    def window(self):
        return self._window

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def is_ready(self) -> bool:
        return bool(self._notify_ready_dict.get("value", False))
