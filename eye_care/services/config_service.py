from __future__ import annotations

from eye_care.api.common import API_VERSION
from eye_care.config.models import AppConfig
from eye_care.config.store import save_config

from .context import ServiceContext


class ConfigService:
    """Home for configuration, icon, category, update, and URL actions.

    Target routes:
    - GET /api/config
    - POST /api/config
    - GET /api/icon
    - GET /api/categories
    - POST /api/categories
    - GET /api/category_names
    - POST /api/categories/delete
    - GET /api/update/check
    - POST /api/open_url
    """

    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx
        self._allowed_config_keys = {f.name for f in AppConfig.__dataclass_fields__.values()}

    def get_config(self) -> dict:
        cfg = self.ctx.controller.cfg
        out = {
            "reminder_work_minutes": int(getattr(cfg, "reminder_work_minutes", 20)),
            "reminder_rest_seconds": int(getattr(cfg, "reminder_rest_seconds", 20)),
            "reminder_rest_unit": str(getattr(cfg, "reminder_rest_unit", "sec")),
            "idle_threshold_s": int(getattr(cfg, "idle_threshold_s", 60)),
            "theme_name": str(getattr(cfg, "theme_name", "solid_dark")),
            "startup_dnd": bool(getattr(cfg, "startup_dnd", False)),
            "startup_show_main": bool(getattr(cfg, "startup_show_main", True)),
            "startup_launch_at_login": bool(getattr(cfg, "startup_launch_at_login", False)),
            "notify_enabled": bool(getattr(cfg, "notify_enabled", True)),
            "notify_sound_enabled": bool(getattr(cfg, "notify_sound_enabled", True)),
            "notify_auto_hide_seconds": int(getattr(cfg, "notify_auto_hide_seconds", 20)),
            "rest_end_sound_enabled": bool(getattr(cfg, "rest_end_sound_enabled", True)),
        }
        return {"api_version": API_VERSION, "config": out}

    def update_config(self, *, body: dict) -> dict:
        cfg = self.ctx.controller.cfg
        log = self.ctx.log
        updates = {k: v for k, v in (body or {}).items() if k in self._allowed_config_keys}
        if "reminder_work_minutes" in updates:
            cfg.reminder_work_minutes = max(1, int(updates["reminder_work_minutes"]))
        if "reminder_rest_seconds" in updates:
            cfg.reminder_rest_seconds = max(1, int(updates["reminder_rest_seconds"]))
        if "reminder_rest_unit" in updates and updates["reminder_rest_unit"] in ("sec", "min"):
            cfg.reminder_rest_unit = updates["reminder_rest_unit"]
        if "idle_threshold_s" in updates:
            cfg.idle_threshold_s = max(3, min(300, int(updates["idle_threshold_s"])))
        if "theme_name" in updates:
            cfg.theme_name = str(updates["theme_name"])
        if "startup_dnd" in updates:
            cfg.startup_dnd = bool(updates["startup_dnd"])
        if "startup_show_main" in updates:
            cfg.startup_show_main = bool(updates["startup_show_main"])
        if "startup_launch_at_login" in updates:
            cfg.startup_launch_at_login = bool(updates["startup_launch_at_login"])
            try:
                from eye_care.utils.launch_at_login import set_launch_at_login
                set_launch_at_login(cfg.startup_launch_at_login)
            except Exception as e:
                log.warning("launch_at_login apply failed: %s", e)
        if "notify_enabled" in updates:
            cfg.notify_enabled = bool(updates["notify_enabled"])
        if "notify_sound_enabled" in updates:
            cfg.notify_sound_enabled = bool(updates["notify_sound_enabled"])
        if "notify_auto_hide_seconds" in updates:
            v = int(updates["notify_auto_hide_seconds"])
            cfg.notify_auto_hide_seconds = max(0, min(600, v))
        if "rest_end_sound_enabled" in updates:
            cfg.rest_end_sound_enabled = bool(updates["rest_end_sound_enabled"])
        save_config(self.ctx.controller.cfg_path, cfg)
        self.ctx.controller.on_config_updated()
        return {"ok": True, "api_version": API_VERSION}

    def get_icon(self, *, app_short: str) -> dict:
        raise NotImplementedError("Step 2 skeleton only: icon extraction not wired yet")

    def get_categories(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: categories extraction not wired yet")

    def save_categories(self, *, mapping: dict) -> dict:
        raise NotImplementedError("Step 2 skeleton only: categories extraction not wired yet")

    def get_category_names(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: categories extraction not wired yet")

    def delete_category(self, *, name: str) -> dict:
        raise NotImplementedError("Step 2 skeleton only: categories extraction not wired yet")

    def check_update(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: update extraction not wired yet")

    def open_url_action(self, *, action: str) -> dict:
        raise NotImplementedError("Step 2 skeleton only: open_url extraction not wired yet")
