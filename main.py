from __future__ import annotations

import sys
import traceback
import faulthandler
import tkinter as tk
from pathlib import Path

from eye_care.core.engine import CoreEngine
from eye_care.core.models import CoreConfig
from eye_care.data.repo import StatsRepository
from eye_care.state.controller import AppController

from eye_care.ui.main_window import MainWindow
from eye_care.ui.floating import FloatingWindow
from eye_care.ui.tray_icon import TrayIcon
from eye_care.ui.notify import set_notify_root, notify_need_break


def app_root_dir() -> Path:
    # 打包后：exe 所在目录；开发态：main.py 所在目录
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    return app_root_dir() / "data"


def _write_crash_log(msg: str) -> None:
    try:
        base = data_dir()
        base.mkdir(exist_ok=True)
        (base / "crash.log").write_text(msg, encoding="utf-8")
    except Exception:
        pass


def main() -> None:
    base = data_dir()
    base.mkdir(exist_ok=True)

    try:
        with (base / "crash.log").open("w", encoding="utf-8") as f:
            faulthandler.enable(file=f)
    except Exception:
        pass

    try:
        repo = StatsRepository(base)
        repo.ensure_initialized()

        cfg = CoreConfig(
            idle_threshold_s=60,
            work_threshold_s=45 * 60,
            rest_time_s=5 * 60,
        )
        engine = CoreEngine(cfg)
        controller = AppController(base, engine, repo)

        root = tk.Tk()
        root.title("EyE Care")
        set_notify_root(root)

        def on_need_break(_):
            notify_need_break("护眼提醒", "该休息一下了（浮窗右键：马上休息 / ESC 可跳过）")

        controller.on_need_break = on_need_break
        controller.start()

        main_win = MainWindow(root, controller, base)

        def show_main():
            root.deiconify()
            root.lift()
            root.focus_force()

        def hide_main():
            root.withdraw()

        float_win = FloatingWindow(
            root=root,
            controller=controller,
            data_dir=base,
            on_show_main=show_main,
            on_rest_now=main_win.rest_now,
            on_exit=lambda: root.quit(),
        )

        root.protocol("WM_DELETE_WINDOW", hide_main)

        tray = TrayIcon(
            controller=controller,
            icon_dir=app_root_dir(),  # ✅ icon.ico 从 exe 同目录找
            on_show_main=show_main,
            on_toggle_float=float_win.toggle,
            on_exit=lambda: root.quit(),
        )
        tray.start()

        root.mainloop()

    except Exception:
        _write_crash_log(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
