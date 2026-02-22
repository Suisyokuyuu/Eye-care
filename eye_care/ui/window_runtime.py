from __future__ import annotations

import json
import logging
import os
from typing import Callable

from .action_contracts import normalize_notify_window_action
from .web_routes import build_ui_page_url


class NotifyOverlayRuntime:
    """Notify/overlay runtime helper to keep main.py lightweight."""

    def __init__(self, *, api_port: int, debug_console: bool, logger: logging.Logger) -> None:
        self._api_port = int(api_port)
        self._debug_console = bool(debug_console)
        self._log = logger

    def build_rest_overlay_url(self, screen_idx: int) -> str:
        url = f"{build_ui_page_url(self._api_port, 'rest')}?screen={int(screen_idx)}"
        if self._debug_console or os.environ.get("EYECARE_DEBUG_CONSOLE", "0") == "1":
            url += "&debug=1"
        return url

    def build_notify_url(self) -> str:
        return build_ui_page_url(self._api_port, "notify")

    def bind_notify_bridge(
        self,
        *,
        notify_bridge,
        notify_ready: dict,
        debug_notify_only: dict,
        notify_title_token_getter: Callable[[], str | None],
        hide_notify_with_fade: Callable[[str], None],
        clear_prompt_dedupe: Callable[[], None],
        show_rest_overlay: Callable[[], None],
        on_ready_for_show: Callable[[], None] | None = None,
        on_action_done: Callable[[], None] | None = None,
    ) -> None:
        """Bind notify window bridge handlers (window behavior only).
        on_action_done: 用户点击（rest/snooze/dismiss/auto-close）后调用，用于上报 on_notify_complete(True)。
        """

        def _notify_action(action: str):
            act = normalize_notify_window_action(action)
            if not act:
                self._log.warning("notify: ignore unknown window action")
                return

            # fallback: JS callback means page is alive
            if not notify_ready.get("value"):
                notify_ready["value"] = True

            hide_notify_with_fade(f"action:{act}")
            if callable(on_action_done):
                try:
                    on_action_done()
                except Exception:
                    self._log.exception("notify: on_action_done failed")

            if bool(debug_notify_only.get("v")):
                debug_notify_only["v"] = False
                return

            try:
                clear_prompt_dedupe()
            except Exception:
                self._log.exception("notify: clear_prompt_dedupe failed")

            if act == "rest":
                self._log.info("通知触发：立刻休息 - 显示休息遮罩")
                show_rest_overlay()
                return

            if act == "dismiss":
                self._log.info("通知触发：dismiss（fade_out -> hide）")
            elif act == "auto-close":
                self._log.info("通知触发：自动隐藏")
            else:
                self._log.info("通知触发：稍后")

        def _notify_log_handler(payload: dict):
            # notify_log means frontend JS is alive; used as loaded fallback
            try:
                if not notify_ready.get("value"):
                    notify_ready["value"] = True
                    self._log.info("notify: marked ready via notify_log fallback")
                s = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
                from eye_care.diagnostics import diag
                diag.emit("HARD_NOTIFY_FRONTEND", self._log, "前端埋点", payload=s[:500] if len(s) > 500 else s)
            except Exception:
                self._log.exception("notify: notify_log handler failed")

        notify_bridge.set_handler(_notify_action)
        notify_bridge.set_log_handler(_notify_log_handler)
        if callable(on_ready_for_show):
            notify_bridge.set_ready_for_show_handler(on_ready_for_show)
