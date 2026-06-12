from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from eye_care.api.common import API_VERSION
from eye_care.config.models import AppConfig
from eye_care.config.store import save_config

from .context import ServiceContext, ServiceError


_icon_stat_fail_cache: dict = {}


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
        app_short = str(app_short or "").strip()
        if not app_short:
            return {"error": "missing app", "code": "bad_request"}

        controller = self.ctx.controller
        log = self.ctx.log
        icons_dir = Path(controller.data_dir) / "app_icons"
        icons_dir.mkdir(parents=True, exist_ok=True)
        index_path = icons_dir / "icon_index.json"

        icon_index = {}
        if index_path.exists():
            try:
                icon_index = json.loads(index_path.read_text(encoding="utf-8") or "{}")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
                log.debug("icon index read failed: %s", exc)
                icon_index = {}
        if not isinstance(icon_index, dict):
            icon_index = {}

        paths = controller.get_app_paths()
        exe_path = paths.get(app_short)
        if not exe_path:
            return {"error": "app path unknown", "code": "icon_file_missing"}

        exe_path_obj = Path(exe_path)

        def _cleanup_missing(reason: str) -> dict:
            removed = False
            remove_fn = getattr(controller, "remove_app_path", None)
            try:
                if callable(remove_fn):
                    removed = bool(remove_fn(app_short, exe_path))
            except Exception as cleanup_err:
                log.warning("icon cleanup failed app=%s reason=%s err=%s", app_short, reason, cleanup_err)
            if removed:
                log.info("icon: removed stale app_path for app=%s reason=%s", app_short, reason)
            return {"error": "file not found", "code": "icon_file_missing"}

        cached = icon_index.get(app_short) or icon_index.get(app_short.lower())
        current_mtime = None
        current_size = None
        cache_valid = False

        try:
            exe_stat = exe_path_obj.stat()
            current_mtime = exe_stat.st_mtime
            current_size = exe_stat.st_size
        except Exception as exc:
            if app_short not in _icon_stat_fail_cache:
                _icon_stat_fail_cache[app_short] = True
                log.warning("config: stat exe failed for %s: %s", app_short, exc)
            try:
                if not exe_path_obj.exists():
                    return _cleanup_missing("stat_failed_missing")
            except Exception:
                pass

        if cached and isinstance(cached, dict):
            cached_mtime = cached.get("mtime")
            cached_size = cached.get("size")
            cached_sha1 = cached.get("sha1")
            if cached_mtime and current_mtime and abs(cached_mtime - current_mtime) < 1:
                cache_valid = True
            elif cached_size and current_size and cached_size == current_size:
                cache_valid = True
            if cache_valid and cached_sha1:
                png_path = icons_dir / f"{cached_sha1}.png"
                if png_path.exists():
                    try:
                        raw = png_path.read_bytes()
                        return {
                            "ok": True,
                            "app_short": app_short,
                            "data_url": "data:image/png;base64," + base64.b64encode(raw).decode("ascii"),
                            "cache": "hit",
                        }
                    except Exception as exc:
                        log.debug("icon cache read failed for %s: %s", app_short, exc)

        _ICON_HASH_CHUNK = 1024 * 1024
        _ICON_HASH_MAX = 64 * 1024 * 1024
        exe_sha1 = None
        try:
            st = exe_path_obj.stat()
            if st.st_size <= _ICON_HASH_MAX:
                h = hashlib.sha1()
                with open(exe_path, "rb") as f:
                    while True:
                        chunk = f.read(_ICON_HASH_CHUNK)
                        if not chunk:
                            break
                        h.update(chunk)
                exe_sha1 = h.hexdigest()
            else:
                log.debug("icon hash skipped: file too large (%s > %s)", st.st_size, _ICON_HASH_MAX)
        except Exception as exc:
            log.debug("exe sha1 compute failed: %s", exc)

        if not exe_path_obj.exists():
            return _cleanup_missing("exists_check_missing")

        try:
            from eye_care.ui.win_icon_extract import extract_icon_to_png
        except Exception as exc:
            log.exception("icon extract import failed")
            return {"error": str(exc), "code": "icon_unavailable"}

        if exe_sha1 and current_mtime:
            cached_png_path = icons_dir / f"{exe_sha1}.png"
            if extract_icon_to_png(exe_path, str(cached_png_path), size=64):
                icon_index[app_short] = {"sha1": exe_sha1, "mtime": current_mtime, "size": current_size}
                try:
                    index_path.write_text(json.dumps(icon_index, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception as exc:
                    log.debug("icon index write failed: %s", exc)
                try:
                    raw = cached_png_path.read_bytes()
                    return {
                        "ok": True,
                        "app_short": app_short,
                        "data_url": "data:image/png;base64," + base64.b64encode(raw).decode("ascii"),
                        "cache": "miss",
                    }
                except Exception as exc:
                    log.debug("cached icon read failed for %s: %s", app_short, exc)

        return {"error": "extract failed", "code": "icon_error", "app_short": app_short}

    def get_categories(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: categories extraction not wired yet")

    def save_categories(self, *, mapping: dict) -> dict:
        raise NotImplementedError("Step 2 skeleton only: categories extraction not wired yet")

    def get_category_names(self) -> dict:
        get_cats = getattr(self.ctx.controller.repo, "get_app_categories", None)
        overrides = getattr(self.ctx.controller.cfg, "app_category_overrides", None) or {}
        names = set()
        if get_cats:
            for value in get_cats().values():
                if value and str(value).strip():
                    names.add(str(value).strip())
        for value in overrides.values():
            if value and str(value).strip():
                names.add(str(value).strip())
        names.discard("")
        names.add("其他")
        return {"api_version": API_VERSION, "categories": sorted(names)}

    def delete_category(self, *, name: str) -> dict:
        name = str(name or "").strip()
        if not name:
            raise ServiceError("name required", code="categories_error", http_status=400)
        repo = self.ctx.controller.repo
        cfg = self.ctx.controller.cfg
        get_cats = getattr(repo, "get_app_categories", None)
        if not get_cats:
            raise ServiceError("not supported", code="categories_error", http_status=501)
        mapping = get_cats()
        changed = {k: "其他" for k, value in mapping.items() if value == name}
        if changed:
            new_mapping = dict(mapping)
            for key in changed:
                new_mapping[key] = "其他"
            getattr(repo, "save_app_categories", lambda x: None)(new_mapping)
        overrides = dict(getattr(cfg, "app_category_overrides", None) or {})
        override_changed = False
        for key, value in list(overrides.items()):
            if value == name:
                overrides[key] = "其他"
                override_changed = True
        if override_changed:
            cfg.app_category_overrides = overrides
            save_config(self.ctx.controller.cfg_path, cfg)
            if hasattr(repo, "set_category_overrides"):
                repo.set_category_overrides(cfg.app_category_overrides)
        return {"ok": True, "api_version": API_VERSION}

    def check_update(self) -> dict:
        from eye_care.api.common import _UPDATE_CACHE_TTL, _parse_semver, _update_check_cache
        now = time.time()
        if _update_check_cache and (now - _update_check_cache.get("_ts", 0)) < _UPDATE_CACHE_TTL:
            cached = _update_check_cache
            return {
                "ok": True,
                "current": cached.get("current", ""),
                "latest": cached.get("latest", ""),
                "has_update": cached.get("has_update", False),
                "html_url": cached.get("html_url", ""),
                "asset_url": cached.get("asset_url", ""),
                "error": "",
            }
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/Suisyokuyuu/Eye-care/releases/latest",
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "Eye-care",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            tag = (data.get("tag_name") or "").strip().lstrip("v")
            html_url = (data.get("html_url") or "").strip()
            assets = data.get("assets") or []
            asset_url = ""
            if assets and isinstance(assets[0], dict):
                asset_url = (assets[0].get("browser_download_url") or "").strip()
            from eye_care.version import APP_VERSION
            latest_ver = _parse_semver(tag or "0.0.0")
            current_ver = _parse_semver(APP_VERSION)
            has_update = latest_ver > current_ver
            _update_check_cache.update({
                "_ts": now,
                "current": APP_VERSION,
                "latest": tag or "0.0.0",
                "has_update": has_update,
                "html_url": html_url,
                "asset_url": asset_url,
            })
            return {
                "ok": True,
                "current": APP_VERSION,
                "latest": tag or "0.0.0",
                "has_update": has_update,
                "html_url": html_url,
                "asset_url": asset_url,
                "error": "",
            }
        except urllib.error.HTTPError as exc:
            from eye_care.version import APP_VERSION
            if exc.code == 404:
                release_page = "https://github.com/Suisyokuyuu/Eye-care/releases"
                _update_check_cache.update({
                    "_ts": now,
                    "current": APP_VERSION,
                    "latest": "",
                    "has_update": False,
                    "html_url": release_page,
                    "asset_url": "",
                })
                return {
                    "ok": True,
                    "current": APP_VERSION,
                    "latest": "",
                    "has_update": False,
                    "html_url": release_page,
                    "asset_url": "",
                    "error": "",
                }
            err = str(exc)
            if exc.code == 403:
                err = "请求过于频繁，请稍后再试"
            _update_check_cache["_ts"] = 0
            return {
                "ok": False,
                "current": APP_VERSION,
                "latest": "",
                "has_update": False,
                "html_url": "",
                "asset_url": "",
                "error": err,
            }
        except Exception as exc:
            self.ctx.log.exception("config_service.check_update failed")
            from eye_care.version import APP_VERSION
            return {
                "ok": False,
                "current": APP_VERSION,
                "latest": "",
                "has_update": False,
                "html_url": "",
                "asset_url": "",
                "error": str(exc)[:200],
            }

    def open_url_action(self, *, action: str) -> dict:
        action = str(action or "").strip()
        actions = {
            "release_notes": "https://github.com/Suisyokuyuu/Eye-care/releases",
            "help": "https://github.com/Suisyokuyuu/Eye-care",
        }
        if not action or action not in actions:
            raise ServiceError("不支持的操作 action: release_notes, help", code="bad_request", http_status=400)
        webbrowser.open(actions[action])
        return {"ok": True}
