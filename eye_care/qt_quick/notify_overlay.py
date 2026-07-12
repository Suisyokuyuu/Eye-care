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
        self._visibility_generation = 0

        self._engine = QQmlApplicationEngine()
        self._engine.load(QUrl.fromLocalFile(str(_QML_PATH)))
        roots = self._engine.rootObjects()
        if not roots:
            raise RuntimeError("加载 NotifyOverlay.qml 失败（rootObjects 为空），检查 QML 语法/QtQuick 是否可用")
        self._win = roots[0]
        self._win.actionTriggered.connect(self._handle_action)

        self._place_on_screen(QGuiApplication.primaryScreen())

        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._on_auto_hide)

    # ---- 对外 API ----
    def show_notify(self, *, message: str, auto_hide_s: int = 20) -> None:
        """显示浮层并渐入；auto_hide_s 秒后若未操作则自动以 dismiss 隐藏。"""
        self._visibility_generation += 1
        try:
            self._place_on_screen(self._target_screen())
        except Exception:
            self._log.debug("qml.notify place_on_screen failed", exc_info=True)
        self._win.setProperty("messageText", str(message or ""))
        self._win.setProperty("cardVisible", False)  # 先归零，保证 Behavior 渐入
        self._win.setVisible(True)
        self._apply_acrylic()
        # 重新抢占置顶 band：WindowStaysOnTopHint 只保证"在普通窗口之上"，但另一个 topmost
        # 窗口（前台无边框全屏、其它置顶提示）可能排在我们之上→气泡被遮。每次弹出强制把 hwnd
        # 提到 topmost band 顶部，SWP_NOACTIVATE 避免抢焦点打断用户。
        self._raise_topmost()
        # 下一拍再置 true，触发淡入动画
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._win.setProperty("cardVisible", True))
        secs = max(0, min(600, int(20 if auto_hide_s is None else auto_hide_s)))
        if secs > 0:
            self._hide_timer.start(secs * 1000)
        else:
            self._hide_timer.stop()
        self._log.info("qml.notify.show auto_hide_s=%s", secs)

    def hide_notify(self, *, reason: str = "dismiss") -> None:
        """渐出后隐藏窗口。"""
        self._hide_timer.stop()
        self._visibility_generation += 1
        generation = self._visibility_generation
        self._win.setProperty("cardVisible", False)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(230, lambda: self._hide_if_current(generation))
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

    def _hide_if_current(self, generation: int) -> None:
        if generation == self._visibility_generation:
            self._win.setVisible(False)

    def _place_on_screen(self, screen) -> None:
        if screen is None:
            return
        try:
            self._win.setScreen(screen)
        except Exception:
            self._log.debug("qml.notify setScreen failed", exc_info=True)
        geo = screen.availableGeometry()
        self._win.setWidth(self.WIDTH)
        self._win.setHeight(self.HEIGHT)
        self._win.setX(geo.x() + max(0, geo.width() - self.WIDTH - self.MARGIN))
        self._win.setY(geo.y() + max(0, geo.height() - self.HEIGHT - self.MARGIN))

    @staticmethod
    def _target_screen():
        """优先前台应用所在屏，取不到时回退鼠标屏幕。"""
        from PySide6.QtGui import QGuiApplication, QCursor
        try:
            import ctypes
            from ctypes import wintypes

            class _RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG),
                ]

            class _MONITORINFOEXW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                    ("rcWork", _RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32),
                ]

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            monitor_from_window = user32.MonitorFromWindow
            monitor_from_window.argtypes = [wintypes.HWND, wintypes.DWORD]
            monitor_from_window.restype = ctypes.c_void_p
            get_monitor_info = user32.GetMonitorInfoW
            get_monitor_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFOEXW)]
            get_monitor_info.restype = wintypes.BOOL
            monitor = monitor_from_window(hwnd, 2) if hwnd else None
            if monitor:
                info = _MONITORINFOEXW()
                info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
                if get_monitor_info(monitor, ctypes.byref(info)):
                    device = str(info.szDevice or "").casefold()
                    for screen in QGuiApplication.screens() or []:
                        if str(screen.name() or "").casefold() == device:
                            return screen
        except Exception:
            pass
        return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()

    def _raise_topmost(self) -> None:
        """把窗口强制提到 topmost band 顶部（不抢焦点）。仅 Windows 生效，失败静默降级。"""
        try:
            self._win.raise_()
        except Exception:
            pass
        try:
            import ctypes
            hwnd = int(self._win.winId())
            if not hwnd:
                return
            HWND_TOPMOST = -1
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            ctypes.windll.user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
        except Exception:
            self._log.debug("qml.notify.raise_topmost 失败", exc_info=True)

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
