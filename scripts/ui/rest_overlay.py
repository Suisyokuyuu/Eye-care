from __future__ import annotations

import ctypes
import tkinter as tk
from typing import Callable, List, Tuple

from scripts.state.utils import seconds_to_mmss


def _enum_monitors() -> List[Tuple[int, int, int, int]]:
    user32 = ctypes.windll.user32

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_long * 4),
        ctypes.c_double,
    )

    rects: List[Tuple[int, int, int, int]] = []

    def _cb(hmon, hdc, lprc, _data):
        r = lprc.contents
        left, top, right, bottom = r[0], r[1], r[2], r[3]
        rects.append((left, top, right - left, bottom - top))
        return 1

    user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_cb), 0)
    if not rects:
        # fallback：单屏
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        rects = [(0, 0, sw, sh)]
    return rects


class RestOverlay:
    """
    多屏遮罩 + 圆环倒计时
    - 倒计时结束 => on_complete()
    - ESC => on_skip()

    倒计时显示：X分X秒；小于1分钟显示X秒
    """

    def __init__(self, root: tk.Tk, seconds: int, on_skip: Callable[[], None], on_complete: Callable[[], None]):
        self.root = root
        self.total = max(1, int(seconds))
        self.remaining = max(0, int(seconds))
        self.on_skip = on_skip
        self.on_complete = on_complete

        self.wins: List[tk.Toplevel] = []
        self.canvases: List[tk.Canvas] = []
        self.text_ids: List[int] = []
        self.arc_ids: List[int] = []

        self._build()
        self._tick()

    def _build(self) -> None:
        for (x, y, w, h) in _enum_monitors():
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="#000000")
            win.attributes("-alpha", 0.55)
            win.geometry(f"{w}x{h}+{x}+{y}")

            # 只在第一个窗口 grab，避免 Tk 多窗口 grab 冲突
            if not self.wins:
                win.grab_set()
                win.focus_set()
                win.bind("<Escape>", self._skip)

            c = tk.Canvas(win, bg="#000000", highlightthickness=0)
            c.pack(fill=tk.BOTH, expand=True)

            # 圆环参数
            cx, cy = w // 2, h // 2
            r = max(90, min(w, h) // 6)

            # 圆环底色
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#374151", width=14)

            # 进度弧（从 90° 开始，逆时针填充）
            arc = c.create_arc(
                cx - r,
                cy - r,
                cx + r,
                cy + r,
                start=90,
                extent=0,
                style="arc",
                outline="#ffffff",
                width=14,
            )

            # 文字（✅ 用 mm:ss 风格的中文）
            txt = c.create_text(
                cx,
                cy,
                text=seconds_to_mmss(self.remaining),
                fill="#ffffff",
                font=("Segoe UI", 48, "bold"),
            )
            c.create_text(
                cx,
                cy + r + 40,
                text="休息中 · 按 ESC 可跳过本轮休息",
                fill="#e5e7eb",
                font=("Segoe UI", 12),
            )

            self.wins.append(win)
            self.canvases.append(c)
            self.arc_ids.append(arc)
            self.text_ids.append(txt)

    def _update_visuals(self) -> None:
        # remaining 从 total -> 0：ratio 从 0 -> 1
        ratio = max(0.0, min(1.0, 1.0 - (self.remaining / self.total)))
        extent = -360.0 * ratio  # 逆时针更像表盘
        text = seconds_to_mmss(self.remaining)

        for c, arc, txt in zip(self.canvases, self.arc_ids, self.text_ids):
            c.itemconfig(arc, extent=extent)
            c.itemconfig(txt, text=text)

    def _tick(self) -> None:
        self._update_visuals()

        if self.remaining <= 0:
            self._complete()
            return

        self.remaining -= 1
        # 只用第一个窗口的 after 调度，避免多窗口同时 tick
        self.wins[0].after(1000, self._tick)

    def _destroy_all(self) -> None:
        try:
            if self.wins:
                try:
                    self.wins[0].grab_release()
                except Exception:
                    pass
        except Exception:
            pass

        for w in self.wins:
            try:
                w.destroy()
            except Exception:
                pass

    def _complete(self) -> None:
        self._destroy_all()
        try:
            self.on_complete()
        except Exception:
            pass

    def _skip(self, _=None) -> None:
        self._destroy_all()
        try:
            self.on_skip()
        except Exception:
            pass
