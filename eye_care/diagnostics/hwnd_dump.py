"""Win32 窗口硬日志：用于排查通知窗/休息遮罩的 hwnd、cloaked、样式等问题。"""
from __future__ import annotations

import logging
from typing import Optional


def harden_hwnd_dump(
    hwnd: int, where: str, logger: logging.Logger, log_prefix: str = "HARD_NOTIFY_HWND_DUMP"
) -> None:
    """硬日志：完整 dump 窗口信息，用于判定 hwnd 是否打在正确的窗口、是否被 cloak。仅在 debug 开关打开时执行。"""
    try:
        from .debug_switch import is_debug_enabled
        if not is_debug_enabled():
            return
    except ImportError:
        return
    try:
        import win32gui
        import win32con
        info: dict = {}
        try:
            info["class"] = win32gui.GetClassName(int(hwnd)) or ""
        except Exception:
            info["class"] = "?"
        try:
            info["text"] = (win32gui.GetWindowText(int(hwnd)) or "")[:80]
        except Exception:
            info["text"] = "?"
        try:
            info["visible"] = bool(win32gui.IsWindowVisible(int(hwnd)))
        except Exception:
            info["visible"] = "?"
        try:
            r = win32gui.GetWindowRect(int(hwnd))
            info["rect"] = "x=%d y=%d w=%d h=%d" % (r[0], r[1], r[2] - r[0], r[3] - r[1])
        except Exception:
            info["rect"] = "?"
        try:
            style = win32gui.GetWindowLong(int(hwnd), win32con.GWL_STYLE)
            info["style"] = "0x%08X" % (style & 0xFFFFFFFF)
        except Exception:
            info["style"] = "?"
        try:
            ex_style = win32gui.GetWindowLong(int(hwnd), win32con.GWL_EXSTYLE)
            info["exstyle"] = "0x%08X" % (ex_style & 0xFFFFFFFF)
            info["has_WS_EX_LAYERED"] = bool(ex_style & win32con.WS_EX_LAYERED)
        except Exception:
            info["exstyle"] = "?"
            info["has_WS_EX_LAYERED"] = "?"
        try:
            parent = win32gui.GetParent(int(hwnd))
            info["parent"] = int(parent) if parent else 0
        except Exception:
            info["parent"] = "?"
        try:
            import ctypes
            DWMWA_CLOAKED = 14
            cloaked = ctypes.c_int()
            dwm = ctypes.windll.dwmapi
            hr = dwm.DwmGetWindowAttribute(
                ctypes.c_void_p(int(hwnd)),
                ctypes.c_uint(DWMWA_CLOAKED),
                ctypes.byref(cloaked),
                ctypes.sizeof(ctypes.c_int),
            )
            hr_signed = int(hr)
            hr_hex = "0x%08X" % (hr_signed & 0xFFFFFFFF) if hr_signed < 0 else "0x%08X" % hr_signed
            if hr == 0:
                info["cloaked"] = int(cloaked.value)
                info["cloaked_hr"] = "0x00000000"
            else:
                info["cloaked"] = "?"
                info["cloaked_hr"] = hr_hex
        except Exception as e:
            info["cloaked"] = "?"
            info["cloaked_hr"] = "err:%s" % (str(e)[:50])
        children: list = []

        def _enum_child(h, _):
            try:
                c = win32gui.GetClassName(h) or "?"
                children.append(c)
            except Exception:
                children.append("?")
            return len(children) < 10

        win32gui.EnumChildWindows(int(hwnd), _enum_child, None)
        info["children_class"] = children[:10]
        logger.info(
            "%s where=%s hwnd=%s DWMWA_CLOAKED hr=%s cloaked=%s %s children=%s",
            log_prefix, where, hwnd,
            info.get("cloaked_hr", "?"),
            info.get("cloaked", "?"),
            " ".join("%s=%s" % (k, v) for k, v in info.items() if k not in ("children_class", "cloaked", "cloaked_hr")),
            info.get("children_class", []),
        )
    except Exception as e:
            logger.warning("%s where=%s hwnd=%s err=%s", log_prefix, where, hwnd, str(e)[:100])


# 与 harden_hwnd_dump 同实现，便于调用方统一用 dump_hwnd 命名
dump_hwnd = harden_hwnd_dump


def rest_overlay_children_dump(
    parent_hwnd: int, parent_w: int, parent_h: int, logger: logging.Logger,
    win_enable_acrylic_fn,
) -> None:
    """枚举 rest overlay 子窗口，识别全屏 child，打 GetLayeredWindowAttributes + acrylic 返回值。仅在 debug 开关打开时执行。"""
    try:
        from .debug_switch import is_debug_enabled
        if not is_debug_enabled():
            return
    except ImportError:
        return
    try:
        import win32gui
        import win32con
        import ctypes
        from ctypes import wintypes

        children_info: list = []
        fullscreen_child: Optional[int] = None
        fullscreen_child_class = ""
        fullscreen_candidates: list = []

        def _enum_child(h, _):
            nonlocal fullscreen_child, fullscreen_child_class
            cls = win32gui.GetClassName(h) or "?"
            r = win32gui.GetWindowRect(h)
            cw, ch = r[2] - r[0], r[3] - r[1]
            visible = bool(win32gui.IsWindowVisible(h))
            ex_style = win32gui.GetWindowLong(h, win32con.GWL_EXSTYLE)
            exstyle_hex = "0x%08X" % (ex_style & 0xFFFFFFFF)
            info = "hwnd=%s class=%s rect=(%d,%d,%d,%d) w=%d h=%d visible=%s exstyle=%s" % (
                h, cls, r[0], r[1], r[2], r[3], cw, ch, visible, exstyle_hex,
            )
            children_info.append(info)
            if cw >= parent_w and ch >= parent_h:
                fullscreen_candidates.append((h, cls, cw * ch))
            return True

        win32gui.EnumChildWindows(int(parent_hwnd), _enum_child, None)

        def _priority(cls: str) -> int:
            if "Chrome_RenderWidgetHostHWND" in cls:
                return 0
            if "Intermediate" in cls and "D3D" in cls:
                return 1
            return 2

        fullscreen_candidates.sort(key=lambda x: (_priority(x[1]), -x[2]))
        if fullscreen_candidates:
            fullscreen_child = fullscreen_candidates[0][0]
            fullscreen_child_class = fullscreen_candidates[0][1]
        logger.info(
            "HARD_REST_OVERLAY_CHILDREN parent_hwnd=%s parent_size=%dx%d children=%s fullscreen_child=%s fullscreen_child_class=%s",
            parent_hwnd, parent_w, parent_h,
            "; ".join(children_info[:20]),
            fullscreen_child,
            fullscreen_child_class or "?",
        )

        if fullscreen_child:
            chwnd = int(fullscreen_child)
            try:
                ck = wintypes.COLORREF()
                alpha = wintypes.BYTE()
                flags = wintypes.DWORD()
                u = ctypes.windll.user32
                u.GetLayeredWindowAttributes.argtypes = [
                    wintypes.HWND,
                    ctypes.POINTER(wintypes.COLORREF),
                    ctypes.POINTER(wintypes.BYTE),
                    ctypes.POINTER(wintypes.DWORD),
                ]
                u.GetLayeredWindowAttributes.restype = wintypes.BOOL
                ret = u.GetLayeredWindowAttributes(chwnd, ctypes.byref(ck), ctypes.byref(alpha), ctypes.byref(flags))
                logger.info(
                    "HARD_REST_OVERLAY_FULLSCREEN_CHILD hwnd=%s GetLayeredWindowAttributes_ok=%s color_key=0x%x alpha=%s flags=0x%x",
                    chwnd, bool(ret), ck.value, alpha.value, flags.value,
                )
            except Exception as e:
                logger.warning("HARD_REST_OVERLAY_FULLSCREEN_CHILD GetLayeredWindowAttributes failed hwnd=%s err=%s", chwnd, str(e)[:80])

            try:
                ok = win_enable_acrylic_fn(chwnd, tint_color=0x33101826, blur=True, where="rest_overlay_fullscreen_child")
                logger.info("HARD_REST_OVERLAY_FULLSCREEN_CHILD hwnd=%s acrylic_apply_ok=%s", chwnd, ok)
            except Exception as e:
                logger.warning("HARD_REST_OVERLAY_FULLSCREEN_CHILD acrylic apply failed hwnd=%s err=%s", chwnd, str(e)[:80])
    except Exception as e:
        logger.warning("HARD_REST_OVERLAY_CHILDREN_DUMP failed: %s", str(e)[:100])
