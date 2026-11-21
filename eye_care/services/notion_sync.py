"""Manual / scheduled Notion synchronization of the shared daily AI reports."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

from eye_care.config.store import save_config
from .ai_export import build_ai_export
from .notion_client import NotionClient, NotionError, page_id, property_text
from .notion_credentials import NotionCredentials
from .device_identity import sync_directory_lock


def _atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class NotionSyncService:
    def __init__(self, controller, *, credentials=None, client_factory=NotionClient,
                 report_builder=build_ai_export, persist=True):
        self.controller = controller
        self.credentials = credentials or NotionCredentials(controller.data_dir)
        self._client_factory = client_factory
        self._report_builder = report_builder
        self.persist = persist
        self._path = Path(controller.data_dir) / "notion_sync_state.json"
        self._lock = threading.RLock()
        self._operation = threading.Lock()
        self._closing = threading.Event()
        self._startup_checked = False
        try:
            self._state = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(self._state, dict):
                self._state = {}
        except (OSError, ValueError):
            self._state = {}
        if not isinstance(self._state.get("pages"), dict):
            self._state["pages"] = {}
        if not isinstance(self._state.get("pending_creates"), dict):
            self._state["pending_creates"] = {}

    def settings(self):
        cfg = self.controller.cfg
        return {"parent_page": str(getattr(cfg, "notion_parent_page", "") or ""),
                "dashboard_page": str(getattr(cfg, "notion_dashboard_page", "") or ""),
                "days": max(1, min(30, int(getattr(cfg, "notion_sync_days", 7) or 7))),
                "include_sites": bool(getattr(cfg, "notion_include_sites", False)),
                "on_startup": bool(getattr(cfg, "notion_sync_on_startup", False)),
                "daily": bool(getattr(cfg, "notion_sync_daily", False)),
                "time": str(getattr(cfg, "notion_sync_time", "23:00")),
                "device_name": str(getattr(cfg, "notion_device_name", "") or ""),
                "has_token": bool(self.credentials.exists())}

    def status(self):
        with self._lock:
            return {key: self._state.get(key, "") for key in
                    ("last_success_at", "last_attempt_at", "last_error", "last_page_url", "last_summary")}

    def save_settings(self, values: dict, token=""):
        if not self.persist:
            raise NotionError("预览模式不能保存同步设置。")
        parent = str(values.get("parent_page", "")).strip()
        if parent:
            parent = "https://www.notion.so/" + page_id(parent).replace("-", "")
        dashboard = str(values.get("dashboard_page", "")).strip()
        if dashboard:
            dashboard = "https://www.notion.so/" + page_id(dashboard).replace("-", "")
        sync_time = str(values.get("time", "23:00"))
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", sync_time):
            raise NotionError("同步时间请按 HH:MM 填写，例如 23:00。")
        try:
            days = int(values.get("days", 7))
        except (TypeError, ValueError):
            raise NotionError("请选择 1 到 30 天的导出范围。") from None
        if not 1 <= days <= 30:
            raise NotionError("请选择 1 到 30 天的导出范围。")
        startup, daily = bool(values.get("on_startup")), bool(values.get("daily"))
        if (startup or daily) and (not parent or not (token.strip() or self.credentials.exists())):
            raise NotionError("启用自动同步前，请先填写页面链接和密钥。")
        if token.strip():
            self.credentials.save(token.strip())
        cfg = self.controller.cfg
        schedule_changed = daily and (not cfg.notion_sync_daily or cfg.notion_sync_time != sync_time)
        fields = {"notion_parent_page": parent, "notion_sync_days": days,
                  "notion_dashboard_page": dashboard,
                  "notion_device_name": str(values.get("device_name", "")).strip()[:60],
                  "notion_include_sites": bool(values.get("include_sites")),
                  "notion_sync_on_startup": startup, "notion_sync_daily": daily,
                  "notion_sync_time": sync_time}
        old = {key: getattr(cfg, key) for key in fields}
        try:
            for key, value in fields.items():
                setattr(cfg, key, value)
            save_config(self.controller.cfg_path, cfg)
        except OSError:
            for key, value in old.items():
                setattr(cfg, key, value)
            raise NotionError("设置保存失败，请检查数据目录是否可写。") from None
        if schedule_changed:
            with self._lock:
                self._state["last_schedule_slot"] = self._slot(datetime.now().astimezone())
                self._save_state()

    def clear_token(self):
        if not self.persist:
            raise NotionError("预览模式不能清除密钥。")
        self.credentials.clear()
        values = self.settings()
        values.update(on_startup=False, daily=False)
        self.save_settings(values)

    def _save_state(self):
        if self.persist:
            _atomic_json(self._path, self._state)

    def _slot(self, now):
        hour, minute = map(int, self.settings()["time"].split(":"))
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < due:
            due -= timedelta(days=1)
        return due.isoformat(timespec="minutes")

    def automatic_reason(self, now=None):
        if not self.persist or self._closing.is_set():
            return ""
        now = now or datetime.now().astimezone()
        cfg = self.settings()
        if not cfg["parent_page"] or not cfg["has_token"]:
            return ""
        try:
            last = datetime.fromisoformat(self._state.get("last_attempt_at", ""))
            if self._state.get("last_error") and (now - last).total_seconds() < 900:
                return ""
        except (ValueError, TypeError):
            pass
        if not self._startup_checked:
            self._startup_checked = True
            if cfg["on_startup"]:
                return "startup"
        if cfg["daily"]:
            if not self._state.get("last_schedule_slot"):
                self._state["last_schedule_slot"] = self._slot(now)
                self._save_state()
            elif self._state["last_schedule_slot"] != self._slot(now):
                return "daily"
        return ""

    def export_json(self, out_path):
        if not self.persist:
            raise NotionError("预览模式不能写出文件。")
        cfg = self.settings()
        envelope = self._report_builder(self.controller, cfg["days"], cfg["include_sites"])
        _atomic_json(Path(out_path), envelope)
        return {"days": len(envelope["days"]), "path": str(out_path)}

    def sync(self, trigger="manual", on_progress=None):
        if not self.persist:
            raise NotionError("预览模式不会上传数据。")
        if self._closing.is_set() or not self._operation.acquire(blocking=False):
            raise NotionError("同步正在进行或软件正在退出，请稍后重试。")
        try:
            with sync_directory_lock(self.controller.data_dir):
                return self._sync_locked(trigger, on_progress)
        finally:
            self._operation.release()

    def _sync_locked(self, trigger, on_progress):
        try:
            # Another process may have completed since this service was constructed.
            try:
                disk = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(disk, dict):
                    self._state.update(disk)
            except (OSError, ValueError):
                pass
            now = datetime.now().astimezone()
            with self._lock:
                self._state.update(last_attempt_at=now.isoformat(), last_error="")
                self._save_state()
            cfg = self.settings()
            parent = page_id(cfg["parent_page"])
            client = self._client_factory(self.credentials.load())
            source, database = client.resolve_source(parent)
            envelope = self._report_builder(self.controller, cfg["days"], cfg["include_sites"])
            written = unchanged = empty = 0
            changed_totals = {}
            for index, report in enumerate(envelope["days"]):
                if self._closing.is_set():
                    raise NotionError("同步已停止；下次可继续更新已完成的记录。")
                day = report["local_date"]
                key = f"eye_care_daily@2/{report['device_id']}/{day}"
                top = report.get("top_apps", report["apps"][:5])
                report = {**report, "apps": [{k: v for k, v in app.items() if k != "icon"} for app in top],
                          "top_apps": top, "sync_key": key, "notion_layout": 3}
                row = client.find_day(source, key, report["device_id"], day)
                state_key = f"{source}/{key}"
                previous = self._state["pages"].get(state_key, {})
                if not row and previous.get("page_id"):
                    row = client.get_record(source, previous["page_id"], key, report["device_id"], day)
                if row:
                    self._state["pending_creates"].pop(state_key, None)
                elif state_key in self._state["pending_creates"]:
                    raise NotionError("上次创建结果尚未确认，已暂停新建以防重复。请稍后重试；若持续出现，请先核对 Notion 中该日期的记录。")
                target = row["id"] if row else None
                digest = hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
                if not report["has_records"] and not target:
                    empty += 1
                elif target and property_text(row, "内容指纹") == digest:
                    unchanged += 1
                else:
                    uploaded = {**report, "exported_at": envelope["generated_at"], "timezone": envelope["local_timezone"]}
                    uploaded = client.prepare_record(uploaded)
                    if target:
                        client.update_record(target, uploaded, digest)
                    else:
                        # Recover a lost POST response by querying the stable key next time.
                        self._state["pending_creates"][state_key] = now.isoformat()
                        self._save_state()
                        try:
                            target = client.create_record(source, uploaded, digest)
                        except NotionError as exc:
                            # A timeout is ambiguous; a definite rejected request is not.
                            if exc.status in (400, 401, 402, 403, 404, 413, 422, 429):
                                self._state["pending_creates"].pop(state_key, None)
                                self._save_state()
                            raise
                    with self._lock:
                        self._state["pages"][state_key] = {"page_id": target, "digest": digest}
                        self._state["pending_creates"].pop(state_key, None)
                        self._save_state()
                    if report.get("data_kind", "正式数据") == "正式数据":
                        changed_totals[target] = report["total_usage_seconds"]
                    written += 1
                if on_progress:
                    on_progress(index + 1, len(envelope["days"]))
            if envelope["days"]:
                client.refresh_dashboard(source, [r["local_date"] for r in envelope["days"]], changed_totals)
            summary = f"同步完成：更新 {written} 天，未变化 {unchanged} 天，无记录 {empty} 天。"
            with self._lock:
                self._state.update(last_success_at=datetime.now().astimezone().isoformat(), last_error="", last_summary=summary)
                self._state["last_page_url"] = "https://www.notion.so/" + page_id(database).replace("-", "")
                if cfg["daily"]:
                    self._state["last_schedule_slot"] = self._slot(now)
                self._save_state()
            return {"summary": summary, "written": written, "unchanged": unchanged, "empty": empty}
        except NotionError as exc:
            with self._lock:
                self._state["last_error"] = str(exc)
                self._save_state()
            raise
        except Exception:
            with self._lock:
                self._state["last_error"] = "同步未完成，请检查网络或本地数据目录后重试。"
                try:
                    self._save_state()
                except OSError:
                    pass
            raise NotionError(self._state["last_error"]) from None

    def stop(self):
        self._closing.set()
