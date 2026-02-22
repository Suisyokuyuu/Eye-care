from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from eye_care.diagnostics import diag, log_exception_summary

log = logging.getLogger(__name__)


@dataclass
class TrayCallbacks:
    """Pywebview 托盘回调，由 main.py 传入。三模式互斥由 on_set_run_mode 保证。"""
    on_set_run_mode: Callable[[str], None]  # "normal" | "dnd" | "leave"，三选一
    on_quit: Callable[[], None]
    is_window_visible: Callable[[], bool]
    is_paused: Callable[[], bool]
    is_dnd: Callable[[], bool]
    is_force_idle: Callable[[], bool]
    is_auto_idle: Callable[[], bool]  # 自动 idle（无操作一段时间后由正常模式进入）
    run_on_main: Optional[Callable[[Callable[[], None]], None]] = None  # 可选，用于将回调调度到主线程
    on_show_main: Optional[Callable[[], None]] = None  # 只显示主界面并前置，无 toggle
    # M5 可选：打开设置、立即休息、检查更新、打开数据目录
    on_open_settings: Optional[Callable[[], None]] = None
    on_rest_start: Optional[Callable[[], None]] = None
    on_check_update: Optional[Callable[[], None]] = None
    on_open_data_dir: Optional[Callable[[], None]] = None
    # 调试功能：抓取线程栈
    on_dump_threads: Optional[Callable[[], None]] = None

    def _run(self, fn: Callable[[], None]) -> None:
        if self.run_on_main:
            self.run_on_main(fn)
        else:
            fn()


class PywebviewTrayIcon:
    """基于 TrayCallbacks 的托盘图标，供 pywebview 主入口使用。"""

    def __init__(
        self,
        *,
        icon_path: Path | str,
        callbacks: TrayCallbacks,
        title: str = "EyE Care",
    ):
        self._icon_path = Path(icon_path)
        self._callbacks = callbacks
        self._title = title
        self._stop_evt = threading.Event()
        self._icon = None
        self._base_img = None
        self._thr: Optional[threading.Thread] = None
        self._icon_frame_logged = False  # 仅在首次帧异常时记录

    def start(self) -> bool:
        try:
            import pystray  # noqa: F401
            from PIL import Image  # noqa: F401
        except Exception:
            log.exception("tray disabled (pystray/PIL not available)")
            return False

        self._stop_evt.clear()
        self._base_img = self._load_base_icon()
        self._thr = threading.Thread(target=self._run_safe, daemon=True, name="tray_thread")
        self._thr.start()
        log.info("tray: pywebview tray thread started")
        return True

    def stop(self) -> None:
        """停止托盘：设置停止事件，托盘线程退出循环后自行 icon.stop()，再 join 等待。"""
        self._stop_evt.set()
        if self._thr and self._thr.is_alive():
            self._thr.join(timeout=1.5)
            if self._thr.is_alive():
                log.warning("tray: 托盘线程在 1.5s 内未退出，主退出不等待")
            else:
                log.info("tray: 托盘线程已退出")

    def _run_safe(self) -> None:
        try:
            self._run()
        except Exception:
            log.exception("tray: pywebview run crashed")

    def _load_base_icon(self):
        try:
            from PIL import Image, ImageDraw
        except Exception:
            return None
        p = self._icon_path
        if p.exists():
            try:
                img = Image.open(str(p))
                best = None
                best_area = -1
                n = getattr(img, "n_frames", 1)
                for i in range(int(n) or 1):
                    try:
                        img.seek(i)
                        frame = img.copy()
                    except Exception as e:
                        if not self._icon_frame_logged:
                            self._icon_frame_logged = True
                            log.warning("tray icon frame seek/copy failed (first): path=%s frame=%s err=%s", p, i, e)
                        continue
                    w, h = frame.size
                    if w * h > best_area:
                        best_area = w * h
                        best = frame
                if best is not None:
                    return best.convert("RGBA").resize((64, 64))
            except Exception:
                log.exception("tray: failed to load icon")
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((6, 6, 58, 58), fill=(255, 255, 255, 235))
        d.ellipse((26, 26, 38, 38), fill=(76, 159, 112, 255))
        return img

    def _mode(self) -> str:
        if self._callbacks.is_auto_idle():
            return "IDLE"
        if self._callbacks.is_force_idle():
            return "LEAVE"
        if self._callbacks.is_dnd():
            return "DND"
        return "NORMAL"

    def _is_mode_current(self, mode_key: str) -> bool:
        """当前是否为指定模式（用于 Clash 风 ◉/○ 前缀）。"""
        if mode_key == "normal":
            return not self._callbacks.is_dnd() and not self._callbacks.is_force_idle() and not self._callbacks.is_auto_idle()
        if mode_key == "dnd":
            return self._callbacks.is_dnd()
        if mode_key == "leave":
            return self._callbacks.is_force_idle()
        return False

    def _mode_label(self, mode_key: str, label: str) -> str:
        """Clash 风：选中 ◉，未选中 ○。调用时若回调抛错则返回安全默认，避免托盘不显示。"""
        try:
            mark = "◉" if self._is_mode_current(mode_key) else "○"
            return f"{mark} {label}"
        except Exception:
            return f"○ {label}"

    def _make_icon_img(self):
        try:
            from PIL import Image, ImageDraw
        except Exception:
            return self._base_img
        base = (self._base_img or self._load_base_icon())
        if base is None:
            return None
        base = base.copy()
        mode = self._mode()
        badge_px = 34
        badge2 = badge_px * 2
        badge = Image.new("RGBA", (badge2, badge2), (0, 0, 0, 0))
        d = ImageDraw.Draw(badge)
        pad = 4
        x0, y0, x1, y1 = pad, pad, badge2 - pad, badge2 - pad
        if mode == "DND":
            d.ellipse((x0, y0, x1, y1), fill=(255, 255, 255, 220), outline=(239, 68, 68, 255), width=8)
            d.line((x0 + 10, y1 - 10, x1 - 10, y0 + 10), fill=(239, 68, 68, 255), width=10)
        elif mode in ("LEAVE", "IDLE"):
            # 钟表徽标（暂停 / 自动 idle，图标一致）
            cx, cy = badge2 // 2, badge2 // 2
            r = (badge2 - pad * 2) // 2
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 220), outline=(148, 163, 184, 255), width=5)
            d.line((cx, cy, cx, cy - r + 8), fill=(100, 116, 139, 255), width=4)   # 时针 12
            d.line((cx, cy, cx + r - 8, cy), fill=(100, 116, 139, 255), width=3)  # 分针 3
        else:
            d.ellipse((x0, y0, x1, y1), fill=(22, 163, 74, 255), outline=(22, 163, 74, 255), width=6)
        badge_small = badge.resize((badge_px, badge_px), resample=Image.Resampling.LANCZOS)
        bx = base.width - badge_px - 1
        by = base.height - badge_px - 1
        base.alpha_composite(badge_small, (bx, by))
        return base

    def _run(self) -> None:
        import pystray
        cb = self._callbacks

        def _show_main(_icon=None, _item=None):
            if getattr(cb, "on_show_main", None):
                cb._run(cb.on_show_main)

        def _set_mode(mode: str):
            def _do():
                cb.on_set_run_mode(mode)
            cb._run(_do)

        def _set_normal(_icon=None, _item=None):
            _set_mode("normal")

        def _set_dnd(_icon=None, _item=None):
            _set_mode("dnd")

        def _set_leave(_icon=None, _item=None):
            _set_mode("leave")

        def _exit(_icon=None, _item=None):
            self._stop_evt.set()
            try:
                if self._icon:
                    self._icon.visible = False
            except Exception as e:
                log_exception_summary(log, "DIAG_EXCEPTION", "tray fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_TRAY_FALLBACK")
            cb._run(cb.on_quit)

        # M5-A Clash 风菜单：模式项用 ◉/○ 前缀，不用 radio（系统圆点不可控）
        def _build_menu():
            menu_items = [
                pystray.MenuItem("显示主界面", _show_main, default=True),
            ]
            if getattr(cb, "on_rest_start", None):
                menu_items.append(pystray.MenuItem("立即休息", lambda *a: cb._run(cb.on_rest_start)))
            # 用构建时求值的静态文案，避免 Windows 首次显示时执行 callable 导致托盘不显示
            menu_items.extend([
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(self._mode_label("normal", "正常"), _set_normal),
                pystray.MenuItem(self._mode_label("dnd", "勿扰"), _set_dnd),
                pystray.MenuItem(self._mode_label("leave", "离开"), _set_leave),
                pystray.Menu.SEPARATOR,
            ])
            if getattr(cb, "on_check_update", None):
                menu_items.append(pystray.MenuItem("检查更新…", lambda *a: cb._run(cb.on_check_update)))
            if getattr(cb, "on_open_settings", None):
                menu_items.append(pystray.MenuItem("打开设置", lambda *a: cb._run(cb.on_open_settings)))
            if getattr(cb, "on_open_data_dir", None):
                menu_items.append(pystray.MenuItem("打开数据目录", lambda *a: cb._run(cb.on_open_data_dir)))
            menu_items.extend([
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", _exit),
            ])
            return pystray.Menu(*menu_items)

        self._build_menu_fn = _build_menu
        menu = _build_menu()
        self._icon = pystray.Icon(self._title, self._make_icon_img(), self._title, menu)

        # Windows 上 pystray 的 run() 放到后台线程里偶发“不显示/无响应”。
        # 使用 run_detached() 让 pystray 自己管理其消息循环线程，并保持 _icon 引用避免被 GC。
        try:
            self._icon.run_detached()
            log.info("tray: run_detached started")
        except Exception:
            # 兜底：如果 run_detached 不存在或失败，再退回 run()（可能会阻塞）
            log.exception("tray: run_detached failed, fallback to run()")
            self._icon.run()
            return

        # 刷新循环在 run_detached 之后启动，避免在图标未就绪时访问 _icon 导致不显示
        time.sleep(0.5)  # 给 Windows 时间完成托盘图标注册后再动 menu/icon
        def _refresh_loop():
            last_sig = None
            last_bytes = None
            first_run = True  # 标记第一次运行，确保初始化时刷新菜单
            while not self._stop_evt.is_set():
                try:
                    sig = self._mode()
                    # 首次运行或模式变化时刷新菜单
                    if first_run or (last_sig is not None and last_sig != sig):
                        # 记录托盘模式变化
                        if first_run:
                            diag.emit("DIAG_TRAY_INIT", log, "托盘初始化", mode=sig)
                        else:
                            diag.emit("DIAG_TRAY_MODE_CHANGE", log, "托盘模式变化", from_mode=last_sig, to_mode=sig)
                        try:
                            self._icon.menu = self._build_menu_fn()
                            self._icon.update_menu()
                        except Exception as e:
                            log_exception_summary(log, "DIAG_EXCEPTION", "tray fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_TRAY_FALLBACK")
                    first_run = False
                    last_sig = sig
                    img = self._make_icon_img()
                    b = img.tobytes() if img else None
                    if b and b != last_bytes:
                        try:
                            self._icon.icon = img
                        except Exception as e:
                            log_exception_summary(log, "DIAG_EXCEPTION", "tray fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_TRAY_FALLBACK")
                        last_bytes = b
                except Exception as e:
                    log_exception_summary(log, "DIAG_EXCEPTION", "tray fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_TRAY_FALLBACK")
                time.sleep(0.2)

        threading.Thread(target=_refresh_loop, daemon=True, name="tray_refresh").start()

        # 保持该线程存活，直到 stop() 或退出菜单触发。
        while not self._stop_evt.is_set():
            time.sleep(0.2)

        try:
            self._icon.stop()
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "tray fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_TRAY_FALLBACK")
