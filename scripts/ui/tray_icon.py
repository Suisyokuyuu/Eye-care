from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw

from scripts.state.controller import AppController


class TrayIcon:
    """
    Windows tray icon (pystray).
    - 状态点：NORMAL绿 / IDLE蓝 / NEED_BREAK橙 / DND红 / WATCH紫
    - 菜单：单选互斥模式 + 马上休息 + 显示主界面/浮窗/退出
    """

    def __init__(
        self,
        controller: AppController,
        icon_dir: Path,
        on_show_main: Callable[[], None],
        on_toggle_float: Callable[[], None],
        on_rest_now: Callable[[], None],
        on_exit: Callable[[], None],
    ):
        self.controller = controller
        self.icon_dir = Path(icon_dir)

        self.on_show_main = on_show_main
        self.on_toggle_float = on_toggle_float
        self.on_rest_now = on_rest_now
        self.on_exit = on_exit

        self._stop_evt = threading.Event()
        self._base_icon_img: Optional[Image.Image] = None

    def start(self) -> None:
        threading.Thread(target=self._run_safe, daemon=True).start()

    def stop(self) -> None:
        self._stop_evt.set()

    # ---------------- internal ----------------

    def _run_safe(self) -> None:
        try:
            self._run()
        except Exception:
            pass

    def _load_base_icon(self) -> Image.Image:
        # 先用 icon.ico（如果有）
        ico = self.icon_dir / "icon.ico"
        if ico.exists():
            try:
                img = Image.open(str(ico)).convert("RGBA")
                return img.resize((64, 64))
            except Exception:
                pass

        # fallback：简单圆形
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((6, 6, 58, 58), fill=(255, 255, 255, 235))
        d.ellipse((26, 26, 38, 38), fill=(76, 159, 112, 255))
        return img

    def _status_signature(self):
        st = self.controller.get_ui_status()
        mode = getattr(st, "manual_mode", "") or ("WATCHING" if st.watching else ("DND" if st.dnd else "NORMAL"))
        return (mode, st.run_mode, bool(st.need_break))

    def _make_icon_img(self) -> Image.Image:
        st = self.controller.get_ui_status()
        mode = getattr(st, "manual_mode", "") or ("WATCHING" if st.watching else ("DND" if st.dnd else "NORMAL"))

        base = (self._base_icon_img or self._load_base_icon()).copy()
        d = ImageDraw.Draw(base)

        bx0, by0, bx1, by1 = 42, 42, 62, 62

        if mode == "WATCHING" or st.watching:
            d.ellipse((bx0, by0, bx1, by1), fill="#7c3aed", outline="#7c3aed")
            d.polygon([(49, 46), (49, 58), (60, 52)], fill="white")
            return base

        if mode == "DND" or st.dnd:
            d.ellipse((bx0, by0, bx1, by1), fill="#ef4444", outline="#ef4444")
            d.rectangle((48, 51, 58, 54), fill="white")
            return base

        if st.run_mode == "IDLE":
            d.ellipse((bx0, by0, bx1, by1), fill="#2563eb", outline="#2563eb")
            d.text((48, 44), "Z", fill="white")
            return base

        if st.need_break:
            d.ellipse((bx0, by0, bx1, by1), fill="#d97706", outline="#d97706")
            return base

        d.ellipse((bx0, by0, bx1, by1), fill="#16a34a", outline="#16a34a")
        return base

    def _run(self) -> None:
        try:
            import pystray
        except Exception:
            return

        self._base_icon_img = self._load_base_icon()
        self._stop_evt.clear()

        def _open_main(_icon, _item):
            self.on_show_main()

        def _toggle_float(_icon, _item):
            self.on_toggle_float()

        def _rest_now(_icon, _item):
            self.on_rest_now()

        # 模式互斥 set_*
        def _set_normal(_icon, _item):
            self.controller.set_normal()

        def _set_dnd(_icon, _item):
            self.controller.set_dnd()

        def _set_watch(_icon, _item):
            self.controller.set_watching()

        def _exit(_icon, _item):
            self._stop_evt.set()
            try:
                self.on_exit()
            finally:
                try:
                    icon.stop()
                except Exception:
                    pass

        # checked 单选
        def _mode_of_status():
            st = self.controller.get_ui_status()
            return getattr(st, "manual_mode", "") or ("WATCHING" if st.watching else ("DND" if st.dnd else "NORMAL"))

        def _checked_normal(_item):
            return _mode_of_status() == "NORMAL"

        def _checked_dnd(_item):
            return _mode_of_status() == "DND"

        def _checked_watch(_item):
            return _mode_of_status() == "WATCHING"

        menu = pystray.Menu(
            pystray.MenuItem("打开主界面", _open_main, default=True),
            pystray.MenuItem("显示/隐藏浮窗", _toggle_float),
            pystray.MenuItem("马上休息", _rest_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("正常模式", _set_normal, checked=_checked_normal),
            pystray.MenuItem("勿扰模式", _set_dnd, checked=_checked_dnd),
            pystray.MenuItem("视频模式", _set_watch, checked=_checked_watch),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", _exit),
        )

        icon = pystray.Icon("EyE Care", self._make_icon_img(), "EyE Care", menu)

        def _refresh_loop():
            last_bytes = None
            last_sig = None

            while not self._stop_evt.is_set():
                try:
                    sig = self._status_signature()
                    img = self._make_icon_img()
                    b = img.tobytes()

                    if last_bytes is None or b != last_bytes:
                        icon.icon = img
                        last_bytes = b

                    if last_sig is None or sig != last_sig:
                        try:
                            icon.update_menu()
                        except Exception:
                            pass
                        last_sig = sig

                except Exception:
                    pass

                time.sleep(0.25)

        threading.Thread(target=_refresh_loop, daemon=True).start()
        icon.run()
