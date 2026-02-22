"""
DPI awareness and console hide functions for bootstrap.
"""
import logging
import os
import sys

log = logging.getLogger(__name__)


def enable_high_dpi_awareness():
    """在创建任何窗口之前调用，4K/高缩放下单窗口尺寸与位置正确。"""
    try:
        import ctypes
        # Per-monitor v2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (ImportError, AttributeError, OSError, ValueError) as e:
        log.debug("DPI API SetProcessDpiAwarenessContext unavailable: %s", e)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return
    except (ImportError, AttributeError, OSError, ValueError) as e:
        log.debug("DPI API SetProcessDpiAwareness unavailable: %s", e)
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except (ImportError, AttributeError, OSError, ValueError) as e:
        log.debug("DPI API SetProcessDPIAware unavailable: %s", e)


def hide_console_if_needed():
    """Windows：仅在使用 --debug 时保留控制台；默认无控制台。"""
    if sys.platform != "win32":
        return
    if "--debug" in sys.argv or os.environ.get("EYECARE_DEBUG_CONSOLE", "0") == "1":
        return
    try:
        import ctypes
        h = ctypes.windll.kernel32.GetConsoleWindow()
        if h:
            ctypes.windll.user32.ShowWindow(h, 0)  # SW_HIDE
    except (ImportError, AttributeError, OSError, ValueError) as e:
        log.debug("hide_console_if_needed skipped: %s", e)
