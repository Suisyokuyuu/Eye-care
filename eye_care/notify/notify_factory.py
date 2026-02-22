"""
Notify window geometry calculation functions.
"""
import ctypes
from typing import Tuple


def calculate_notify_geometry() -> Tuple[int, int, float]:
    """Calculate notify window geometry based on screen DPI."""
    user32 = ctypes.windll.user32
    w, h = 400, 160
    scale = 1.0
    try:
        dpi = user32.GetDpiForSystem()
        scale = float(dpi) / 96.0 if dpi else 1.0
    except Exception:
        scale = 1.0
    w = int(w * scale)
    h = int(h * scale)
    return w, h, scale


def calculate_notify_init_position() -> Tuple[int, int]:
    """Calculate initial notify window position (off-screen by default)."""
    user32 = ctypes.windll.user32
    try:
        vx = user32.GetSystemMetrics(76)
        vy = user32.GetSystemMetrics(77)
        vw = user32.GetSystemMetrics(78)
        vh = user32.GetSystemMetrics(79)
        x_init = int(vx + vw + 200)
        y_init = int(vy + vh + 200)
    except Exception:
        x_init, y_init = -2000, -2000
    return x_init, y_init
