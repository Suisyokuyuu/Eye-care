"""
Notify hwnd diagnostics helpers.
"""
from typing import Any, Optional

from eye_care.diagnostics import diag
from eye_care.diagnostics.debug_switch import is_debug_enabled


def diag_notify_hwnd_alpha(logger: Any, hwnd: Optional[int], where: str) -> None:
    """Emit notify hwnd/exstyle/alpha diagnostic in debug mode."""
    if not hwnd or not is_debug_enabled():
        return

    import ctypes
    from ctypes import wintypes

    import win32con
    import win32gui

    h = int(hwnd)
    ex = win32gui.GetWindowLong(h, win32con.GWL_EXSTYLE)
    layered = bool(ex & win32con.WS_EX_LAYERED)
    alpha = None
    if layered:
        user32 = ctypes.WinDLL("user32")
        cr = wintypes.DWORD()
        ba = wintypes.BYTE()
        fl = wintypes.DWORD()
        if user32.GetLayeredWindowAttributes(h, ctypes.byref(cr), ctypes.byref(ba), ctypes.byref(fl)):
            if fl.value & 0x2:  # LWA_ALPHA
                alpha = ba.value

    diag.emit(
        "DIAG_NOTIFY_HWND_ALPHA",
        logger,
        "notify window hwnd/exstyle/alpha",
        where=where,
        hwnd=h,
        exstyle_hex=hex(ex & 0xFFFFFFFF),
        ws_ex_layered=layered,
        alpha=alpha if alpha is not None else "n/a",
    )


def log_notify_ex_style(logger: Any, hwnd: Optional[int], where: str) -> None:
    """Log notify hwnd extended style."""
    if not hwnd:
        return
    try:
        import win32con
        import win32gui

        ex = win32gui.GetWindowLong(int(hwnd), win32con.GWL_EXSTYLE)
        layered = bool(ex & 0x80000)  # WS_EX_LAYERED
        if is_debug_enabled():
            diag.emit(
                "DIAG_NOTIFY_PIPE",
                logger,
                "window exstyle",
                step=where,
                hwnd=hwnd,
                ex_style_hex=hex(ex),
                ws_ex_layered=layered,
            )
    except Exception as e:
        diag.emit("DIAG_NOTIFY_PIPE", logger, "exstyle read failed", step=where, hwnd=hwnd, err=str(e)[:60])


def log_notify_window_class(logger: Any, hwnd: Optional[int], where: str) -> None:
    """Log notify hwnd class name."""
    if not hwnd:
        return
    try:
        import win32gui

        cls = win32gui.GetClassName(int(hwnd)) or ""
        txt = (win32gui.GetWindowText(int(hwnd)) or "")[:60]
        if is_debug_enabled():
            diag.emit(
                "DIAG_NOTIFY_PIPE",
                logger,
                "window class",
                step=where,
                hwnd=hwnd,
                class_name=cls,
                window_text=txt,
            )
    except Exception as e:
        diag.emit("DIAG_NOTIFY_PIPE", logger, "window class read failed", step=where, hwnd=hwnd, err=str(e)[:60])
