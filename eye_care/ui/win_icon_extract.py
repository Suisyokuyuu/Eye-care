
# -*- coding: utf-8 -*-
"""
Windows icon extraction helpers.

Goal: get higher-resolution app icons (ExtraLarge/Jumbo) from Windows Shell
to improve UI clarity. Falls back gracefully.

This module returns PNG files on disk (used by IconCache). It does NOT store
any exe paths; the caller decides cache keys.

Implementation notes:
- Prefer system image list (SHGetImageList) with SHIL_JUMBO/EXTRALARGE.
- Convert HICON -> PIL Image via DrawIconEx onto a 32bpp DIBSection
  (more robust than GetIconInfo/GetObjectW paths on some Python/Win builds).
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from pathlib import Path

from eye_care.diagnostics.diag_events import log_exception_summary

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore

log = logging.getLogger(__name__)


# ---------- helpers: types ----------
if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_uint64
else:
    ULONG_PTR = ctypes.c_uint32

HRESULT = ctypes.c_long
HICON = wintypes.HANDLE  # HICON is HANDLE
HBITMAP = wintypes.HANDLE
HDC = wintypes.HDC
BOOL = wintypes.BOOL
UINT = wintypes.UINT
DWORD = wintypes.DWORD
INT = ctypes.c_int
LONG = ctypes.c_long


class SHFILEINFO(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


# BITMAPINFOHEADER / BITMAPINFO for DIBSection
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", DWORD),
        ("biWidth", LONG),
        ("biHeight", LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", DWORD),
        ("biSizeImage", DWORD),
        ("biXPelsPerMeter", LONG),
        ("biYPelsPerMeter", LONG),
        ("biClrUsed", DWORD),
        ("biClrImportant", DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [("rgbBlue", wintypes.BYTE), ("rgbGreen", wintypes.BYTE), ("rgbRed", wintypes.BYTE), ("rgbReserved", wintypes.BYTE)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]


# ---------- constants ----------
# SHGetFileInfo flags
SHGFI_ICON = 0x000000100
SHGFI_SYSICONINDEX = 0x000004000
SHGFI_USEFILEATTRIBUTES = 0x000000010
SHGFI_LARGEICON = 0x000000000  # 32x32
SHGFI_SMALLICON = 0x000000001  # 16x16

FILE_ATTRIBUTE_NORMAL = 0x00000080

# Shell image list sizes
SHIL_LARGE = 0
SHIL_SMALL = 1
SHIL_EXTRALARGE = 2
SHIL_SYSSMALL = 3
SHIL_JUMBO = 4

# IImageList.GetIcon flags
ILD_TRANSPARENT = 0x00000001

# GDI constants
BI_RGB = 0
DIB_RGB_COLORS = 0

DI_NORMAL = 0x0003  # DI_IMAGE | DI_MASK
SRCCOPY = 0x00CC0020


# ---------- COM interface for IImageList ----------
class GUID(ctypes.Structure):
    _fields_ = [("Data1", DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]

    @staticmethod
    def from_str(s: str) -> "GUID":
        # expects "{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}"
        import uuid
        u = uuid.UUID(s)
        data = u.bytes_le
        g = GUID()
        ctypes.memmove(ctypes.byref(g), data, 16)
        return g


IID_IImageList = GUID.from_str("{46EB5926-582E-4017-9FDF-E8998DAA0950}")


class IImageList(ctypes.Structure):
    pass


# vtbl: we only need GetIcon (index 6 in IImageList vtbl)
GetIconProto = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, INT, UINT, ctypes.POINTER(HICON))


class IImageListVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", ctypes.c_void_p),
        ("AddRef", ctypes.c_void_p),
        ("Release", ctypes.c_void_p),
        ("Add", ctypes.c_void_p),
        ("ReplaceIcon", ctypes.c_void_p),
        ("SetOverlayImage", ctypes.c_void_p),
        ("Replace", ctypes.c_void_p),
        ("AddMasked", ctypes.c_void_p),
        ("Draw", ctypes.c_void_p),
        ("Remove", ctypes.c_void_p),
        ("GetIcon", GetIconProto),  # NOTE: actual position differs in some docs; we will resolve dynamically below
    ]


# We cannot rely on the vtbl layout above across all systems; safer: fetch function pointer by index.
def _iml_geticon(iml_ptr, index: int, flags: int) -> int:
    # vtbl is first pointer
    vtbl = ctypes.cast(iml_ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    vtbl_arr = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))
    # According to common IImageList layout, GetIcon is vtbl index 6 (0-based after IUnknown: QueryInterface/AddRef/Release -> 3, then methods)
    # In practice, GetIcon index is 6 (IUnknown 0-2, Add=3, ReplaceIcon=4, SetOverlayImage=5, Replace=6, AddMasked=7, Draw=8, Remove=9, GetIcon=10) for newer layouts.
    # We'll try a couple of known indices.
    candidates = [10, 6, 11]
    last_err = None
    for vi in candidates:
        fn = vtbl_arr[vi]
        if not fn:
            continue
        func = GetIconProto(fn)
        hicon = HICON(0)
        hr = func(iml_ptr, index, flags, ctypes.byref(hicon))
        if hr >= 0 and int(ctypes.cast(hicon, ctypes.c_void_p).value or 0) != 0:
            return int(ctypes.cast(hicon, ctypes.c_void_p).value)
        last_err = hr
    raise OSError(f"IImageList.GetIcon failed hr={last_err}")


# ---------- winapi setup ----------
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_ole32 = ctypes.WinDLL("ole32", use_last_error=True)

_setup_done = False


def _setup_winapi():
    global _setup_done
    if _setup_done:
        return

    # SHGetFileInfoW
    _shell32.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, DWORD, ctypes.POINTER(SHFILEINFO), UINT, UINT]
    _shell32.SHGetFileInfoW.restype = ULONG_PTR

    # SHGetImageList (HRESULT)
    try:
        _shell32.SHGetImageList.argtypes = [INT, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        _shell32.SHGetImageList.restype = HRESULT
    except Exception as e:
        log_exception_summary(log, "DIAG_EXCEPTION", "win icon fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_WIN_ICON_FALLBACK")

    # user32 / gdi32 used by DIBSection path
    _user32.DestroyIcon.argtypes = [wintypes.HICON]
    _user32.DestroyIcon.restype = BOOL

    _user32.DrawIconEx.argtypes = [HDC, INT, INT, wintypes.HICON, INT, INT, UINT, wintypes.HBRUSH, UINT]
    _user32.DrawIconEx.restype = BOOL

    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = HDC

    _user32.ReleaseDC.argtypes = [wintypes.HWND, HDC]
    _user32.ReleaseDC.restype = INT

    _gdi32.CreateCompatibleDC.argtypes = [HDC]
    _gdi32.CreateCompatibleDC.restype = HDC

    _gdi32.DeleteDC.argtypes = [HDC]
    _gdi32.DeleteDC.restype = BOOL

    _gdi32.CreateDIBSection.argtypes = [HDC, ctypes.POINTER(BITMAPINFO), UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, DWORD]
    _gdi32.CreateDIBSection.restype = HBITMAP

    _gdi32.SelectObject.argtypes = [HDC, wintypes.HGDIOBJ]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ

    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteObject.restype = BOOL

    _setup_done = True


def _get_sys_icon_index(path: str) -> int:
    """Return the system image list index for the given file.

    IMPORTANT:
    - If the file exists, do NOT use SHGFI_USEFILEATTRIBUTES. Otherwise Windows may
      return the generic file-type icon (e.g. for .exe) instead of the embedded
      application icon. This is exactly what caused Notepad4 to show a generic
      document icon.
    - If the file does not exist, fall back to USEFILEATTRIBUTES with
      FILE_ATTRIBUTE_NORMAL.
    """
    shfi = SHFILEINFO()

    # Prefer real file lookup when possible.
    try:
        exists = Path(path).exists()
    except Exception:
        exists = False

    if exists:
        flags = SHGFI_SYSICONINDEX
        ret = _shell32.SHGetFileInfoW(path, 0, ctypes.byref(shfi), ctypes.sizeof(shfi), flags)
    else:
        flags = SHGFI_SYSICONINDEX | SHGFI_USEFILEATTRIBUTES
        ret = _shell32.SHGetFileInfoW(path, FILE_ATTRIBUTE_NORMAL, ctypes.byref(shfi), ctypes.sizeof(shfi), flags)

    if ret == 0:
        raise OSError(f"SHGetFileInfoW failed err={ctypes.get_last_error()}")
    return int(shfi.iIcon)



def _get_imagelist(which: int) -> ctypes.c_void_p:
    # call shell32.SHGetImageList(which, IID_IImageList, &ppv)
    ppv = ctypes.c_void_p()
    try:
        hr = _shell32.SHGetImageList(which, ctypes.byref(IID_IImageList), ctypes.byref(ppv))
    except AttributeError as e:
        raise OSError("SHGetImageList not available") from e
    if hr < 0 or not ppv.value:
        raise OSError(f"SHGetImageList failed hr={hr} err={ctypes.get_last_error()}")
    return ppv


def _hicon_to_pil(hicon_int: int, size: int) -> "Image.Image":
    if Image is None:
        raise RuntimeError("Pillow not installed; cannot convert icon to PNG")

    _setup_winapi()

    hicon = wintypes.HICON(hicon_int)
    # Create 32bpp top-down DIB
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = size
    bmi.bmiHeader.biHeight = -size  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    bits = ctypes.c_void_p()
    screen_dc = _user32.GetDC(None)
    mem_dc = _gdi32.CreateCompatibleDC(screen_dc)
    hbm = _gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
    if not hbm:
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(None, screen_dc)
        raise OSError(f"CreateDIBSection failed err={ctypes.get_last_error()}")

    old = _gdi32.SelectObject(mem_dc, hbm)
    ok = _user32.DrawIconEx(mem_dc, 0, 0, hicon, size, size, 0, None, DI_NORMAL)

    # Copy bytes
    try:
        if not ok:
            raise OSError(f"DrawIconEx failed err={ctypes.get_last_error()}")
        buf = (ctypes.c_ubyte * (size * size * 4)).from_address(bits.value)
        # DIB is BGRA
        img = Image.frombuffer("RGBA", (size, size), bytes(buf), "raw", "BGRA", 0, 1)
        return img
    finally:
        _gdi32.SelectObject(mem_dc, old)
        _gdi32.DeleteObject(hbm)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(None, screen_dc)


def _normalize_icon_canvas(img: "Image.Image", target: int) -> "Image.Image":
    """Normalize icons that come back as a tiny glyph in a big transparent canvas.

    On some apps, the system image list returns a valid HICON but the rendered
    bitmap contains a small icon in the top-left corner, leaving most of the
    canvas fully transparent. The result looks "empty" in UI.

    Strategy:
    - Find the alpha bounding box.
    - If it occupies far less than the target canvas, crop + center + upscale.
    - Otherwise, keep as-is.
    """
    if Image is None:
        return img
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    if img.size != (target, target):
        # keep behavior deterministic
        img = img.resize((target, target), resample=Image.LANCZOS)

    alpha = img.split()[-1]
    bbox = alpha.getbbox()
    if not bbox:
        return img

    x0, y0, x1, y1 = bbox
    bw, bh = (x1 - x0), (y1 - y0)

    # If it already fills most of the canvas, don't touch it.
    if bw >= int(target * 0.80) and bh >= int(target * 0.80):
        return img

    # If the non-transparent area is *too* small, it's almost certainly the issue.
    if bw <= int(target * 0.10) or bh <= int(target * 0.10):
        # still normalize, but avoid division by zero/degenerate crops
        pass

    cropped = img.crop(bbox)
    side = max(bw, bh)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(cropped, ((side - bw) // 2, (side - bh) // 2))
    if side != target:
        square = square.resize((target, target), resample=Image.LANCZOS)
    return square


def _extract_via_imagelist(path: str, desired_size: int) -> "Image.Image":
    idx = _get_sys_icon_index(path)
    # try jumbo then extralarge
    for which in (SHIL_JUMBO, SHIL_EXTRALARGE, SHIL_LARGE):
        try:
            iml = _get_imagelist(which)
            hicon_int = _iml_geticon(iml, idx, ILD_TRANSPARENT)
            try:
                # Use desired_size for target; if jumbo returned bigger, DrawIconEx will scale into our DIB anyway.
                img = _hicon_to_pil(hicon_int, desired_size)
                return _normalize_icon_canvas(img, desired_size)
            finally:
                # DestroyIcon the returned HICON
                _user32.DestroyIcon(wintypes.HICON(hicon_int))
        except Exception:
            continue
    raise OSError("image list icon not available")


def extract_icon_to_png(exe_path: str, out_png: str, size: int = 256) -> bool:
    """
    Extract icon for exe_path (or any file path) and save to out_png as PNG.
    Returns True on success, False on failure.

    size: target raster size (we prefer 256 for clarity; caller may downscale)
    """
    _setup_winapi()

    try:
        img = _extract_via_imagelist(exe_path, size)
    except Exception:
        # Last-resort: small icon via SHGetFileInfoW with SHGFI_ICON
        try:
            shfi = SHFILEINFO()
            flags = SHGFI_ICON | SHGFI_LARGEICON
            ret = _shell32.SHGetFileInfoW(exe_path, 0, ctypes.byref(shfi), ctypes.sizeof(shfi), flags)
            if ret == 0 or not shfi.hIcon:
                return False
            hicon_int = int(ctypes.cast(shfi.hIcon, ctypes.c_void_p).value or 0)
            if not hicon_int:
                return False
            try:
                img = _normalize_icon_canvas(_hicon_to_pil(hicon_int, size), size)
            finally:
                _user32.DestroyIcon(wintypes.HICON(hicon_int))
        except Exception:
            return False

    try:
        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        img.save(out_png, format="PNG")
        return True
    except Exception:
        return False
