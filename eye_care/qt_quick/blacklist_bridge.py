"""黑名单页 QML 数据桥（step3）。

复刻 web `#blacklistModal`：列出已排除计时的应用（display_name + app_short），可逐个移除。
后端口径对齐 StatsService.get_blacklist / remove_from_blacklist（读 cfg.blacklist_apps + get_display_name）。

设计要点（与设置桥一致）：
  - 唯一转换/移除实现，生产与预览共用，差异只在 loader/remover：
      生产 → remover 落盘(从 cfg.blacklist_apps 删 + save_config)。
      预览 → remover **沙箱**（只 log，不落盘）。
  - bridge 维护 `_items` 为列表真相；remove() 先乐观地从内存列表删并发信号，再调 remover，
    这样沙箱预览也能即时看到移除效果（不依赖 reload 回读 cfg）。

QML 侧 contextProperty `blacklistBridge`：读 `items`（[{appShort, displayName}]），点「移除」调 `remove(appShort)`。
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import QObject, Property, Signal, Slot

log = logging.getLogger(__name__)


def _display_of(controller, app_short: str) -> str:
    fn = getattr(controller, "get_display_name", None)
    if callable(fn):
        try:
            return fn(app_short)
        except Exception:  # noqa: BLE001
            pass
    return (app_short or "").replace(".exe", "") or app_short


def build_blacklist_io(controller, *, persist: bool, log: Optional[logging.Logger] = None):
    """围绕 controller.cfg.blacklist_apps 造 (loader, remover)。

    persist=True（生产）：remover 从 cfg 删 + save_config。
    persist=False（预览）：remover 只 log（沙箱）。
    """
    lg = log or logging.getLogger(__name__)

    _icon_cache: dict = {}   # appShort → data_url，避免每次 reload 重抽取

    def _icon_for(app_short: str) -> str:
        if not app_short:
            return ""
        if app_short in _icon_cache:
            return _icon_cache[app_short]
        url = ""
        try:
            from eye_care.services.context import ServiceContext
            from eye_care.services.config_service import ConfigService
            svc = ConfigService(ServiceContext(controller=controller, log=lg))
            url = (svc.get_icon(app_short=app_short) or {}).get("data_url") or ""
        except Exception:
            url = ""
        _icon_cache[app_short] = url
        return url

    def loader() -> list:
        bl = getattr(controller.cfg, "blacklist_apps", None) or []
        bl = list(bl) if isinstance(bl, (list, tuple)) else []
        return [{"appShort": a, "displayName": _display_of(controller, a), "icon": _icon_for(a)}
                for a in sorted(set(bl))]

    def remover(app_short: str) -> None:
        app_short = str(app_short or "").strip()
        if not app_short:
            return
        if not persist:
            lg.info("[blacklist 预览沙箱] 不落盘，移除=%s", app_short)
            return
        cfg = controller.cfg
        bl = getattr(cfg, "blacklist_apps", None) or []
        bl = list(bl) if isinstance(bl, (list, tuple)) else []
        if app_short in bl:
            bl.remove(app_short)
        cfg.blacklist_apps = list(sorted(set(bl)))
        from eye_care.config.store import save_config
        save_config(controller.cfg_path, cfg)
        lg.info("blacklist 移除并落盘：%s（剩 %d）", app_short, len(cfg.blacklist_apps))

    return loader, remover


class BlacklistBridge(QObject):
    """黑名单桥：QML 读 `items`、`remove(appShort)` 移除、`reload()` 重读。"""

    itemsChanged = Signal()

    def __init__(self, loader: Callable[[], list], remover: Callable[[str], None], *, parent=None):
        super().__init__(parent)
        self._loader = loader
        self._remover = remover
        self._items: list = []
        self.reload()

    @Property("QVariantList", notify=itemsChanged)
    def items(self) -> list:
        return self._items

    @Slot()
    def reload(self) -> None:
        try:
            self._items = self._loader() or []
        except Exception as e:  # noqa: BLE001
            log.warning("blacklist reload 失败: %s", e)
            self._items = []
        self.itemsChanged.emit()

    @Slot(str)
    def remove(self, app_short: str) -> None:
        app_short = str(app_short or "").strip()
        if not app_short:
            return
        # 乐观更新：先从内存列表删（沙箱预览也能即时反映），再调 remover
        self._items = [x for x in self._items if x.get("appShort") != app_short]
        self.itemsChanged.emit()
        try:
            self._remover(app_short)
        except Exception as e:  # noqa: BLE001
            log.warning("blacklist remove 落库失败: %s", e)
