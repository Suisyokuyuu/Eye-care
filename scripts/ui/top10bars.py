from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Tuple

from scripts.state.utils import seconds_to_hhmmss


# =============================================================
# [UI] Top10Bars：旧版右侧“条状 Top10”（Canvas 绘制）
# =============================================================

class Top10Bars(ttk.Frame):
    def __init__(self, master, title: str = "使用时间概览（Top 10）"):
        super().__init__(master)

        self.title = ttk.Label(self, text=title, font=("Segoe UI", 10, "bold"))
        self.title.pack(anchor="w", padx=8, pady=(8, 4))

        self.canvas = tk.Canvas(self, highlightthickness=0, bg="white")
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self._data: List[Tuple[str, int]] = []
        self._icon_map: Dict[str, str] = {}
        self._icon_cache: Dict[str, tk.PhotoImage] = {}
        self.canvas.bind("<Configure>", lambda _e: self._redraw())

    def update_data(self, app_seconds: Dict[str, int], icon_map: Dict[str, str] | None = None) -> None:
        items = sorted(app_seconds.items(), key=lambda x: x[1], reverse=True)[:10]
        self._data = [(k, int(v)) for k, v in items]
        self._icon_map = dict(icon_map or {})
        self._redraw()

    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")

        w = max(c.winfo_width(), 1)
        h = max(c.winfo_height(), 1)

        if not self._data:
            c.create_text(10, 10, anchor="nw", text="暂无数据", fill="#777777")
            return

        total = sum(v for _, v in self._data) or 1

        row_h = 34
        top = 8
        left = 8
        bar_left = 58
        bar_right = w - 16
        bar_w = max(bar_right - bar_left, 50)

        bar_color = "#4aa46c"
        faint = "#e5e7eb"

        for i, (name, sec) in enumerate(self._data):
            y = top + i * row_h
            if y + row_h > h:
                break

            pct = sec / total
            fill_w = int(bar_w * pct)

            icon = self._load_icon(name)
            if icon:
                c.create_image(left + 12, y + 17, image=icon)
            else:
                c.create_rectangle(left, y + 9, left + 24, y + 25, fill="#cfe8d8", outline="#9fcdb0")
            c.create_rectangle(bar_left, y + 9, bar_left + bar_w, y + 25, fill=faint, outline=faint)
            c.create_rectangle(bar_left, y + 9, bar_left + fill_w, y + 25, fill=bar_color, outline=bar_color)

            label = f"{name}  {seconds_to_hhmmss(sec)}"
            c.create_text(bar_left + 8, y + 17, anchor="w", text=label, fill="white")

    def _load_icon(self, name: str) -> tk.PhotoImage | None:
        path = self._icon_map.get(name)
        if not path:
            return None
        cached = self._icon_cache.get(path)
        if cached:
            return cached
        try:
            img = tk.PhotoImage(file=path)
        except Exception:
            return None
        self._icon_cache[path] = img
        return img
