from __future__ import annotations

import json
import time
import traceback
import tkinter as tk
from pathlib import Path
from typing import Callable

from PIL import Image, ImageTk

from scripts.state.controller import AppController


class FloatingWindow:
    """
    精简发布版浮窗（重写版）：
    - 无 Top 统计
    - iOS-ish 卡片：状态点 + 标题 + 当前应用(icon+name) + 状态/已连续看屏幕
    - 整窗可拖（✅ 右下角大热区 + 明显把手：缩放更好用）
    - hover 透明->不透明
    - 右键菜单与托盘一致文案：正常模式/勿扰模式/视频模式（当前模式打勾）
    - 双击打开主窗口
    """

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

        # hover 透明度
        self._alpha_idle = 0.88
        self._alpha_hover = 1.0
        self.win.attributes("-alpha", self._alpha_idle)

        self._visible = False

        # 拖拽/缩放状态
        self._drag = {"mode": None, "x": 0, "y": 0, "wx": 0, "wy": 0, "w": 0, "h": 0}

        # ✅ 缩放热区变大：更好抓
        self._resize_hot = 36

        # 最小尺寸（给内容留空间）
        self._min_w, self._min_h = 180, 120

        self.var_topmost = tk.BooleanVar(value=True)

        self._last_icon_path = ""
        self._icon_img = None

        # ---------------- UI ----------------
        # 外层：用浅灰做细边框底
        self.outer = tk.Frame(self.win, bg="#d1d5db")  # 更像 iOS 边缘线
        self.outer.pack(fill=tk.BOTH, expand=True)

        # ✅ 边框回到 1
        self.card = tk.Frame(self.outer, bg="#ffffff")
        self.card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.titlebar = tk.Frame(self.card, bg="#f8fafc", height=26)
        self.titlebar.pack(fill=tk.X)

        self.dot = tk.Canvas(self.titlebar, width=16, height=16, bg="#f3f4f6", highlightthickness=0)
        self.dot.pack(side=tk.LEFT, padx=(8, 4), pady=6)

        self.lbl_title = tk.Label(
            self.titlebar, text="EyE Care", bg="#f3f4f6", fg="#111827", font=("Segoe UI", 9, "bold")
        )
        self.lbl_title.pack(side=tk.LEFT, pady=4)

        self.lbl_mode = tk.Label(
            self.titlebar, text="", bg="#f3f4f6", fg="#7c3aed", font=("Segoe UI", 9, "bold")
        )
        self.lbl_mode.pack(side=tk.LEFT, padx=(6, 0), pady=4)

        # 右侧：应用名 + icon
        self.lbl_icon = tk.Label(self.titlebar, bg="#f3f4f6")
        self.lbl_icon.pack(side=tk.RIGHT, padx=(0, 6), pady=4)

        self.lbl_app = tk.Label(self.titlebar, text="", bg="#f3f4f6", fg="#6B7280", font=("Segoe UI", 9))
        self.lbl_app.pack(side=tk.RIGHT, padx=(0, 8), pady=4)

        self.body = tk.Frame(self.card, bg="#ffffff")
        self.body.pack(fill=tk.BOTH, expand=True)

        self.lbl_status = tk.Label(self.body, text="", bg="#ffffff", fg="#111827", font=("Segoe UI", 9))
        self.lbl_status.pack(anchor="w", padx=10, pady=(10, 0))

        # ✅ 字体不要太大，留出呼吸感；需要休息时会变橙色
        self.lbl_work = tk.Label(self.body, text="", bg="#ffffff", fg="#111827", font=("Segoe UI", 9, "bold"))
        self.lbl_work.pack(anchor="w", padx=10, pady=(4, 2))

        self.lbl_hint = tk.Label(self.body, text="", bg="#ffffff", fg="#6B7280", font=("Segoe UI", 9))
        self.lbl_hint.pack(anchor="w", padx=10, pady=(0, 10))

        # ✅ 右下角缩放热区：做大一点，点到这块区域就能拖拽缩放
        self.resize_handle = tk.Label(
            self.card,
            text="◢",
            bg="#ffffff",
            fg="#9CA3AF",
            font=("Segoe UI", 12),
            width=2,   # 视觉上更“占位”，但真正热区由 padding + place 控制
        )
        
        # 用 place 固定在右下角，给足“可点区域”
        self.resize_handle.place(relx=1.0, rely=1.0, anchor="se", x=-2, y=-2, width=32, height=32)

        # ---------------- bindings ----------------
        # 鼠标移动：负责切换 cursor（缩放/普通）
        self.win.bind("<Motion>", self._on_motion)

        # 右键菜单（全窗）
        self.win.bind("<Button-3>", self._right_click)

        # 双击打开主窗口（全窗，缩放热区除外）
        self.win.bind("<Double-Button-1>", self._on_double_click)

        # hover：透明度
        for w in (self.win, self.outer, self.card, self.titlebar, self.body, self.resize_handle):
            w.bind("<Enter>", self._on_enter, add="+")
            w.bind("<Leave>", self._on_leave, add="+")

        # ✅ 整窗可拖（但是缩放热区会优先进入 resize）
        drag_widgets = (
            self.win,
            self.outer,
            self.card,
            self.titlebar,
            self.body,
            self.dot,
            self.lbl_title,
            self.lbl_mode,
            self.lbl_app,
            self.lbl_icon,
            self.lbl_status,
            self.lbl_work,
            self.lbl_hint,
        )
        for w in drag_widgets:
            w.bind("<Button-1>", self._mouse_down, add="+")
            w.bind("<B1-Motion>", self._mouse_move, add="+")
            w.bind("<ButtonRelease-1>", self._mouse_up, add="+")

        # ✅ 把手本身也能缩放（更好用）
        def _force_resize_down(e):
            # 强制进入 resize（不依赖热区判断）
            w = self.win.winfo_width()
            h = self.win.winfo_height()
            self._drag["mode"] = "resize"
            self._drag["x"] = e.x_root
            self._drag["y"] = e.y_root
            self._drag["w"] = w
            self._drag["h"] = h
            return "break"

        self.resize_handle.bind("<Button-1>", _force_resize_down, add="+")
        self.resize_handle.bind("<B1-Motion>", self._mouse_move, add="+")
        self.resize_handle.bind("<ButtonRelease-1>", self._mouse_up, add="+")
        self.resize_handle.bind("<Enter>", lambda _e: self.win.configure(cursor="size_nw_se"), add="+")
        self.resize_handle.bind("<Leave>", lambda _e: self.win.configure(cursor="arrow"), add="+")

        # controller -> UI tick（从后台线程回主线程）
        def _ui_tick():
            self.root.after(0, self._update)

        self.controller.register_ui_listener(_ui_tick)

        self._load_config()
        self._schedule_update()

    # ---------------- debug log ----------------
    def _log(self, tag: str) -> None:
        try:
            p = self.data_dir / "bg_errors.log"
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            with p.open("a", encoding="utf-8") as f:
                f.write(f"\n[{ts}] FloatingWindow::{tag}\n{traceback.format_exc()}\n")
        except Exception:
            pass

    # ---------------- hover alpha ----------------
    def _on_enter(self, _e: tk.Event) -> None:
        if self._visible:
            try:
                self.win.attributes("-alpha", self._alpha_hover)
            except Exception:
                pass

    def _on_leave(self, _e: tk.Event) -> None:
        if self._visible:
            try:
                self.win.attributes("-alpha", self._alpha_idle)
            except Exception:
                pass

    # ---------------- visibility ----------------
    def toggle(self) -> None:
        try:
            if self._visible:
                self.hide()
            else:
                self.show()
        except Exception:
            self._log("toggle")

    def _ensure_onscreen(self) -> None:
        try:
            self.win.update_idletasks()
            sw = self.win.winfo_screenwidth()
            sh = self.win.winfo_screenheight()

            x = self.win.winfo_x()
            y = self.win.winfo_y()
            w = self.win.winfo_width()
            h = self.win.winfo_height()

            if w <= 50 or h <= 50:
                w, h = 180, 120

            if x < -w or x > sw - 50 or y < -h or y > sh - 50:
                x, y = 100, 100

            w = max(int(w), self._min_w)
            h = max(int(h), self._min_h)
            self.win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            self._log("ensure_onscreen")

    def show(self) -> None:
        try:
            if self._visible:
                self.win.deiconify()
                self.win.state("normal")
                self.win.overrideredirect(True)
                self.win.attributes("-topmost", bool(self.var_topmost.get()))
                self.win.attributes("-alpha", self._alpha_idle)
                self._ensure_onscreen()
                self.win.lift()
                self.win.focus_force()
                return

            self._visible = True
            self.win.deiconify()
            self.win.state("normal")
            self.win.overrideredirect(True)
            self.win.attributes("-topmost", bool(self.var_topmost.get()))
            self.win.attributes("-alpha", self._alpha_idle)

            self._ensure_onscreen()
            self.win.lift()
            self.win.focus_force()
            self.win.update_idletasks()
        except Exception:
            self._log("show")

    def hide(self) -> None:
        try:
            if not self._visible:
                return
            self._visible = False
            self.win.withdraw()
            self._save_config()
        except Exception:
            self._log("hide")

    # ---------------- mouse ----------------
    def _in_resize_hot(self, e: tk.Event) -> bool:
        try:
            w = self.win.winfo_width()
            h = self.win.winfo_height()
            return (e.x >= w - self._resize_hot) and (e.y >= h - self._resize_hot)
        except Exception:
            return False

    def _on_motion(self, e: tk.Event) -> None:
        # ✅ 缩放热区：显示缩放光标；其它地方：普通箭头
        try:
            if self._in_resize_hot(e):
                self.win.configure(cursor="size_nw_se")
            else:
                self.win.configure(cursor="arrow")
        except Exception:
            pass

    def _mouse_down(self, e: tk.Event) -> None:
        w = self.win.winfo_width()
        h = self.win.winfo_height()

        # ✅ 右下角 resize 热区优先（包括把手）
        if self._in_resize_hot(e):
            self._drag["mode"] = "resize"
            self._drag["x"] = e.x_root
            self._drag["y"] = e.y_root
            self._drag["w"] = w
            self._drag["h"] = h
            return

        # 其它区域 move（整窗可拖）
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

    def _on_double_click(self, e: tk.Event):
        # 缩放热区双击不处理
        if self._in_resize_hot(e):
            return "break"
        try:
            self.on_show_main()
        except Exception:
            pass
        return "break"

    # ---------------- menu ----------------
    def _right_click(self, e: tk.Event):
        menu = tk.Menu(self.win, tearoff=0)
        menu.add_command(label="打开主界面", command=self.on_show_main)
        menu.add_command(label="马上休息", command=self.on_rest_now)
        menu.add_separator()

        menu.add_checkbutton(label="总是最前", variable=self.var_topmost, command=self._toggle_topmost)
        menu.add_command(label="隐藏浮窗", command=self.hide)
        menu.add_separator()

        # 模式（当前模式打勾）
        st = self.controller.get_ui_status()
        cur = getattr(st, "manual_mode", "") or (
            "WATCHING" if getattr(st, "watching", False) else ("DND" if getattr(st, "dnd", False) else "NORMAL")
        )
        mode_var = tk.StringVar(value=cur)

        menu.add_radiobutton(label="正常模式", variable=mode_var, value="NORMAL", command=self.controller.set_normal)
        menu.add_radiobutton(label="勿扰模式", variable=mode_var, value="DND", command=self.controller.set_dnd)
        menu.add_radiobutton(label="视频模式", variable=mode_var, value="WATCHING", command=self.controller.set_watching)

        menu.add_separator()
        menu.add_command(label="退出", command=self.on_exit)

        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _toggle_topmost(self) -> None:
        self.win.attributes("-topmost", bool(self.var_topmost.get()))
        self._save_config()

    # ---------------- update ----------------
    def _schedule_update(self) -> None:
        self._update()
        self.root.after(1000, self._schedule_update)

    def _update(self) -> None:
        if not self._visible:
            return

        st = self.controller.get_ui_status()

        # app / icon
        self.lbl_app.config(text=getattr(st, "front_app", "") or "")
        self._update_app_icon(getattr(st, "front_app_icon", "") or "")

        mode = getattr(st, "manual_mode", "") or (
            "WATCHING" if getattr(st, "watching", False) else ("DND" if getattr(st, "dnd", False) else "NORMAL")
        )

        if mode == "WATCHING":
            self.lbl_mode.config(text="【视频】", fg="#7c3aed")
        elif mode == "DND":
            self.lbl_mode.config(text="【勿扰】", fg="#ef4444")
        else:
            self.lbl_mode.config(text="", fg="#7c3aed")

        # 状态点颜色：视频/勿扰优先，其次空闲/需要休息/正常
        if mode == "WATCHING":
            dot = "#7c3aed"
        elif mode == "DND":
            dot = "#ef4444"
        elif getattr(st, "run_mode", "") == "IDLE":
            dot = "#2563eb"
        elif getattr(st, "need_break", False):
            dot = "#d97706"
        else:
            dot = "#16a34a"
        self._draw_dot(dot)

        # 文案
        self.lbl_status.config(text=getattr(st, "status_text", "") or "状态：—")

        work_text = getattr(st, "work_text", "") or "已连续看屏幕：—"
        suppressed = (mode in ("DND", "WATCHING"))

        # ✅ 需要休息时：已连续看屏幕这一行变橙色
        if getattr(st, "need_break", False) and (not suppressed) and getattr(st, "run_mode", "") != "IDLE":
            self.lbl_work.config(text=work_text, fg="#d97706")
        else:
            self.lbl_work.config(text=work_text, fg="#111827")

        if getattr(st, "need_break", False) and (not suppressed) and getattr(st, "run_mode", "") != "IDLE":
            self.lbl_hint.config(text="建议休息：右键 → 马上休息", fg="#d97706")
        elif getattr(st, "run_mode", "") == "IDLE" and getattr(st, "rest_done_in_idle", False):
            self.lbl_hint.config(text="本轮已完成休息，返回后开始新一轮", fg="#16a34a")
        else:
            self.lbl_hint.config(text="右键可切换模式 / 休息", fg="#6B7280")

    def _draw_dot(self, color: str) -> None:
        c = self.dot
        c.delete("all")
        c.create_oval(2, 2, 14, 14, fill=color, outline=color)

    def _update_app_icon(self, path: str) -> None:
        if path == self._last_icon_path:
            return
        self._last_icon_path = path or ""
        if not path:
            self._icon_img = None
            self.lbl_icon.configure(image="")
            return
        try:
            img = Image.open(path).convert("RGBA").resize((16, 16), Image.LANCZOS)
            self._icon_img = ImageTk.PhotoImage(img)
            self.lbl_icon.configure(image=self._icon_img)
        except Exception:
            self._icon_img = None
            self.lbl_icon.configure(image="")

    # ---------------- config ----------------
    def _cfg_path(self) -> Path:
        return self.data_dir / "float_ui.json"

    def _load_config(self) -> None:
        try:
            p = self._cfg_path()
            if not p.exists():
                self.win.geometry("180x120+100+100")
                self.show()
                return

            obj = json.loads(p.read_text(encoding="utf-8"))
            x = int(obj.get("x", 100))
            y = int(obj.get("y", 100))
            w = int(obj.get("w", 180))
            h = int(obj.get("h", 120))
            topmost = bool(obj.get("topmost", True))
            visible = bool(obj.get("visible", True))

            self.var_topmost.set(topmost)
            self.win.attributes("-topmost", topmost)

            w = max(w, self._min_w)
            h = max(h, self._min_h)
            self.win.geometry(f"{w}x{h}+{x}+{y}")
            self._ensure_onscreen()

            if visible:
                self.show()
        except Exception:
            self._log("load_config")
            self.win.geometry("180x120+100+100")

    def _save_config(self) -> None:
        try:
            obj = {
                "x": int(self.win.winfo_x()),
                "y": int(self.win.winfo_y()),
                "w": int(self.win.winfo_width()),
                "h": int(self.win.winfo_height()),
                "topmost": bool(self.var_topmost.get()),
                "visible": bool(self._visible),
            }
            self._cfg_path().write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
