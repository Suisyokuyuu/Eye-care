"""M4：显示名与黑名单工具，仅依赖 config，不依赖 repo。"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import AppConfig


def get_display_name(cfg: AppConfig, app_short: str) -> str:
    """显示名：有别名用别名，否则去掉 .exe（仅展示层，不改 repo key）。"""
    if not app_short:
        return ""
    overrides = getattr(cfg, "app_display_overrides", None) or {}
    if app_short in overrides and overrides[app_short]:
        return str(overrides[app_short]).strip()
    s = str(app_short).strip()
    if s.lower().endswith(".exe"):
        return s[:-4].strip() or s
    return s


def is_blacklisted(cfg: AppConfig, app_short: str) -> bool:
    """是否在黑名单（排除计时）。"""
    if not app_short:
        return False
    blacklist = getattr(cfg, "blacklist_apps", None) or []
    return app_short in blacklist
