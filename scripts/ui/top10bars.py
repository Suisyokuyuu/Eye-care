from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Tuple, Optional

from PIL import Image, ImageTk

from scripts.state.utils import seconds_to_hhmmss


# =============================================================
# [UI] Top10Bars：右侧“条状 Top10”（Canvas 绘制 + 图标）
# - icon_map: app_short_name -> icon_png_path
# - 仅在按应用短名时传 icon_map；类别模式可以不传
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

        # Tk 图片引用：必须保活
        self._tk_keep: List[ImageTk.PhotoImage] = []
        self._icon_cache: Dict[str, ImageTk.PhotoImage] = {}

        self.canvas.bind("<Configure>", lambda _e: self._redraw())

    def update_data(self, app_seconds: Dict[str, int], icon_map: Optional[Dict[str, str]] = None) -> None:
        items = sorted(app_seconds.items(), key=lambda x: x[1], reverse=True)[:10]
        self._data = [(k, int(v)) for k, v in items]
        self._icon_map = icon_map or {}
        self._redraw()

    def _get_icon(self, path: str, size: int = 18) -> Optional[ImageTk.PhotoImage]:
        if not path:
            return None
        if not os.path.exists(path):
            return None

        key = f"{path}|{size}"
        hit = self._icon_cache.get(key)
        if hit:
            return hit

        try:
            img = Image.open(path).convert("RGBA")
            img = img.resize((size, size), Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(img)
            self._icon_cache[key] = tk_img
            return tk_img
        except Exception:
            return None

    @staticmethod
    def _ellipsize(text: str, max_chars: int = 16) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1] + "…"

    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        self._tk_keep.clear()

        w = max(c.winfo_width(), 1)
        h = max(c.winfo_height(), 1)

        if not self._data:
            c.create_text(10, 10, anchor="nw", text="暂无数据", fill="#777777")
            return

        total = sum(v for _, v in self._data) or 1

        row_h = 34
        top = 8

        # 左侧：图标+名称区域
        icon_x = 10
        name_x = 34
        name_area_w = 160
        bar_left = name_x + name_area_w
        bar_right = w - 16
        bar_w = max(bar_right - bar_left, 50)

        bar_color = "#4C9F70"
        faint = "#E5F2EB"
        name_color = "#111827"
        muted = "#6B7280"

        for i, (name, sec) in enumerate(self._data):
            y = top + i * row_h
            if y + row_h > h:
                break

            pct = sec / total
            fill_w = int(bar_w * pct)

            # icon
            icon_path = self._icon_map.get(name, "")
            tk_icon = self._get_icon(icon_path, size=18)
            if tk_icon:
                c.create_image(icon_x, y + 17, image=tk_icon, anchor="w")
                self._tk_keep.append(tk_icon)
            else:
                # placeholder
                c.create_rectangle(icon_x, y + 8, icon_x + 18, y + 26, fill="#cfe8d8", outline="#9fcdb0")

            # name
            show_name = self._ellipsize(name, max_chars=18)
            c.create_text(name_x, y + 17, anchor="w", text=show_name, fill=name_color, font=("Segoe UI", 9))

            # bar
            c.create_rectangle(bar_left, y + 9, bar_left + bar_w, y + 25, fill=faint, outline=faint)
            c.create_rectangle(bar_left, y + 9, bar_left + fill_w, y + 25, fill=bar_color, outline=bar_color)

            # time label（短条显示在条外）
            t = seconds_to_hhmmss(sec)
            if fill_w >= 70:
                c.create_text(bar_left + fill_w - 6, y + 17, anchor="e",
                              text=t, fill="white", font=("Segoe UI", 9, "bold"))
            else:
                c.create_text(bar_left + fill_w + 6, y + 17, anchor="w",
                              text=t, fill=muted, font=("Segoe UI", 9, "bold"))
