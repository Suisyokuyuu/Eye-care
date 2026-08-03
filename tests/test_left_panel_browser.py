"""浏览器 domain 统计「展示层」测试。

覆盖：
  1. LeftPanelBridge.setView 三值映射（bro*→browser）+ 开关关时 _render 回退 app 视图。
  2. browser 分支：列表项 name=domain、isDomain=True、icon 来自 mock domain resolver。
  3. browserEnabled 翻转即使列表内容不变也发 dataChanged（签名含 flag 的回归测试）。
  4. SnapshotService 3 新键：开=取数、关=空且 repo domain 方法零调用。

开发机 Linux 无 PySide6 —— 本测试内联最小 PySide6.QtCore stub（Signal/Slot/Property/QObject
纯 Python 替身），在 import 被测模块前注入 sys.modules。
"""
from __future__ import annotations

import logging
import sys
import types
import unittest


# ── 内联最小 PySide6.QtCore stub（仅本测试所需符号）──────────────────────────
def _install_qtcore_stub() -> None:
    if "PySide6.QtCore" in sys.modules:
        return

    class _BoundSignal:
        def __init__(self) -> None:
            self._subs: list = []

        def connect(self, fn) -> None:
            self._subs.append(fn)

        def emit(self, *args) -> None:
            for fn in list(self._subs):
                fn(*args)

    class Signal:
        def __init__(self, *args, **kwargs) -> None:
            self._name = None

        def __set_name__(self, owner, name) -> None:
            self._name = name

        def __get__(self, obj, objtype=None):
            if obj is None:
                return self
            store = obj.__dict__.setdefault("_bound_signals", {})
            if self._name not in store:
                store[self._name] = _BoundSignal()
            return store[self._name]

    def Slot(*args, **kwargs):
        def deco(fn):
            return fn
        return deco

    def Property(*args, **kwargs):
        # @Property(type, notify=...) 装饰 getter → 普通 python property
        def deco(fn):
            return property(fn)
        return deco

    class QObject:
        def __init__(self, parent=None) -> None:
            self._parent = parent

    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QObject = QObject
    qtcore.Signal = Signal
    qtcore.Slot = Slot
    qtcore.Property = Property

    pyside6 = sys.modules.get("PySide6") or types.ModuleType("PySide6")
    pyside6.QtCore = qtcore
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore


_install_qtcore_stub()

from eye_care.qt_quick.left_panel_bridge import LeftPanelBridge  # noqa: E402


# ── 通用 mock snapshot ───────────────────────────────────────────────────────
def _snapshot(*, browser_enabled: bool) -> dict:
    return {
        "range_key": "day",
        "vm": {"local_date": "2026-07-19", "daily_usage": {"chrome": 3600, "code": 1800}},
        "usage_by_category": {"浏览": 3600, "开发": 1800},
        "range_daily_usage": {"chrome": 3600, "code": 1800},
        "range_usage_by_category": {"浏览": 3600, "开发": 1800},
        "app_paths": {},
        "display_names": {"chrome": "Chrome", "code": "Code"},
        "today_total_seconds": 5400,
        "range_start": "2026-07-19",
        "range_end": "2026-07-19",
        "record_browser_enabled": browser_enabled,
        "browser_domains": {"github.com": 1200, "google.com": 600} if browser_enabled else {},
        "range_browser_domains": {"github.com": 1200, "google.com": 600} if browser_enabled else {},
    }


class LeftPanelBrowserBridgeTests(unittest.TestCase):
    def _make(self, *, browser_enabled: bool, domain_resolver=None):
        snap = _snapshot(browser_enabled=browser_enabled)
        return LeftPanelBridge(
            lambda *a, **k: snap,
            today_str="2026-07-19",
            domain_icon_resolver=domain_resolver,
        )

    # 1a. setView 三值映射
    def test_setview_maps_browser_prefix(self) -> None:
        bridge = self._make(browser_enabled=True)
        bridge.setView("browser")
        self.assertEqual(bridge._view, "browser")
        bridge.setView("bro")
        self.assertEqual(bridge._view, "browser")
        bridge.setView("cat")
        self.assertEqual(bridge._view, "category")
        bridge.setView("anything")
        self.assertEqual(bridge._view, "app")

    # 1b. 开关关时 _render 回退 app 视图
    def test_render_falls_back_to_app_when_disabled(self) -> None:
        bridge = self._make(browser_enabled=False)
        bridge._view = "browser"        # 强制停在 browser 视图
        bridge._render()
        self.assertEqual(bridge._view, "app")
        self.assertFalse(bridge.browserEnabled)
        # 回退后渲染的是 app 列表（app key）
        names = [it["key"] for it in bridge.appList]
        self.assertIn("chrome", names)

    # 2. browser 分支：name=domain、isDomain=True、icon 来自 resolver
    def test_browser_branch_items(self) -> None:
        resolver = lambda d: "data:image/png;base64,ICON_" + d
        bridge = self._make(browser_enabled=True, domain_resolver=resolver)
        bridge.setView("browser")
        by_key = {it["key"]: it for it in bridge.appList}
        self.assertEqual(set(by_key), {"github.com", "google.com"})
        gh = by_key["github.com"]
        self.assertEqual(gh["name"], "github.com")          # domain 原样，name=key
        self.assertTrue(gh["isDomain"])
        self.assertEqual(gh["icon"], "data:image/png;base64,ICON_github.com")
        # app 视图的项 isDomain=False
        bridge.setView("app")
        self.assertTrue(all(not it["isDomain"] for it in bridge.appList))

    # 3. browserEnabled 翻转即使列表内容不变也发 dataChanged（签名含 flag）
    def test_browser_enabled_flip_emits_even_when_list_unchanged(self) -> None:
        # 两个 snapshot：列表内容完全一致（app 视图），仅 record_browser_enabled 不同。
        base = {
            "range_key": "day",
            "vm": {"local_date": "2026-07-19", "daily_usage": {"chrome": 3600}},
            "usage_by_category": {"浏览": 3600},
            "range_daily_usage": {"chrome": 3600},
            "range_usage_by_category": {"浏览": 3600},
            "app_paths": {},
            "display_names": {"chrome": "Chrome"},
            "today_total_seconds": 3600,
            "range_start": "2026-07-19",
            "range_end": "2026-07-19",
            "browser_domains": {},
            "range_browser_domains": {},
        }
        state = {"snap": dict(base, record_browser_enabled=False)}
        bridge = LeftPanelBridge(lambda *a, **k: state["snap"], today_str="2026-07-19")
        self.assertFalse(bridge.browserEnabled)

        fired = {"n": 0}
        bridge.dataChanged.connect(lambda: fired.__setitem__("n", fired["n"] + 1))

        # 翻开开关：app 列表内容不变，但 browserEnabled 从 False→True 必须发 dataChanged
        state["snap"] = dict(base, record_browser_enabled=True)
        bridge.refresh()
        self.assertEqual(fired["n"], 1)
        self.assertTrue(bridge.browserEnabled)

        # 再次 refresh 同一 snapshot（无任何变化）→ 签名相同 → 不再发
        bridge.refresh()
        self.assertEqual(fired["n"], 1)

    # 附：domain icon 未命中不设重试上限（解析器只读本地缓存，不联网）
    def test_domain_icon_retries_indefinitely(self) -> None:
        calls = {"n": 0}

        def resolver(_d):
            calls["n"] += 1
            return ""       # 恒未命中

        bridge = self._make(browser_enabled=True, domain_resolver=resolver)
        for _ in range(20):
            bridge._domain_icon_for("miss.com")
        # 图标要等站点累计够时长才被抓下来，远超 5 拍；设上限会导致抓到了也不显示
        self.assertEqual(calls["n"], 20)

    def test_clear_domain_icon_cache_forces_reresolve(self) -> None:
        # 站点详情页清除图标缓存后，左栏必须丢掉自己那份 data_url，否则卡片仍是旧图标
        state = {"v": "data:old"}
        bridge = self._make(browser_enabled=True, domain_resolver=lambda d: state["v"])
        self.assertEqual(bridge._domain_icon_for("bilibili.com"), "data:old")

        state["v"] = ""                      # 缓存被清 → 解析器取不到了
        self.assertEqual(bridge._domain_icon_for("bilibili.com"), "data:old")  # 仍吃旧缓存

        bridge.clearDomainIconCache()
        self.assertEqual(bridge._domain_icon_for("bilibili.com"), "")

    def test_domain_icon_success_is_cached(self) -> None:
        calls = {"n": 0}

        def resolver(_d):
            calls["n"] += 1
            return "data:image/png;base64,AAA"

        bridge = self._make(browser_enabled=True, domain_resolver=resolver)
        for _ in range(5):
            url = bridge._domain_icon_for("hit.com")
        self.assertEqual(url, "data:image/png;base64,AAA")
        self.assertEqual(calls["n"], 1)   # 命中后永久缓存，不再调解析器


# ── SnapshotService 3 新键 ───────────────────────────────────────────────────
class _State:
    is_paused = False
    is_dnd = False
    force_idle = False
    auto_idle = False


class _VM:
    def __init__(self, local_date, daily_usage):
        self.local_date = local_date
        self.daily_usage = daily_usage


class _Cfg:
    blacklist_apps: list = []

    def __init__(self, record_browser_enabled: bool):
        self.record_browser_enabled = record_browser_enabled


class _Repo:
    """记录 domain 方法调用次数，验证关闭时零调用。"""

    def __init__(self):
        self.domain_calls = 0
        self.domain_range_calls = 0

    def get_daily_usage(self, d):
        return {"chrome": 3600, "code": 1800}

    def get_usage_range(self, dr, dim="app"):
        if dim == "category":
            return {"浏览": 3600, "开发": 1800}
        return {"chrome": 3600, "code": 1800}

    def get_hourly_usage(self, d):
        return {0: 1800, 1: 3600}

    def get_events(self, d):
        return []

    def get_hourly_breakdown(self, d, dim="app"):
        return {}

    def get_app_category(self, app):
        return "浏览" if app == "chrome" else "开发"

    def get_daily_domain_usage(self, d):
        self.domain_calls += 1
        return {"github.com": 1200, "google.com": 600}

    def get_domain_usage_range(self, dr):
        self.domain_range_calls += 1
        return {"github.com": 5000, "google.com": 2000}


class _Controller:
    def __init__(self, record_browser_enabled: bool):
        self.repo = _Repo()
        self.cfg = _Cfg(record_browser_enabled)

    def snapshot_today(self):
        vm = _VM("2026-07-19", {"chrome": 3600, "code": 1800})
        extra = {"state": _State(), "app_paths": {}, "idle_s": 0, "fg": "", "rest": {}, "debug": {}}
        return vm, extra

    def snapshot_for_date(self, d):
        return self.snapshot_today()

    def get_display_name(self, k):
        return {"chrome": "Chrome", "code": "Code"}.get(k, k)


def _get_snapshot(controller, *, range_key="day"):
    from eye_care.services.context import ServiceContext
    from eye_care.services.snapshot_service import SnapshotService
    ctx = ServiceContext(controller=controller, log=logging.getLogger("test"))
    svc = SnapshotService(ctx)
    return svc.get_snapshot(query={"range": range_key})


class SnapshotServiceBrowserKeysTests(unittest.TestCase):
    def test_enabled_day_fetches_domains(self) -> None:
        ctrl = _Controller(record_browser_enabled=True)
        payload = _get_snapshot(ctrl, range_key="day")
        self.assertTrue(payload["record_browser_enabled"])
        self.assertEqual(payload["browser_domains"], {"github.com": 1200, "google.com": 600})
        # day 范围：range_browser_domains == browser_domains（无独立 range 查询）
        self.assertEqual(payload["range_browser_domains"], payload["browser_domains"])
        self.assertEqual(ctrl.repo.domain_calls, 1)
        self.assertEqual(ctrl.repo.domain_range_calls, 0)

    def test_enabled_week_fetches_range(self) -> None:
        ctrl = _Controller(record_browser_enabled=True)
        payload = _get_snapshot(ctrl, range_key="week")
        self.assertTrue(payload["record_browser_enabled"])
        self.assertEqual(payload["browser_domains"], {"github.com": 1200, "google.com": 600})
        self.assertEqual(payload["range_browser_domains"], {"github.com": 5000, "google.com": 2000})
        self.assertEqual(ctrl.repo.domain_calls, 1)
        self.assertEqual(ctrl.repo.domain_range_calls, 1)

    def test_disabled_empty_and_zero_repo_calls(self) -> None:
        ctrl = _Controller(record_browser_enabled=False)
        payload = _get_snapshot(ctrl, range_key="week")
        self.assertFalse(payload["record_browser_enabled"])
        self.assertEqual(payload["browser_domains"], {})
        self.assertEqual(payload["range_browser_domains"], {})
        # 关闭时对 domain repo 方法零调用
        self.assertEqual(ctrl.repo.domain_calls, 0)
        self.assertEqual(ctrl.repo.domain_range_calls, 0)


if __name__ == "__main__":
    unittest.main()
