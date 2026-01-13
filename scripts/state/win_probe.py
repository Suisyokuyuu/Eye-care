from __future__ import annotations

import os
import sys
import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Tuple

from PIL import Image


# =============================================================
# [State] Windows Probe：纯 ctypes 获取前台进程短名（更稳）
# - 不依赖 pywin32 / psutil，避免“抓不到进程导致永远无数据”
# =============================================================

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    GetForegroundWindow = user32.GetForegroundWindow
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    GetIconInfo = user32.GetIconInfo
    DestroyIcon = user32.DestroyIcon

    OpenProcess = kernel32.OpenProcess
    CloseHandle = kernel32.CloseHandle
    QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW

    ExtractIconExW = shell32.ExtractIconExW

    CreateCompatibleDC = gdi32.CreateCompatibleDC
    DeleteDC = gdi32.DeleteDC
    GetObjectW = gdi32.GetObjectW
    GetDIBits = gdi32.GetDIBits
    SelectObject = gdi32.SelectObject
    DeleteObject = gdi32.DeleteObject

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    class ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL),
            ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HBITMAP),
            ("hbmColor", wintypes.HBITMAP),
        ]

    class BITMAP(ctypes.Structure):
        _fields_ = [
            ("bmType", ctypes.c_long),
            ("bmWidth", ctypes.c_long),
            ("bmHeight", ctypes.c_long),
            ("bmWidthBytes", ctypes.c_long),
            ("bmPlanes", ctypes.c_ushort),
            ("bmBitsPixel", ctypes.c_ushort),
            ("bmBits", ctypes.c_void_p),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [
            ("bmiHeader", BITMAPINFOHEADER),
            ("bmiColors", wintypes.DWORD * 3),
        ]

    BI_RGB = 0


def get_foreground_app_short_name() -> str:
    """返回前台进程短名（不含 .exe），失败返回空字符串。"""
    if sys.platform != "win32":
        return ""

    name, _exe = get_foreground_app_info()
    return name


def get_foreground_app_info() -> Tuple[str, str]:
    """返回 (进程短名, exe 路径)。失败返回空字符串。"""
    if sys.platform != "win32":
        return "", ""

    hwnd = GetForegroundWindow()
    if not hwnd:
        return "", ""

    pid = wintypes.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return "", ""

    hproc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not hproc:
        return "", ""

    try:
        size = 260
        while True:
            buf_len = wintypes.DWORD(size)
            buf = ctypes.create_unicode_buffer(size)
            ok = QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(buf_len))
            if ok:
                exe_path = buf.value
                name = os.path.splitext(os.path.basename(exe_path))[0]
                return name, exe_path
            if ctypes.get_last_error() == 122 and size < 4096:  # ERROR_INSUFFICIENT_BUFFER
                size *= 2
                continue
            return "", ""
    finally:
        CloseHandle(hproc)


def _hicon_to_image(hicon: int) -> Image.Image | None:
    if sys.platform != "win32" or not hicon:
        return None

    iconinfo = ICONINFO()
    if not GetIconInfo(hicon, ctypes.byref(iconinfo)):
        return None

    try:
        hbm = iconinfo.hbmColor or iconinfo.hbmMask
        if not hbm:
            return None

        bmp = BITMAP()
        if not GetObjectW(hbm, ctypes.sizeof(BITMAP), ctypes.byref(bmp)):
            return None

        width = int(bmp.bmWidth)
        height = int(bmp.bmHeight)
        if width <= 0 or height <= 0:
            return None

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        buf_len = width * height * 4
        pixel_buf = (ctypes.c_ubyte * buf_len)()

        hdc = CreateCompatibleDC(0)
        try:
            SelectObject(hdc, hbm)
            if not GetDIBits(hdc, hbm, 0, height, ctypes.byref(pixel_buf), ctypes.byref(bmi), 0):
                return None
        finally:
            DeleteDC(hdc)

        return Image.frombuffer("RGBA", (width, height), bytes(pixel_buf), "raw", "BGRA", 0, 1)
    except Exception:
        return None
    finally:
        if iconinfo.hbmColor:
            DeleteObject(iconinfo.hbmColor)
        if iconinfo.hbmMask:
            DeleteObject(iconinfo.hbmMask)


def extract_app_icon_png(exe_path: str, out_path: Path, size: int = 32) -> bool:
    """从 exe 抽取图标并保存为 PNG。"""
    if sys.platform != "win32":
        return False

    if not exe_path:
        return False

    hicon_large = wintypes.HICON()
    hicon_small = wintypes.HICON()
    count = ExtractIconExW(exe_path, 0, ctypes.byref(hicon_large), ctypes.byref(hicon_small), 1)
    if count <= 0:
        return False

    hicon = hicon_large or hicon_small
    image = None
    try:
        image = _hicon_to_image(hicon)
    finally:
        if hicon_large:
            DestroyIcon(hicon_large)
        if hicon_small:
            DestroyIcon(hicon_small)

    if image is None:
        return False

    try:
        if size and image.size != (size, size):
            image = image.resize((size, size), Image.LANCZOS)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(out_path, format="PNG")
        return True
    except Exception:
        return False
