"""浏览器站点归并功能测试（展示层）。

覆盖：
  1. AppConfig 新字段默认值 + ConfigService get/update 对称支持。
  2. SnapshotService browser_domains 归并 + payload 带 site_display_overrides。
  3. api.common._timebars_for_day/_range browser 维度归并（keys=site_key）。
  4. 左/右栏桥 browser 分支显示名套用点（key 仍 site_key，label 套 override）。
  5. SitesBridge / build_sites_io：list 归并、detail 子站点行、set_independent/set_display_name。

开发机 Linux 无 PySide6 → 内联最小 QtCore stub，在 import 被测桥模块前注入。
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path


# ── 最小 PySide6.QtCore stub ─────────────────────────────────────────────────
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
        def __init__(self, *a, **k) -> None:
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

    def Slot(*a, **k):
        def deco(fn):
            return fn
        return deco

    def Property(*a, **k):
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

from eye_care.config.models import AppConfig  # noqa: E402
from eye_care.services.context import ServiceContext  # noqa: E402
from eye_care.services.config_service import ConfigService  # noqa: E402
from eye_care.services.snapshot_service import SnapshotService  # noqa: E402
from eye_care.api.common import _timebars_for_day, _timebars_for_range  # noqa: E402
from eye_care.qt_quick.left_panel_bridge import LeftPanelBridge  # noqa: E402
from eye_care.qt_quick.right_panel_bridge import RightPanelBridge  # noqa: E402
from eye_care.qt_quick.sites_bridge import SitesBridge, build_sites_io  # noqa: E402

_LOG = logging.getLogger("test")


# ── 1. 配置默认值 + get/update ───────────────────────────────────────────────
class _CfgCtrl:
    def __init__(self, cfg, cfg_path):
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.updated = 0

    def on_config_updated(self):
        self.updated += 1


class ConfigChainTests(unittest.TestCase):
    def test_defaults(self):
        cfg = AppConfig()
        self.assertEqual(cfg.site_independent_hosts,
                         ["drive.google.com", "photos.google.com", "mail.google.com"])
        self.assertEqual(cfg.site_display_overrides, {})

    def test_get_config_returns_fields(self):
        with tempfile.TemporaryDirectory() as d:
            ctrl = _CfgCtrl(AppConfig(), Path(d) / "cfg.json")
            svc = ConfigService(ServiceContext(controller=ctrl, log=_LOG))
            out = svc.get_config()["config"]
            self.assertEqual(out["site_independent_hosts"],
                             ["drive.google.com", "photos.google.com", "mail.google.com"])
            self.assertEqual(out["site_display_overrides"], {})

    def test_update_config_symmetric(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "cfg.json"
            ctrl = _CfgCtrl(AppConfig(), path)
            svc = ConfigService(ServiceContext(controller=ctrl, log=_LOG))
            svc.update_config(body={
                "site_independent_hosts": ["Mail.Google.com.", "x.com", "x.com"],  # 规整+去重
                "site_display_overrides": {"mail.google.com": "Gmail", "bad": ""},  # 空值剔除
            })
            self.assertEqual(ctrl.cfg.site_independent_hosts, ["mail.google.com", "x.com"])
            self.assertEqual(ctrl.cfg.site_display_overrides, {"mail.google.com": "Gmail"})
            self.assertTrue(ctrl.updated >= 1)
            # 已落盘
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["site_independent_hosts"], ["mail.google.com", "x.com"])


# ── 2. Snapshot 归并 + display overrides ─────────────────────────────────────
class _State:
    is_paused = is_dnd = force_idle = auto_idle = False


class _VM:
    def __init__(self, d, u):
        self.local_date = d
        self.daily_usage = u


class _SnapCfg:
    blacklist_apps: list = []

    def __init__(self, ind, overrides):
        self.record_browser_enabled = True
        self.site_independent_hosts = ind
        self.site_display_overrides = overrides


class _SnapRepo:
    def get_daily_usage(self, d):
        return {"chrome": 3600}

    def get_usage_range(self, dr, dim="app"):
        return {"浏览": 3600} if dim == "category" else {"chrome": 3600}

    def get_hourly_usage(self, d):
        return {0: 3600}

    def get_events(self, d):
        return []

    def get_app_category(self, app):
        return "浏览"

    def get_daily_domain_usage(self, d):
        return {"bilibili.com": 100, "space.bilibili.com": 50,
                "mail.google.com": 40, "accounts.google.com": 7}

    def get_domain_usage_range(self, dr):
        return {"bilibili.com": 200, "space.bilibili.com": 100, "mail.google.com": 80}


class _SnapCtrl:
    def __init__(self, ind, overrides):
        self.repo = _SnapRepo()
        self.cfg = _SnapCfg(ind, overrides)

    def snapshot_today(self):
        return _VM("2026-07-19", {"chrome": 3600}), {
            "state": _State(), "app_paths": {}, "idle_s": 0, "fg": "", "rest": {}, "debug": {}}

    def snapshot_for_date(self, d):
        return self.snapshot_today()

    def get_display_name(self, k):
        return k


class SnapshotMergeTests(unittest.TestCase):
    def _snap(self, range_key="day"):
        ctrl = _SnapCtrl(["mail.google.com"], {"mail.google.com": "Gmail"})
        svc = SnapshotService(ServiceContext(controller=ctrl, log=_LOG))
        return svc.get_snapshot(query={"range": range_key})

    def test_browser_domains_merged(self):
        p = self._snap("day")
        # space.bilibili.com 并入 bilibili.com；accounts.google.com 并入 google.com；
        # mail.google.com 独立保留。
        self.assertEqual(p["browser_domains"],
                         {"bilibili.com": 150, "google.com": 7, "mail.google.com": 40})
        self.assertEqual(p["site_display_overrides"], {"mail.google.com": "Gmail"})

    def test_range_merged(self):
        p = self._snap("week")
        self.assertEqual(p["range_browser_domains"],
                         {"bilibili.com": 300, "mail.google.com": 80})


# ── 3. timebars 归并 ─────────────────────────────────────────────────────────
class _TbRepo:
    def get_daily_domain_usage(self, d):
        return {"bilibili.com": 100, "space.bilibili.com": 50, "mail.google.com": 40}

    def get_hourly_domain_breakdown(self, d):
        return {9: {"bilibili.com": 60, "space.bilibili.com": 30, "mail.google.com": 20}}

    def get_domain_usage_range(self, dr):
        return {"bilibili.com": 100, "space.bilibili.com": 50, "mail.google.com": 40}


class _TbCtrl:
    def __init__(self, ind):
        self.repo = _TbRepo()
        self.cfg = types.SimpleNamespace(site_independent_hosts=ind)


class TimebarsMergeTests(unittest.TestCase):
    def test_day_keys_merged(self):
        labels, keys, rows = _timebars_for_day(_TbCtrl(["mail.google.com"]), "2026-07-19", dim="browser")
        self.assertIn("bilibili.com", keys)
        self.assertIn("mail.google.com", keys)
        self.assertNotIn("space.bilibili.com", keys)
        # 第 9 小时 bilibili.com 桶 = 60+30 = 90
        idx_b = keys.index("bilibili.com")
        self.assertEqual(rows[9][idx_b], 90)

    def test_range_keys_merged(self):
        labels, keys, rows = _timebars_for_range(
            _TbCtrl(["mail.google.com"]), "week", "2026-07-13", "2026-07-19", dim="browser")
        self.assertIn("bilibili.com", keys)
        self.assertNotIn("space.bilibili.com", keys)


# ── 4. 左/右栏桥 browser 显示名套用点 ────────────────────────────────────────
def _browser_snap():
    return {
        "range_key": "day",
        "vm": {"local_date": "2026-07-19", "daily_usage": {}},
        "record_browser_enabled": True,
        "browser_domains": {"mail.google.com": 100, "google.com": 50},
        "range_browser_domains": {"mail.google.com": 100, "google.com": 50},
        "site_display_overrides": {"mail.google.com": "Gmail"},
        "range_start": "2026-07-19", "range_end": "2026-07-19",
        # 右栏 timebar 字段
        "timebar_dim": "browser",
        "timebar_labels": ["9"],
        "timebar_keys": ["mail.google.com", "其他"],
        "timebar_values": [[100, 0]],
        "display_names": {}, "app_paths": {},
    }


class BridgeDisplayNameTests(unittest.TestCase):
    def test_left_browser_label_override(self):
        snap = _browser_snap()
        bridge = LeftPanelBridge(lambda *a, **k: snap, today_str="2026-07-19")
        bridge.setView("browser")
        by_key = {it["key"]: it for it in bridge.appList}
        self.assertEqual(by_key["mail.google.com"]["name"], "Gmail")   # label 套 override
        self.assertEqual(by_key["google.com"]["name"], "google.com")   # 无 override → 原域名
        # key 仍是 site_key（颜色/图标按它走）
        self.assertIn("mail.google.com", by_key)

    def test_right_browser_series_and_top4_override(self):
        snap = _browser_snap()
        bridge = RightPanelBridge(lambda *a, **k: snap, today_str="2026-07-19")
        bridge.setDim("browser")
        names = {s["key"]: s["name"] for s in bridge.barSeries}
        self.assertEqual(names.get("mail.google.com"), "Gmail")
        top_names = [t["name"] for t in bridge.top4]
        self.assertIn("Gmail", top_names)


# ── 5. SitesBridge / build_sites_io ──────────────────────────────────────────
class _SitesRepo:
    def __init__(self, raw):
        self._raw = raw

    def get_domain_usage_range(self, dr):
        return dict(self._raw)


class _SitesCtrl:
    def __init__(self, cfg, cfg_path, raw):
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.repo = _SitesRepo(raw)

    def on_config_updated(self):
        pass


class SitesBridgeTests(unittest.TestCase):
    _RAW = {
        "bilibili.com": 100, "space.bilibili.com": 50,
        "mail.google.com": 40, "foo.mail.google.com": 5,
        "google.com": 30, "accounts.google.com": 7,
    }

    def _make(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        cfg = AppConfig(site_independent_hosts=["mail.google.com"])
        ctrl = _SitesCtrl(cfg, Path(self._tmp.name) / "cfg.json", self._RAW)
        io = build_sites_io(ctrl, persist=True, log=_LOG, today="2026-07-19",
                            domain_icon_resolver=lambda d: "ic:" + d)
        return SitesBridge(io), ctrl

    def test_list_merged(self):
        bridge, _ = self._make()
        bridge.reload()
        by = {s["siteKey"]: s for s in bridge.sitesList}
        self.assertEqual(by["bilibili.com"]["sec"], 150)
        self.assertEqual(by["google.com"]["sec"], 37)       # google + accounts
        self.assertEqual(by["mail.google.com"]["sec"], 45)  # mail + foo.mail
        self.assertTrue(by["mail.google.com"]["independent"])
        self.assertEqual(by["bilibili.com"]["icon"], "ic:bilibili.com")

    def test_detail_hosts_checkable(self):
        bridge, _ = self._make()
        bridge.openSite("bilibili.com")
        rows = {h["host"]: h for h in bridge.detail["hosts"]}
        self.assertFalse(rows["bilibili.com"]["checkable"])       # 裸主域名不给勾选框
        self.assertTrue(rows["space.bilibili.com"]["checkable"])
        self.assertFalse(rows["space.bilibili.com"]["independent"])

    def test_detail_independent_site(self):
        bridge, _ = self._make()
        bridge.openSite("mail.google.com")
        rows = {h["host"]: h for h in bridge.detail["hosts"]}
        self.assertTrue(bridge.detail["isIndependentSite"])
        self.assertTrue(rows["mail.google.com"]["independent"])
        self.assertTrue(rows["mail.google.com"]["checkable"])
        self.assertIn("foo.mail.google.com", rows)

    def test_set_independent_on_and_off(self):
        bridge, ctrl = self._make()
        bridge.openSite("bilibili.com")
        # 勾选独立统计 space.bilibili.com
        bridge.setIndependent("space.bilibili.com", True)
        self.assertIn("space.bilibili.com", ctrl.cfg.site_independent_hosts)
        by = {s["siteKey"]: s for s in bridge.sitesList}
        self.assertIn("space.bilibili.com", by)                 # 成了独立站点
        self.assertEqual(by["bilibili.com"]["sec"], 100)        # 主域名不再含子站点
        # 取消勾选已独立的 mail.google.com → 并回 google.com
        bridge.setIndependent("mail.google.com", False)
        self.assertNotIn("mail.google.com", ctrl.cfg.site_independent_hosts)
        by2 = {s["siteKey"]: s for s in bridge.sitesList}
        self.assertNotIn("mail.google.com", by2)
        self.assertEqual(by2["google.com"]["sec"], 82)          # 30+7+40+5

    def test_set_display_name(self):
        bridge, ctrl = self._make()
        bridge.setDisplayName("bilibili.com", "B站")
        self.assertEqual(ctrl.cfg.site_display_overrides.get("bilibili.com"), "B站")
        by = {s["siteKey"]: s for s in bridge.sitesList}
        self.assertEqual(by["bilibili.com"]["displayName"], "B站")
        # 清空 → 移除 override
        bridge.setDisplayName("bilibili.com", "  ")
        self.assertNotIn("bilibili.com", ctrl.cfg.site_display_overrides)

    def test_config_applied_signal(self):
        bridge, _ = self._make()
        fired = {"n": 0}
        bridge.configApplied.connect(lambda: fired.__setitem__("n", fired["n"] + 1))
        bridge.setDisplayName("google.com", "谷歌")
        self.assertEqual(fired["n"], 1)


if __name__ == "__main__":
    unittest.main()
