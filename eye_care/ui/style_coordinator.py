"""
P0-2 样式协调器：Rest/Notify 窗口透明/磨砂应用统一状态机。
所有样式应用（hwnd 探测、Win32 样式、透明、Acrylic、降级）仅在此模块执行；
rest/notify 只负责创建窗口与 show，通过本模块 ensure_ready 后再显示。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from eye_care.diagnostics import diag, log_exception_summary
from eye_care.ui.gui_dispatcher import is_gui_thread
from eye_care.ui.state_machines import StyleShadowMachine
from eye_care.ui.state_machines.types import StyleState as StyleMachineState

log = logging.getLogger(__name__)

# 状态机阶段
class StylePhase(str, Enum):
    INIT = "INIT"
    HWND_READY = "HWND_READY"
    WEBVIEW_READY = "WEBVIEW_READY"
    STYLE_APPLYING = "STYLE_APPLYING"
    STYLE_APPLIED = "STYLE_APPLIED"
    READY = "READY"
    DEGRADED = "DEGRADED"


@dataclass
class StyleState:
    """单个窗口/overlay 的样式状态。"""
    phase: StylePhase = StylePhase.INIT
    attempt: int = 0
    last_error: str = ""
    t_start: float = 0.0
    t_last: float = 0.0
    hwnd_ok: bool = False
    webview_ok: bool = False
    acrylic_ok: bool = False
    mode: str = ""  # REST | NOTIFY
    overlay_id: Any = None
    ready_evt: threading.Event = field(default_factory=threading.Event)
    inflight: bool = False  # 防重入：已有 apply 在队列中未执行完时不再 post


@dataclass
class StyleTarget:
    """样式应用目标：由 rest/notify 构建并传给 coordinator。"""
    kind: str  # REST | NOTIFY
    overlay_id: Any  # 多屏 idx 或 "notify"
    get_native: Callable[[], Any]  # 返回 native 窗口对象或 None
    get_webview: Callable[[], Any]  # 返回 WebView2 对象或 None
    get_hwnd: Callable[[], Optional[int]]  # 返回 hwnd 或 None
    get_bounds: Optional[Callable[[], tuple]] = None  # REST 用 (sx,sy,sw,sh)，NOTIFY 可 None
    set_hwnd: Optional[Callable[[int], None]] = None  # 可选：coordinator 拿到 hwnd 后回写
    state: StyleState = field(default_factory=StyleState)
    on_ready: Optional[Callable[[str, bool], None]] = None  # NOTIFY 就绪栅栏：("transparent"|"acrylic", True)


# 重试上限与间隔（与 FN09 原 50 次 / 100ms 一致）
MAX_APPLY_ATTEMPTS = 50
RETRY_INTERVAL_S = 0.08

# 降级背景：半透明暗色，避免黑底与透明穿透（ARGB）
DEGRADED_ALPHA = 230
DEGRADED_R, DEGRADED_G, DEGRADED_B = 0x11, 0x18, 0x27


class StyleCoordinator:
    """统一样式应用：状态机 + 幂等 apply + ensure_ready。"""

    def __init__(self, logger: logging.Logger, win_effects: Any) -> None:
        self._log = logger
        self._win_effects = win_effects
        self._shadows: dict[tuple[str, Any], StyleShadowMachine] = {}

    def apply(self, target: StyleTarget, dispatcher: Any) -> None:
        """
        单入口：永远只投递到 dispatcher，不在当前调用栈同步执行 _apply_step，避免卡死 GUI。
        幂等：已 READY/DEGRADED 或已有 inflight 则不重复投递。
        """
        target.state.mode = target.kind
        target.state.overlay_id = target.overlay_id
        if target.state.phase in (StylePhase.READY, StylePhase.DEGRADED):
            if is_debug_enabled():
                diag.emit("DIAG_STYLE_READY", self._log, "已就绪，跳过", kind=target.kind, overlay_id=target.overlay_id)
            return
        if getattr(target.state, "inflight", False):
            return
        target.state.inflight = True
        dispatcher.post(self._apply_step, target, dispatcher, target.state.attempt)

    def ensure_ready(
        self,
        target: StyleTarget,
        dispatcher: Any,
        timeout_s: float = 2.0,
        pump_fn: Optional[Callable[[], None]] = None,
    ) -> bool:
        """
        在 GUI 线程调用：若未就绪则先 apply，再等待 READY/DEGRADED 或超时。
        pump_fn 用于在等待时消费 dispatcher 队列（避免卡死）。
        返回 True 表示已 READY 或 DEGRADED（可安全 show），False 表示超时。
        """
        if not is_gui_thread():
            self._log.warning("ensure_ready 应在 GUI 线程调用")
            return False
        # M0：NOTIFY 不等待 style 完成，show 不依赖本结果
        if target.kind == "NOTIFY":
            return True
        if target.state.phase in (StylePhase.READY, StylePhase.DEGRADED):
            if is_debug_enabled():
                diag.emit("DIAG_STYLE_READY", self._log, "样式已就绪，跳过", kind=target.kind, overlay_id=target.overlay_id)
            return True
        self.apply(target, dispatcher)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if target.state.phase in (StylePhase.READY, StylePhase.DEGRADED):
                return True
            if pump_fn:
                try:
                    pump_fn()
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
            target.state.ready_evt.wait(0.05)
        diag.emit("DIAG_STYLE_APPLY_FAIL", self._log, "ensure_ready 超时", kind=target.kind, overlay_id=target.overlay_id, will_retry=0)
        return False

    def _apply_step(self, target: StyleTarget, dispatcher: Any, attempt: int) -> None:
        """由 dispatcher 在 GUI 线程执行：单次样式应用步骤。所有 return 前清 inflight。"""
        state = target.state
        hwnd_lo = None  # 用于分段日志，至少低 16 位
        key = (target.kind, target.overlay_id)
        shadow = self._shadows.setdefault(key, StyleShadowMachine(self._log))
        shadow.set_overlay(target.overlay_id)

        def _clear_inflight():
            try:
                state.inflight = False
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")

        if state.phase in (StylePhase.READY, StylePhase.DEGRADED):
            if is_debug_enabled():
                diag.emit("DIAG_STYLE_READY", self._log, "已就绪，跳过", kind=target.kind, overlay_id=target.overlay_id)
            _clear_inflight()
            return
        if state.t_start <= 0:
            state.t_start = time.perf_counter()
        state.t_last = time.perf_counter()
        state.attempt = attempt
        _dbg_style = False
        try:
            from eye_care.diagnostics.debug_switch import is_debug_enabled
            _dbg_style = is_debug_enabled()
        except ImportError:
            _dbg_style = False

        diag.emit(
            "DIAG_STYLE_APPLY_START", self._log, "样式应用开始",
            kind=target.kind, overlay_id=target.overlay_id, attempt=attempt, state=state.phase.value,
        )

        # 1) 获取 hwnd
        hwnd = target.get_hwnd()
        if not hwnd:
            if attempt < MAX_APPLY_ATTEMPTS:
                diag.emit(
                    "DIAG_STYLE_APPLY_FAIL", self._log, "未拿到 hwnd，将重试",
                    kind=target.kind, overlay_id=target.overlay_id, attempt=attempt, will_retry=1,
                )
                _clear_inflight()
                threading.Timer(RETRY_INTERVAL_S, lambda: dispatcher.post(self._apply_step, target, dispatcher, attempt + 1)).start()
                return
            diag.emit(
                "DIAG_STYLE_DEGRADED", self._log, "进入降级：hwnd 超时",
                kind=target.kind, overlay_id=target.overlay_id, reason="hwnd_timeout",
            )
            shadow.record(StyleMachineState.DEGRADED, "HWND_TIMEOUT", kind=target.kind)
            self._apply_degraded(target)
            state.phase = StylePhase.DEGRADED
            state.ready_evt.set()
            diag.emit("DIAG_STYLE_READY", self._log, "降级就绪，允许 show", kind=target.kind, overlay_id=target.overlay_id)
            _clear_inflight()
            return
        hwnd_full = int(hwnd)
        hwnd_lo = hwnd_full & 0xFFFF
        state.hwnd_ok = True
        if state.phase == StylePhase.INIT:
            shadow.record(StyleMachineState.WAIT_HWND, "TARGET_READY", kind=target.kind)
            shadow.record(StyleMachineState.APPLY_WIN32_STYLE, "HWND_READY", kind=target.kind)
        if target.kind == "NOTIFY":
            try:
                from eye_care.ui.win_utils import native_handle_to_int
                native = target.get_native()
                native_handle_raw = None
                if native is not None:
                    native_handle_raw = getattr(native, "Handle", None) or getattr(native, "handle", None)
                    if callable(native_handle_raw):
                        native_handle_raw = native_handle_raw()
                native_handle_int = native_handle_to_int(native_handle_raw)
                same = (int(hwnd) == native_handle_int) if native_handle_int is not None else None
                if is_debug_enabled():
                    diag.emit("DIAG_NOTIFY_PIPE", self._log, "样式hwnd一致性", step="style_hwnd_check", hwnd_from_title=int(hwnd), hwnd_from_native_int=native_handle_int, same=same)
            except Exception as e:
                diag.emit("DIAG_NOTIFY_PIPE", self._log, "样式hwnd检查异常", step="style_hwnd_check", err=str(e)[:60])
        if target.set_hwnd:
            try:
                target.set_hwnd(int(hwnd))
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
        if state.phase == StylePhase.INIT:
            state.phase = StylePhase.HWND_READY
            if _dbg_style:
                diag.emit("DIAG_STYLE_STAGE", self._log, "阶段变更", kind=target.kind, overlay_id=target.overlay_id, stage=state.phase.value, attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)

        # 2) Win32 样式：必须在窗口线程执行，否则 SetWindowLong/SetWindowPos 会引发同步消息 → 死锁
        if _dbg_style:
            diag.emit("DIAG_STYLE_STAGE", self._log, "阶段变更", kind=target.kind, overlay_id=target.overlay_id, stage="WIN32_STYLE_START", attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)
        try:
            import win32gui
            import win32con

            def _do_win32_style():
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                style &= ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME & ~win32con.WS_BORDER & ~win32con.WS_DLGFRAME
                win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
                ex_before = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                ex = ex_before
                ex |= win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TOPMOST
                # REST/NOTIFY 均不抢焦点，避免点击时“争抢激活”导致闪频
                ex |= getattr(win32con, "WS_EX_NOACTIVATE", 0x08000000)
                if target.kind == "NOTIFY":
                    # NOTIFY：保留 WS_EX_LAYERED，否则 WinForms/WebView2 会退化成不透明白底
                    ex |= win32con.WS_EX_LAYERED
                ex &= ~win32con.WS_EX_APPWINDOW & ~win32con.WS_EX_WINDOWEDGE & ~win32con.WS_EX_CLIENTEDGE
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex)
                if target.kind == "NOTIFY":
                    ex_after = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                    ex_after_u = int(ex_after) & 0xFFFFFFFF
                    ws_ex_layered_after = bool(ex_after_u & win32con.WS_EX_LAYERED)
                    if _dbg_style:
                        diag.emit(
                            "DIAG_STYLE_STAGE", self._log, "NOTIFY exstyle ensure WS_EX_LAYERED",
                            kind=target.kind, overlay_id=target.overlay_id,
                            ex_style_before=hex(ex_before & 0xFFFFFFFF), ex_style_after=hex(ex_after_u),
                            ws_ex_layered_after=ws_ex_layered_after,
                        )
                if target.get_bounds:
                    sx, sy, sw, sh = target.get_bounds()
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_TOPMOST, sx, sy, sw, sh,
                        win32con.SWP_FRAMECHANGED | win32con.SWP_NOACTIVATE | win32con.SWP_NOSENDCHANGING
                    )
                else:
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                        win32con.SWP_FRAMECHANGED | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | win32con.SWP_NOSENDCHANGING
                    )

            native = target.get_native()
            run_direct = True
            if native and getattr(native, "InvokeRequired", None) is True:
                run_direct = False
                done_evt = threading.Event()
                def _wrap():
                    try:
                        _do_win32_style()
                    finally:
                        try:
                            done_evt.set()
                        except Exception as e:
                            log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                posted = False
                try:
                    try:
                        native.BeginInvoke(_wrap)
                        posted = True
                    except Exception:
                        from System import Action
                        native.BeginInvoke(Action(_wrap))
                        posted = True
                except Exception:
                    posted = False
                if posted:
                    # M0：NOTIFY 只投递不等待，避免阻塞 show
                    if target.kind == "NOTIFY":
                        shadow.record(StyleMachineState.DEGRADED, "WIN32_STYLE_FAIL", reason_code="notify_post_no_wait", kind=target.kind)
                        state.phase = StylePhase.DEGRADED
                        state.ready_evt.set()
                        _clear_inflight()
                        return
                    deadline = time.time() + 0.4
                    try:
                        import clr
                        clr.AddReference("System.Windows.Forms")
                        from System.Windows.Forms import Application as WinFormsApp
                    except Exception:
                        WinFormsApp = None
                    while (not done_evt.is_set()) and (time.time() < deadline):
                        try:
                            if WinFormsApp:
                                # ALLOWED DoEvents: see docs/GUI_DISPATCHER_RULES.md (whitelist)
                                WinFormsApp.DoEvents()
                        except Exception as e:
                            log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                        time.sleep(0.01)
                    if not done_evt.is_set():
                        diag.emit("DIAG_STYLE_APPLY_FAIL", self._log, "Win32样式投递超时，降级", kind=target.kind, overlay_id=target.overlay_id, attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)
                        raise RuntimeError("WIN32_STYLE_TIMEOUT")
                else:
                    run_direct = True
            if run_direct:
                _do_win32_style()
            if _dbg_style:
                diag.emit("DIAG_STYLE_STAGE", self._log, "阶段变更", kind=target.kind, overlay_id=target.overlay_id, stage="WIN32_STYLE_DONE", attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)
            if target.kind == "REST" and hwnd and win32gui.IsWindow(hwnd):
                try:
                    wr = win32gui.GetWindowRect(hwnd)
                    cr = win32gui.GetClientRect(hwnd)
                    self._log.info(
                        "REST_OVERLAY_RECT_DIAG overlay_id=%s GetWindowRect=(left=%s,top=%s,right=%s,bottom=%s) GetClientRect=(left=%s,top=%s,right=%s,bottom=%s)",
                        target.overlay_id, wr[0], wr[1], wr[2], wr[3], cr[0], cr[1], cr[2], cr[3],
                    )
                    webview_child_rect = [None]

                    def _enum_webview_child(child_h, _):
                        try:
                            cls = (win32gui.GetClassName(child_h) or "").strip()
                            if "Chrome_WidgetWin" in cls or "WebView" in cls or "Edge" in cls:
                                webview_child_rect[0] = win32gui.GetWindowRect(child_h)
                                return False
                        except Exception as e:
                            log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                        return True

                    win32gui.EnumChildWindows(hwnd, _enum_webview_child, None)
                    if webview_child_rect[0] is not None:
                        r = webview_child_rect[0]
                        self._log.info(
                            "REST_OVERLAY_RECT_DIAG overlay_id=%s WebView2_child GetWindowRect=(left=%s,top=%s,right=%s,bottom=%s)",
                            target.overlay_id, r[0], r[1], r[2], r[3],
                        )
                    else:
                        self._log.info("REST_OVERLAY_RECT_DIAG overlay_id=%s WebView2_child not found (EnumChildWindows)", target.overlay_id)
                except Exception as _e:
                    self._log.info("REST_OVERLAY_RECT_DIAG overlay_id=%s error=%s", target.overlay_id, _e)
        except Exception as e:
            state.last_error = str(e)[:200]
            shadow.record(StyleMachineState.DEGRADED, "WIN32_STYLE_FAIL", reason_code=state.last_error[:40], kind=target.kind)
            diag.emit("DIAG_STYLE_APPLY_FAIL", self._log, "Win32 样式异常", kind=target.kind, overlay_id=target.overlay_id, err=state.last_error[:80], will_retry=0, attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)
            self._apply_degraded(target)
            state.phase = StylePhase.DEGRADED
            state.ready_evt.set()
            _clear_inflight()
            return

        shadow.record(StyleMachineState.APPLY_WEBVIEW_BG, "WIN32_STYLE_OK", kind=target.kind)

        # 3) 透明口径：native BackColor + WebView2 DefaultBackgroundColor
        # 关键：必须“同步完成”后才允许继续 Acrylic。否则会出现：ACRYLIC_DONE 在 WEBVIEW_BG_SET_OK 之前，导致首帧白/灰。
        state.phase = StylePhase.STYLE_APPLYING
        if _dbg_style:
            diag.emit("DIAG_STYLE_STAGE", self._log, "阶段变更", kind=target.kind, overlay_id=target.overlay_id, stage="SET_TRANSPARENT_START", attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)

        native = target.get_native()
        webview_obj = None
        try:
            webview_obj = target.get_webview() if callable(target.get_webview) else None
        except Exception:
            webview_obj = None

        # WebView2 就绪门槛：拿不到 webview 不允许推进，避免“假成功→白底”。M0：NOTIFY 不重试，直接降级。
        if native and not webview_obj:
            if target.kind == "NOTIFY":
                shadow.record(StyleMachineState.DEGRADED, "WEBVIEW_BG_FAIL", reason_code="notify_no_webview", kind=target.kind)
                diag.emit("DIAG_STYLE_DEGRADED", self._log, "NOTIFY 无 webview，M0 直接降级", kind=target.kind, overlay_id=target.overlay_id)
                self._apply_degraded(target)
                state.phase = StylePhase.DEGRADED
                state.ready_evt.set()
                _clear_inflight()
                return
            if attempt < MAX_APPLY_ATTEMPTS:
                diag.emit(
                    "DIAG_STYLE_APPLY_FAIL", self._log, "未拿到 webview，将重试(避免白底)",
                    kind=target.kind, overlay_id=target.overlay_id, attempt=attempt, will_retry=1, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo,
                )
                _clear_inflight()
                threading.Timer(RETRY_INTERVAL_S, lambda: dispatcher.post(self._apply_step, target, dispatcher, attempt + 1)).start()
                return
            shadow.record(StyleMachineState.DEGRADED, "WEBVIEW_BG_FAIL", reason_code="webview_timeout", kind=target.kind)
            diag.emit(
                "DIAG_STYLE_DEGRADED", self._log, "进入降级：webview 超时",
                kind=target.kind, overlay_id=target.overlay_id, reason="webview_timeout", attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo,
            )
            self._apply_degraded(target)
            state.phase = StylePhase.DEGRADED
            state.ready_evt.set()
            diag.emit("DIAG_STYLE_READY", self._log, "降级就绪，允许 show", kind=target.kind, overlay_id=target.overlay_id)
            _clear_inflight()
            return

        if native:
            try:
                # 透明设置：同步完成（Invoke/直调），不要 BeginInvoke
                def _set_transparent_sync():
                    try:
                        import clr
                        clr.AddReference("System.Drawing")
                        clr.AddReference("System.Windows.Forms")
                        from System.Drawing import Color
                        trans = Color.FromArgb(0, 0, 0, 0)

                        # WebView2 背景透明：必须在 Acrylic 之前完成
                        try:
                            if webview_obj is not None:
                                webview_obj.DefaultBackgroundColor = trans
                                if _dbg_style:
                                    diag.emit("DIAG_STYLE_STAGE", self._log, "阶段变更", kind=target.kind, overlay_id=target.overlay_id, stage="WEBVIEW_BG_SET_OK", attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)
                                # === 补齐冻结口径：CoreWebView2 / Controller 也要设透明 ===
                                try:
                                    _core = getattr(webview_obj, "CoreWebView2", None)
                                    if _core is not None:
                                        try:
                                            _core.DefaultBackgroundColor = trans
                                        except Exception as e:
                                            log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                                        _ctl = (
                                            getattr(webview_obj, "CoreWebView2Controller", None)
                                            or getattr(webview_obj, "Controller", None)
                                            or getattr(_core, "Controller", None)
                                        )
                                        if _ctl is not None:
                                            try:
                                                _ctl.DefaultBackgroundColor = trans
                                            except Exception as e:
                                                log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                                except Exception as e:
                                    log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                                # DPI 缩放：为 WebView2 设置 zoom（解决 4K 下内容缩放不一致）
                                try:
                                    import ctypes
                                    dpi = 96
                                    try:
                                        dpi = ctypes.windll.user32.GetDpiForWindow(int(hwnd))
                                    except Exception as e:
                                        log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                                    scale = float(dpi) / 96.0 if dpi else 1.0
                                    try:
                                        if hasattr(webview_obj, "CoreWebView2") and webview_obj.CoreWebView2 is not None:
                                            webview_obj.CoreWebView2.ZoomFactor = scale
                                    except Exception as e:
                                        log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                                except Exception as e:
                                    log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                            else:
                                if _dbg_style:
                                    diag.emit("DIAG_STYLE_STAGE", self._log, "阶段变更", kind=target.kind, overlay_id=target.overlay_id, stage="WEBVIEW_BG_SET_SKIP", attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)
                        except Exception as e:
                            if _dbg_style:
                                diag.emit("DIAG_STYLE_STAGE", self._log, "阶段变更", kind=target.kind, overlay_id=target.overlay_id, stage="WEBVIEW_BG_SET_FAIL", err=str(e)[:120], attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)
                            # webview 背景没设成功，视为失败，触发重试/降级
                            raise

                        # 宿主背景透明
                        try:
                            native.BackColor = trans
                        except Exception as e:
                            if _dbg_style:
                                diag.emit(
                                    "DIAG_STYLE_STAGE", self._log, "阶段变更",
                                    kind=target.kind, overlay_id=target.overlay_id,
                                    stage="SET_HOST_TRANSPARENT_FAIL", err=str(e)[:120], attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo,
                                )
                            # NOTIFY 定向硬日志：抓白底根因，读回 host/webview 当前色值
                            if target.kind == "NOTIFY":
                                try:
                                    bc = getattr(native, "BackColor", None)
                                    wv_bc = getattr(webview_obj, "DefaultBackgroundColor", None) if webview_obj else None
                                    host_a = getattr(bc, "A", None) if bc is not None else None
                                    host_r = getattr(bc, "R", None) if bc is not None else None
                                    host_g = getattr(bc, "G", None) if bc is not None else None
                                    host_b = getattr(bc, "B", None) if bc is not None else None
                                    wv_a = getattr(wv_bc, "A", None) if wv_bc is not None else None
                                    wv_r = getattr(wv_bc, "R", None) if wv_bc is not None else None
                                    wv_g = getattr(wv_bc, "G", None) if wv_bc is not None else None
                                    wv_b = getattr(wv_bc, "B", None) if wv_bc is not None else None
                                    same = (host_a == wv_a and host_r == wv_r and host_g == wv_g and host_b == wv_b) if (bc is not None and wv_bc is not None) else None
                                    if _dbg_style:
                                        diag.emit(
                                            "DIAG_STYLE_STAGE", self._log, "NOTIFY SET_HOST_TRANSPARENT_FAIL 读回",
                                            kind=target.kind, overlay_id=target.overlay_id,
                                            host_BackColor_A=host_a, host_BackColor_R=host_r, host_BackColor_G=host_g, host_BackColor_B=host_b,
                                            webview_DefaultBackgroundColor_A=wv_a, webview_DefaultBackgroundColor_R=wv_r, webview_DefaultBackgroundColor_G=wv_g, webview_DefaultBackgroundColor_B=wv_b,
                                            same=same,
                                        )
                                except Exception as read_ex:
                                    if _dbg_style:
                                        diag.emit("DIAG_STYLE_STAGE", self._log, "NOTIFY 读回 BackColor/DefaultBackgroundColor 失败", kind=target.kind, overlay_id=target.overlay_id, read_err=str(read_ex)[:80])

                        try:
                            native.Invalidate(True)
                            native.Refresh()
                        except Exception as e:
                            log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                    except Exception:
                        raise

                # 若已在 GUI 线程且不需要 invoke，则直接执行（同步）
                executed = False
                try:
                    if hasattr(native, "InvokeRequired") and native.InvokeRequired is False:
                        _set_transparent_sync()
                        executed = True
                except Exception:
                    executed = False

                if not executed:
                    # 关键：不要同步 Invoke（会在某些时序/线程下死锁），改为 BeginInvoke + 等待完成
                    done_evt = threading.Event()

                    def _wrap():
                        try:
                            _set_transparent_sync()
                        finally:
                            try:
                                done_evt.set()
                            except Exception as e:
                                log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")

                    posted = False
                    try:
                        try:
                            native.BeginInvoke(_wrap)
                            posted = True
                        except Exception:
                            from System import Action
                            native.BeginInvoke(Action(_wrap))
                            posted = True
                    except Exception:
                        posted = False

                    if posted:
                        # M0：NOTIFY 只投递不等待
                        if target.kind == "NOTIFY":
                            state.phase = StylePhase.DEGRADED
                            state.ready_evt.set()
                            _clear_inflight()
                            return
                        deadline = time.time() + 0.4
                        try:
                            import clr
                            clr.AddReference("System.Windows.Forms")
                            from System.Windows.Forms import Application as WinFormsApp
                        except Exception:
                            WinFormsApp = None

                        while (not done_evt.is_set()) and (time.time() < deadline):
                            try:
                                if WinFormsApp:
                                    # ALLOWED DoEvents: see docs/GUI_DISPATCHER_RULES.md (whitelist)
                                    WinFormsApp.DoEvents()
                            except Exception as e:
                                log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                            time.sleep(0.01)

                        if not done_evt.is_set():
                            raise RuntimeError("SET_TRANSPARENT_TIMEOUT")
                    else:
                        _set_transparent_sync()

                if _dbg_style:
                    diag.emit("DIAG_STYLE_STAGE", self._log, "阶段变更", kind=target.kind, overlay_id=target.overlay_id, stage="SET_TRANSPARENT_DONE", attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)
                if target.kind == "NOTIFY":
                    if is_debug_enabled():
                        diag.emit("DIAG_NOTIFY_PIPE", self._log, "透明设置完成", step="style_transparent_done", hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)
                    if target.on_ready:
                        try:
                            target.on_ready("transparent", True)
                        except Exception as e:
                            log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                state.webview_ok = True
            except Exception as e:
                state.webview_ok = False
                state.last_error = str(e)[:200]
                diag.emit("DIAG_STYLE_APPLY_FAIL", self._log, "透明设置失败，将重试", kind=target.kind, overlay_id=target.overlay_id, err=state.last_error[:80], will_retry=1 if attempt < MAX_APPLY_ATTEMPTS else 0, attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)
                if attempt < MAX_APPLY_ATTEMPTS:
                    _clear_inflight()
                    threading.Timer(RETRY_INTERVAL_S, lambda: dispatcher.post(self._apply_step, target, dispatcher, attempt + 1)).start()
                    return
                shadow.record(StyleMachineState.DEGRADED, "WEBVIEW_BG_FAIL", reason_code=state.last_error[:40] or "transparent_fail", kind=target.kind)
                self._apply_degraded(target)
                state.phase = StylePhase.DEGRADED
                state.ready_evt.set()
                _clear_inflight()
                return

            if state.webview_ok:
                shadow.record(StyleMachineState.VERIFY_FIRST_FRAME, "WEBVIEW_BG_OK", kind=target.kind)
                state.phase = StylePhase.WEBVIEW_READY
                if _dbg_style:
                    diag.emit("DIAG_STYLE_STAGE", self._log, "阶段变更", kind=target.kind, overlay_id=target.overlay_id, stage=state.phase.value, attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)

        # 4) Acrylic
        if _dbg_style:
            diag.emit("DIAG_STYLE_STAGE", self._log, "阶段变更", kind=target.kind, overlay_id=target.overlay_id, stage="ACRYLIC_START", attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo)
        if target.kind == "NOTIFY" and is_debug_enabled():
            diag.emit("DIAG_NOTIFY_PIPE", self._log, "即将调用acrylic", step="acrylic_in", hwnd_full=int(hwnd))
        acrylic_ok = False
        try:
            acrylic_ok = self._win_effects.enable_acrylic(hwnd=hwnd, tint_color=0x33101826, blur=True, where="%s overlay_id=%s" % (target.kind, target.overlay_id))
        except Exception as e:
            state.last_error = str(e)[:200]
        state.acrylic_ok = acrylic_ok
        if _dbg_style:
            diag.emit("DIAG_STYLE_STAGE", self._log, "阶段变更", kind=target.kind, overlay_id=target.overlay_id, stage="ACRYLIC_DONE", attempt=attempt, hwnd_full=hwnd_full, hwnd_lo=hwnd_lo, acrylic_ok=acrylic_ok)
        if acrylic_ok:
            shadow.record(StyleMachineState.READY, "FIRST_FRAME_OK", kind=target.kind)
            if target.kind == "NOTIFY" and target.on_ready:
                try:
                    target.on_ready("acrylic", True)
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
            state.phase = StylePhase.STYLE_APPLIED
            state.phase = StylePhase.READY
            state.ready_evt.set()
            dt_ms = int((time.perf_counter() - state.t_start) * 1000)
            diag.emit(
                "DIAG_STYLE_APPLY_OK", self._log, "样式应用成功",
                kind=target.kind, overlay_id=target.overlay_id, dt_ms=dt_ms, attempt=attempt, acrylic=1, fallback=0,
            )
            diag.emit("DIAG_STYLE_READY", self._log, "最终就绪，允许 show", kind=target.kind, overlay_id=target.overlay_id)
            _clear_inflight()
            return
        # Acrylic 失败：重试或降级
        if attempt < MAX_APPLY_ATTEMPTS:
            diag.emit(
                "DIAG_STYLE_APPLY_FAIL", self._log, "Acrylic 失败，将重试",
                kind=target.kind, overlay_id=target.overlay_id, err=state.last_error[:80] if state.last_error else "acrylic_fail", will_retry=1,
            )
            _clear_inflight()
            threading.Timer(RETRY_INTERVAL_S, lambda: dispatcher.post(self._apply_step, target, dispatcher, attempt + 1)).start()
            return
        shadow.record(StyleMachineState.DEGRADED, "FIRST_FRAME_TIMEOUT", reason_code="acrylic_fail", kind=target.kind)
        diag.emit(
            "DIAG_STYLE_DEGRADED", self._log, "进入降级：Acrylic 多次失败",
            kind=target.kind, overlay_id=target.overlay_id, reason="acrylic_fail", attempt=attempt,
        )
        self._apply_degraded(target)
        state.phase = StylePhase.DEGRADED
        state.ready_evt.set()
        dt_ms = int((time.perf_counter() - state.t_start) * 1000)
        diag.emit("DIAG_STYLE_APPLY_OK", self._log, "降级应用完成", kind=target.kind, overlay_id=target.overlay_id, dt_ms=dt_ms, attempt=attempt, acrylic=0, fallback=1)
        diag.emit("DIAG_STYLE_READY", self._log, "降级就绪，允许 show", kind=target.kind, overlay_id=target.overlay_id)
        _clear_inflight()

    def _apply_degraded(self, target: StyleTarget) -> None:
        """降级：半透明暗色背景，避免黑底与透明穿透。必须在 GUI 线程。"""
        native = target.get_native()
        if not native:
            return
        try:
            def _set_degraded():
                try:
                    import clr
                    clr.AddReference("System.Drawing")
                    clr.AddReference("System.Windows.Forms")
                    from System.Drawing import Color
                    # 半透明暗色，与 REST/NOTIFY 统一
                    c = Color.FromArgb(DEGRADED_ALPHA, DEGRADED_R, DEGRADED_G, DEGRADED_B)
                    browser = getattr(native, "browser", None)
                    wv = getattr(browser, "webview", None) if browser else None
                    if wv:
                        wv.DefaultBackgroundColor = c
                    try:
                        native.BackColor = c
                    except Exception as e:
                        log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                    try:
                        native.Invalidate(True)
                        native.Refresh()
                    except Exception as e:
                        log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
            from System import Action
            try:
                native.BeginInvoke(Action(_set_degraded))
            except Exception:
                try:
                    native.Invoke(Action(_set_degraded))
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "style fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_STYLE_FALLBACK")
        except Exception as e:
            diag.emit("DIAG_STYLE_APPLY_FAIL", self._log, "降级设置异常", kind=target.kind, overlay_id=target.overlay_id, err=str(e)[:80], will_retry=0)
