"""应用设置 + 应用详情 QML 数据桥（step3）。

复刻 web `#appSettingsModal`（已记录应用列表，可搜索→点进详情）与 `#appDetailModal`
（左:使用时间段小时柱图；右:类别下拉(可加新类)/显示名/前台自动勿扰/排除计时）。

后端逻辑**直接复用** StatsService/ConfigService（读操作只读安全）：
  - 列表    StatsService.get_apps_list
  - 类别名  ConfigService.get_category_names
  - 详情    StatsService.get_app_details（hourly_seconds_for_date + 当前 category/display/auto_dnd）
  - 保存    StatsService.update_app_settings
  - 排除    StatsService.exclude_app（**删数据，破坏性**）
预览沙箱(persist=False)：list/categories/detail 照常读真，save/exclude 只 log 不落盘（exclude 尤其不能跑）。

QML 侧 contextProperty `appsBridge`：列表读 `appsList`，类别读 `categories`，
点应用调 `openDetail(appShort)` 填 `detail`，保存 `saveDetail({...})`，排除 `excludeApp(appShort)`，加类 `addCategory(name)`。
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, Property, Signal, Slot

log = logging.getLogger(__name__)


def _daily_series(daily: dict, range_start, range_end) -> list:
    """{iso:秒} → 按 range_start..range_end 顺序的 [{label:"M/D", sec}]（复刻 web appTimeChart 的逐日柱）。"""
    import datetime as _dt
    out: list = []
    try:
        start = _dt.date.fromisoformat(str(range_start))
        end = _dt.date.fromisoformat(str(range_end))
        cur = start
        while cur <= end:
            iso = cur.isoformat()
            out.append({"label": f"{cur.month}/{cur.day}", "sec": int((daily or {}).get(iso, 0) or 0)})
            cur += _dt.timedelta(days=1)
    except Exception:  # noqa: BLE001
        for k in sorted((daily or {}).keys()):
            out.append({"label": str(k)[5:].replace("-", "/"), "sec": int(daily[k] or 0)})
    return out


def build_apps_io(controller, *, persist: bool, log: Optional[logging.Logger] = None):
    """围绕 controller 造应用设置 IO（复用 StatsService/ConfigService）。

    persist=True（生产）：save/exclude 落库。
    persist=False（预览）：save/exclude 只 log（沙箱，exclude 破坏性，绝不在预览跑）。
    """
    lg = log or logging.getLogger(__name__)
    from eye_care.services.context import ServiceContext
    from eye_care.services.stats_service import StatsService
    from eye_care.services.config_service import ConfigService

    ctx = ServiceContext(controller=controller, log=lg)
    stats = StatsService(ctx)
    cfgsvc = ConfigService(ctx)
    _ICON_MAX_RETRIES = 5
    _icon_cache: dict = {}
    _icon_miss_count: dict = {}

    def _icon_for(app_short: str) -> str:
        if not app_short:
            return ""
        if app_short in _icon_cache:
            return _icon_cache[app_short]
        if _icon_miss_count.get(app_short, 0) >= _ICON_MAX_RETRIES:
            return ""
        try:
            url = (cfgsvc.get_icon(app_short=app_short) or {}).get("data_url") or ""
        except Exception:
            url = ""
        if url:
            _icon_cache[app_short] = url
            _icon_miss_count.pop(app_short, None)
        else:
            _icon_miss_count[app_short] = _icon_miss_count.get(app_short, 0) + 1
        return url

    class _AppsIO:
        def list(self) -> list:
            apps = stats.get_apps_list().get("apps", []) or []
            for a in apps:
                if isinstance(a, dict):
                    a["icon"] = _icon_for(str(a.get("app_short") or ""))
            return apps

        def categories(self) -> list:
            return cfgsvc.get_category_names().get("categories", ["其他"]) or ["其他"]

        def detail(self, app: str) -> dict:
            d = stats.get_app_details(query={"app": app, "days": 7}) or {}
            paths = {}
            try:
                paths = controller.get_app_paths() or {}
            except Exception:  # noqa: BLE001
                paths = {}
            hourly = d.get("hourly_seconds_for_date") or {}
            # 使用时间段图表（复刻 web appTimeChart）：range_start..range_end 按天的使用秒数。
            daily = d.get("daily_seconds") or {}
            series = _daily_series(daily, d.get("range_start"), d.get("range_end"))
            return {
                "appShort": app,
                "title": d.get("display_name") or app,
                "path": paths.get(app, "") or paths.get(app.lower(), ""),
                "icon": _icon_for(app),
                "daily": series,
                "hourly": [int(hourly.get(str(h), 0) or 0) for h in range(24)],
                "category": d.get("category") or "其他",
                "displayNameOverride": d.get("display_name_override") or "",
                "autoDnd": bool(d.get("auto_dnd_on_focus")),
            }

        def save(self, app: str, payload: dict) -> None:
            if not persist:
                lg.info("[apps 预览沙箱] 保存 %s = %s（不落盘）", app, payload)
                return
            stats.update_app_settings(body={"app_short": app, **(payload or {})})

        def exclude(self, app: str) -> None:
            if not persist:
                lg.info("[apps 预览沙箱] 排除 %s（破坏性，预览跳过）", app)
                return
            stats.exclude_app(app_short=app)

    return _AppsIO()


class AppsBridge(QObject):
    appsListChanged = Signal()
    categoriesChanged = Signal()
    detailChanged = Signal()

    def __init__(self, io, *, parent=None):
        super().__init__(parent)
        self._io = io
        self._apps: list = []
        self._categories: list = ["其他"]
        self._detail: dict = {}
        # 不在构造期 reload：get_apps_list 会扫 90 天，放到页面打开时再拉（AppSettingsPage.onOpen 调 reload），避免拖慢启动。

    @Property("QVariantList", notify=appsListChanged)
    def appsList(self) -> list:
        return self._apps

    @Property("QVariantList", notify=categoriesChanged)
    def categories(self) -> list:
        return self._categories

    @Property("QVariantMap", notify=detailChanged)
    def detail(self) -> dict:
        return self._detail

    @Slot()
    def reload(self) -> None:
        try:
            self._apps = self._io.list()
        except Exception as e:  # noqa: BLE001
            log.warning("apps list 读取失败: %s", e)
            self._apps = []
        try:
            self._categories = self._io.categories()
        except Exception as e:  # noqa: BLE001
            log.warning("categories 读取失败: %s", e)
            self._categories = ["其他"]
        self.appsListChanged.emit()
        self.categoriesChanged.emit()

    @Slot(str)
    def openDetail(self, app_short: str) -> None:
        app_short = str(app_short or "").strip()
        if not app_short:
            return
        # 从左栏卡片直接进详情时，列表可能还没加载过类别 → 确保下拉有数据。
        if len(self._categories) <= 1:
            try:
                self._categories = self._io.categories()
                self.categoriesChanged.emit()
            except Exception:  # noqa: BLE001
                pass
        try:
            self._detail = self._io.detail(app_short)
        except Exception as e:  # noqa: BLE001
            log.warning("app detail 读取失败 %s: %s", app_short, e)
            self._detail = {"appShort": app_short, "title": app_short, "hourly": [0] * 24,
                            "category": "其他", "displayNameOverride": "", "autoDnd": False, "path": ""}
        self.detailChanged.emit()

    @Slot(str)
    def addCategory(self, name: str) -> None:
        name = str(name or "").strip()
        if not name or name in self._categories:
            return
        self._categories = sorted(set(self._categories) | {name})
        self.categoriesChanged.emit()

    @Slot("QVariantMap")
    def saveDetail(self, payload) -> None:
        p = dict(payload) if payload else {}
        app = str(p.pop("appShort", "") or self._detail.get("appShort", "")).strip()
        if not app:
            return
        body = {}
        if "category" in p:
            body["category"] = str(p["category"] or "其他")
        if "displayName" in p:
            body["display_name"] = str(p["displayName"] or "").strip()
        if "autoDnd" in p:
            body["auto_dnd_on_focus"] = bool(p["autoDnd"])
        try:
            self._io.save(app, body)
        except Exception as e:  # noqa: BLE001
            log.warning("app save 失败 %s: %s", app, e)
        self.reload()

    @Slot(str)
    def excludeApp(self, app_short: str) -> None:
        app_short = str(app_short or "").strip()
        if not app_short:
            return
        try:
            self._io.exclude(app_short)
        except Exception as e:  # noqa: BLE001
            log.warning("app exclude 失败 %s: %s", app_short, e)
        # 乐观：从列表移除（沙箱也即时反映）
        self._apps = [a for a in self._apps if a.get("app_short") != app_short]
        self.appsListChanged.emit()
