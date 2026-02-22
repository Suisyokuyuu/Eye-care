from __future__ import annotations

WINDOW_NOTIFY_ACTIONS = {"rest", "snooze", "auto-close", "dismiss"}


def normalize_notify_window_action(action: str) -> str:
    a = str(action or "").strip().lower()
    if a in WINDOW_NOTIFY_ACTIONS:
        return a
    return ""
