from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from datetime import date
from typing import Callable, List, Tuple

from eye_care.state.controller import AppController
from eye_care.state.utils import seconds_to_hhmmss


class FloatingWindow:
    def __init__(
        self,
        root: tk.Tk,
        controller: AppController,
        data_dir: Path,
        on_show_main: Callable[[], None],
        on_rest_now: Callable[[], None],
        on_exit: Callable[[], None],
    ):
        self.root = root
        self.controller = controller
        self.data_dir = Path(data_dir)

        self.on_show_main = on_show_main
        self.on_rest_now = on_rest_now
        self.on_exit = on_exit

        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.90)

        self._visible = False

        self._drag = {"mode": None, "x": 0, "y": 0, "wx": 0, "wy": 0, "w": 0, "h": 0}
        self._resize_hot = 16
        self._min_w, self._min_h = 320, 160

        self.var_topmost = tk.BooleanVar(value=True)
        self.var_show_top = tk.BooleanVar(value=True)

        self.outer = tk.Frame(self.win, bg="#111827")
        self.outer.pack(fill=tk.BOTH, expand=True)

        self.card = tk.Frame(self.outer, bg="#ffffff")
        self.card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.titlebar = tk.Frame(self.card, bg="#f3f4f6", height=28)
        self.titlebar.pack(fill=tk.X)

        self.dot = tk.Canvas(self.titlebar, width=16, height=16, bg="#f3f4f6", highlightthickness=0)
        self.dot.pack(side=tk.LEFT, padx=(8, 4), pady=6)

        self.lbl_title = tk.Label(self.titlebar, text="EyE Care", bg="#f3f4f6", fg="#111827",
                                  font=("Segoe UI", 9, "bold"))
        self.lbl_title.pack(side=tk.LEFT, pady=4)

        self.lbl_mode = tk.Label(self.titlebar, text="", bg="#f3f4f6", fg="#7c3aed",
                                 font=("Segoe UI", 9, "bold"))
        self.lbl_mode.pack(side=tk.LEFT, padx=(6, 0), pady=4)

        self.lbl_app = tk.Label(self.titlebar, text="", bg="#f3f4f6", fg="#6B7280",
                                font=("Segoe UI", 9))
        self.lbl_app.pack(side=tk.RIGHT, padx=(0, 8), pady=4)

        for w in (self.titlebar, self.lbl_title, self.lbl_app, self.dot, self.lbl_mode):
            w.bind("<Button-1>", self._mouse_down)
            w.bind("<B1-Motion>", self._mouse_move)
            w.bind("<ButtonRelease-1>", self._mouse_up)
            w.bind("<Button-3>", self._right_click)

        self.body = tk.Frame(self.card, bg="#ffffff")
        self.body.pack(fill=tk.BOTH, expand=True)

        self.lbl_status = tk.Label(self.body, text="", bg="#ffffff", fg="#111827", font=("Segoe UI", 9))
        self.lbl_status.pack(anchor="w", padx=10, pady=(8, 0))

        self.lbl_work = tk.Label(self.body, text="", bg="#ffffff", fg="#111827", font=("Segoe UI", 10, "bold"))
        self.lbl_work.pack(anchor="w", padx=10, pady=(2, 6))

        self.sep = tk.Frame(self.body, bg="#e5e7eb", height=1)
        self.sep.pack(fill=tk.X, padx=10, pady=(0, 8))

        self.top_block = tk.Frame(self.body, bg="#ffffff")
        self.top_block.pack(fill=tk.BOTH, expand=False)

        self.lbl_top = tk.Label(self.top_block, text="Top 应用（今日）", bg="#ffffff", fg="#111827",
                                font=("Segoe UI", 9, "bold"))
        self.lbl_top.pack(anchor="w", padx=10)

        self.canvas = tk.Canvas(self.top_block, bg="#ffffff", highlightthickness=0, height=130)
        self.canvas.pack(fill=tk.BOTH, expand=False, padx=10, pady=(6, 8))

        self.lbl_hint = tk.Label(self.body, text="", bg="#ffffff", fg="#6B7280", font=("Segoe UI", 9))
        self.lbl_hint.pack(anchor="w", padx=10, pady=(0, 8))

        self.win.bind("<Motion>", self._on_motion)
        self.win.bind("<Button-1>", self._mouse_down)
        self.win.bind("<B1-Motion>", self._mouse_move)
        self.win.bind("<ButtonRelease-1>", self._mouse_up)
        self.win.bind("<Button-3>", self._right_click)

        def _ui_tick():
            self.root.after(0, self._update)

        self.controller.register_ui_listener(_ui_tick)

        self._load_config()
        self._schedule_update()

    def toggle(self) -> None:
        if self._visible:
            self.hide()
        else:
            self.show()

    def show(self) -> None:
        if self._visible:
            return
        self._visible = True
        self.win.deiconify()

    def hide(self) -> None:
        if not self._visible:
            return
        self._visible = False
        self.win.withdraw()
        self._save_config()

    def _on_motion(self, e: tk.Event) -> None:
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        if e.x >= w - self._resize_hot and e.y >= h - self._resize_hot:
            self.win.configure(cursor="size_nw_se")
        else:
            self.win.configure(cursor="arrow")

    def _mouse_down(self, e: tk.Event) -> None:
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        if e.x >= w - self._resize_hot and e.y >= h - self._resize_hot:
            self._drag["mode"] = "resize"
            self._drag["x"] = e.x_root
            self._drag["y"] = e.y_root
            self._drag["w"] = w
            self._drag["h"] = h
            return

        self._drag["mode"] = "move"
        self._drag["x"] = e.x_root
        self._drag["y"] = e.y_root
        self._drag["wx"] = self.win.winfo_x()
        self._drag["wy"] = self.win.winfo_y()

    def _mouse_move(self, e: tk.Event) -> None:
        if self._drag["mode"] == "move":
            dx = e.x_root - self._drag["x"]
            dy = e.y_root - self._drag["y"]
            x = self._drag["wx"] + dx
            y = self._drag["wy"] + dy
            self.win.geometry(f"+{x}+{y}")
        elif self._drag["mode"] == "resize":
            dx = e.x_root - self._drag["x"]
            dy = e.y_root - self._drag["y"]
            nw = max(self._min_w, int(self._drag["w"] + dx))
            nh = max(self._min_h, int(self._drag["h"] + dy))
            self.win.geometry(f"{nw}x{nh}+{self.win.winfo_x()}+{self.win.winfo_y()}")

    def _mouse_up(self, _e: tk.Event) -> None:
        self._drag["mode"] = None
        self._save_config()

    def _right_click(self, e: tk.Event) -> None:
        menu = tk.Menu(self.win, tearoff=0)
        menu.add_command(label="显示主窗口", command=self.on_show_main)
        menu.add_separator()

        menu.add_checkbutton(label="总是最前", variable=self.var_topmost, command=self._toggle_topmost)
        menu.add_checkbutton(label="显示Top应用（今日）", variable=self.var_show_top, command=self._toggle_top_block)

        menu.add_separator()
        menu.add_command(label="勿扰模式（不提醒）", command=self.controller.toggle_dnd)
        menu.add_command(label="观影模式（不提醒）", command=self.controller.toggle_watching)
        menu.add_command(label="马上休息", command=self.on_rest_now)

        menu.add_separator()
        menu.add_command(label="隐藏浮窗", command=self.hide)
        menu.add_command(label="退出", command=self.on_exit)

        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def _toggle_topmost(self) -> None:
        self.win.attributes("-topmost", bool(self.var_topmost.get()))
        self._save_config()

    def _toggle_top_block(self) -> None:
        if self.var_show_top.get():
            self.sep.pack(fill=tk.X, padx=10, pady=(0, 8))
            self.top_block.pack(fill=tk.BOTH, expand=False)
            self._autosize(True)
        else:
            self.top_block.forget()
            self.sep.forget()  # ✅ 不留空白
            self._autosize(False)
        self._save_config()

    def _autosize(self, show_top: bool) -> None:
        w = self.win.winfo_width()
        x = self.win.winfo_x()
        y = self.win.winfo_y()
        target = 280 if show_top else 170
        self.win.geometry(f"{w}x{target}+{x}+{y}")

    def _schedule_update(self) -> None:
        self._update()
        self.root.after(1000, self._schedule_update)

    def _update(self) -> None:
        if not self._visible:
            return

        st = self.controller.get_ui_status()
        self.lbl_app.config(text=st.front_app or "")

        if st.watching:
            self.lbl_mode.config(text="【观影】")
        elif st.dnd:
            self.lbl_mode.config(text="【勿扰】")
        else:
            self.lbl_mode.config(text="")

        if st.run_mode == "IDLE":
            dot = "#2563eb"
        elif st.watching:
            dot = "#7c3aed"
        elif st.dnd:
            dot = "#ef4444"
        elif st.need_break:
            dot = "#d97706"
        else:
            dot = "#16a34a"
        self._draw_dot(dot)

        self.lbl_status.config(text=st.status_text or "状态：—")
        self.lbl_work.config(text=st.work_text or "连续工作：—")

        if self.var_show_top.get():
            top = self.controller.get_metrics_for_range(date.today(), date.today())
            items = sorted(top.items(), key=lambda x: x[1], reverse=True)[:5]
            total = sum(v for _, v in items) or 1
            self._draw_top(items, total)

        if st.need_break and (not st.dnd) and (not st.watching) and st.run_mode != "IDLE":
            self.lbl_hint.config(text="建议休息：右键 → 马上休息", fg="#d97706")
        elif st.run_mode == "IDLE" and st.rest_done_in_idle:
            self.lbl_hint.config(text="本轮已完成休息，返回后开始新一轮", fg="#16a34a")
        else:
            self.lbl_hint.config(text="右键可切换模式 / 休息", fg="#6B7280")

    def _draw_dot(self, color: str) -> None:
        c = self.dot
        c.delete("all")
        c.create_oval(2, 2, 14, 14, fill=color, outline=color)

    def _draw_top(self, items: List[Tuple[str, int]], total: int) -> None:
        c = self.canvas
        c.delete("all")
        w = max(c.winfo_width(), 1)
        if not items:
            c.create_text(0, 0, anchor="nw", text="暂无数据", fill="#6B7280")
            return

        row_h = 28
        top = 6
        bar_left = 90
        bar_right = w - 10
        bar_w = max(bar_right - bar_left, 50)

        bg_bar = "#e5f2eb"
        fg_bar = "#4c9f70"

        for i, (name, sec) in enumerate(items):
            y = top + i * row_h
            pct = sec / (total or 1)
            fill_w = int(bar_w * pct)

            c.create_text(0, y + 12, anchor="w", text=name, fill="#111827", font=("Segoe UI", 9))
            c.create_rectangle(bar_left, y + 5, bar_left + bar_w, y + 21, fill=bg_bar, outline=bg_bar)
            c.create_rectangle(bar_left, y + 5, bar_left + fill_w, y + 21, fill=fg_bar, outline=fg_bar)

            label = seconds_to_hhmmss(sec)
            text_color = "white" if fill_w > 80 else "#111827"
            text_x = bar_left + 8 if fill_w > 80 else (bar_left + fill_w + 6)
            c.create_text(text_x, y + 13, anchor="w", text=label, fill=text_color, font=("Segoe UI", 9, "bold"))

    def _cfg_path(self) -> Path:
        return self.data_dir / "float_ui.json"

    def _load_config(self) -> None:
        try:
            p = self._cfg_path()
            if not p.exists():
                self.win.geometry("360x280+1200+120")
                self.show()
                return

            obj = json.loads(p.read_text(encoding="utf-8"))
            x = int(obj.get("x", 1200))
            y = int(obj.get("y", 120))
            w = int(obj.get("w", 360))
            h = int(obj.get("h", 280))
            topmost = bool(obj.get("topmost", True))
            visible = bool(obj.get("visible", True))
            show_top = bool(obj.get("show_top", True))

            self.var_topmost.set(topmost)
            self.var_show_top.set(show_top)
            self.win.attributes("-topmost", topmost)

            self.win.geometry(f"{w}x{h}+{x}+{y}")
            if show_top:
                self.sep.pack(fill=tk.X, padx=10, pady=(0, 8))
                self.top_block.pack(fill=tk.BOTH, expand=False)
                self._autosize(True)
            else:
                self.top_block.forget()
                self.sep.forget()
                self._autosize(False)

            if visible:
                self.show()
        except Exception:
            self.win.geometry("360x280+1200+120")
            self.show()

    def _save_config(self) -> None:
        try:
            obj = {
                "x": int(self.win.winfo_x()),
                "y": int(self.win.winfo_y()),
                "w": int(self.win.winfo_width()),
                "h": int(self.win.winfo_height()),
                "topmost": bool(self.var_topmost.get()),
                "visible": bool(self._visible),
                "show_top": bool(self.var_show_top.get()),
            }
            self._cfg_path().write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
