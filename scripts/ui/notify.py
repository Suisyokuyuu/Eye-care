from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

_NOTIFY_ROOT: tk.Tk | None = None

# 旧的短气泡
_ACTIVE_TOAST: tk.Toplevel | None = None

# 新的常驻提醒窗
_ACTIVE_NOTICE: tk.Toplevel | None = None
_NOTICE_TITLE: tk.Label | None = None
_NOTICE_MSG: tk.Label | None = None
_NOTICE_HINT: tk.Label | None = None
_NOTICE_ON_REST: Optional[Callable[[], None]] = None
_NOTICE_ON_SKIP: Optional[Callable[[], None]] = None


def set_notify_root(root: tk.Tk) -> None:
    """兼容旧版 main.py：注入 Tk root。"""
    global _NOTIFY_ROOT
    _NOTIFY_ROOT = root


# ---------------- 短气泡（保留） ----------------

def _safe_show_toast(root: tk.Tk, title: str, message: str) -> None:
    global _ACTIVE_TOAST
    try:
        if not root.winfo_exists():
            return
    except Exception:
        return

    if _ACTIVE_TOAST is not None:
        try:
            if _ACTIVE_TOAST.winfo_exists():
                _ACTIVE_TOAST.destroy()
        except Exception:
            pass
        _ACTIVE_TOAST = None

    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.attributes("-alpha", 0.95)

    w, h = 340, 115
    try:
        x = win.winfo_screenwidth() - w - 24
        y = win.winfo_screenheight() - h - 80
    except Exception:
        x, y = 200, 200
    win.geometry(f"{w}x{h}+{x}+{y}")

    frame = tk.Frame(win, bg="#ffffff", bd=1, relief="solid")
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        frame,
        text=title,
        bg="#ffffff",
        fg="#111827",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w", padx=12, pady=(10, 4))

    tk.Label(
        frame,
        text=message,
        bg="#ffffff",
        fg="#374151",
        font=("Segoe UI", 9),
        wraplength=w - 24,
        justify="left",
    ).pack(anchor="w", padx=12)

    _ACTIVE_TOAST = win

    def _close():
        global _ACTIVE_TOAST
        try:
            if win.winfo_exists():
                win.destroy()
        except Exception:
            pass
        if _ACTIVE_TOAST is win:
            _ACTIVE_TOAST = None

    win.after(3500, _close)


def show_toast(root: tk.Tk, title: str, message: str) -> None:
    """给一般信息用：短气泡，3.5 秒自动消失。"""
    _safe_show_toast(root, title, message)


# ---------------- 常驻提醒窗（新增） ----------------

def _safe_close_notice() -> None:
    global _ACTIVE_NOTICE, _NOTICE_TITLE, _NOTICE_MSG, _NOTICE_HINT
    global _NOTICE_ON_REST, _NOTICE_ON_SKIP

    if _ACTIVE_NOTICE is not None:
        try:
            if _ACTIVE_NOTICE.winfo_exists():
                _ACTIVE_NOTICE.destroy()
        except Exception:
            pass

    _ACTIVE_NOTICE = None
    _NOTICE_TITLE = None
    _NOTICE_MSG = None
    _NOTICE_HINT = None
    _NOTICE_ON_REST = None
    _NOTICE_ON_SKIP = None


def close_break_notice() -> None:
    """关闭常驻提醒窗，并切换为勿扰模式。"""
    try:
        from scripts.state.controller import get_controller
        controller = get_controller()
        controller.set_run_mode("DND")
    except Exception:
        # 防御：就算失败，也至少把窗关掉
        pass

    _safe_close_notice()

def _popup_notice_menu(win: tk.Toplevel, x: int, y: int, on_close=None) -> None:
    menu = tk.Menu(win, tearoff=0)
    menu.add_command(label="马上休息", command=_notice_rest)
    menu.add_command(label="跳过本轮", command=_notice_skip)
    menu.add_separator()

    def _close_and_dnd():
        try:
            if callable(on_close):
                on_close()
        except Exception:
            pass
        close_break_notice()

    menu.add_command(label="进入勿扰模式", command=_close_and_dnd)

    try:
        menu.tk_popup(x, y)
    finally:
        menu.grab_release()

def _notice_rest() -> None:
    """马上休息：先关气泡，再执行回调（避免UI卡顿导致延迟消失）"""
    global _NOTICE_ON_REST, _ACTIVE_NOTICE
    cb = _NOTICE_ON_REST

    # ✅ 先立刻关闭气泡窗
    try:
        close_break_notice()
    except Exception:
        pass

    if not cb:
        return

    # ✅ 回调放到下一帧执行
    try:
        win = _ACTIVE_NOTICE
        if win:
            win.after(0, cb)
        else:
            cb()
    except Exception:
        try:
            cb()
        except Exception:
            pass

def _notice_skip() -> None:
    """跳过本轮：先关气泡，再执行回调（避免UI卡顿导致延迟消失）"""
    global _NOTICE_ON_SKIP, _ACTIVE_NOTICE
    cb = _NOTICE_ON_SKIP

    # ✅ 先立刻关闭气泡窗
    try:
        close_break_notice()
    except Exception:
        pass

    if not cb:
        return

    # ✅ 回调放到下一帧执行
    try:
        win = _ACTIVE_NOTICE
        if win:
            win.after(0, cb)
        else:
            cb()
    except Exception:
        try:
            cb()
        except Exception:
            pass

def show_break_notice(
    root: tk.Tk,
    title: str,
    message: str,
    on_rest: Callable[[], None],
    on_skip: Callable[[], None],
    on_close: Optional[Callable[[], None]] = None,
) -> None:
    
    """护眼提醒：常驻，直到用户右键选择/状态解除。必须在主线程调用。"""
    global _ACTIVE_NOTICE, _NOTICE_TITLE, _NOTICE_MSG, _NOTICE_HINT
    global _NOTICE_ON_REST, _NOTICE_ON_SKIP

    try:
        if not root.winfo_exists():
            return
    except Exception:
        return

    # 更新回调
    _NOTICE_ON_REST = on_rest
    _NOTICE_ON_SKIP = on_skip

    # 已存在：只更新文本并置顶
    if _ACTIVE_NOTICE is not None:
        try:
            if _ACTIVE_NOTICE.winfo_exists():
                if _NOTICE_TITLE:
                    _NOTICE_TITLE.config(text=title)
                if _NOTICE_MSG:
                    _NOTICE_MSG.config(text=message)
                _ACTIVE_NOTICE.lift()
                _ACTIVE_NOTICE.attributes("-topmost", True)
                return
        except Exception:
            _safe_close_notice()

    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.attributes("-alpha", 0.96)

    w, h = 360, 135
    try:
        x = win.winfo_screenwidth() - w - 24
        y = win.winfo_screenheight() - h - 100
    except Exception:
        x, y = 200, 200
    win.geometry(f"{w}x{h}+{x}+{y}")

    frame = tk.Frame(win, bg="#ffffff", bd=1, relief="solid")
    frame.pack(fill=tk.BOTH, expand=True)

    _NOTICE_TITLE = tk.Label(
        frame,
        text=title,
        bg="#ffffff",
        fg="#111827",
        font=("Segoe UI", 10, "bold"),
    )
    _NOTICE_TITLE.pack(anchor="w", padx=12, pady=(10, 4))

    _NOTICE_MSG = tk.Label(
        frame,
        text=message,
        bg="#ffffff",
        fg="#374151",
        font=("Segoe UI", 9),
        wraplength=w - 24,
        justify="left",
    )
    _NOTICE_MSG.pack(anchor="w", padx=12)

    _NOTICE_HINT = tk.Label(
        frame,
        text="右键：马上休息 / 跳过本轮 / 进入勿扰模式",
        bg="#ffffff",
        fg="#d97706",
        font=("Segoe UI", 9, "bold"),
    )
    _NOTICE_HINT.pack(anchor="w", padx=12, pady=(8, 10))

    # 右键菜单（✅ 只绑定一次，避免重复弹）
    def _on_rclick(e):
        _popup_notice_menu(win, e.x_root, e.y_root, on_close=on_close)
        return "break"

    win.bind("<Button-3>", _on_rclick)

    # 点一下也能置顶（不关闭）
    win.bind("<Button-1>", lambda _e: win.lift())

    _ACTIVE_NOTICE = win

# 兼容旧版 main.py：从后台线程调用也安全
def notify_need_break(title: str, message: str) -> None:
    root = _NOTIFY_ROOT
    if not root:
        return

    def _go():
        # 没有回调时，退化成短气泡
        try:
            show_toast(root, title, message)
        except Exception:
            pass

    try:
        root.after(0, _go)
    except Exception:
        pass
