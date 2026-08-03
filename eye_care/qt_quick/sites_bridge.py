"""站点设置 + 站点详情 QML 数据桥（浏览器站点归并功能）。

「应用设置」页顶部「网站」页签列出各站点（按 site_key 归并后，含图标/时长，扫近 90 天，
懒加载：AppSettingsPage.onOpen 才 reload）。点站点进「站点详情页」；左栏浏览器视图点击
域名卡片也打开同一详情页。

站点详情：站点图标+名称、显示名编辑（site_display_overrides，key=site_key，留空=显示域名）、
子域名列表（该站点范围内近 90 天实际出现过的原始 host，每行 host/时长/勾选框「独立统计」）。
勾选 → host 加入独立名单（变成自己的站点）；取消 → 并回主域名。裸主域名行（host==注册域本身）
不给勾选框。所有变更即时生效并回溯（展示层合并）。

设计与 apps_bridge 同构：
  - build_sites_io(controller, persist, ...) 造 IO（复用 ConfigService.update_config 落库，
    复用 favicon 解析器取站点图标）；persist=False 预览沙箱只 log。
  - SitesBridge(io) 暴露 sitesList / detail 属性 + reload / openSite / setIndependent /
    setDisplayName 槽；变更后 emit configApplied，由 runtime_shell 接到左右栏 refresh。
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Callable, Optional

from PySide6.QtCore import QObject, Property, Signal, Slot

from eye_care.utils.site_rules import merge_domain_usage, registrable_domain, site_key
from .left_panel_bridge import format_work_time

log = logging.getLogger(__name__)

_SCAN_DAYS = 90


def build_sites_io(controller, *, persist: bool, log: Optional[logging.Logger] = None,
                   today: Optional[str] = None,
                   domain_icon_resolver: Optional[Callable[[str], str]] = None,
                   domain_icon_clearer: Optional[Callable[[str], bool]] = None):
    """围绕 controller 造站点设置 IO（复用 ConfigService + favicon 解析器）。

    persist=True（生产）：set_independent/set_display_name 经 ConfigService.update_config 落库。
    persist=False（预览）：只 log（沙箱，不落盘、不动 cfg）。
    """
    lg = log or logging.getLogger(__name__)
    from eye_care.services.context import ServiceContext
    from eye_care.services.config_service import ConfigService

    cfgsvc = ConfigService(ServiceContext(controller=controller, log=lg))
    _today = today
    _icon_cache: dict = {}

    def _today_str() -> str:
        return _today or _dt.date.today().isoformat()

    def _independent() -> list:
        return list(getattr(controller.cfg, "site_independent_hosts", None) or [])

    def _overrides() -> dict:
        return dict(getattr(controller.cfg, "site_display_overrides", None) or {})

    def _raw_usage() -> dict:
        """近 90 天各**原始 host**（未归并）秒数。功能从未开过 → {}。"""
        from eye_care.data.repository import DateRange
        try:
            end = _dt.date.fromisoformat(_today_str())
        except Exception:  # noqa: BLE001
            end = _dt.date.today()
        start = end - _dt.timedelta(days=_SCAN_DAYS - 1)
        try:
            return controller.repo.get_domain_usage_range(
                DateRange(start_local_date=start.isoformat(), end_local_date=end.isoformat())) or {}
        except Exception as e:  # noqa: BLE001
            lg.warning("sites: 读取 domain 范围失败: %s", e)
            return {}

    def _icon_for(host: str) -> str:
        """host → favicon data_url（成功永久缓存；取不到 → "" 走首字母兜底）。

        未命中不设重试上限，理由同 `left_panel_bridge._domain_icon_for`：解析器只读
        本地缓存不联网，而图标要等站点累计够时长才被抓下来，设上限会白白漏显示。
        """
        if not host or not domain_icon_resolver:
            return ""
        if host in _icon_cache:
            return _icon_cache[host]
        try:
            url = domain_icon_resolver(host) or ""
        except Exception:  # noqa: BLE001
            url = ""
        if url:
            _icon_cache[host] = url
        return url

    def _apply(body: dict) -> None:
        if not persist:
            lg.info("[sites 预览沙箱] %s（不落盘）", body)
            return
        cfgsvc.update_config(body=body)

    class _SitesIO:
        def list(self) -> list:
            independent = _independent()
            overrides = _overrides()
            merged = merge_domain_usage(_raw_usage(), independent)
            items = sorted(merged.items(), key=lambda kv: int(kv[1] or 0), reverse=True)
            out = []
            for sk, sec in items:
                sec = int(sec or 0)
                out.append({
                    "siteKey": sk,
                    "displayName": overrides.get(sk) or sk,
                    "dur": format_work_time(sec),
                    "sec": sec,
                    "icon": _icon_for(sk),
                    "independent": sk in independent,
                })
            return out

        def detail(self, sk: str) -> dict:
            sk = str(sk or "").strip().lower().rstrip(".")
            independent = _independent()
            overrides = _overrides()
            raw = _raw_usage()
            # 站点范围 = 当前 site_key 命中该站点的原始 host（含站点自身定义 host，
            # 使独立站点取消勾选后该行仍可见，不会「点一下就消失」）。
            rows_src = []
            for host, sec in raw.items():
                h = str(host or "").strip().lower().rstrip(".")
                if not h:
                    continue
                if site_key(h, independent) == sk or h == sk:
                    rows_src.append((h, int(sec or 0)))
            rows_src.sort(key=lambda x: x[1], reverse=True)
            hosts = []
            for host, sec in rows_src:
                reg = registrable_domain(host)
                hosts.append({
                    "host": host,
                    "sec": sec,
                    "dur": format_work_time(sec),
                    "independent": host in independent,
                    # 裸主域名行（host==注册域本身）不给勾选框。
                    "checkable": host != reg,
                })
            return {
                "siteKey": sk,
                "title": overrides.get(sk) or sk,
                "displayNameOverride": overrides.get(sk, ""),
                "icon": _icon_for(sk),
                "isIndependentSite": sk in independent,
                "hosts": hosts,
            }

        def set_independent(self, host: str, on: bool) -> None:
            host = str(host or "").strip().lower().rstrip(".")
            if not host:
                return
            cur = _independent()
            has = host in cur
            if on and not has:
                cur = cur + [host]
            elif not on and has:
                cur = [x for x in cur if x != host]
            else:
                return
            _apply({"site_independent_hosts": cur})

        def clear_icon(self, sk: str) -> bool:
            """清掉该站点的图标缓存（不落配置，纯缓存操作，故不走 `_apply`/persist）。

            预览沙箱下 domain_icon_clearer 为 None → 无操作返回 False。
            """
            sk = str(sk or "").strip().lower().rstrip(".")
            if not sk or not domain_icon_clearer:
                return False
            try:
                ok = bool(domain_icon_clearer(sk))
            except Exception as e:  # noqa: BLE001
                lg.warning("sites: 清除图标缓存失败 %s: %s", sk, e)
                return False
            _icon_cache.pop(sk, None)   # 本地解析缓存也要丢，否则详情页还显示旧图标
            return ok

        def set_display_name(self, sk: str, name: str) -> None:
            sk = str(sk or "").strip().lower().rstrip(".")
            if not sk:
                return
            name = str(name or "").strip()
            ov = _overrides()
            if name:
                ov[sk] = name
            else:
                ov.pop(sk, None)
            _apply({"site_display_overrides": ov})

    return _SitesIO()


class SitesBridge(QObject):
    """站点设置/详情桥（见模块 docstring）。"""

    sitesListChanged = Signal()
    detailChanged = Signal()
    configApplied = Signal()   # 归并规则/显示名变更 → runtime_shell 接到左右栏 refresh
    iconCacheCleared = Signal()  # 图标缓存被清 → 左栏需丢掉自己那份 data_url 缓存

    def __init__(self, io, *, parent=None):
        super().__init__(parent)
        self._io = io
        self._sites: list = []
        self._detail: dict = {}
        self._current: str = ""
        # 不在构造期 reload：list 会扫 90 天，放到页面打开时再拉（AppSettingsPage.onOpen 调 reload）。

    @Property("QVariantList", notify=sitesListChanged)
    def sitesList(self) -> list:
        return self._sites

    @Property("QVariantMap", notify=detailChanged)
    def detail(self) -> dict:
        return self._detail

    @Slot()
    def reload(self) -> None:
        try:
            self._sites = self._io.list()
        except Exception as e:  # noqa: BLE001
            log.warning("sites list 读取失败: %s", e)
            self._sites = []
        self.sitesListChanged.emit()

    @Slot(str)
    def openSite(self, site_key_arg: str) -> None:
        sk = str(site_key_arg or "").strip().lower().rstrip(".")
        if not sk:
            return
        self._current = sk
        try:
            self._detail = self._io.detail(sk)
        except Exception as e:  # noqa: BLE001
            log.warning("site detail 读取失败 %s: %s", sk, e)
            self._detail = {"siteKey": sk, "title": sk, "displayNameOverride": "",
                            "icon": "", "isIndependentSite": False, "hosts": []}
        self.detailChanged.emit()

    def _after_config_change(self) -> None:
        """配置变更后：刷新详情（若有）与列表，并通知外部（左右栏）刷新。"""
        if self._current:
            try:
                self._detail = self._io.detail(self._current)
                self.detailChanged.emit()
            except Exception as e:  # noqa: BLE001
                log.warning("site detail 刷新失败 %s: %s", self._current, e)
        self.reload()
        self.configApplied.emit()

    @Slot(str, bool)
    def setIndependent(self, host: str, on: bool) -> None:
        try:
            self._io.set_independent(host, bool(on))
        except Exception as e:  # noqa: BLE001
            log.warning("setIndependent 失败 %s=%s: %s", host, on, e)
            return
        self._after_config_change()

    @Slot()
    def clearIcon(self) -> None:
        """清掉当前站点的图标缓存（详情页「清除图标缓存」按钮）。

        只动缓存不动配置，所以不走 `_after_config_change`：刷新详情 + 列表让图标立刻
        变回首字母，再 emit `iconCacheCleared` 让左栏丢掉它自己那份 data_url 缓存。
        """
        if not self._current:
            return
        try:
            self._io.clear_icon(self._current)
        except Exception as e:  # noqa: BLE001
            log.warning("clearIcon 失败 %s: %s", self._current, e)
            return
        try:
            self._detail = self._io.detail(self._current)
            self.detailChanged.emit()
        except Exception as e:  # noqa: BLE001
            log.warning("site detail 刷新失败 %s: %s", self._current, e)
        self.reload()
        self.iconCacheCleared.emit()

    @Slot(str, str)
    def setDisplayName(self, site_key_arg: str, name: str) -> None:
        try:
            self._io.set_display_name(site_key_arg, name)
        except Exception as e:  # noqa: BLE001
            log.warning("setDisplayName 失败 %s: %s", site_key_arg, e)
            return
        self._after_config_change()
