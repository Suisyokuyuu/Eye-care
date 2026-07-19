"""右栏时段柱状图 + Top4 跟随左栏视图维度（应用/分类/浏览器）测试。

覆盖：
  1. api/common._timebars_for_day/_range 的 dim 参数：category/browser 维度的 keys/values/「其他」桶；
     browser 无数据时全空不炸。
  2. SnapshotService：dim=browser 且开关关 → timebar_dim 回退 "app"；dim=category 正常；payload 含 timebar_dim。
  3. RightPanelBridge（QtCore stub）：setDim 归一化、切 dim 触发 recompute、provider 收到 dim、
     Top4 browser 维度用 domain 名、category 维度用分类名。

开发机 Linux 无 PySide6 —— 复用 test_left_panel_browser 的最小 QtCore stub 思路。
"""
from __future__ import annotations

import logging
import sys
import types
import unittest


# ── 内联最小 PySide6.QtCore stub ─────────────────────────────────────────────
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


# ── mock repo/controller ─────────────────────────────────────────────────────
class _Repo:
    """纯 dict 返回；覆盖 timebars 各 dim 用到的读方法。"""

    def get_daily_usage(self, d):
        return {"chrome.exe": 3600, "code.exe": 1800}

    def get_usage_range(self, dr, dim="app"):
        if dim == "category":
            return {"浏览": 3600, "开发": 1800}
        return {"chrome.exe": 3600, "code.exe": 1800}

    def get_hourly_breakdown(self, d, dim="app"):
        if dim == "category":
            return {0: {"浏览": 1000, "开发": 500}}
        return {0: {"chrome.exe": 1000, "code.exe": 500, "misc.exe": 200}}

    def get_daily_domain_usage(self, d):
        return {"a.com": 3600, "b.com": 1800}

    def get_domain_usage_range(self, dr):
        return {"a.com": 7200, "b.com": 3600}

    def get_hourly_domain_breakdown(self, d):
        return {0: {"a.com": 1000, "b.com": 500, "c.com": 200}}


class _EmptyRepo:
    """全空（浏览器功能关/无数据）。"""

    def get_daily_usage(self, d):
        return {}

    def get_usage_range(self, dr, dim="app"):
        return {}

    def get_hourly_breakdown(self, d, dim="app"):
        return {}

    def get_daily_domain_usage(self, d):
        return {}

    def get_domain_usage_range(self, dr):
        return {}

    def get_hourly_domain_breakdown(self, d):
        return {}


class _Ctrl:
    def __init__(self, repo):
        self.repo = repo


# ── 1. _timebars_for_day/_range dim ──────────────────────────────────────────
class TimebarsDimTests(unittest.TestCase):
    def test_day_browser(self) -> None:
        from eye_care.api.common import _timebars_for_day
        labels, keys, rows = _timebars_for_day(_Ctrl(_Repo()), "2026-07-19", dim="browser")
        self.assertEqual(labels, [str(i) for i in range(24)])
        self.assertEqual(keys, ["a.com", "b.com", "其他"])
        # 小时 0：a.com=1000 b.com=500 其他=1700-1500=200
        self.assertEqual(rows[0], [1000, 500, 200])
        # 其他小时全 0
        self.assertEqual(rows[1], [0, 0, 0])

    def test_day_category(self) -> None:
        from eye_care.api.common import _timebars_for_day
        labels, keys, rows = _timebars_for_day(_Ctrl(_Repo()), "2026-07-19", dim="category")
        self.assertEqual(keys, ["浏览", "开发", "其他"])
        # 小时 0：浏览=1000 开发=500 其他=0（该小时总量=1500）
        self.assertEqual(rows[0], [1000, 500, 0])

    def test_day_app_default(self) -> None:
        from eye_care.api.common import _timebars_for_day
        _, keys, rows = _timebars_for_day(_Ctrl(_Repo()), "2026-07-19")
        self.assertEqual(keys, ["chrome.exe", "code.exe", "其他"])
        self.assertEqual(rows[0], [1000, 500, 200])

    def test_day_browser_empty_no_crash(self) -> None:
        from eye_care.api.common import _timebars_for_day
        labels, keys, rows = _timebars_for_day(_Ctrl(_EmptyRepo()), "2026-07-19", dim="browser")
        self.assertEqual(keys, ["其他"])
        self.assertEqual(len(rows), 24)
        self.assertTrue(all(r == [0] for r in rows))

    def test_range_browser(self) -> None:
        from eye_care.api.common import _timebars_for_range
        labels, keys, rows = _timebars_for_range(_Ctrl(_Repo()), "week", "2026-07-13", "2026-07-19", dim="browser")
        self.assertEqual(keys, ["a.com", "b.com", "其他"])
        # 每天 get_daily_domain_usage=a.com 3600/b.com 1800 → 其他=0
        self.assertEqual(rows[0], [3600, 1800, 0])
        self.assertEqual(len(rows), 7)

    def test_range_category(self) -> None:
        from eye_care.api.common import _timebars_for_range
        _, keys, rows = _timebars_for_range(_Ctrl(_Repo()), "week", "2026-07-13", "2026-07-19", dim="category")
        self.assertEqual(keys, ["浏览", "开发", "其他"])
        self.assertEqual(rows[0], [3600, 1800, 0])

    def test_range_browser_empty_no_crash(self) -> None:
        from eye_care.api.common import _timebars_for_range
        _, keys, rows = _timebars_for_range(_Ctrl(_EmptyRepo()), "week", "2026-07-13", "2026-07-19", dim="browser")
        self.assertEqual(keys, ["其他"])
        self.assertTrue(all(r == [0] for r in rows))


# ── 2. SnapshotService timebar_dim ───────────────────────────────────────────
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


class _SnapRepo(_Repo):
    def get_hourly_usage(self, d):
        return {0: 1500}

    def get_events(self, d):
        return []

    def get_app_category(self, app):
        return "浏览" if app == "chrome.exe" else "开发"


class _SnapController:
    def __init__(self, record_browser_enabled: bool):
        self.repo = _SnapRepo()
        self.cfg = _Cfg(record_browser_enabled)

    def snapshot_today(self):
        vm = _VM("2026-07-19", {"chrome.exe": 3600, "code.exe": 1800})
        extra = {"state": _State(), "app_paths": {}, "idle_s": 0, "fg": "", "rest": {}, "debug": {}}
        return vm, extra

    def snapshot_for_date(self, d):
        return self.snapshot_today()

    def get_display_name(self, k):
        return {"chrome.exe": "Chrome", "code.exe": "Code"}.get(k, k)


def _get_snapshot(controller, *, range_key="day", dim="app"):
    from eye_care.services.context import ServiceContext
    from eye_care.services.snapshot_service import SnapshotService
    ctx = ServiceContext(controller=controller, log=logging.getLogger("test"))
    svc = SnapshotService(ctx)
    return svc.get_snapshot(query={"range": range_key, "dim": dim})


class SnapshotTimebarDimTests(unittest.TestCase):
    def test_dim_category_normal(self) -> None:
        payload = _get_snapshot(_SnapController(True), dim="category")
        self.assertEqual(payload["timebar_dim"], "category")
        self.assertEqual(payload["timebar_keys"], ["浏览", "开发", "其他"])

    def test_dim_browser_enabled(self) -> None:
        payload = _get_snapshot(_SnapController(True), dim="browser")
        self.assertEqual(payload["timebar_dim"], "browser")
        self.assertEqual(payload["timebar_keys"], ["a.com", "b.com", "其他"])

    def test_dim_browser_disabled_falls_back_to_app(self) -> None:
        payload = _get_snapshot(_SnapController(False), dim="browser")
        # 开关关 → 回退 app
        self.assertEqual(payload["timebar_dim"], "app")
        self.assertEqual(payload["timebar_keys"], ["chrome.exe", "code.exe", "其他"])

    def test_dim_illegal_falls_back_to_app(self) -> None:
        payload = _get_snapshot(_SnapController(True), dim="nonsense")
        self.assertEqual(payload["timebar_dim"], "app")


# ── 3. RightPanelBridge setDim ───────────────────────────────────────────────
def _bridge_snapshot(dim: str) -> dict:
    """模拟后端按 dim 已回写好的 snapshot。"""
    if dim == "browser":
        keys = ["a.com", "b.com", "其他"]
    elif dim == "category":
        keys = ["浏览", "开发", "其他"]
    else:
        keys = ["chrome.exe", "code.exe", "其他"]
    return {
        "range_key": "day",
        "timebar_dim": dim,
        "vm": {"local_date": "2026-07-19", "daily_usage": {"chrome.exe": 3600, "code.exe": 1800}},
        "usage_by_category": {"浏览": 3600, "开发": 1800},
        "range_usage_by_category": {"浏览": 3600, "开发": 1800},
        "range_daily_usage": {"chrome.exe": 3600, "code.exe": 1800},
        "browser_domains": {"a.com": 3600, "b.com": 1800},
        "range_browser_domains": {"a.com": 3600, "b.com": 1800},
        "display_names": {"chrome.exe": "Chrome", "code.exe": "Code"},
        "app_paths": {},
        "timebar_labels": [str(i) for i in range(24)],
        "timebar_keys": keys,
        "timebar_values": [[1000, 500, 0]] + [[0, 0, 0]] * 23,
        "rest": {},
        "range_start": "2026-07-19",
        "range_end": "2026-07-19",
    }


class RightPanelSetDimTests(unittest.TestCase):
    def _make(self):
        from eye_care.qt_quick.right_panel_bridge import RightPanelBridge
        seen = {"dim": None}

        def provider(range_key, date=None, rs=None, re=None, *, dim="app"):
            seen["dim"] = dim
            return _bridge_snapshot(dim)

        bridge = RightPanelBridge(provider, today_str="2026-07-19")
        return bridge, seen

    def test_setdim_normalizes(self) -> None:
        bridge, _ = self._make()
        bridge.setDim("browser")
        self.assertEqual(bridge._dim, "browser")
        bridge.setDim("bro")
        self.assertEqual(bridge._dim, "browser")
        bridge.setDim("cat")
        self.assertEqual(bridge._dim, "category")
        bridge.setDim("whatever")
        self.assertEqual(bridge._dim, "app")

    def test_setdim_triggers_recompute_and_passes_dim(self) -> None:
        bridge, seen = self._make()
        self.assertEqual(seen["dim"], "app")   # 初次 _recompute
        bridge.setDim("browser")
        self.assertEqual(seen["dim"], "browser")   # provider 收到 dim

    def test_setdim_reset_anim_emitted(self) -> None:
        bridge, _ = self._make()
        fired = {"n": 0}
        bridge.resetAnim.connect(lambda: fired.__setitem__("n", fired["n"] + 1))
        bridge.setDim("category")
        self.assertEqual(fired["n"], 1)
        # 同一 dim 再切不重复触发
        bridge.setDim("category")
        self.assertEqual(fired["n"], 1)

    def test_top4_browser_uses_domain_names(self) -> None:
        bridge, _ = self._make()
        bridge.setDim("browser")
        names = [t["name"] for t in bridge.top4]
        self.assertIn("a.com", names)
        self.assertIn("b.com", names)
        # 柱状图 series 也用 domain 名
        snames = [s["name"] for s in bridge.barSeries]
        self.assertIn("a.com", snames)

    def test_top4_category_uses_category_names(self) -> None:
        bridge, _ = self._make()
        bridge.setDim("category")
        names = [t["name"] for t in bridge.top4]
        self.assertIn("浏览", names)
        self.assertIn("开发", names)

    def test_top4_app_uses_resolved_names(self) -> None:
        bridge, _ = self._make()
        # 默认 app 维度：display_names 解析 chrome.exe→Chrome
        names = [t["name"] for t in bridge.top4]
        self.assertIn("Chrome", names)


if __name__ == "__main__":
    unittest.main()
