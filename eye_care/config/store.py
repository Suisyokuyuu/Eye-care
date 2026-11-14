from __future__ import annotations
import json
from dataclasses import asdict, fields
from pathlib import Path
from .models import AppConfig

def load_config(path: Path) -> AppConfig:
    """Load persisted config.

    - Ignores unknown keys (forward/backward compatible).
    - Applies basic sanity clamps.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return AppConfig()

        allowed = {f.name for f in fields(AppConfig)}
        filtered = {k: v for k, v in data.items() if k in allowed}
        for key, default in (
            ("app_category_overrides", {}),
            ("app_display_overrides", {}),
            ("app_auto_dnd_on_focus", {}),
            ("blacklist_apps", []),
            # 站点显示名别名（key=site_key）。site_independent_hosts 不列此处——其默认
            # 非空（预置 Google 三件套），交给 dataclass default_factory 兜底，避免被 [] 覆盖。
            ("site_display_overrides", {}),
        ):
            if key not in filtered:
                filtered[key] = default
            if key == "blacklist_apps" and isinstance(filtered[key], list):
                filtered[key] = [str(x).strip() for x in filtered[key] if x]

        cfg = AppConfig(**filtered)

        # ---- sanity clamp ----
        try:
            cfg.idle_threshold_s = max(3, min(300, int(cfg.idle_threshold_s)))
        except Exception:
            cfg.idle_threshold_s = 60
        try:
            cfg.reminder_work_minutes = max(1, int(cfg.reminder_work_minutes))
        except Exception:
            cfg.reminder_work_minutes = 20
        try:
            cfg.reminder_rest_seconds = max(1, int(cfg.reminder_rest_seconds))
        except Exception:
            cfg.reminder_rest_seconds = 20
        if getattr(cfg, "reminder_rest_unit", "") not in ("sec", "min"):
            cfg.reminder_rest_unit = "sec"

        try:
            cfg.toast_fade_seconds = max(0, int(getattr(cfg, "toast_fade_seconds", 0)))
        except Exception:
            cfg.toast_fade_seconds = 0

        try:
            cfg.notion_sync_days = max(1, min(30, int(cfg.notion_sync_days)))
        except (ValueError, TypeError):
            cfg.notion_sync_days = 7
        for key in ("notion_include_sites", "notion_sync_on_startup", "notion_sync_daily"):
            setattr(cfg, key, getattr(cfg, key) is True)
        import re
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(cfg.notion_sync_time)):
            cfg.notion_sync_time = "23:00"
        cfg.notion_parent_page = str(cfg.notion_parent_page or "")
        cfg.notion_dashboard_page = str(cfg.notion_dashboard_page or "")
        cfg.notion_device_name = str(cfg.notion_device_name or "").strip()[:60]
        cfg.background_image = str(cfg.background_image or "")
        for key, lo, hi, default in (("background_dim", 0, 80, 35), ("background_blur", 0, 30, 0),
                                      ("panel_opacity", 40, 95, 68)):
            try:
                setattr(cfg, key, max(lo, min(hi, int(getattr(cfg, key)))))
            except (ValueError, TypeError):
                setattr(cfg, key, default)

        return cfg
    except Exception:
        return AppConfig()

def save_config(path: Path, cfg: AppConfig) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
