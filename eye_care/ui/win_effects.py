from __future__ import annotations

import logging

from eye_care.diagnostics.diag_events import log_exception_summary


def _dbg_log(log: logging.Logger, msg: str, *args: object, **kwargs: object) -> None:
    """HARD_NOTIFY_* 仅 Debug 时输出（见 DIAG_MIGRATION_DISPUTE_REPORT 4.B）。"""
    try:
        from eye_care.diagnostics.debug_switch import is_debug_enabled
        if is_debug_enabled():
            log.info(msg, *args, **kwargs)
    except ImportError:
        return


class WinEffects:
    """Windows visual effects helpers (Acrylic + layered alpha fade)."""

    def __init__(self, logger: logging.Logger) -> None:
        self._log = logger
        self._exstyle_restore: dict = {}  # hwnd -> exstyle before Layered was added (restore when animation ends)
        self._alpha_callsite_seen: set = set()  # (hwnd, where) 仅首次打印 CALLSITE，避免卡顿
        self._acrylic_applied_hwnds: set = set()  # 已成功 apply 过的 hwnd，rest_fade_in_done 时不再重复 apply，避免 DWM 重建材质导致裂线

    def enable_acrylic(self, hwnd: int, tint_color: int = 0xBB101826, blur: bool = True, where: str = "", quiet: bool = False) -> bool:
        try:
            hwnd_int = int(hwnd)
            if where == "rest_fade_in_done" and hwnd_int in self._acrylic_applied_hwnds:
                return True  # 已应用过，不再重复 apply，避免 DWM 重建材质
            import ctypes
            from ctypes import wintypes

            def _ex_style(h: int):
                try:
                    import win32con
                    import win32gui
                    return win32gui.GetWindowLong(int(h), win32con.GWL_EXSTYLE)
                except Exception:
                    return None

            ex_before = _ex_style(hwnd)
            if not quiet:
                try:
                    from eye_care.diagnostics.debug_switch import is_debug_enabled
                    if is_debug_enabled():
                        self._log.info(
                            "NOTIFY_PIPE_ACRYLIC_ENTER where=%s hwnd=%s ex_style_before=0x%X ws_ex_layered=%s",
                            where, hwnd, ex_before if ex_before is not None else 0,
                            bool(ex_before & 0x00080000) if ex_before is not None else None,
                        )
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "win effect fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_WIN_EFFECT_FALLBACK")

            ACCENT_ENABLE_BLURBEHIND = 3
            ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

            class ACCENTPOLICY(ctypes.Structure):
                _fields_ = [
                    ("AccentState", ctypes.c_int),
                    ("AccentFlags", ctypes.c_int),
                    ("GradientColor", ctypes.c_int),
                    ("AnimationId", ctypes.c_int),
                ]

            class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
                _fields_ = [
                    ("Attribute", ctypes.c_int),
                    ("Data", ctypes.c_void_p),
                    ("SizeOfData", ctypes.c_size_t),
                ]

            WCA_ACCENT_POLICY = 19
            user32 = ctypes.WinDLL("user32", use_last_error=True)

            accent = ACCENTPOLICY()
            accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND if blur else ACCENT_ENABLE_BLURBEHIND
            accent.AccentFlags = 2
            accent.GradientColor = ctypes.c_int(tint_color)
            accent.AnimationId = 0

            data = WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = WCA_ACCENT_POLICY
            data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
            data.SizeOfData = ctypes.sizeof(accent)

            set_attr = getattr(user32, "SetWindowCompositionAttribute", None)
            if not set_attr:
                self._log.warning("notify: acrylic api missing where=%s hwnd=%s", where, hwnd)
                return False

            try:
                set_attr.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWCOMPOSITIONATTRIBDATA)]
                set_attr.restype = wintypes.BOOL
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "win effect fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_WIN_EFFECT_FALLBACK")

            ctypes.set_last_error(0)
            ret = int(set_attr(int(hwnd), ctypes.byref(data)))
            gle = int(ctypes.get_last_error())
            ok = ret != 0
            if ok:
                self._acrylic_applied_hwnds.add(hwnd_int)
            if quiet:
                try:
                    from eye_care.diagnostics.debug_switch import is_debug_enabled
                    if is_debug_enabled():
                        self._log.info("ACRYLIC_REAPPLY where=%s hwnd=%s ok=%s", where, hwnd, ok)
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "win effect fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_WIN_EFFECT_FALLBACK")
            else:
                ex_after = _ex_style(hwnd)
                ex_after_u = (int(ex_after) & 0xFFFFFFFF) if ex_after is not None else 0
                ws_ex_layered_after = bool(ex_after_u & 0x00080000)
                try:
                    from eye_care.diagnostics.debug_switch import is_debug_enabled
                    if is_debug_enabled():
                        self._log.info(
                            "notify: acrylic apply where=%s ok=%s ret=%s gle=%s hwnd=%s tint=0x%08X blur=%s",
                            where, ok, ret, gle, hwnd, int(tint_color) & 0xFFFFFFFF, bool(blur)
                        )
                        self._log.info(
                            "NOTIFY_PIPE_ACRYLIC_AFTER where=%s hwnd=%s ret=%s gle=%s ex_style_after=0x%X ws_ex_layered_after=%s",
                            where, hwnd, ret, gle, ex_after_u, ws_ex_layered_after,
                        )
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "win effect fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_WIN_EFFECT_FALLBACK")
            return ok
        except Exception as e:
            try:
                self._log.exception("notify: acrylic exception where=%s hwnd=%s err=%s", where, hwnd, e)
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "win effect fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_WIN_EFFECT_FALLBACK")
            return False

    def _rest_overlay_force_repaint(self, hwnd: int) -> None:
        """强制 Rest 宿主窗口及子窗重绘，缓解混合 DPI/副屏竖屏下 Acrylic 合成延迟导致的裂线（点击后消失）。"""
        try:
            import ctypes
            h = int(hwnd)
            user32 = ctypes.windll.user32
            RDW_INVALIDATE = 0x0001
            RDW_ERASE = 0x0004
            RDW_ALLCHILDREN = 0x0080
            RDW_FRAME = 0x0400
            RDW_UPDATENOW = 0x0100
            user32.InvalidateRect(h, None, 1)
            user32.RedrawWindow(
                h, None, None,
                RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_FRAME | RDW_UPDATENOW,
            )
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "win effect fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_WIN_EFFECT_FALLBACK")

    def notify_set_alpha(self, hwnd: int, alpha: int, where: str) -> None:
        """
        Layered 仅在动画期间存在；动画结束（alpha>=255 渐入完成 或 alpha==0 渐出完成）时恢复原 exstyle 并可选重刷 Acrylic。
        本函数是日志 "HARD_NOTIFY_ALPHA where=..." 的唯一打印点（本文件内）。
        """
        try:
            import traceback
            import win32con
            import win32gui

            a = max(0, min(255, int(alpha)))
            hwnd_int = int(hwnd)
            key = (hwnd_int, where)
            if key not in self._alpha_callsite_seen:
                self._alpha_callsite_seen.add(key)
                _dbg_log(
                    self._log,
                    "HARD_NOTIFY_ALPHA_CALLSITE stack=%s",
                    " | ".join([l.strip() for l in traceback.format_stack(limit=6)]),
                )

            # 需要 Layered 时先加并缓存 ex_before（动画开始或进行中）
            try:
                ex = win32gui.GetWindowLong(hwnd_int, win32con.GWL_EXSTYLE)
                if (ex & win32con.WS_EX_LAYERED) == 0:
                    if hwnd_int not in self._exstyle_restore:
                        self._exstyle_restore[hwnd_int] = ex
                    win32gui.SetWindowLong(hwnd_int, win32con.GWL_EXSTYLE, ex | win32con.WS_EX_LAYERED)
                    _dbg_log(
                        self._log,
                        "HARD_NOTIFY_LAYERED_FIX where=%s hwnd=%s ex_before=0x%X ex_after=0x%X",
                        where, hwnd_int, ex, ex | win32con.WS_EX_LAYERED,
                    )
            except Exception as e:
                log_exception_summary(self._log, "DIAG_EXCEPTION", "win effect fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_WIN_EFFECT_FALLBACK")
            win32gui.SetLayeredWindowAttributes(hwnd_int, 0, a, win32con.LWA_ALPHA)
            if "notify" in (where or ""):
                try:
                    from eye_care.diagnostics import diag
                    from eye_care.diagnostics.debug_switch import is_debug_enabled
                    if is_debug_enabled():
                        diag.emit("DIAG_NOTIFY_HWND_ALPHA", self._log, "notify_set_alpha", where=where, hwnd=hwnd_int, alpha=a)
                except Exception as e:
                    log_exception_summary(self._log, "DIAG_EXCEPTION", "win effect fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_WIN_EFFECT_FALLBACK")
            if a in (0, 255):
                _dbg_log(self._log, "HARD_NOTIFY_ALPHA where=%s hwnd=%s alpha=%d", where, hwnd_int, a)

            # 动画结束：恢复 exstyle（去掉 Layered），渐入完成时再重刷 Acrylic
            if a >= 255 and where == "rest_fade_in":
                ex_restore = self._exstyle_restore.pop(hwnd_int, None)
                if ex_restore is not None:
                    try:
                        win32gui.SetWindowLong(hwnd_int, win32con.GWL_EXSTYLE, ex_restore)
                        _dbg_log(
                            self._log,
                            "HARD_NOTIFY_LAYERED_RESTORE where=rest_fade_in_done hwnd=%s ex_restored=0x%X",
                            hwnd_int, ex_restore & 0xFFFFFFFF,
                        )
                        self.enable_acrylic(hwnd_int, tint_color=0x33101826, blur=True, where="rest_fade_in_done", quiet=True)
                    except Exception as e:
                        _dbg_log(self._log, "HARD_NOTIFY_LAYERED_RESTORE_FAIL hwnd=%s err=%s", hwnd_int, e)
            # 渐出时不在 alpha=0 恢复 exstyle，避免去掉 Layered 后出现一帧闪屏；由调用方在 hide 后再调 restore_exstyle_after_hide
            elif a == 0 and where in ("rest_fade_out", "notify_fade_out"):
                pass
        except Exception as e:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "notify alpha 设置", "降级继续", detail=str(e)[:200], reason_code="E_NOTIFY_ALPHA", where=where, hwnd=hwnd, alpha=alpha)

    def ensure_notify_visible_before_show(self, hwnd: int) -> None:
        """Show 前若窗口仍是 WS_EX_LAYERED+alpha=0（上次 fade-out 未恢复），强制去掉 Layered 使窗口不透明可见。须在 GUI 线程。"""
        try:
            import win32con
            import win32gui
            h = int(hwnd)
            if not win32gui.IsWindow(h):
                return
            ex = win32gui.GetWindowLong(h, win32con.GWL_EXSTYLE)
            if (ex & win32con.WS_EX_LAYERED) == 0:
                return
            new_ex = ex & (~win32con.WS_EX_LAYERED) & 0xFFFFFFFF
            win32gui.SetWindowLong(h, win32con.GWL_EXSTYLE, new_ex)
            _dbg_log(
                self._log,
                "HARD_NOTIFY_LAYERED_REMOVE_FOR_SHOW hwnd=%s ex_before=0x%X ex_after=0x%X",
                h, ex & 0xFFFFFFFF, new_ex,
            )
        except Exception as e:
            _dbg_log(self._log, "ensure_notify_visible_before_show hwnd=%s err=%s", hwnd, e)

    def restore_exstyle_after_hide(self, hwnds: list) -> None:
        """渐出并 hide 后调用，恢复各 hwnd 的 exstyle（去掉 Layered），避免在 alpha=0 时恢复导致闪屏。须在 GUI 线程。"""
        try:
            import win32con
            import win32gui
            for hwnd in hwnds:
                h = int(hwnd)
                ex_restore = self._exstyle_restore.pop(h, None)
                if ex_restore is not None:
                    try:
                        if win32gui.IsWindow(h):
                            win32gui.SetWindowLong(h, win32con.GWL_EXSTYLE, ex_restore)
                            try:
                                from eye_care.diagnostics import diag
                                from eye_care.diagnostics.debug_switch import is_debug_enabled
                                if is_debug_enabled():
                                    diag.emit("DIAG_NOTIFY_LAYERED_RESTORE", self._log, "恢复exstyle(去Layered)", hwnd=h, ex_restored=ex_restore & 0xFFFFFFFF)
                            except Exception as e:
                                log_exception_summary(self._log, "DIAG_EXCEPTION", "win effect fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_WIN_EFFECT_FALLBACK")
                            _dbg_log(
                                self._log,
                                "HARD_NOTIFY_LAYERED_RESTORE where=after_hide hwnd=%s ex_restored=0x%X",
                                h, ex_restore & 0xFFFFFFFF,
                            )
                    except Exception as e:
                        _dbg_log(self._log, "HARD_NOTIFY_LAYERED_RESTORE_FAIL where=after_hide hwnd=%s err=%s", h, e)
        except Exception:
            self._log.exception("restore_exstyle_after_hide failed")
