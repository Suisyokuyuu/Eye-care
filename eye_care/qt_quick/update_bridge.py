"""检查更新 QML 数据桥（step3）。

复刻 web `#updateCheckModal`：点检查→显示结果（已是最新 / 发现新版本 + 前往下载 / 失败）。
后端复用 ConfigService.check_update（GitHub releases 比对 + 缓存）。网络调用放后台线程，
结果经 QueuedConnection 信号回主线程更新属性，避免卡 UI。

QML 侧 contextProperty `updateBridge`：打开页调 `check()`，绑 `message`/`busy`/`hasUpdate`，
有更新点「前往下载」调 `openUrl()`。
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt

log = logging.getLogger(__name__)


def build_update_io(controller, log: Optional[logging.Logger] = None):
    """造 (checker, opener)。checker 复用 ConfigService.check_update；opener=浏览器打开。"""
    lg = log or logging.getLogger(__name__)
    import webbrowser
    from eye_care.services.context import ServiceContext
    from eye_care.services.config_service import ConfigService

    ctx = ServiceContext(controller=controller, log=lg)
    cfgsvc = ConfigService(ctx)

    def checker() -> dict:
        return cfgsvc.check_update()

    def opener(url: str) -> None:
        webbrowser.open(url)

    return checker, opener


class UpdateBridge(QObject):
    stateChanged = Signal()
    _resultReady = Signal(object)   # 后台线程 → 主线程（QueuedConnection）

    def __init__(self, checker: Callable[[], dict], opener: Callable[[str], None], *, parent=None):
        super().__init__(parent)
        self._checker = checker
        self._opener = opener
        self._busy = False
        self._message = "点击下方按钮检查更新"
        self._hasUpdate = False
        self._htmlUrl = ""
        self._current = ""
        self._latest = ""
        self._error = ""
        self._resultReady.connect(self._applyResult, Qt.QueuedConnection)

    @Property(bool, notify=stateChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=stateChanged)
    def message(self) -> str:
        return self._message

    @Property(bool, notify=stateChanged)
    def hasUpdate(self) -> bool:
        return self._hasUpdate

    @Property(str, notify=stateChanged)
    def htmlUrl(self) -> str:
        return self._htmlUrl

    @Slot()
    def check(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._message = "正在检查…"
        self._error = ""
        self._hasUpdate = False
        self.stateChanged.emit()

        def work():
            try:
                res = self._checker() or {}
            except Exception as e:  # noqa: BLE001
                res = {"ok": False, "error": str(e)[:200]}
            self._resultReady.emit(res)

        threading.Thread(target=work, daemon=True).start()

    @Slot(object)
    def _applyResult(self, res) -> None:
        res = res or {}
        self._busy = False
        ok = res.get("ok")
        err = res.get("error") or ""
        self._current = str(res.get("current") or "")
        self._latest = str(res.get("latest") or "")
        self._htmlUrl = str(res.get("html_url") or "")
        self._hasUpdate = bool(res.get("has_update"))
        if not ok and err:
            self._message = "检查失败：" + err
            self._error = err
        elif self._hasUpdate:
            self._message = "发现新版本 v%s（当前 v%s）" % (self._latest, self._current)
        else:
            ver = self._current or self._latest or ""
            self._message = "已是最新版本" + (("（v%s）" % ver) if ver else "")
        self.stateChanged.emit()

    @Slot()
    def openUrl(self) -> None:
        if not self._htmlUrl:
            return
        try:
            self._opener(self._htmlUrl)
        except Exception as e:  # noqa: BLE001
            log.warning("打开下载页失败: %s", e)
