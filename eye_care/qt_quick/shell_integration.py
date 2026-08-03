"""外壳整合工厂（step4 接生产用）——用一个**真实 controller** 一次性造齐 AppShell 需要的全部桥。

runtime_shell 拿到就绪的 controller 后调 `build_shell_bridges(controller, persist=True)`，
再把返回的桥 setContextProperty 给 AppShell.qml 即可。persist=True 真落盘（生产）。

返回 dict（key 与 AppShell.qml 的 contextProperty 同名）：
    leftPanelBridge / rightPanelBridge / settingsBridge / blacklistBridge /
    appsBridge / updateBridge / calendarBridge，外加 provider（左右栏共享）。

注意：本工厂要求 controller 非空。
"""
from __future__ import annotations

import logging
from typing import Optional


def _build_icon_resolver(controller, lg):
    """造 app_short → 图标 data_url 的解析器（复用 ConfigService.get_icon，抽取/缓存 exe 图标）。失败 → ""。"""
    try:
        from eye_care.services.context import ServiceContext
        from eye_care.services.config_service import ConfigService
        svc = ConfigService(ServiceContext(controller=controller, log=lg))
    except Exception:
        lg.warning("icon resolver 构建失败 → 卡片用首字母兜底", exc_info=True)
        return None

    def resolver(app_short: str) -> str:
        try:
            r = svc.get_icon(app_short=app_short) or {}
            return r.get("data_url") or ""
        except Exception:
            return ""
    return resolver


def _build_domain_icon_resolver(controller, lg):
    """造 domain → favicon data_url 的解析器 + 持有 FaviconService。

    返回 `(resolver, service)`：resolver 供 LeftPanelBridge 注入（非阻塞，miss 返回 ""）；
    service 需被外层持有（防 GC）并在退出时 `stop()`。构建失败 → `(None, None)`（domain 卡片走首字母兜底）。
    FaviconService 是普通对象（非 QObject），缓存目录（domain_icons）在 data_dir 下由服务自管。
    """
    try:
        from pathlib import Path
        from eye_care.services.favicon_service import FaviconService
        data_dir = Path(getattr(controller, "data_dir", "."))
        service = FaviconService(data_dir, log=lg)
    except Exception:
        lg.warning("favicon 服务构建失败 → domain 卡片用首字母兜底", exc_info=True)
        return None, None

    def resolver(domain: str) -> str:
        # get_icon 只读本地缓存，渲染永不联网（抓取全部由下面的预取回调触发）。
        try:
            return service.get_icon(domain) or ""
        except Exception:
            return ""

    # 预取接线：controller 每拍在「用户正停留在某站点」且当天累计够久时回调，抓取便与
    # 真实浏览同时发生（详见 AppController._maybe_prefetch_favicon）。controller 不认识
    # FaviconService，只持有这个非阻塞回调；没接上 → 全程不抓，图标走首字母兜底。
    try:
        controller.set_favicon_prefetch(service.prefetch)
    except Exception:
        lg.warning("favicon 预取接线失败 → 不再抓取图标，domain 卡片走首字母兜底", exc_info=True)

    return resolver, service


def build_shell_bridges(controller, *, persist: bool, log: Optional[logging.Logger] = None,
                        today: Optional[str] = None, color_cache: Optional[dict] = None) -> dict:
    """用真实 controller 造齐 7 个桥 + provider。persist=True 真落盘；False=沙箱(写操作只 log)。"""
    if controller is None:
        raise ValueError("build_shell_bridges 需要非空 controller")
    lg = log or logging.getLogger(__name__)

    from eye_care.qt_quick.dashboard_data import make_provider
    from eye_care.qt_quick.left_panel_bridge import LeftPanelBridge
    from eye_care.qt_quick.right_panel_bridge import RightPanelBridge
    from eye_care.qt_quick.settings_bridge import SettingsBridge, build_settings_io
    from eye_care.qt_quick.blacklist_bridge import BlacklistBridge, build_blacklist_io
    from eye_care.qt_quick.apps_bridge import AppsBridge, build_apps_io
    from eye_care.qt_quick.update_bridge import UpdateBridge, build_update_io
    from eye_care.qt_quick.calendar_bridge import CalendarBridge, build_calendar_io
    from eye_care.qt_quick.sites_bridge import SitesBridge, build_sites_io

    if today is None:
        from datetime import date as _date
        today = _date.today().isoformat()
    shared_colors = color_cache if color_cache is not None else {}

    provider = make_provider(controller, lg)
    icon_resolver = _build_icon_resolver(controller, lg)
    domain_icon_resolver, favicon_service = _build_domain_icon_resolver(controller, lg)
    left = LeftPanelBridge(provider, today_str=today, color_cache=shared_colors,
                           icon_resolver=icon_resolver, domain_icon_resolver=domain_icon_resolver)
    right = RightPanelBridge(provider, today_str=today, color_cache=shared_colors)

    s_loader, s_saver = build_settings_io(controller, persist=persist, log=lg)
    settings = SettingsBridge(s_loader, s_saver)

    b_loader, b_remover = build_blacklist_io(controller, persist=persist, log=lg)
    blacklist = BlacklistBridge(b_loader, b_remover)

    apps = AppsBridge(build_apps_io(controller, persist=persist, log=lg))

    # 站点设置/详情桥：复用同一 favicon 解析器（共享 FaviconService，不另建）。
    # clearer 让详情页能清掉单个站点的图标缓存；无 service（构建失败）时为 None → 按钮无操作。
    domain_icon_clearer = favicon_service.clear if favicon_service is not None else None
    sites = SitesBridge(build_sites_io(controller, persist=persist, log=lg,
                                       today=today, domain_icon_resolver=domain_icon_resolver,
                                       domain_icon_clearer=domain_icon_clearer))

    u_checker, u_opener = build_update_io(controller, lg)
    update = UpdateBridge(u_checker, u_opener)

    calendar = CalendarBridge(build_calendar_io(controller, lg), today=today)

    lg.info("外壳桥装配完成（persist=%s）：left/right/settings/blacklist/apps/update/calendar", persist)
    return {
        "provider": provider,
        "leftPanelBridge": left,
        "rightPanelBridge": right,
        "settingsBridge": settings,
        "blacklistBridge": blacklist,
        "appsBridge": apps,
        "sitesBridge": sites,
        "updateBridge": update,
        "calendarBridge": calendar,
        # FaviconService 非 QObject、不是 contextProperty（不在 CONTEXT_PROPERTY_NAMES）：
        # 放进 dict 仅为防 GC + 供退出时 stop()。runtime_shell 循环 setContextProperty 只遍历
        # CONTEXT_PROPERTY_NAMES，不会把它当 QObject 传给 QML。
        "_faviconService": favicon_service,
    }


# AppShell.qml 需要的 contextProperty 名（runtime_shell 接线时核对用；provider 不是 contextProperty）。
CONTEXT_PROPERTY_NAMES = (
    "leftPanelBridge", "rightPanelBridge", "settingsBridge", "blacklistBridge",
    "appsBridge", "sitesBridge", "updateBridge", "calendarBridge",
)
