from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageOps

from eye_care.state.controller import AppController


class TrayIcon:
    def __init__(
        self,
        controller: AppController,
        icon_dir: Path,
        on_show_main: Callable[[], None],
        on_toggle_float: Callable[[], None],
        on_exit: Callable[[], None],
    ):
        self.controller = controller
        self.icon_dir = Path(icon_dir)
        self.on_show_main = on_show_main
        self.on_toggle_float = on_toggle_float
        self.on_exit = on_exit

        self._base_icon_img: Optional[Image.Image] = None

    def start(self) -> None:
        threading.Thread(target=self._run_safe, daemon=True).start()

    def _run_safe(self) -> None:
        try:
            self._run()
        except Exception as e:
            print("[TrayIcon] crashed:", e)

    def _load_base_icon(self) -> Image.Image:
        ico = self.icon_dir / "icon.ico"
        if ico.exists():
            try:
                img = Image.open(str(ico)).convert("RGBA")
                img = img.resize((64, 64))
                return img
            except Exception as e:
                print("[TrayIcon] icon.ico load failed:", e)

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((6, 6, 58, 58), fill=(255, 255, 255, 235))
        d.ellipse((26, 26, 38, 38), fill=(76, 159, 112, 255))
        return img

    def _make_icon_img(self) -> Image.Image:
        st = self.controller.get_ui_status()
        base = (self._base_icon_img or self._load_base_icon()).copy()
        d = ImageDraw.Draw(base)

        bx0, by0, bx1, by1 = 42, 42, 62, 62

        if st.run_mode == "IDLE":
            d.ellipse((bx0, by0, bx1, by1), fill="#2563eb", outline="#2563eb")
            d.text((48, 44), "Z", fill="white")
            return base

        if st.watching:
            d.ellipse((bx0, by0, bx1, by1), fill="#7c3aed", outline="#7c3aed")
            d.polygon([(49, 46), (49, 58), (60, 52)], fill="white")
            return base

        if st.dnd:
            d.ellipse((bx0, by0, bx1, by1), fill="#ef4444", outline="#ef4444")
            d.rectangle((48, 51, 58, 54), fill="white")
            return base

        if st.need_break:
            d.ellipse((bx0, by0, bx1, by1), fill="#d97706", outline="#d97706")
            return base

        d.ellipse((bx0, by0, bx1, by1), fill="#16a34a", outline="#16a34a")
        return base

    def _run(self) -> None:
        try:
            import pystray
        except Exception as e:
            print("[TrayIcon] pystray not available:", e)
            return

        self._base_icon_img = self._load_base_icon()

        def _open_main(_icon, _item):
            self.on_show_main()

        def _toggle_float(_icon, _item):
            self.on_toggle_float()

        def _toggle_dnd(_icon, _item):
            self.controller.toggle_dnd()

        def _toggle_watch(_icon, _item):
            self.controller.toggle_watching()

        def _exit(_icon, _item):
            try:
                self.on_exit()
            finally:
                try:
                    icon.stop()
                except Exception:
                    pass

        def _checked_dnd(_item):
            return self.controller.get_ui_status().dnd

        def _checked_watch(_item):
            return self.controller.get_ui_status().watching

        menu = pystray.Menu(
            pystray.MenuItem("打开主界面", _open_main, default=True),
            pystray.MenuItem("显示/隐藏浮窗", _toggle_float),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("勿扰模式（不提醒）", _toggle_dnd, checked=_checked_dnd),
            pystray.MenuItem("观影模式（不提醒）", _toggle_watch, checked=_checked_watch),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", _exit),
        )

        icon = pystray.Icon("EyE Care", self._make_icon_img(), "EyE Care", menu)

        def _refresh_loop():
            last = None
            while True:
                try:
                    cur = self._make_icon_img()
                    if last is None or cur.tobytes() != last.tobytes():
                        icon.icon = cur
                        # 强制触发一次菜单更新，避免部分环境不刷新 icon
                        try:
                            icon.update_menu()
                        except Exception:
                            pass
                        last = cur
                    if not icon.visible:
                        break
                except Exception:
                    break
                time.sleep(0.2)

        threading.Thread(target=_refresh_loop, daemon=True).start()
        icon.run()
