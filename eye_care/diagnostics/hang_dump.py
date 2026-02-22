from __future__ import annotations

import faulthandler
import os
import threading
import time
from pathlib import Path


def dump_threads(data_dir: Path, reason: str = "manual") -> Path:
    """Write a thread dump to data_dir/debug_hang/*.log.

    设计目标：当 UI 卡死时仍然可以通过托盘菜单触发，把所有线程栈导出，
    用于定位卡在哪里（Tk 主线程、图标抓取线程、tick_loop、repo.flush 等）。
    """
    data_dir = Path(data_dir)
    out_dir = data_dir / "debug_hang"
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"hang_dump_{ts}_{reason}.log"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"reason={reason}\n")
        f.write(f"pid={os.getpid()}\n")
        f.write(f"time={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("\n-- threads --\n")
        for t in threading.enumerate():
            f.write(f"{t.name} (daemon={t.daemon}) ident={t.ident}\n")
        f.write("\n-- traceback (all threads) --\n")
        try:
            faulthandler.dump_traceback(file=f, all_threads=True)
        except Exception as e:
            f.write(f"faulthandler.dump_traceback failed: {e}\n")

    return out_path
