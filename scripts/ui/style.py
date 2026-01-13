from __future__ import annotations

import tkinter as tk
from tkinter import ttk


# =============================================================
# [UI] 旧版清爽风：尽量贴近 Windows 原生（不扎眼）
# =============================================================

def apply_legacy_clean_style(root: tk.Tk) -> None:
    style = ttk.Style()

    # Windows：vista 最接近“新一点的系统控件”
    try:
        if root.tk.call("tk", "windowingsystem") == "win32":
            style.theme_use("vista")
        else:
            style.theme_use("clam")
    except Exception:
        pass

    # 只做“轻量统一”，不做高饱和配色
    style.configure(".", font=("Segoe UI", 10))
    style.configure("Treeview", rowheight=24)
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
