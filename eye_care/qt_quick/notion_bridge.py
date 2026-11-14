"""Native QML adapter. All Notion / disk export work runs off the UI thread."""
from __future__ import annotations

import threading
from datetime import datetime

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QTimer
from PySide6.QtGui import QGuiApplication

from eye_care.services.notion_client import NotionError, page_id
from eye_care.ui.file_dialog import _create_file_dialog_safe
from eye_care.utils.desktop import open_system_url


class NotionBridge(QObject):
    stateChanged = Signal()
    _eventReady = Signal(object)

    def __init__(self, service, *, parent=None, url_opener=None):
        super().__init__(parent)
        self._service = service
        self._url_opener = url_opener or open_system_url
        self._link_message = ""
        self._busy = False
        self._closed = False
        self._message = service.status().get("last_error") or service.status().get("last_summary") or "保存连接后，点击“立即同步”上传所选日期的统计。"
        self._error = bool(service.status().get("last_error"))
        self._eventReady.connect(self._apply_event, Qt.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self._automatic_tick)

    @Property("QVariantMap", notify=stateChanged)
    def config(self):
        return self._service.settings()

    @Property(bool, notify=stateChanged)
    def busy(self):
        return self._busy

    @Property(bool, notify=stateChanged)
    def preview(self):
        return not self._service.persist

    @Property(str, notify=stateChanged)
    def message(self):
        return self._message

    @Property(bool, notify=stateChanged)
    def error(self):
        return self._error

    @Property(str, notify=stateChanged)
    def lastSuccess(self):
        value = self._service.status().get("last_success_at")
        try:
            return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S") if value else "尚未同步"
        except (ValueError, TypeError):
            return "尚未同步"

    @Property(str, notify=stateChanged)
    def pageUrl(self):
        # The configured landing page contains linked views; old state may point
        # at a legacy day page rather than the current statistics home.
        settings = self._service.settings()
        value = settings.get("dashboard_page") or settings.get("parent_page") or self._service.status().get("last_page_url")
        try:
            return "https://www.notion.so/" + page_id(value).replace("-", "") if value else ""
        except NotionError:
            return ""

    @Property(str, notify=stateChanged)
    def linkMessage(self):
        return self._link_message

    def _feedback(self, text, error=False):
        self._message, self._error = text, error
        self.stateChanged.emit()

    @Slot("QVariantMap", str, result=bool)
    def saveSettings(self, values, token):
        if self._busy or self.preview:
            return False
        try:
            self._service.save_settings(dict(values), token)
            self._feedback("设置已保存。手动同步请点击“立即同步”。")
            return True
        except NotionError as exc:
            self._feedback(str(exc), True)
        except Exception:
            self._feedback("保存失败，请检查数据目录权限。", True)
        return False

    @Slot()
    def clearToken(self):
        if self._busy or self.preview:
            return
        try:
            self._service.clear_token()
            self._feedback("密钥已清除，自动同步已关闭。")
        except Exception:
            self._feedback("清除密钥失败，请检查数据目录权限。", True)

    @Slot()
    def syncNow(self):
        self._start("manual")

    def _start(self, trigger, export_path=None):
        if self._busy or self._closed or self.preview:
            return
        self._busy = True
        self._feedback("正在导出文件…" if export_path else "正在同步到 Notion…")

        def work():
            try:
                if export_path:
                    result = self._service.export_json(export_path)
                    text = f"已导出 {result['days']} 天的 AI 数据（JSON）。"
                else:
                    def progress(current, total):
                        self._eventReady.emit({"progress": f"正在同步到 Notion… {current}/{total}"})
                    result = self._service.sync(trigger, progress)
                    text = result["summary"]
                self._eventReady.emit({"done": True, "message": text})
            except NotionError as exc:
                self._eventReady.emit({"done": True, "error": str(exc)})
            except Exception:
                self._eventReady.emit({"done": True, "error": "操作未完成，请检查网络或文件权限后重试。"})

        threading.Thread(target=work, daemon=True, name="notion_sync").start()

    @Slot(object)
    def _apply_event(self, event):
        if self._closed:
            return
        if event.get("progress"):
            self._feedback(event["progress"])
        elif event.get("done"):
            self._busy = False
            self._feedback(event.get("error") or event.get("message") or "已完成", bool(event.get("error")))

    @Slot()
    def exportJson(self):
        if self._busy or self.preview:
            return
        try:
            path = _create_file_dialog_safe("save", save_filename="eye_care_ai_export.json",
                                            file_types=("JSON Files (*.json)",), title="导出 AI 统计数据")
            if path:
                self._start("export", str(path if isinstance(path, str) else path[0]))
        except Exception:
            self._feedback("无法打开文件保存窗口。", True)

    @Slot(result=bool)
    @Slot(str, result=bool)
    def openPage(self, value=""):
        try:
            url = "https://www.notion.so/" + page_id(value).replace("-", "") if value else self.pageUrl
            if url and self._url_opener(url):
                self._link_message = "已请求打开统计页；若浏览器没有弹出，可用“复制链接”手动打开。"
                self.stateChanged.emit()
                return True
        except Exception:
            pass
        self._link_message = "未能打开浏览器，请用“复制链接”手动打开。"
        self._feedback("无法打开默认浏览器。请复制上方 Notion 链接，在浏览器中打开。", True)
        return False

    @Slot(str, result=bool)
    def copyPageLink(self, value):
        try:
            url = "https://www.notion.so/" + page_id(value).replace("-", "") if value else self.pageUrl
            if not url:
                raise NotionError("Missing link")
            QGuiApplication.clipboard().setText(url)
            self._link_message = "统计页链接已复制。"
            self.stateChanged.emit()
            return True
        except Exception:
            self._link_message = "请先填写有效的 Notion 链接。"
            self.stateChanged.emit()
            return False

    @Slot()
    def startAutomatic(self):
        if self.preview or self._closed:
            return
        self._timer.start()
        QTimer.singleShot(15000, self._automatic_tick)

    @Slot()
    def _automatic_tick(self):
        if self._busy or self._closed:
            return
        try:
            reason = self._service.automatic_reason()
            if reason:
                self._start(reason)
        except Exception:
            self._feedback("自动同步配置无效，请打开同步设置检查。", True)

    @Slot()
    def shutdown(self):
        self._closed = True
        self._timer.stop()
        self._service.stop()
