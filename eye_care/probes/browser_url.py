from __future__ import annotations

"""浏览器 domain 采集探针的跨平台入口（仿 probes/fullscreen.py 范式）。

Windows 走 win_browser_url 的真实 UIA 实现；非 Windows / comtypes 缺失 / 构造异常
一律降级为 no-op watcher（所有方法安全，get_domain 恒返回 ""）。
构造绝不抛异常，controller 可无条件持有并调用。
"""

import sys


class _NoopWatcher:
    """无实现平台的占位 watcher：start/stop/set_active 均 no-op，get_domain 恒 ""。"""

    def start(self) -> None:
        pass

    def stop(self, timeout_s: float = 2.0) -> None:
        pass

    def set_active(self, active: bool) -> None:
        pass

    def get_domain(self, max_age_s: float = 6.0) -> str:
        return ""


def make_browser_watcher(log=None):
    """返回 BrowserUrlWatcher（Windows）或 _NoopWatcher（其它情况）。绝不抛异常。"""
    try:
        if not sys.platform.startswith("win"):
            if log is not None:
                log.debug("browser_url: 非 Windows 平台，使用 no-op watcher")
            return _NoopWatcher()
        from .win_browser_url import BrowserUrlWatcher
        return BrowserUrlWatcher(log=log)
    except ImportError as e:
        if log is not None:
            log.debug("browser_url: 依赖缺失(%s)，降级 no-op", type(e).__name__)
    except Exception as e:
        if log is not None:
            log.debug("browser_url: 构造异常(%s)，降级 no-op", type(e).__name__)
    return _NoopWatcher()
