from __future__ import annotations

import tkinter as tk


class ToolTip:
    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._enter)
        widget.bind("<Leave>", self._leave)

    def _enter(self, _):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6

        self.tip = tk.Toplevel(self.widget)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)

        frame = tk.Frame(self.tip, bg="#111827", bd=0)
        frame.pack(fill=tk.BOTH, expand=True)

        lbl = tk.Label(frame, text=self.text, bg="#111827", fg="#ffffff",
                       font=("Segoe UI", 9), justify="left", wraplength=360)
        lbl.pack(padx=10, pady=8)

        self.tip.geometry(f"+{x}+{y}")

    def _leave(self, _):
        if self.tip:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None
