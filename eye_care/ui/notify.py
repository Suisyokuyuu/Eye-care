from __future__ import annotations

import tkinter as tk

_NOTIFY_ROOT: tk.Tk | None = None


def set_notify_root(root: tk.Tk) -> None:
    """兼容旧版 main.py：注入 Tk root。"""
    global _NOTIFY_ROOT
    _NOTIFY_ROOT = root


def _safe_show_toast(root: tk.Tk, title: str, message: str) -> None:
    # root 已销毁/正在退出时直接放弃，避免 TclError 闪退
    try:
        if not root.winfo_exists():
            return
    except Exception:
        return

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

    win.after(3500, lambda: (win.winfo_exists() and win.destroy()))


def show_toast(root: tk.Tk, title: str, message: str) -> None:
    """给新版 main_window 用：必须在主线程触发。"""
    _safe_show_toast(root, title, message)


def notify_need_break(title: str, message: str) -> None:
    """
    兼容旧版 main.py：使用已注入的 root 弹气泡。
    可以从后台线程调用，会通过 root.after 切回主线程。
    """
    root = _NOTIFY_ROOT
    if not root:
        return
    try:
        root.after(0, lambda: _safe_show_toast(root, title, message))
    except Exception:
        pass
