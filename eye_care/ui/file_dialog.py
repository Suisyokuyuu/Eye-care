"""文件保存/打开对话框（tkinter 实现）。

原 pywebview 的 create_file_dialog 在 Windows 上有 bug，统一用 tkinter.filedialog。
从已退役的 window_api.py 抽出，供导入/导出复用。
"""
from __future__ import annotations

from typing import Optional


def _convert_file_types(file_types: tuple) -> tuple:
    """将 "Description (*.ext)" 格式转换为 tkinter 的 (描述, *.ext) 元组。"""
    import re
    result = []
    for ft in file_types:
        match = re.match(r'^(.+?)\s*\((\*\.\w+)\)$', ft.strip())
        if match:
            desc, ext = match.groups()
            result.append((desc, ext))
        else:
            ext_match = re.search(r'(\*\.\w+)', ft)
            if ext_match:
                result.append((ft, ext_match.group(1)))
            else:
                result.append((ft, "*.*"))
    return tuple(result)


def _create_file_dialog_safe(dialog_type: str, **kwargs) -> Optional[str | list[str]]:
    """tkinter.filedialog 保存/打开对话框。返回路径（或多选列表），取消返回 None。"""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    try:
        if dialog_type == "save":
            save_filename = kwargs.get("save_filename", "")
            file_types = kwargs.get("file_types", ("All files (*.*)",))
            ft_tuple = _convert_file_types(file_types)
            path = filedialog.asksaveasfilename(
                initialfile=save_filename,
                filetypes=ft_tuple,
                title=kwargs.get("title", "Save File"),
            )
            return path if path else None
        elif dialog_type == "open":
            allow_multiple = kwargs.get("allow_multiple", False)
            file_types = kwargs.get("file_types", ("All files (*.*)",))
            ft_tuple = _convert_file_types(file_types)
            if allow_multiple:
                paths = filedialog.askopenfilenames(
                    filetypes=ft_tuple,
                    title=kwargs.get("title", "Open File"),
                )
                return list(paths) if paths else None
            path = filedialog.askopenfilename(
                filetypes=ft_tuple,
                title=kwargs.get("title", "Open File"),
            )
            return path if path else None
        return None
    finally:
        root.destroy()
