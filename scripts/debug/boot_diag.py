from __future__ import annotations

import os
import time
import threading
from datetime import date

def _now():
    return time.strftime("%H:%M:%S")

def attach_boot_diag(controller, data_dir=None, interval=1.0):
    """
    挂载到主程序：启动后周期性打印关键状态，帮你定位：
    - 引擎阈值是否真的应用（work/rest/idle）
    - 当前 run_mode / manual_mode / need_break / continuous_work
    - 前台 app / icon_path
    - icon 缓存命中情况（Top10 需要的 icon 有多少能拿到）
    """
    if os.environ.get("EYECARE_DEBUG", "").strip() not in ("1", "true", "TRUE", "on", "ON"):
        return

    print(f"[{_now()}] [diag] enabled. interval={interval}s")

    # --- monkeypatch: 观察 refresh_now/_refresh_now 是否被调用，以及前台app/icon是否更新 ---
    if hasattr(controller, "_refresh_now"):
        _orig_refresh_now = controller._refresh_now

        def _wrap_refresh_now():
            try:
                _orig_refresh_now()
                st = controller.get_ui_status()
                print(f"[{_now()}] [diag] _refresh_now() front_app={getattr(st, 'front_app', None)!r} "
                      f"icon={getattr(st, 'front_app_icon', None)!r}")
            except Exception as e:
                print(f"[{_now()}] [diag] _refresh_now() error: {e}")

        controller._refresh_now = _wrap_refresh_now

    # --- 周期性 dump ---
    def dump_once():
        try:
            st = controller.get_ui_status()

            # 引擎配置（看看是不是启动就按 config.json 应用了）
            eng = controller.engine
            cfg = getattr(eng, "cfg", None)
            if cfg:
                idle = getattr(cfg, "idle_threshold_s", None)
                work = getattr(cfg, "work_threshold_s", None)
                rest = getattr(cfg, "rest_time_s", None)
            else:
                idle = work = rest = None

            run_mode = getattr(st, "run_mode", None)
            manual = getattr(st, "manual_mode", None)
            need_break = getattr(st, "need_break", None)
            cw = getattr(st, "continuous_work_s", None)
            front_app = getattr(st, "front_app", None)
            front_icon = getattr(st, "front_app_icon", None)

            print(f"[{_now()}] [diag] cfg: idle={idle}s work={work}s rest={rest}s | "
                  f"run_mode={run_mode} manual={manual} need_break={need_break} continuous={cw} | "
                  f"front={front_app!r} icon={front_icon!r}")

            # icon 缓存现状
            icon_cache = getattr(controller, "_icon_by_app", {})
            if isinstance(icon_cache, dict):
                print(f"[{_now()}] [diag] icon_cache size={len(icon_cache)} sample={list(icon_cache.items())[:3]}")

            # Top10 icon 命中率（仅检查“今日 top10”）
            try:
                top = controller.get_metrics_for_range(date.today(), date.today())
                items = sorted(top.items(), key=lambda x: x[1], reverse=True)[:10]
                apps = [n for n, _ in items]
                icon_map = controller.get_icon_map_for_apps(apps)
                hit = len(icon_map) if isinstance(icon_map, dict) else 0
                print(f"[{_now()}] [diag] Top10 apps={apps[:5]}... icon_hit={hit}/{len(apps)}")
            except Exception as e:
                print(f"[{_now()}] [diag] Top10 icon check error: {e}")

        except Exception as e:
            print(f"[{_now()}] [diag] dump error: {e}")

    def loop():
        # 启动后先连打几次，抓“最开始那几秒”的状态
        for _ in range(3):
            dump_once()
            time.sleep(0.5)
        while True:
            dump_once()
            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
