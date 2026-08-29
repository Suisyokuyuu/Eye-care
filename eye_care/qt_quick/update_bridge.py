"""QML bridge for automatic update checking, download, install and restart."""
from __future__ import annotations

import logging
import threading
from typing import Optional

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt


log = logging.getLogger(__name__)


def build_update_io(controller, log: Optional[logging.Logger] = None):
    import webbrowser
    from eye_care.bootstrap.constants import PROJECT_ROOT
    from eye_care.update_service import UpdateService

    lg = log or logging.getLogger(__name__)
    service = UpdateService(
        data_dir=controller.data_dir,
        install_dir=PROJECT_ROOT,
        logger=lg,
    )
    service.cleanup_runtime_helpers()
    return service, webbrowser.open


class UpdateBridge(QObject):
    stateChanged = Signal()
    updateReady = Signal(str)
    restartRequested = Signal()
    _eventReady = Signal(object)

    def __init__(self, service, opener, *, parent=None):
        super().__init__(parent)
        self._service = service
        self._opener = opener
        self._busy = False
        self._message = "点击下方按钮检查更新"
        self._has_update = False
        self._ready = False
        self._progress = 0
        self._html_url = ""
        self._current = getattr(service, "current_version", "")
        self._latest = ""
        self._release_notes = ""
        self._eventReady.connect(self._apply_event, Qt.QueuedConnection)

        pending = service.get_pending()
        if pending:
            self._set_ready(str(pending.get("version") or ""), emit_signal=False)
        else:
            previous = service.read_last_result()
            if previous and previous.get("ok") and previous.get("status") == "updated":
                self._message = "已成功升级到 v%s" % (previous.get("to_version") or self._current)
            elif previous and not previous.get("ok"):
                self._message = "上次升级失败，已保留旧版本：" + str(previous.get("error") or "未知错误")[:160]

    @Property(bool, notify=stateChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=stateChanged)
    def message(self) -> str:
        return self._message

    @Property(bool, notify=stateChanged)
    def hasUpdate(self) -> bool:
        return self._has_update

    @Property(bool, notify=stateChanged)
    def readyToInstall(self) -> bool:
        return self._ready

    @Property(int, notify=stateChanged)
    def progress(self) -> int:
        return self._progress

    @Property(str, notify=stateChanged)
    def htmlUrl(self) -> str:
        return self._html_url

    @Property(str, notify=stateChanged)
    def currentVersion(self) -> str:
        return self._current

    @Property(str, notify=stateChanged)
    def latestVersion(self) -> str:
        return self._latest

    @Property(str, notify=stateChanged)
    def releaseNotes(self) -> str:
        return self._release_notes

    @Slot()
    def check(self) -> None:
        self._start_check(automatic=False)

    @Slot()
    def startAutomatic(self) -> None:
        if self._ready:
            return
        self._start_check(automatic=True)

    def _start_check(self, *, automatic: bool) -> None:
        if self._busy:
            return
        pending = self._service.get_pending()
        if pending:
            self._set_ready(str(pending.get("version") or ""), emit_signal=not automatic)
            return
        self._busy = True
        self._progress = 0
        self._message = "正在后台检查更新…" if automatic else "正在检查更新…"
        self.stateChanged.emit()

        def work() -> None:
            try:
                result = self._service.check_update(force=not automatic) or {}
                will_download = bool(
                    result.get("ok")
                    and result.get("has_update")
                    and result.get("downloadable")
                    and self._service.can_auto_install
                )
                self._eventReady.emit({"kind": "checked", "result": result, "will_download": will_download})
                if not will_download:
                    return

                def on_progress(received: int, total: int) -> None:
                    percent = int(received * 100 / total) if total > 0 else 0
                    self._eventReady.emit({"kind": "progress", "percent": max(0, min(99, percent))})

                staged = self._service.download_and_stage(result, on_progress)
                self._eventReady.emit({"kind": "ready", "result": staged})
            except Exception as exc:  # noqa: BLE001
                self._eventReady.emit({"kind": "error", "error": str(exc)[:300]})

        threading.Thread(target=work, daemon=True, name="auto_update").start()

    @Slot(object)
    def _apply_event(self, event) -> None:
        event = event or {}
        kind = event.get("kind")
        if kind == "checked":
            result = event.get("result") or {}
            self._current = str(result.get("current") or self._current)
            self._latest = str(result.get("latest") or "")
            self._html_url = str(result.get("html_url") or "")
            self._release_notes = str(result.get("release_notes") or "")
            self._has_update = bool(result.get("has_update"))
            if not result.get("ok"):
                self._busy = False
                self._message = "检查失败：" + str(result.get("error") or "未知错误")
            elif not self._has_update:
                self._busy = False
                self._message = "已是最新版本（v%s）" % (self._current or self._latest)
            elif event.get("will_download"):
                self._message = "发现 v%s，正在后台下载…" % self._latest
            elif self._has_update and not self._service.can_auto_install:
                self._busy = False
                self._message = "发现 v%s；源码运行模式不自动覆盖程序，请使用打包版升级" % self._latest
            else:
                self._busy = False
                self._message = str(result.get("error") or "发现新版，但当前发布包不能自动安装")
            self.stateChanged.emit()
            return
        if kind == "progress":
            self._progress = int(event.get("percent") or 0)
            self._message = "正在下载 v%s… %d%%" % (self._latest, self._progress)
            self.stateChanged.emit()
            return
        if kind == "ready":
            result = event.get("result") or {}
            self._set_ready(str(result.get("version") or self._latest), emit_signal=True)
            return
        if kind == "error":
            self._busy = False
            self._message = "自动更新失败：" + str(event.get("error") or "未知错误")
            self.stateChanged.emit()

    def _set_ready(self, version: str, *, emit_signal: bool) -> None:
        self._busy = False
        self._ready = True
        self._has_update = True
        self._progress = 100
        self._latest = version or self._latest
        self._message = "v%s 已下载并校验完成，重启即可升级" % self._latest
        self.stateChanged.emit()
        if emit_signal:
            self.updateReady.emit(self._latest)

    @Slot()
    def install(self) -> None:
        if self._busy or not self._ready:
            return
        self._busy = True
        self._message = "正在启动升级器…"
        self.stateChanged.emit()
        try:
            self._service.launch_installer()
        except Exception as exc:  # noqa: BLE001
            self._busy = False
            self._message = "无法开始升级：" + str(exc)[:240]
            self.stateChanged.emit()
            return
        self._message = "程序即将退出并完成升级…"
        self.stateChanged.emit()
        self.restartRequested.emit()

    @Slot()
    def openUrl(self) -> None:
        if not self._html_url:
            return
        try:
            self._opener(self._html_url)
        except Exception as exc:  # noqa: BLE001
            log.warning("打开发布页失败: %s", exc)
