"""QML 全屏休息遮罩宿主。

加载 RestOverlay.qml，负责：铺满指定屏幕、Windows Acrylic、淡入淡出、倒计时（单调时钟驱动、
每 250ms 刷 timeText）、到点自动完成、把「跳过本轮」动作转回调。后端业务（rest_complete /
rest_snooze）由回调方接既有 controller，本类不碰业务——仅视图宿主 + 计时。

每屏一个实例（与旧 RestOverlayWindow 一一对应）。QML 同步加载、无 channel 握手，
故 rest_ready 恒为 True，可被 runtime_shell 的 rest 显示/关闭链原样复用。

由 runtime_shell 的 _ensure_rest_overlays 在 rest_use_qml 时创建。
"""
from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Callable, Optional

_QML_PATH = Path(__file__).resolve().parent / "qml" / "RestOverlay.qml"


class QmlRestOverlay:
    """包装一块屏幕的 QML 休息遮罩。

    参数：
      screen_idx: 屏序号（与 rest_overlays 列表下标一致）。
      screen: QScreen，决定铺满哪块屏。
      on_snooze(): 点「跳过本轮」或 Esc 时回调（业务：rest_snooze + 关全部 + 释放守卫）。
      on_complete(): 倒计时自然到点时回调（业务：放提示音 + rest_complete + 关全部）。
      win_effects: 可选，提供 enable_acrylic(hwnd, ...)；None 则跳过亚克力（仍可见，无毛玻璃）。
      log: 可选 logger。
    """

    # 与 web 版一致：极淡 tint，磨砂主要靠系统 Acrylic
    ACRYLIC_TINT = 0x33101826

    def __init__(
        self,
        *,
        screen_idx: int,
        screen=None,
        on_snooze: Optional[Callable[[], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
        win_effects=None,
        log: Optional[logging.Logger] = None,
    ) -> None:
        from PySide6.QtCore import QUrl, QTimer
        from PySide6.QtQml import QQmlApplicationEngine

        self.screen_idx = int(screen_idx)
        self.rest_ready = True          # QML 同步加载，立即就绪
        self.rest_started = False
        self._log = log or logging.getLogger(__name__)
        self._on_snooze = on_snooze
        self._on_complete = on_complete
        self._win_effects = win_effects
        self._screen = screen
        self._acrylic_applied = False
        self._end_mono = 0.0
        self._duration = 0

        self._engine = QQmlApplicationEngine()
        self._engine.load(QUrl.fromLocalFile(str(_QML_PATH)))
        roots = self._engine.rootObjects()
        if not roots:
            raise RuntimeError("加载 RestOverlay.qml 失败（rootObjects 为空），检查 QML 语法/QtQuick 是否可用")
        self._win = roots[0]
        self._win.actionTriggered.connect(self._handle_action)

        # 铺满目标屏（用 geometry 全屏，含任务栏）。显示前还会再次同步，适配运行期 DPI/分辨率变化。
        self.sync_geometry()
        if screen is not None:
            for signal_name in ("geometryChanged", "availableGeometryChanged", "logicalDotsPerInchChanged"):
                try:
                    getattr(screen, signal_name).connect(lambda *_args: self.sync_geometry())
                except Exception:
                    pass

        # 倒计时：单调时钟驱动，每 250ms 刷一次；系统校时不会让倒计时跳变。
        self._tick_timer = QTimer()
        self._tick_timer.setInterval(250)
        self._tick_timer.timeout.connect(self._tick)

    # ---- 对外 API（与旧 RestOverlayWindow 同名同义）----
    def show_overlay(self, *, duration_s: int) -> None:
        from PySide6.QtCore import QTimer

        self.sync_geometry()
        self.rest_started = True
        self._duration = max(1, int(duration_s or 20))
        self._end_mono = time.monotonic() + self._duration
        self._win.setProperty("overlayVisible", False)  # 先归零，保证 Behavior 渐入
        self._win.setProperty("timeText", self._fmt(self._duration))
        self._win.setVisible(True)
        self._apply_acrylic()
        QTimer.singleShot(0, lambda: self._win.setProperty("overlayVisible", True))
        self._tick()
        self._tick_timer.start()
        self._log.info("qml.rest.show screen=%s duration_s=%s", self.screen_idx, self._duration)

    def hide_overlay(self) -> None:
        from PySide6.QtCore import QTimer

        self._tick_timer.stop()
        self.rest_started = False
        self._win.setProperty("overlayVisible", False)
        QTimer.singleShot(350, lambda: self._win.setVisible(False))
        self._log.info("qml.rest.hide screen=%s", self.screen_idx)

    def isVisible(self) -> bool:
        try:
            return bool(self._win.isVisible())
        except Exception:
            return False

    @property
    def window(self):
        return self._win

    @property
    def screen_name(self) -> str:
        try:
            return str(self._screen.name()) if self._screen is not None else ""
        except Exception:
            return ""

    def sync_geometry(self) -> None:
        """按目标 QScreen 的逻辑坐标重新铺满，避免手工 DPR 换算造成二次缩放。"""
        screen = self._screen
        if screen is None:
            return
        try:
            self._win.setScreen(screen)
        except Exception:
            self._log.debug("qml.rest setScreen failed screen=%s", self.screen_idx, exc_info=True)
        try:
            geo = screen.geometry()
            self._win.setX(geo.x())
            self._win.setY(geo.y())
            self._win.setWidth(geo.width())
            self._win.setHeight(geo.height())
        except Exception:
            self._log.exception("qml.rest sync geometry failed screen=%s", self.screen_idx)

    # ---- 内部 ----
    def _tick(self) -> None:
        left = self._end_mono - time.monotonic()
        self._win.setProperty("timeText", self._fmt(left))
        if self._end_mono > 0 and left <= 0:
            self._tick_timer.stop()
            self._log.info("qml.rest.auto_complete screen=%s", self.screen_idx)
            if callable(self._on_complete):
                try:
                    self._on_complete()
                except Exception:
                    self._log.exception("qml rest on_complete 回调异常 screen=%s", self.screen_idx)

    def _handle_action(self, name: str) -> None:
        self._log.info("qml.rest.action screen=%s name=%s", self.screen_idx, name)
        # 目前 QML 仅发 "snooze"
        if callable(self._on_snooze):
            try:
                self._on_snooze()
            except Exception:
                self._log.exception("qml rest on_snooze 回调异常 screen=%s", self.screen_idx)

    @staticmethod
    def _fmt(sec) -> str:
        # 剩余 19.9 秒应显示 00:20；向下取整会让倒计时一出现就少一秒。
        sec = max(0, int(math.ceil(float(sec))))
        return "%02d:%02d" % (sec // 60, sec % 60)

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
            ok = bool(self._win_effects.enable_acrylic(
                hwnd, tint_color=self.ACRYLIC_TINT, blur=True, where="qml_rest screen=%s" % self.screen_idx))
            self._acrylic_applied = ok
            self._log.info("qml.rest.acrylic screen=%s hwnd=%s ok=%s", self.screen_idx, hwnd, ok)
        except Exception:
            self._log.exception("qml rest acrylic 应用失败 screen=%s hwnd=%s", self.screen_idx, hwnd)
