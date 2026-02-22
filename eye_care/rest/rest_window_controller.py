"""
RestWindowController：休息遮罩窗口生命周期（创建、show、hide、样式）。
所有方法必须在 GUI 线程调用。
透明口径：BackColor 与 DefaultBackgroundColor 统一为透明，acrylic 未成功也不退化为黑底。
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from typing import Any, Callable, List, Optional

from eye_care.diagnostics import diag, log_exception_summary
from eye_care.diagnostics.debug_switch import is_debug_enabled
from eye_care.ui.style_coordinator import StyleCoordinator, StyleState, StyleTarget
from eye_care.ui.state_machines import RestShadowMachine
from eye_care.ui.state_machines.types import RestState as RestMachineState

log = logging.getLogger(__name__)


class RestWindowController:
    """休息遮罩控制器。仅负责窗口 UI。"""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        win_effects,
        window_runtime,
        window_api,  # WindowApi for js_api on rest overlay windows
        controller_getter: Callable[[], Any],
        dispatcher,
        harden_hwnd_dump: Optional[Callable[..., None]] = None,
        rest_overlay_children_dump: Optional[Callable[..., None]] = None,
        main_window_enabled_cb: Optional[Callable[[bool], None]] = None,
        on_rest_closed_cb: Optional[Callable[[], None]] = None,
    ) -> None:
        self._log = logger
        self._win_effects = win_effects
        self._window_runtime = window_runtime
        self._window_api = window_api
        self._controller_getter = controller_getter
        self._dispatcher = dispatcher
        self._harden_hwnd_dump = harden_hwnd_dump or (lambda *a, **k: None)
        self._rest_overlay_children_dump = rest_overlay_children_dump or (lambda *a, **k: None)
        self._main_window_enabled_cb = main_window_enabled_cb
        self._on_rest_closed_cb = on_rest_closed_cb
        self._overlays: list = []
        self._pump_fn: Optional[Callable[[], None]] = None
        self._style_coordinator = StyleCoordinator(self._log, self._win_effects)
        self._rest_pending_show = False
        self._rest_fill_cancel = False  # close 时置 True，show 时置 False，避免关闭后 child_fill 重试继续投递
        self._rest_last_close_time = 0.0  # 上次关闭完成时间，用于「休息完马上立刻休息」防闪频冷却
        # DIAG_METRIC_REST
        self._metric_last_enter_ts: float = 0.0
        self._metric_show_fail_count: int = 0
        self._metric_overlay_create_durations_ms: deque = deque(maxlen=300)
        self._metric_last_overlay_create_ms: float = 0.0
        self._shadow = RestShadowMachine(self._log)
        try:
            self._window_api.set_rest_ready_callback(self._on_rest_ready_for_show)
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "rest set_rest_ready_callback", "休息遮罩 ready 回调可能未注入", detail=str(e)[:200], reason_code="E_REST_READY_CALLBACK")

    def _rest_diag(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """REST_DIAG_* 仅 Debug 时输出（见 DIAG_MIGRATION_DISPUTE_REPORT 4.B）。"""
        if is_debug_enabled():
            self._log.info(msg, *args, **kwargs)

    def _on_rest_ready_for_show(self, screen_idx: int) -> None:
        """Rest 页加载完成后由 WindowApi 在 GUI 线程调用；仅 ready 后再 show 避免首帧黑屏。"""
        for ro in self._overlays:
            if ro.get("idx") == screen_idx:
                ro["ready"] = True
                if self._rest_pending_show:
                    self._show_one_overlay(ro)
                break

    def _show_one_overlay(self, ro: dict) -> None:
        """对单个 overlay 执行 show + 宿主窗口渐入(0→255) + restFadeIn + start(duration)。须在 GUI 线程。"""
        w = ro.get("window")
        if not w:
            return
        hwnd = ro.get("hwnd") or self._get_hwnd_for_ro(ro)
        # 先按该屏分辨率把遮罩设到正确位置和大小，再渐入（每屏一块磨砂，避免裂线）
        if hwnd and ro.get("bounds"):
            self._rest_diag("REST_DIAG_SHOW_OVERLAY screen_idx=%s hwnd=%s bounds=%s", ro.get("idx"), hwnd, ro["bounds"])
            self._apply_overlay_bounds(hwnd, ro["bounds"], screen_idx=ro.get("idx"))
            self._log_precise_overlay_rect(hwnd, ro.get("idx"), ro["bounds"], label="show")
        start_with_alpha_zero = False
        if hwnd:
            try:
                import win32gui
                if win32gui.IsWindow(hwnd):
                    self._win_effects.notify_set_alpha(hwnd, 0, "rest_fade_in_start")
                    start_with_alpha_zero = True
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
        try:
            w.show()
            if getattr(w, "bring_to_front", None) is not None:
                w.bring_to_front()
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
        try:
            import win32gui
            import win32con
            hwnd = hwnd or ro.get("hwnd") or self._get_hwnd_for_ro(ro)
            if hwnd:
                ro["hwnd"] = hwnd
            if hwnd and win32gui.IsWindow(hwnd) and not ro.get("_rect_logged"):
                try:
                    r = win32gui.GetWindowRect(hwnd)
                    ro["_rect_logged"] = True
                    exp = ro.get("bounds", (0, 0, 0, 0))
                    self._log.info(
                        "REST_OVERLAY_RECT_ACTUAL screen_idx=%s expected_bounds=(%s,%s,%s,%s) GetWindowRect=(left=%s,top=%s,right=%s,bottom=%s)",
                        ro.get("idx"), exp[0], exp[1], exp[2], exp[3],
                        r[0], r[1], r[2], r[3],
                    )
                except Exception:
                    ro["_rect_logged"] = True
            if hwnd and win32gui.IsWindow(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
                if not start_with_alpha_zero:
                    self._win_effects.notify_set_alpha(hwnd, 0, "rest_fade_in_start")
                    start_with_alpha_zero = True
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
        if start_with_alpha_zero and hwnd:
            self._run_rest_fade_in(hwnd)
        # 将 JS 调用投递到下一帧执行，避免第二次点休息时 evaluate_js 在 GUI 线程阻塞导致卡死
        duration = self._rest_duration_seconds()
        try:
            cfg = getattr(self._controller_getter(), "cfg", None)
            sound_enabled = getattr(cfg, "rest_end_sound_enabled", True)
        except Exception:
            sound_enabled = True
        self._dispatcher.post(
            lambda: self._apply_rest_js_after_show(ro, duration, sound_enabled)
        )

    def _apply_rest_js_after_show(self, ro: dict, duration: int, sound_enabled: bool) -> None:
        """GUI 线程：窗口 show 后执行 restFadeIn + 音效开关 + EyeCareRest.start，合并为单次脚本注入以减少同步 round-trip。
        
        硬约束：GUI 线程内 evaluate_js 应合并为单次调用，避免多次同步 round-trip。
        """
        if getattr(self, "_rest_fill_cancel", False):
            return
        w = ro.get("window")
        if not w:
            return
        # 合并3次 evaluate_js 为一次脚本注入（IIFE 包装）
        js = f"""(function(){{
  // restFadeIn
  if (window.restFadeIn) window.restFadeIn();
  // 音效开关
  window.__rest_end_sound_enabled = {str(bool(sound_enabled)).lower()};
  // EyeCareRest.start
  var duration = {duration};
  var attempts = 0;
  var maxAttempts = 80;
  function run(){{
    try {{
      if (window.EyeCareRest && window.EyeCareRest.start) {{
        window.EyeCareRest.start(duration);
        return;
      }}
    }} catch(e) {{}}
    attempts++;
    if (attempts < maxAttempts) setTimeout(run, 100);
  }}
  run();
}})();"""
        try:
            w.evaluate_js(js)
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")

    def set_pump_fn(self, fn: Optional[Callable[[], None]]) -> None:
        """设置等待样式时的队列消费函数（main 在 GUI loop 内注入），避免阻塞导致样式任务不执行。"""
        self._pump_fn = fn

    def _get_all_screen_bounds(self) -> list:
        """使用 Win32 EnumDisplayMonitors + GetMonitorInfo 的 rcMonitor（虚拟桌面坐标），
        为每块屏取准边界，避免混合 DPI 下 overlay 跨屏/漏屏/中间裂线。
        返回: [(idx, left, top, width, height, device_name), ...]
        """
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            out: list = []
            # MONITORINFOEXW.rcMonitor 与虚拟桌面坐标系一致，每屏一块
            class RECT(ctypes.Structure):
                _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                            ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

            class MONITORINFOEXW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32),
                ]

            def _enum_proc(h_mon, h_dc, rect, lparam):
                idx = len(out)
                mi = MONITORINFOEXW()
                mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
                if user32.GetMonitorInfoW(h_mon, ctypes.byref(mi)):
                    r = mi.rcMonitor
                    left, top = r.left, r.top
                    w, h = r.right - r.left, r.bottom - r.top
                    dev = mi.szDevice.strip() or ("Monitor_%d" % idx)
                    out.append((idx, left, top, w, h, dev))
                return 1

            EnumMonitorsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)
            user32.EnumDisplayMonitors(None, None, EnumMonitorsProc(_enum_proc), 0)
            if out:
                for idx, left, top, w, h, dev in out:
                    self._rest_diag("REST_DIAG_SCREEN_BOUNDS source=ctypes idx=%s dev=%s left=%s top=%s width=%s height=%s", idx, dev, left, top, w, h)
                return out
        except Exception as e:
            self._rest_diag("REST_DIAG_SCREEN_BOUNDS ctypes_failed err=%s", e)
            pass
        try:
            import win32api
            out = []
            for idx, (h_mon, _hdc, _rect) in enumerate(win32api.EnumDisplayMonitors()):
                try:
                    info = win32api.GetMonitorInfo(h_mon)
                    rc = info.get("Monitor") or info.get("rcMonitor")
                    if rc is None:
                        continue
                    left = getattr(rc, "Left", getattr(rc, "left", rc[0]))
                    top = getattr(rc, "Top", getattr(rc, "top", rc[1]))
                    right = getattr(rc, "Right", getattr(rc, "right", rc[2]))
                    bottom = getattr(rc, "Bottom", getattr(rc, "bottom", rc[3]))
                    w, h = right - left, bottom - top
                    dev = (info.get("Device") or info.get("szDevice") or "").strip() or ("Monitor_%d" % idx)
                    out.append((idx, left, top, w, h, dev))
                except (IndexError, TypeError, KeyError, Exception):
                    continue
            if out:
                for idx, left, top, w, h, dev in out:
                    self._rest_diag("REST_DIAG_SCREEN_BOUNDS source=win32api idx=%s dev=%s left=%s top=%s width=%s height=%s", idx, dev, left, top, w, h)
                return out
        except Exception as e:
            self._rest_diag("REST_DIAG_SCREEN_BOUNDS win32api_failed err=%s", e)
            pass
        try:
            import ctypes
            # 仅用主屏尺寸（SM_CX/CYSCREEN），不用虚拟桌面 SM_CXVIRTUALSCREEN 等，避免一块磨砂盖多屏
            w = ctypes.windll.user32.GetSystemMetrics(0)
            h = ctypes.windll.user32.GetSystemMetrics(1)
            return [(0, 0, 0, w, h, "Primary")]
        except Exception:
            return [(0, 0, 0, 1920, 1080, "Primary")]

    def _rest_duration_seconds(self) -> int:
        try:
            cfg = getattr(self._controller_getter(), "cfg", None)
            if not cfg:
                return 20
            unit = getattr(cfg, "reminder_rest_unit", "sec")
            v = int(getattr(cfg, "reminder_rest_seconds", 20) or 20)
            raw = max(1, v) * (60 if unit == "min" else 1)
            return max(5, raw)  # 最少 5 秒，与设置页/主界面休息时长下限一致
        except Exception:
            return 20

    _REST_FADE_DURATION_S = 0.9  # 渐入/渐出时长，与 rest.css transition 一致

    def _run_rest_fade_in(self, hwnd: int) -> None:
        """后台线程：宿主窗口 alpha 0→255 渐入（与 Web restFadeIn 同步），步数增多更顺滑。"""
        duration_s = self._REST_FADE_DURATION_S
        steps = max(18, min(36, int(duration_s * 40)))  # 约 25ms/步，更顺滑
        step_dt = duration_s / steps

        def _runner():
            start = time.perf_counter()
            for k in range(0, steps + 1):
                t = k / float(steps)
                # ease-in-out 型：两端慢、中间快，观感更顺
                ease = t * t * (3.0 - 2.0 * t) if t <= 1.0 else 1.0
                a = int(round(255 * ease))
                self._dispatcher.post(
                    lambda _h=hwnd, _a=a: self._win_effects.notify_set_alpha(_h, _a, "rest_fade_in")
                )
                target = start + (k + 1) * step_dt
                wait = target - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)

        threading.Thread(target=_runner, daemon=True, name="rest_fade_in").start()

    def _apply_overlay_bounds(self, hwnd: int, bounds: tuple, screen_idx: Optional[int] = None) -> None:
        """按该屏边界把 overlay 窗口设到正确位置和大小（每屏一块磨砂遮罩）。须在 GUI 线程。"""
        try:
            import win32con
            import win32gui
            if not hwnd or not win32gui.IsWindow(hwnd):
                return
            sx, sy, sw, sh = bounds[0], bounds[1], bounds[2], bounds[3]
            self._rest_diag("REST_DIAG_APPLY_BOUNDS before screen_idx=%s hwnd=%s set_pos=(%s,%s,%s,%s)", screen_idx, hwnd, sx, sy, sw, sh)
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, sx, sy, sw, sh,
                win32con.SWP_NOACTIVATE | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED,
            )
            wr = win32gui.GetWindowRect(hwnd)
            cr = win32gui.GetClientRect(hwnd)
            self._log.info(
                "REST_DIAG_APPLY_BOUNDS after screen_idx=%s hwnd=%s GetWindowRect=(%s,%s,%s,%s) GetClientRect=(%s,%s,%s,%s) client_wh=(%s,%s)",
                screen_idx, hwnd, wr[0], wr[1], wr[2], wr[3], cr[0], cr[1], cr[2], cr[3], cr[2] - cr[0], cr[3] - cr[1],
            )
        except Exception as e:
            self._rest_diag("REST_DIAG_APPLY_BOUNDS_FAIL screen_idx=%s hwnd=%s err=%s", screen_idx, hwnd, e)

    def _log_precise_overlay_rect(self, hwnd: int, screen_idx: Optional[int], expected_bounds: tuple, label: str = "") -> None:
        """更精确的 overlay 矩形诊断：客户区屏幕坐标、边框、子窗与客户区缝隙、副屏中线 Y。"""
        try:
            import win32gui
            if not hwnd or not win32gui.IsWindow(hwnd):
                return
            wr = win32gui.GetWindowRect(hwnd)
            cr = win32gui.GetClientRect(hwnd)
            cw = cr[2] - cr[0]
            ch = cr[3] - cr[1]
            pt0 = win32gui.ClientToScreen(hwnd, (cr[0], cr[1]))
            pt1 = win32gui.ClientToScreen(hwnd, (cr[2], cr[3]))
            client_screen = (pt0[0], pt0[1], pt1[0], pt1[1])
            border_w = (wr[2] - wr[0]) - cw
            border_h = (wr[3] - wr[1]) - ch
            child_rect_screen = None
            child_hwnd = [None]
            def _enum(child, _):
                try:
                    cls = (win32gui.GetClassName(child) or "").strip()
                    if "Chrome_WidgetWin" in cls or "WebView" in cls or "Edge" in cls or "WindowsForms10" in cls:
                        child_hwnd[0] = child
                        return False
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
                return True
            win32gui.EnumChildWindows(hwnd, _enum, None)
            if child_hwnd[0]:
                child_rect_screen = win32gui.GetWindowRect(child_hwnd[0])
            ex_left, ex_top, ex_w, ex_h = expected_bounds[0], expected_bounds[1], expected_bounds[2], expected_bounds[3]
            exp_right = ex_left + ex_w
            exp_bottom = ex_top + ex_h
            diff_left = client_screen[0] - ex_left
            diff_top = client_screen[1] - ex_top
            diff_right = client_screen[2] - exp_right
            diff_bottom = client_screen[3] - exp_bottom
            mid_y_screen = client_screen[1] + ch // 2 if ch else None
            self._log.info(
                "REST_DIAG_PRECISE %s screen_idx=%s hwnd=%s label=%s",
                "|", screen_idx, hwnd, label,
            )
            self._log.info(
                "REST_DIAG_PRECISE host client_screen=(L=%s,T=%s,R=%s,B=%s) client_wh=(%s,%s) border_wh=(%s,%s)",
                client_screen[0], client_screen[1], client_screen[2], client_screen[3], cw, ch, border_w, border_h,
            )
            self._log.info(
                "REST_DIAG_PRECISE expected_bounds=(%s,%s,%s,%s) diff_from_client=(L=%s,T=%s,R=%s,B=%s)",
                ex_left, ex_top, ex_w, ex_h, diff_left, diff_top, diff_right, diff_bottom,
            )
            if child_rect_screen:
                cbl, cbt, cbr, cbb = child_rect_screen[0], child_rect_screen[1], child_rect_screen[2], child_rect_screen[3]
                gap_l = cbl - client_screen[0]
                gap_t = cbt - client_screen[1]
                gap_r = client_screen[2] - cbr
                gap_b = client_screen[3] - cbb
                self._log.info(
                    "REST_DIAG_PRECISE child_rect_screen=(L=%s,T=%s,R=%s,B=%s) child_wh=(%s,%s) gap_from_client=(L=%s,T=%s,R=%s,B=%s)",
                    cbl, cbt, cbr, cbb, cbr - cbl, cbb - cbt, gap_l, gap_t, gap_r, gap_b,
                )
            if mid_y_screen is not None:
                self._rest_diag("REST_DIAG_PRECISE mid_y_screen=%s (client_center) ch=%s", mid_y_screen, ch)
        except Exception as e:
            self._rest_diag("REST_DIAG_PRECISE_FAIL screen_idx=%s hwnd=%s err=%s", screen_idx, hwnd, e)

    def _get_hwnd_for_ro(self, ro: dict) -> Optional[int]:
        """解析 overlay 的 hwnd（已有则返回，否则按 title_token 枚举）。"""
        if ro.get("hwnd"):
            try:
                import win32gui
                if win32gui.IsWindow(int(ro["hwnd"])):
                    return int(ro["hwnd"])
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
        title_token = ro.get("title_token", "")
        if not title_token:
            return None
        try:
            import win32gui
            hwnd = None
            def _cb(h, _):
                nonlocal hwnd
                try:
                    if title_token in (win32gui.GetWindowText(h) or ""):
                        hwnd = h
                        return False
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
                return True
            win32gui.EnumWindows(_cb, None)
            return int(hwnd) if hwnd else None
        except Exception:
            return None

    def destroy_overlays(self) -> None:
        """销毁所有休息遮罩窗口。必须在 GUI 线程调用。"""
        try:
            for ro in self._overlays:
                w = ro.get("window")
                if w:
                    try:
                        w.destroy()
                    except Exception as e:
                        log_exception_summary(self._log, "DIAG_EXCEPTION", "rest overlay destroy", "单窗销毁失败", detail=str(e)[:200], reason_code="E_REST_OVERLAY_DESTROY")
            # 退出时若未经过 close_overlay，确保主窗口恢复可点击
            cb = getattr(self, "_main_window_enabled_cb", None)
            if callable(cb):
                try:
                    cb(True)
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")

    def close_overlay(self) -> None:
        """隐藏休息遮罩：先让所有 overlay 停止倒计时（避免另一屏到 0 触发 auto_complete 播 wav），再 restFadeOut + 宿主渐出 + hide。须在 GUI 线程调用。"""
        self._rest_pending_show = False
        self._rest_fill_cancel = True
        if self._shadow.state == RestMachineState.COUNTDOWN:
            self._shadow.record(RestMachineState.CLOSING, "ABORT")
        elif self._shadow.state == RestMachineState.SHOWN:
            self._shadow.record(RestMachineState.CLOSING, "ABORT")
        try:
            # 合并每个窗口的多次 evaluate_js 为一次脚本注入（IIFE 包装）
            # 硬约束：GUI 线程内 evaluate_js 应合并为单次调用，避免多次同步 round-trip
            for ro in self._overlays:
                w = ro.get("window")
                if w:
                    try:
                        # 合并 stop 和 restFadeOut 为一次调用
                        w.evaluate_js("""(function(){
  if (window.EyeCareRest && window.EyeCareRest.stop) window.EyeCareRest.stop();
  if (window.restFadeOut) window.restFadeOut();
})();""")
                    except Exception as e:
                        log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
            hwnds: List[int] = []
            try:
                import win32gui
                for ro in self._overlays:
                    h = ro.get("hwnd") or self._get_hwnd_for_ro(ro)
                    if h and win32gui.IsWindow(h):
                        hwnds.append(int(h))
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")

            def _do_hide():
                try:
                    for ro in self._overlays:
                        w = ro.get("window")
                        if w:
                            try:
                                w.hide()
                            except Exception as e:
                                log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
                    if self._shadow.state == RestMachineState.CLOSING:
                        try:
                            self._shadow.record(RestMachineState.CLOSED, "CLOSE_DONE")
                        except Exception as e:
                            log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
                except Exception as e:
                    if self._shadow.state == RestMachineState.CLOSING:
                        try:
                            self._shadow.record(RestMachineState.FAILED, "CLOSE_FAIL", reason_code=str(e)[:40])
                        except Exception as e:
                            log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
                finally:
                    # 无论 try/except 是否异常都执行，确保磨砂块关闭、主窗口可点、冷却时间更新
                    if hwnds:
                        try:
                            self._win_effects.restore_exstyle_after_hide(hwnds)
                        except Exception as e:
                            log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
                    cb = getattr(self, "_main_window_enabled_cb", None)
                    if callable(cb):
                        try:
                            cb(True)
                        except Exception as e:
                            log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
                    try:
                        self._rest_last_close_time = time.perf_counter()
                    except Exception as e:
                        log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
                    cb_closed = getattr(self, "_on_rest_closed_cb", None)
                    if callable(cb_closed):
                        try:
                            cb_closed()
                        except Exception as e:
                            log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")

            if hwnds:
                duration_s = self._REST_FADE_DURATION_S
                steps = max(18, min(36, int(duration_s * 40)))
                step_dt = duration_s / steps

                def _fade_out_runner():
                    start = time.perf_counter()
                    for k in range(0, steps + 1):
                        t = k / float(steps)
                        ease = t * t * (3.0 - 2.0 * t) if t <= 1.0 else 1.0
                        a = int(round(255 * (1.0 - ease)))
                        for h in hwnds:
                            self._dispatcher.post(
                                lambda _h=h, _a=a: self._win_effects.notify_set_alpha(_h, _a, "rest_fade_out")
                            )
                        target = start + (k + 1) * step_dt
                        wait = target - time.perf_counter()
                        if wait > 0:
                            time.sleep(wait)
                    self._dispatcher.post(_do_hide)

                threading.Thread(target=_fade_out_runner, daemon=True, name="rest_fade_out").start()
            else:
                threading.Timer(self._REST_FADE_DURATION_S, lambda: self._dispatcher.post(_do_hide)).start()
        except Exception as e:
            if self._shadow.state == RestMachineState.CLOSING:
                self._shadow.record(RestMachineState.FAILED, "CLOSE_FAIL", reason_code=str(e)[:40])
            pass

    # 休息刚结束后立刻再点「立刻休息」时的最小间隔，避免闪频
    _REST_SHOW_COOLDOWN_S = 1.5

    def show_overlay(self) -> None:
        """显示休息遮罩。仅对已 ready 的 overlay 执行 show（静默加载后首显不黑屏）；未 ready 的由 rest_ready_for_show 回调再 show。"""
        try:
            # 保护：休息刚结束马上点「立刻休息」时延迟再显示，避免闪频
            last_close = getattr(self, "_rest_last_close_time", 0.0)
            if last_close > 0:
                elapsed = time.perf_counter() - last_close
                if elapsed < self._REST_SHOW_COOLDOWN_S:
                    delay = self._REST_SHOW_COOLDOWN_S - elapsed
                    threading.Timer(delay, lambda: self._dispatcher.post(self.show_overlay)).start()
                    diag.emit("DIAG_REST_SHOW_COOLDOWN", self._log, "休息刚结束防闪频，延迟再显示", delay_s=round(delay, 2))
                    return
            # 禁用主窗口，避免同屏点击激活主窗口导致 Rest 遮罩闪烁（主屏点会闪、副屏不闪）
            cb = getattr(self, "_main_window_enabled_cb", None)
            if callable(cb):
                try:
                    cb(False)
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "rest fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REST_FALLBACK")
            t_trigger = time.perf_counter()
            try:
                ctrl = self._controller_getter() if self._controller_getter else None
                mode = ctrl._current_mode() if ctrl else ""
            except Exception:
                mode = ""
            self._metric_last_enter_ts = time.time()
            if self._shadow.state in (RestMachineState.IDLE, RestMachineState.CLOSED, RestMachineState.FAILED):
                self._shadow.record(RestMachineState.SCHEDULED, "REQUEST_SHOW")
            if self._shadow.state == RestMachineState.SCHEDULED:
                self._shadow.record(RestMachineState.CREATING, "GUI_START", screen_count=0)
            diag.emit("DIAG_REST_SHOW_ENTER", self._log, "进入显示休息遮罩", mode=mode, source="gui", screen_count=len(self._overlays))
            self._lazy_init_overlays()
            if not self._overlays:
                return
            self._shadow.record(RestMachineState.CREATED, "OVERLAY_CREATE_PARTIAL", screen_count=len(self._overlays))
            self._shadow.record(RestMachineState.SHOWING, "SHOW_OK")
            self._shadow.record(RestMachineState.SHOWN, "SHOW_DONE")
            self._shadow.record(RestMachineState.COUNTDOWN, "COUNTDOWN_START")

            self._rest_pending_show = True
            self._rest_fill_cancel = False
            pump = getattr(self, "_pump_fn", None)

            for ro in self._overlays:
                target = ro.get("_style_target")
                if not target:
                    continue
                ok = False
                try:
                    ok = self._style_coordinator.ensure_ready(target, self._dispatcher, timeout_s=0.25, pump_fn=pump)
                except Exception:
                    ok = False
                if not ok:
                    diag.emit("DIAG_STYLE_APPLY_FAIL", self._log, "REST: ensure_ready超时，跳过等待直接show", kind="REST", overlay_id=target.overlay_id)

            t_before_show = time.perf_counter()
            any_ready = any(ro.get("ready") for ro in self._overlays)
            for ro in self._overlays:
                if ro.get("ready") or not any_ready:
                    self._show_one_overlay(ro)

            trigger_to_show_ms = int((time.perf_counter() - t_trigger) * 1000)
            before_show_elapsed_ms = int((t_before_show - t_trigger) * 1000)
            diag.emit("DIAG_REST_OVERLAY_PERF", self._log, "休息遮罩触发到显示耗时", trigger_to_show_ms=trigger_to_show_ms, before_show_elapsed_ms=before_show_elapsed_ms)
            threading.Timer(0.35, lambda: self._dispatcher.post(self._delayed_rest_repaint)).start()
        except Exception:
            self._metric_show_fail_count += 1
            log_exception_summary(self._log, "DIAG_EXCEPTION", "显示休息遮罩", "遮罩可能未显示")
            self._log.exception("rest: show_overlay failed")

    def get_metric(self) -> dict:
        """返回 DIAG_METRIC_REST 用字段（last_enter_ts, show_fail_count, overlay_create_ms_last, overlay_create_ms_p95_5m）。"""
        p95 = 0.0
        if self._metric_overlay_create_durations_ms:
            sorted_d = sorted(self._metric_overlay_create_durations_ms)
            idx = max(0, int(len(sorted_d) * 0.95) - 1)
            p95 = sorted_d[idx]
        return {
            "last_enter_ts": round(self._metric_last_enter_ts, 2),
            "show_fail_count": self._metric_show_fail_count,
            "overlay_create_ms_last": round(self._metric_last_overlay_create_ms, 2),
            "overlay_create_ms_p95_5m": round(p95, 2),
        }

    def _delayed_rest_repaint(self) -> None:
        """GUI 线程：Rest 显示约 350ms 后按每屏 bounds 重设位置大小并强制重绘。"""
        if getattr(self, "_rest_fill_cancel", False):
            return
        self._rest_diag("REST_DIAG_DELAYED_REPAINT enter overlay_count=%s", len(self._overlays))
        try:
            import win32gui
            for ro in self._overlays:
                h = ro.get("hwnd") or self._get_hwnd_for_ro(ro)
                if not h or not win32gui.IsWindow(h):
                    self._rest_diag("REST_DIAG_DELAYED_REPAINT skip screen_idx=%s no_hwnd=%s", ro.get("idx"), h is None)
                    continue
                self._rest_diag("REST_DIAG_DELAYED_REPAINT screen_idx=%s hwnd=%s bounds=%s", ro.get("idx"), h, ro.get("bounds"))
                if ro.get("bounds"):
                    self._apply_overlay_bounds(h, ro["bounds"], screen_idx=ro.get("idx"))
                self._win_effects._rest_overlay_force_repaint(h)
                if ro.get("bounds"):
                    self._log_precise_overlay_rect(h, ro.get("idx"), ro["bounds"], label="after_delayed_repaint")
        except Exception as e:
            self._rest_diag("REST_DIAG_DELAYED_REPAINT_FAIL err=%s", e)

    def _lazy_init_overlays(self) -> None:
        if self._overlays:
            return
        t0 = time.perf_counter()
        try:
            import webview as _wv
            import uuid
            base_token = uuid.uuid4().hex
            screens = self._get_all_screen_bounds()
            self._rest_diag("REST_DIAG_LAZY_INIT screen_count=%s screens=%s", len(screens), [(i, left, top, w, h, d) for i, left, top, w, h, d in screens])
            api = self._window_api
            for idx, sx, sy, sw, sh, dev in screens:
                # 上下左右各留 1px，其余全覆盖，避免贴边导致主副屏边界/DPI 误拓展
                margin = 1
                sx2 = sx + margin
                sy2 = sy + margin
                sw2 = max(1, sw - 2 * margin)
                sh2 = max(1, sh - 2 * margin)
                self._log.info(
                    "REST_OVERLAY_BOUNDS_EXPECTED screen_idx=%s dev=%s bounds_1px_margin=(sx=%s,sy=%s,sw=%s,sh=%s)",
                    idx, dev, sx2, sy2, sw2, sh2,
                )
                ro = {
                    "idx": idx, "dev": dev, "bounds": (sx2, sy2, sw2, sh2),
                    "ready_evt": threading.Event(),
                    "transparent_applied_evt": threading.Event(),
                    "title_token": "%s_%d" % (base_token, idx),
                    "window": None, "hwnd": None,
                    "ready": False,
                }
                title = f"EyE Care RestOverlay [{ro['title_token']}]"
                url = self._window_runtime.build_rest_overlay_url(idx)
                try:
                    w = _wv.create_window(
                        title, url, x=sx2, y=sy2, width=sw2, height=sh2,
                        frameless=True, easy_drag=False, on_top=True,
                        resizable=False, transparent=True, background_color="#01000000",
                        js_api=api, minimized=False, hidden=True,
                    )
                except (TypeError, ValueError):
                    try:
                        w = _wv.create_window(
                            title, url, x=sx2, y=sy2, width=sw2, height=sh2,
                            frameless=True, easy_drag=False, on_top=True,
                            resizable=False, transparent=False, background_color="#000000",
                            js_api=api, minimized=False, hidden=True,
                        )
                    except (TypeError, ValueError):
                        diag.emit("DIAG_REST_OVERLAY_CREATE_FAIL", self._log, "该屏休息窗创建失败", level=logging.WARNING, screen_idx=idx)
                        continue
                ro["window"] = w
                ro["_style_state"] = StyleState(mode="REST", overlay_id=idx)
                ro["_style_target"] = StyleTarget(
                    kind="REST",
                    overlay_id=idx,
                    get_native=lambda r=ro: getattr(r.get("window"), "native", None),
                    get_webview=lambda r=ro: getattr(getattr(getattr(r.get("window"), "native", None), "browser", None), "webview", None),
                    get_hwnd=lambda r=ro: self._get_hwnd_for_ro(r),
                    get_bounds=lambda r=ro: r.get("bounds", (0, 0, 1920, 1080)),
                    set_hwnd=(lambda r=ro: lambda h: r.__setitem__("hwnd", int(h)))(),
                    state=ro["_style_state"],
                )
                self._overlays.append(ro)
                diag.emit("DIAG_REST_OVERLAY_CREATED", self._log, "休息遮罩窗口已创建，已排队样式(GUI)", screen_idx=ro.get("idx"))
                self._style_coordinator.apply(ro["_style_target"], self._dispatcher)
            dur_ms = (time.perf_counter() - t0) * 1000.0
            self._metric_overlay_create_durations_ms.append(dur_ms)
            self._metric_last_overlay_create_ms = dur_ms
        except Exception:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "休息遮罩整体初始化", "遮罩可能不可用")
            self._log.exception("rest overlay init failed")
