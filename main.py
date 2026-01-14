from __future__ import annotations

import os
import sys
import traceback
import faulthandler
import tkinter as tk
from pathlib import Path

from scripts.core.engine import CoreEngine
from scripts.core.models import CoreConfig
from scripts.data.repo import StatsRepository
from scripts.state.controller import AppController

from scripts.ui.main_window import MainWindow
from scripts.ui.floating import FloatingWindow
from scripts.ui.tray_icon import TrayIcon
from scripts.ui.notify import set_notify_root

def app_root_dir() -> Path:
    # 打包后：exe 所在目录；开发态：main.py 所在目录
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def resource_dir() -> Path:
    # onefile：资源在 _MEIPASS；onedir：_MEIPASS 不存在，就退回 exe 目录
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return app_root_dir()

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
        
        if os.environ.get("EYECARE_DEBUG", "") == "1":
            from scripts.debug.boot_diag import attach_boot_diag
            attach_boot_diag(controller, data_dir=data_dir, interval=1.0)

        root = tk.Tk()
        root.title("EyE Care")
        set_notify_root(root)

        controller.start()

        main_win = MainWindow(root, controller, base)

        def show_main():
            try:
                controller.refresh_now()      # ✅ 强制刷新前台app/icon缓存
            except Exception:
                pass

            try:
                main_win.refresh_all()        # ✅ 强制刷新主界面Top10/列表
            except Exception:
                pass

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
            icon_dir=resource_dir(),
            on_show_main=lambda: root.after(0, show_main),
            on_toggle_float=lambda: root.after(0, float_win.toggle),
            on_rest_now=lambda: root.after(0, main_win.rest_now),
            on_exit=lambda: root.after(0, root.quit),
        )
        tray.start()

        root.mainloop()

    except Exception:
        _write_crash_log(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
