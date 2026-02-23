"""
Config routes.
"""
import json
import tempfile
import webbrowser
from dataclasses import fields
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from ...config.models import AppConfig
from ...config.store import save_config
from ...diagnostics import log_exception_summary
from ...version import APP_VERSION
from ..common import API_VERSION


_allowed_config_keys = {f.name for f in fields(AppConfig)}
_icon_stat_fail_cache: dict = {}  # 模块级：仅在每 app 首次 stat 失败时记录 log.warning


def register_config_routes(app: Flask, controller, log):
    @app.route("/api/config", methods=["GET"])
    def get_config():
        try:
            cfg = controller.cfg
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
            return jsonify({"api_version": API_VERSION, "config": out})
        except Exception as e:
            log.exception("get_config failed")
            return jsonify({"error": str(e), "code": "config_error"}), 500

    @app.route("/api/config", methods=["POST"])
    def post_config():
        try:
            body = request.get_json(force=True, silent=True) or {}
            cfg = controller.cfg
            updates = {k: v for k, v in body.items() if k in _allowed_config_keys}
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
                    from ...utils.launch_at_login import set_launch_at_login
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
            save_config(controller.cfg_path, cfg)
            controller.on_config_updated()
            return jsonify({"ok": True, "api_version": API_VERSION})
        except Exception as e:
            log.exception("post_config failed")
            return jsonify({"error": str(e), "code": "config_error"}), 500

    @app.route("/api/icon", methods=["GET"])
    def icon():
        try:
            import hashlib
            import os

            app_short = request.args.get("app", "").strip()
            if not app_short:
                return jsonify({"error": "missing app", "code": "bad_request"}), 400

            icons_dir = Path(controller.data_dir) / "app_icons"
            icons_dir.mkdir(parents=True, exist_ok=True)
            index_path = icons_dir / "icon_index.json"

            # icon_index.json 格式: {app_short: {"sha1": xxx, "mtime": yyy, "size": zzz}}
            icon_index = {}
            if index_path.exists():
                try:
                    icon_index = json.loads(index_path.read_text(encoding="utf-8") or "{}")
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as e:
                    log.debug("icon index read failed: %s", e)
                    icon_index = {}
            if not isinstance(icon_index, dict):
                icon_index = {}

            paths = controller.get_app_paths()
            exe_path = paths.get(app_short)
            if not exe_path:
                # app 路径未知或已被清理：返回稳定的错误码，避免重复 stat
                return jsonify({"error": "app path unknown", "code": "icon_file_missing"}), 404

            exe_path_obj = Path(exe_path)

            def _cleanup_and_404_missing_exe(reason: str):
                """当检测到 exe 已不存在时，自清理 app_paths 并返回统一错误响应。"""
                removed = False
                remove_fn = getattr(controller, "remove_app_path", None)
                try:
                    if callable(remove_fn):
                        removed = bool(remove_fn(app_short, exe_path))
                except Exception as cleanup_err:
                    log_exception_summary(
                        log,
                        "DIAG_EXCEPTION",
                        "app_paths icon cleanup",
                        "degrade_continue",
                        detail=str(cleanup_err)[:200],
                        reason_code="E_CONTROLLER_FALLBACK",
                    )
                if removed:
                    log.info("icon: removed stale app_path for app=%s reason=%s", app_short, reason)
                return jsonify({"error": "file not found", "code": "icon_file_missing"}), 404

            # 检查缓存是否有效（mtime/size 变化检测 + sha1 校验）
            cached = icon_index.get(app_short) or icon_index.get(app_short.lower())
            cache_valid = False
            current_mtime = None
            current_size = None

            try:
                exe_stat = exe_path_obj.stat()
                current_mtime = exe_stat.st_mtime
                current_size = exe_stat.st_size
            except Exception as e:
                if app_short not in _icon_stat_fail_cache:
                    _icon_stat_fail_cache[app_short] = True
                    log.warning("config: stat exe failed for %s: %s", app_short, e)
                # 若文件已不存在，则就地自清理 app_paths 并返回明确错误码
                try:
                    if not exe_path_obj.exists():
                        return _cleanup_and_404_missing_exe("stat_failed_missing")
                except Exception:
                    # exists() 异常视为非致命，继续后续流程
                    pass

            if cached and isinstance(cached, dict):
                cached_mtime = cached.get("mtime")
                cached_size = cached.get("size")
                cached_sha1 = cached.get("sha1")

                # mtime 检查（1秒误差内视为相同）
                if cached_mtime and current_mtime and abs(cached_mtime - current_mtime) < 1:
                    cache_valid = True
                # size 备选检查
                elif cached_size and current_size and cached_size == current_size:
                    cache_valid = True

                if cache_valid and cached_sha1:
                    png_path = icons_dir / f"{cached_sha1}.png"
                    if png_path.exists():
                        return send_file(str(png_path), mimetype="image/png", max_age=3600)

            # 缓存无效，重新提取图标（分块读取，1MB/块，上限 64MB，失败兜底）
            _ICON_HASH_CHUNK = 1024 * 1024
            _ICON_HASH_MAX = 64 * 1024 * 1024
            exe_sha1 = None
            try:
                st = exe_path_obj.stat()
                if st.st_size > _ICON_HASH_MAX:
                    log.debug("icon hash skipped: file too large (%s > %s)", st.st_size, _ICON_HASH_MAX)
                else:
                    h = hashlib.sha1()
                    with open(exe_path, "rb") as f:
                        while True:
                            chunk = f.read(_ICON_HASH_CHUNK)
                            if not chunk:
                                break
                            h.update(chunk)
                    exe_sha1 = h.hexdigest()
            except Exception as e:
                log.debug("exe sha1 compute failed: %s", e)

            # 如果文件不存在，直接返回错误并自清理（避免调用 Windows API 导致阻塞）
            if not exe_path_obj.exists():
                return _cleanup_and_404_missing_exe("exists_check_missing")

            try:
                from ...ui.win_icon_extract import extract_icon_to_png
            except Exception as e:
                log.exception("icon extract import failed")
                return jsonify({"error": str(e), "code": "icon_unavailable"}), 500

            # 保存到缓存目录
            if exe_sha1 and current_mtime:
                cached_png_path = icons_dir / f"{exe_sha1}.png"
                if extract_icon_to_png(exe_path, str(cached_png_path), size=64):
                    icon_index[app_short] = {
                        "sha1": exe_sha1,
                        "mtime": current_mtime,
                        "size": current_size,
                    }
                    try:
                        index_path.write_text(json.dumps(icon_index, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception as e:
                        log.debug("icon index write failed: %s", e)
                    return send_file(str(cached_png_path), mimetype="image/png", max_age=3600)

            # 缓存失败时使用临时文件
            fd, out_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            temp_in_use = False
            try:
                if extract_icon_to_png(exe_path, out_path, size=64):
                    temp_in_use = True
                    resp = send_file(out_path, mimetype="image/png", max_age=3600)

                    def _cleanup_temp() -> None:
                        try:
                            Path(out_path).unlink(missing_ok=True)
                        except OSError as e:
                            log.debug("icon temp cleanup failed: %s", e)

                    # 使用 call_on_close 在响应发送完成后再删除，避免 Windows 下“文件占用删除失败”
                    try:
                        resp.call_on_close(_cleanup_temp)
                    except Exception:
                        # 极端情况下退化为同步清理（行为与旧版一致）
                        _cleanup_temp()
                    return resp
            finally:
                # 提取失败或中途异常时，同步尝试删除；成功路径由 _cleanup_temp 负责
                if not temp_in_use:
                    try:
                        Path(out_path).unlink(missing_ok=True)
                    except OSError as e:
                        log.debug("icon temp cleanup failed (fallback): %s", e)
            return jsonify({"error": "extract failed", "code": "icon_error"}), 500
        except Exception as e:
            log.exception("icon failed")
            return jsonify({"error": str(e), "code": "icon_error"}), 500

    @app.route("/api/categories", methods=["GET"])
    def get_categories():
        try:
            get_cats = getattr(controller.repo, "get_app_categories", None)
            if not get_cats:
                return jsonify({"error": "not supported", "code": "categories_error"}), 501
            mapping = get_cats()
            return jsonify({"api_version": API_VERSION, "categories": mapping})
        except Exception as e:
            log.exception("get_categories failed")
            return jsonify({"error": str(e), "code": "categories_error"}), 500

    @app.route("/api/categories", methods=["POST"])
    def post_categories():
        try:
            body = request.get_json(force=True, silent=True) or {}
            mapping = body.get("categories")
            if not isinstance(mapping, dict):
                return jsonify({"error": "categories must be a dict", "code": "categories_error"}), 400
            save_cats = getattr(controller.repo, "save_app_categories", None)
            if not save_cats:
                return jsonify({"error": "not supported", "code": "categories_error"}), 501
            save_cats({str(k): str(v) for k, v in mapping.items()})
            return jsonify({"ok": True, "api_version": API_VERSION})
        except Exception as e:
            log.exception("post_categories failed")
            return jsonify({"error": str(e), "code": "categories_error"}), 500

    @app.route("/api/category_names", methods=["GET"])
    def category_names():
        """分类名列表（去重，含「其他」），供 app_details 下拉用。"""
        try:
            get_cats = getattr(controller.repo, "get_app_categories", None)
            overrides = getattr(controller.cfg, "app_category_overrides", None) or {}
            names = set()
            if get_cats:
                for v in get_cats().values():
                    if v and str(v).strip():
                        names.add(str(v).strip())
            for v in overrides.values():
                if v and str(v).strip():
                    names.add(str(v).strip())
            names.discard("")
            names.add("其他")
            return jsonify({"api_version": API_VERSION, "categories": sorted(names)})
        except Exception as e:
            log.exception("category_names failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/categories/delete", methods=["POST"])
    def categories_delete():
        """删除分类：将该分类下所有 app 改为「其他」（repo + config 覆盖）。"""
        try:
            body = request.get_json(force=True, silent=True) or {}
            name = (body.get("name") or "").strip()
            if not name:
                return jsonify({"error": "name required", "code": "categories_error"}), 400
            repo = controller.repo
            cfg = controller.cfg
            get_cats = getattr(repo, "get_app_categories", None)
            if not get_cats:
                return jsonify({"error": "not supported", "code": "categories_error"}), 501
            mapping = get_cats()
            changed = {k: "其他" for k, v in mapping.items() if v == name}
            if changed:
                new_mapping = dict(mapping)
                for k in changed:
                    new_mapping[k] = "其他"
                getattr(repo, "save_app_categories", lambda x: None)(new_mapping)
            overrides = getattr(cfg, "app_category_overrides", None) or {}
            overrides = dict(overrides)
            override_changed = False
            for k, v in list(overrides.items()):
                if v == name:
                    overrides[k] = "其他"
                    override_changed = True
            if override_changed:
                cfg.app_category_overrides = overrides
                save_config(controller.cfg_path, cfg)
                if hasattr(controller.repo, "set_category_overrides"):
                    controller.repo.set_category_overrides(cfg.app_category_overrides)
            return jsonify({"ok": True, "api_version": API_VERSION})
        except Exception as e:
            log.exception("categories/delete failed")
            return jsonify({"error": str(e), "code": "categories_error"}), 500

    @app.route("/api/update/check", methods=["GET"])
    def update_check():
        try:
            import time
            import urllib.error
            import urllib.request
            from ..common import _update_check_cache, _UPDATE_CACHE_TTL, _parse_semver
            now = time.time()
            if _update_check_cache and (now - _update_check_cache.get("_ts", 0)) < _UPDATE_CACHE_TTL:
                c = _update_check_cache
                return jsonify({
                    "ok": True,
                    "current": c.get("current", APP_VERSION),
                    "latest": c.get("latest", ""),
                    "has_update": c.get("has_update", False),
                    "html_url": c.get("html_url", ""),
                    "asset_url": c.get("asset_url", ""),
                    "error": "",
                })
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
            return jsonify({
                "ok": True,
                "current": APP_VERSION,
                "latest": tag or "0.0.0",
                "has_update": has_update,
                "html_url": html_url,
                "asset_url": asset_url,
                "error": "",
            })
        except urllib.error.HTTPError as e:
            err = str(e)
            if e.code == 403:
                err = "请求过于频繁，请稍后再试"
            _update_check_cache["_ts"] = 0
            return jsonify({
                "ok": False,
                "current": APP_VERSION,
                "latest": "",
                "has_update": False,
                "html_url": "",
                "asset_url": "",
                "error": err,
            })
        except Exception as e:
            log.exception("update_check failed")
            return jsonify({
                "ok": False,
                "current": APP_VERSION,
                "latest": "",
                "has_update": False,
                "html_url": "",
                "asset_url": "",
                "error": str(e)[:200],
            })

    # action 白名单：仅允许预定义动作，后端映射固定 URL，不再接收任意 URL
    _OPEN_URL_ACTIONS = {
        "release_notes": "https://github.com/Suisyokuyuu/Eye-care/releases",
        "help": "https://github.com/Suisyokuyuu/Eye-care",
    }

    @app.route("/api/open_url", methods=["POST"])
    def open_url():
        try:
            data = request.get_json() or {}
            action = (data.get("action") or "").strip()
            if not action or action not in _OPEN_URL_ACTIONS:
                return jsonify({"ok": False, "error": "仅支持预定义 action: release_notes, help"}), 400
            url = _OPEN_URL_ACTIONS[action]
            webbrowser.open(url)
            return jsonify({"ok": True})
        except Exception as e:
            log.exception("open_url failed")
            return jsonify({"ok": False, "error": str(e)[:200]}), 500
