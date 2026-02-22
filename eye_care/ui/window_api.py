from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional
import threading

from eye_care.diagnostics.debug_switch import is_debug_enabled
from eye_care.diagnostics import diag, log_exception_summary


def _convert_file_types(file_types: tuple) -> tuple:
    """
    将 pywebview 格式转换为 tkinter 格式。
    pywebview: "ZIP Files (*.zip)" 
    tkinter: ("ZIP Files", "*.zip")
    """
    import re
    result = []
    for ft in file_types:
        # 匹配 "Description (*.ext)" 格式
        match = re.match(r'^(.+?)\s*\((\*\.\w+)\)$', ft.strip())
        if match:
            desc, ext = match.groups()
            result.append((desc, ext))
        else:
            # 如果不匹配，尝试提取 *.ext
            ext_match = re.search(r'(\*\.\w+)', ft)
            if ext_match:
                result.append((ft, ext_match.group(1)))
            else:
                result.append((ft, "*.*"))
    return tuple(result)


def _create_file_dialog_safe(dialog_type: str, **kwargs) -> Optional[str | list[str]]:
    """
    使用 tkinter.filedialog 替代 pywebview 的 create_file_dialog。
    pywebview 6.1 在 Windows 上有 bug，使用 tkinter 作为后备方案。
    """
    import tkinter as tk
    from tkinter import filedialog

    # 创建隐藏的 root 窗口
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    try:
        if dialog_type == "save":
            save_filename = kwargs.get("save_filename", "")
            file_types = kwargs.get("file_types", ("All files (*.*)",))
            # 转换 file_types 格式
            ft_tuple = _convert_file_types(file_types)
            path = filedialog.asksaveasfilename(
                initialfile=save_filename,
                filetypes=ft_tuple,
                title=kwargs.get("title", "Save File")
            )
            return path if path else None
        elif dialog_type == "open":
            allow_multiple = kwargs.get("allow_multiple", False)
            file_types = kwargs.get("file_types", ("All files (*.*)",))
            ft_tuple = _convert_file_types(file_types)
            if allow_multiple:
                paths = filedialog.askopenfilenames(
                    filetypes=ft_tuple,
                    title=kwargs.get("title", "Open File")
                )
                return list(paths) if paths else None
            else:
                path = filedialog.askopenfilename(
                    filetypes=ft_tuple,
                    title=kwargs.get("title", "Open File")
                )
                return path if path else None
        return None
    finally:
        root.destroy()


class WindowApi:
    """pywebview JS API: keep window behavior separate from main orchestrator. 所有 window 操作经 dispatcher 投递到 GUI 线程。"""

    def __init__(
        self,
        *,
        data_dir: Path,
        logger: logging.Logger,
        controller_getter: Callable[[], object | None],
        controller_ready_getter: Callable[[], bool],
        close_rest_overlay_cb: Callable[[], None],
        dispatcher: Optional[Any] = None,
    ) -> None:
        self._window = None
        self._maximized = False
        self._data_dir = Path(data_dir)
        self._tray_enabled = False
        self._rest_show_overlay_fn = None
        self._set_visible_cb = None  # M5: 隐藏时同步主窗口可见状态
        self._dispatcher = dispatcher

        self._log = logger
        self._controller_getter = controller_getter
        self._controller_ready_getter = controller_ready_getter
        self._close_rest_overlay_cb = close_rest_overlay_cb
        self._rest_ready_cb = None  # (screen_idx: int) -> None，由 RestWindowController 注入

    def set_rest_ready_callback(self, cb: Optional[Callable[[int], None]]) -> None:
        """Rest 页加载完成后调用 rest_ready_for_show(screen_idx) 会触发此回调（经 dispatcher 到 GUI）。"""
        self._rest_ready_cb = cb

    def rest_ready_for_show(self, screen_idx: int) -> None:
        """Rest 页首帧/DOM 就绪时由前端调用，便于后端仅在 ready 后再 show，避免首帧黑屏。"""
        try:
            idx = int(screen_idx)
        except (TypeError, ValueError):
            idx = 0
        cb = getattr(self, "_rest_ready_cb", None)
        if self._dispatcher and cb:
            self._dispatcher.post(lambda: cb(idx))
        elif cb:
            try:
                cb(idx)
            except Exception:
                self._log.exception("rest_ready_for_show callback failed: screen_idx=%s", idx)

    def set_dispatcher(self, dispatcher: Any) -> None:
        """注入 GuiDispatcher（main 在创建 dispatcher 后调用）。"""
        self._dispatcher = dispatcher

    def rest_show_overlay(self):
        fn = getattr(self, "_rest_show_overlay_fn", None)
        if fn:
            return fn()
        diag.emit("DIAG_REST_SHOW_FN_NOT_SET", self._log, "显示休息遮罩被调用但未注入回调", level=logging.WARNING)
        return None

    def set_window(self, w):
        self._window = w

    def set_tray_enabled(self, on: bool):
        self._tray_enabled = bool(on)

    def set_visible_cb(self, cb: Optional[Callable[[bool], None]]):
        """M5：设置窗口显隐状态回调，hide 时调用 cb(False) 以同步唯一真源。"""
        self._set_visible_cb = cb

    def _wait_controller(self, timeout: float = 5.0):
        deadline = time.time() + float(timeout)
        while (not self._controller_ready_getter()) and time.time() < deadline:
            time.sleep(0.05)
        return self._controller_getter()

    def close_window(self):
        if self._dispatcher:
            if is_debug_enabled():
                diag.emit("DIAG_DISPATCH_WINDOW_OP", self._log, "窗口操作经Dispatcher投递", op="关闭主窗口")
            self._dispatcher.post(self._do_close_window)
            return
        self._do_close_window()

    def _do_close_window(self):
        if self._window and self._tray_enabled:
            try:
                self._window.hide()
                if self._set_visible_cb:
                    self._set_visible_cb(False)
                return
            except Exception:
                self._log.exception("close_window hide failed")
        if self._window:
            self._window.destroy()

    def minimize_window(self):
        if self._dispatcher and self._window:
            if is_debug_enabled():
                diag.emit("DIAG_DISPATCH_WINDOW_OP", self._log, "窗口操作经Dispatcher投递", op="最小化主窗口")
            self._dispatcher.post(lambda: self._window.minimize() if self._window else None)
            return
        if self._window:
            self._window.minimize()

    def maximize_toggle(self):
        if not self._window:
            return
        if self._dispatcher:
            if is_debug_enabled():
                diag.emit("DIAG_DISPATCH_WINDOW_OP", self._log, "窗口操作经Dispatcher投递", op="最大化/还原主窗口")
            self._dispatcher.post(self._do_maximize_toggle)
            return
        self._do_maximize_toggle()

    def _do_maximize_toggle(self):
        if not self._window:
            return
        try:
            if self._maximized:
                self._window.restore()
                self._maximized = False
            else:
                self._window.maximize()
                self._maximized = True
        except Exception:
            self._log.exception("maximize_toggle failed")

    def close_rest_overlay(self):
        if self._dispatcher:
            if is_debug_enabled():
                diag.emit("DIAG_DISPATCH_WINDOW_OP", self._log, "窗口操作经Dispatcher投递", op="隐藏休息遮罩")
            self._dispatcher.post(lambda: self._close_rest_overlay_cb() if self._close_rest_overlay_cb else None)
        else:
            try:
                self._close_rest_overlay_cb()
            except Exception:
                self._log.exception("close_rest_overlay callback failed")
        return {"ok": True}

    def rest_overlay_log(self, payload: dict):
        try:
            from eye_care.diagnostics.debug_switch import is_debug_enabled
            s = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
            if is_debug_enabled():
                diag.emit("DIAG_REST_OVERLAY_LOG", self._log, "休息遮罩前端埋点", payload=s[:500] if len(s) > 500 else s)
            return {"ok": True}
        except Exception:
            log_exception_summary(self._log, "DIAG_EXCEPTION", "休息遮罩前端日志上报", "仅记录失败，不影响功能")
            return {"ok": False}

    def export_all(self):
        try:
            ctrl = self._wait_controller()
            if not ctrl:
                return {"status": "error", "error": "Controller not ready"}

            from eye_care.data.transfer import export_all

            try:
                if hasattr(ctrl, "repo") and ctrl.repo:
                    import sqlite3

                    db_path = self._data_dir / "eyecare.db"
                    if db_path.exists():
                        conn = sqlite3.connect(str(db_path))
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        conn.close()
            except Exception as e:
                self._log.warning(f"WAL checkpoint failed: {e}")

            import webview

            # 使用 tkinter 替代 pywebview（pywebview 6.1 有 bug）
            path = _create_file_dialog_safe(
                "save",
                save_filename="eye_care_export.zip",
                file_types=("ZIP Files (*.zip)", "All files (*.*)"),
            )
            if not path:
                return {"status": "cancel"}
            out_path = Path(path if isinstance(path, str) else path[0]).resolve()
            meta = export_all(self._data_dir, out_path)
            return {"status": "ok", "path": str(out_path), "meta": meta}
        except Exception as e:
            self._log.exception("export_all failed")
            return {"status": "error", "error": str(e)}

    def import_all(self):
        try:
            ctrl = self._wait_controller()
            if not ctrl:
                return {"status": "error", "error": "Controller not ready"}

            from eye_care.data.transfer import import_all

            path = _create_file_dialog_safe(
                "open",
                allow_multiple=False,
                file_types=("ZIP Files (*.zip)", "JSON Files (*.json)", "All files (*.*)"),
            )
            if not path:
                return {"status": "cancel"}
            in_path = Path(path if isinstance(path, str) else path[0]).resolve()
            res = import_all(self._data_dir, in_path, repo=ctrl.repo)
            try:
                ctrl.repo.merge()
            except Exception as e:
                self._log.warning("import_all: repo.merge after import failed: %s", e)
            return {"status": "ok", "path": str(in_path), "result": res}
        except Exception as e:
            self._log.exception("import_all failed")
            return {"status": "error", "error": str(e)}

    def export_settings(self):
        """导出设置：将 config.json 内容保存到用户选择的 JSON 文件。"""
        try:
            ctrl = self._wait_controller()
            if not ctrl:
                return {"status": "error", "error": "Controller not ready"}
            import webview
            from dataclasses import asdict
            path = _create_file_dialog_safe(
                "save",
                save_filename="eye_care_settings.json",
                file_types=("JSON Files (*.json)", "All files (*.*)"),
            )
            if not path:
                return {"status": "cancel"}
            out_path = Path(path if isinstance(path, str) else path[0]).resolve()
            raw = asdict(ctrl.cfg)
            raw.pop("sample_interval_s", None)
            raw.pop("debug_enabled", None)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"status": "ok", "path": str(out_path)}
        except Exception as e:
            self._log.exception("export_settings failed")
            return {"status": "error", "error": str(e)}

    def import_settings(self):
        """导入设置：从用户选择的 JSON 文件读入并合并到当前 config，写回 config.json。"""
        try:
            ctrl = self._wait_controller()
            if not ctrl:
                return {"status": "error", "error": "Controller not ready"}
            import webview
            from dataclasses import asdict, fields
            from eye_care.config.models import AppConfig
            from eye_care.config.store import save_config
            path = _create_file_dialog_safe(
                "open",
                allow_multiple=False,
                file_types=("JSON Files (*.json)", "All files (*.*)"),
            )
            if not path:
                return {"status": "cancel"}
            in_path = Path(path if isinstance(path, str) else path[0]).resolve()
            data = json.loads(in_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"status": "error", "error": "无效的设置文件格式"}
            allowed = {f.name for f in fields(AppConfig)}
            export_excluded = {"sample_interval_s", "debug_enabled"}
            filtered = {k: v for k, v in data.items() if k in allowed and k not in export_excluded}
            current = asdict(ctrl.cfg) if hasattr(ctrl, "cfg") else {}
            merged = {**current, **filtered}
            merged = {k: merged[k] for k in allowed if k in merged}
            for key, default in (
                ("app_category_overrides", {}),
                ("app_display_overrides", {}),
                ("app_auto_dnd_on_focus", {}),
                ("blacklist_apps", []),
            ):
                if key not in merged:
                    merged[key] = default
                if key == "blacklist_apps" and isinstance(merged[key], list):
                    merged[key] = [str(x).strip() for x in merged[key] if x]
            new_cfg = AppConfig(**merged)
            ctrl.cfg = new_cfg
            save_config(ctrl.cfg_path, ctrl.cfg)
            
            # 同步1：运行态配置
            ctrl.on_config_updated()
            
            # 同步2：分类覆盖到repo
            if hasattr(ctrl.repo, 'set_category_overrides'):
                ctrl.repo.set_category_overrides(
                    getattr(new_cfg, 'app_category_overrides', None) or {}
                )
            
            # 同步3：启动登录即时应用
            if hasattr(new_cfg, 'startup_launch_at_login'):
                try:
                    from eye_care.utils.launch_at_login import set_launch_at_login
                    set_launch_at_login(bool(new_cfg.startup_launch_at_login))
                except Exception as e:
                    self._log.warning("import_settings: launch_at_login apply failed: %s", e)
            
            return {"status": "ok", "path": str(in_path)}
        except Exception as e:
            self._log.exception("import_settings failed")
            return {"status": "error", "error": str(e)}
