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

        return cfg
    except Exception:
        return AppConfig()

def save_config(path: Path, cfg: AppConfig) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
