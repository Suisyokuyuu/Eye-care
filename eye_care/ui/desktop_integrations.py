
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# notify 页面已文件化到 eye_care/ui/web/notify/index.html
# 运行时通过 HTTP 加载（http://127.0.0.1:{port}/notify/）
NOTIFY_HTML_PATH = Path(__file__).resolve().parent / "web" / "notify" / "index.html"


def load_notify_html() -> str:
    """从文件加载 notify 页面 HTML。当前主流程优先通过 URL 加载，本函数仅作兜底/调试入口。"""
    try:
        return NOTIFY_HTML_PATH.read_text(encoding="utf-8")
    except Exception:
        log.exception("load_notify_html: failed to read %s", NOTIFY_HTML_PATH)
        return "<html><body><p>Notify page load error</p></body></html>"


class NotifyBridge:
    """notify 窗口的 JS-Python 桥接。

    职责仅限于窗口行为：
    - notify_action: 接收前端动作（rest/snooze/auto-close），执行窗口隐藏/关闭等 UI 行为
    - notify_log: 接收前端硬日志上报
    - notify_ready_for_show: 方案2 前端 ACK，表示 CSS/DOM/首帧已就绪，可开始淡入

    业务动作（开始休息、稍后等）由前端通过 HTTP /api/* 完成，不经过此桥。
    """

    def __init__(self):
        self._on_action = None
        self._on_log = None
        self._on_ready_for_show = None

    def set_handler(self, fn):
        self._on_action = fn

    def set_log_handler(self, fn):
        self._on_log = fn

    def set_ready_for_show_handler(self, fn):
        self._on_ready_for_show = fn

    def notify_window_action(self, action: str):
        try:
            if callable(self._on_action):
                self._on_action(str(action or ""))
        except Exception:
            log.exception("NotifyBridge.notify_window_action failed")

    # 兼容别名：保留 notify_action -> notify_window_action
    def notify_action(self, action: str):
        self.notify_window_action(action)

    def notify_log(self, payload: dict):
        """Front-end hard logs for notification window."""
        try:
            if callable(self._on_log):
                self._on_log(payload or {})
        except Exception:
            log.exception("NotifyBridge.notify_log failed")

    def notify_ready_for_show(self):
        """方案2：前端确认 CSS/DOM/首帧已就绪，可开始窗口淡入。"""
        try:
            if callable(self._on_ready_for_show):
                self._on_ready_for_show()
        except Exception:
            log.exception("NotifyBridge.notify_ready_for_show failed")
