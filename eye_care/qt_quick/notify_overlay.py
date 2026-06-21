"""QML notify 浮层宿主。

加载 NotifyOverlay.qml，负责：定位（右下角）、Windows Acrylic、淡入淡出、自动隐藏、
把 QML 的 actionTriggered(name) 转给回调。后端业务（rest/snooze）由回调方接既有
controller / HTTP 链路，本类不碰业务逻辑——仅是「视图宿主」。

设计成可独立运行（见 preview.py），便于在没有完整事件链时单测观感与桥路。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

_QML_PATH = Path(__file__).resolve().parent / "qml" / "NotifyOverlay.qml"


class QmlNotifyOverlay:
    """包装 QML notify 浮层窗口。

    参数：
      on_action(name): QML 动作回调，name ∈ {"rest","snooze","dismiss"}。
      win_effects: 可选，提供 enable_acrylic(hwnd, ...)；None 则跳过亚克力（仍可见，只是无毛玻璃）。
      log: 可选 logger。
    """

    WIDTH = 400
    HEIGHT = 160
    MARGIN = 24

    def __init__(
        self,
        *,
        on_action: Optional[Callable[[str], None]] = None,
        win_effects=None,
        log: Optional[logging.Logger] = None,
    ) -> None:
        from PySide6.QtCore import QUrl, QTimer
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine

        self._log = log or logging.getLogger(__name__)
        self._on_action = on_action
        self._win_effects = win_effects
        self._acrylic_applied = False

        self._engine = QQmlApplicationEngine()
        self._engine.load(QUrl.fromLocalFile(str(_QML_PATH)))
        roots = self._engine.rootObjects()
        if not roots:
            raise RuntimeError("加载 NotifyOverlay.qml 失败（rootObjects 为空），检查 QML 语法/QtQuick 是否可用")
        self._win = roots[0]
        self._win.actionTriggered.connect(self._handle_action)

        # 右下角定位
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen is not None else None
        if geo is not None:
            x = geo.x() + max(0, geo.width() - self.WIDTH - self.MARGIN)
            y = geo.y() + max(0, geo.height() - self.HEIGHT - self.MARGIN)
            self._win.setWidth(self.WIDTH)
            self._win.setHeight(self.HEIGHT)
            self._win.setX(x)
            self._win.setY(y)

        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._on_auto_hide)

    # ---- 对外 API ----
    def show_notify(self, *, message: str, auto_hide_s: int = 20) -> None:
        """显示浮层并渐入；auto_hide_s 秒后若未操作则自动以 dismiss 隐藏。"""
        # 每次弹出前重新定位到鼠标所在屏幕，适配多显示器切换场景
        try:
            from PySide6.QtGui import QGuiApplication, QCursor
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                self._win.setX(geo.x() + max(0, geo.width() - self.WIDTH - self.MARGIN))
                self._win.setY(geo.y() + max(0, geo.height() - self.HEIGHT - self.MARGIN))
        except Exception:
            pass
        self._win.setProperty("messageText", str(message or ""))
        self._win.setProperty("cardVisible", False)  # 先归零，保证 Behavior 渐入
        self._win.setVisible(True)
        self._apply_acrylic()
        # 下一拍再置 true，触发淡入动画
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._win.setProperty("cardVisible", True))
        secs = max(1, min(600, int(auto_hide_s or 20)))
        self._hide_timer.start(secs * 1000)
        self._log.info("qml.notify.show auto_hide_s=%s", secs)

    def hide_notify(self, *, reason: str = "dismiss") -> None:
        """渐出后隐藏窗口。"""
        self._hide_timer.stop()
        self._win.setProperty("cardVisible", False)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(230, lambda: self._win.setVisible(False))
        self._log.info("qml.notify.hide reason=%s", reason)

    @property
    def window(self):
        return self._win

    # ---- 内部 ----
    def _handle_action(self, name: str) -> None:
        self._hide_timer.stop()
        self._log.info("qml.notify.action name=%s", name)
        if callable(self._on_action):
            try:
                self._on_action(str(name))
            except Exception:
                self._log.exception("qml notify on_action 回调异常 name=%s", name)
        self.hide_notify(reason=str(name))

    def _on_auto_hide(self) -> None:
        self._log.info("qml.notify.auto_hide_fire")
        self._handle_action("dismiss")

    def _apply_acrylic(self) -> None:
        if self._acrylic_applied or self._win_effects is None:
            return
        try:
            hwnd = int(self._win.winId())
        except Exception:
            hwnd = 0
        if not hwnd:
            return
        try:
            ok = bool(self._win_effects.enable_acrylic(hwnd, tint_color=0xBB101826, blur=True, where="qml_notify"))
            self._acrylic_applied = ok
            self._log.info("qml.notify.acrylic hwnd=%s ok=%s", hwnd, ok)
        except Exception:
            self._log.exception("qml notify acrylic 应用失败 hwnd=%s", hwnd)
