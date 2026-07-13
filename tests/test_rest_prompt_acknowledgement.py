from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace

from eye_care.controller.app_controller import AppController, ControllerState
from eye_care.notify.notification_manager import NotificationManager
from eye_care.qt_quick.notify_overlay import QmlNotifyOverlay


def _controller(
    *, reminder_minutes: int = 20, work_s: int | None = None, due: bool = True
) -> AppController:
    """Build the smallest controller state needed to exercise reminder decisions."""
    controller = AppController.__new__(AppController)
    controller._lock = threading.RLock()
    controller.cfg = SimpleNamespace(reminder_work_minutes=reminder_minutes)
    controller.state = ControllerState()
    controller._app_paths = {}
    controller._debug_notify = False
    controller._last_idle_s = 0
    controller._last_fg_short = "editor.exe"
    controller._cont_work_s = reminder_minutes * 60 if work_s is None else work_s
    controller._rest_ack_work_s = 0
    controller._rest_cycle = 0
    controller._rest_due = due
    controller._rest_notified = False
    controller._rest_snooze_until = 0.0
    controller._rest_next_prompt_work_s = 0
    controller._rest_prompt_acknowledged = False
    controller._is_resting = False
    controller._rest_blocked_last = False
    controller._rest_block_reason_last = ""

    controller._ensure_app_paths_loaded = lambda timeout=2.0: None
    controller.is_blacklisted = lambda _app: False
    controller.get_rest_start_guard_status = lambda: {
        "start_enabled": True,
        "start_unlock_in_ms": 0,
        "start_block_reason": "",
    }
    controller._emit_event = lambda **_kwargs: None
    controller._compensate_auto_idle_on_exit_rest = lambda: None
    return controller


def _rest_state(controller: AppController) -> dict:
    return controller._get_runtime_extra()["rest"]


class RestPromptAcknowledgementTests(unittest.TestCase):
    def test_dispatcher_receives_the_next_prompt_only_after_a_full_interval(self) -> None:
        controller = _controller()
        posted: list[tuple[dict, tuple]] = []
        dispatcher = SimpleNamespace(
            post_notify_show=lambda extra, key: posted.append((extra, key))
        )
        manager = NotificationManager(dispatcher=dispatcher, min_interval_s=1)

        first_extra = controller._get_runtime_extra()
        manager.on_snapshot(first_extra)
        self.assertEqual(len(posted), 1)

        first_key = posted[0][1]
        controller.dismiss_rest_prompt()
        manager.on_notify_complete(
            first_key, True, first_extra, mark_notified=False
        )

        controller._cont_work_s += 60
        manager.on_snapshot(controller._get_runtime_extra())
        self.assertEqual(len(posted), 1)

        controller._cont_work_s = controller._rest_next_prompt_work_s
        manager._last_show_time = 0.0
        manager.on_snapshot(controller._get_runtime_extra())
        self.assertEqual(len(posted), 2)

    def test_notification_timeout_is_treated_as_dismiss(self) -> None:
        overlay = QmlNotifyOverlay.__new__(QmlNotifyOverlay)
        actions: list[str] = []
        overlay._log = SimpleNamespace(info=lambda *_args: None)
        overlay._handle_action = actions.append

        overlay._on_auto_hide()

        self.assertEqual(actions, ["dismiss"])

    def test_auto_dismiss_waits_a_full_interval_not_one_minute(self) -> None:
        controller = _controller()
        self.assertTrue(_rest_state(controller)["should_prompt"])

        controller.dismiss_rest_prompt()
        controller._cont_work_s += 60

        rest = _rest_state(controller)
        self.assertTrue(rest["prompt_acknowledged"])
        self.assertFalse(rest["should_prompt"])

        controller._cont_work_s = controller._rest_next_prompt_work_s - 1
        self.assertFalse(_rest_state(controller)["should_prompt"])

        controller._cont_work_s += 1
        rest = _rest_state(controller)
        self.assertFalse(rest["prompt_acknowledged"])
        self.assertTrue(rest["should_prompt"])

    def test_skip_opens_the_next_round_at_the_exact_interval(self) -> None:
        controller = _controller(reminder_minutes=5)
        controller.rest_snooze()
        next_prompt_work_s = controller._rest_next_prompt_work_s

        controller._cont_work_s = next_prompt_work_s - 1
        self.assertFalse(_rest_state(controller)["should_prompt"])

        controller._cont_work_s = next_prompt_work_s
        self.assertTrue(_rest_state(controller)["should_prompt"])

    def test_completed_rest_restarts_the_cycle(self) -> None:
        controller = _controller(reminder_minutes=5)
        controller.rest_snooze()
        controller.rest_complete()
        controller._cont_work_s = 5 * 60

        rest = _rest_state(controller)
        self.assertFalse(rest["prompt_acknowledged"])
        self.assertTrue(rest["should_prompt"])

    def test_leaving_automatic_dnd_does_not_erase_skip(self) -> None:
        controller = _controller()
        controller.dismiss_rest_prompt()
        controller.state.is_dnd = True
        controller.state.dnd_reason = "auto_fullscreen"
        controller.state.prev_mode_before_auto_dnd = "normal"

        controller._reconcile_auto_dnd(auto_app="", auto_fullscreen=False)

        self.assertTrue(controller._rest_notified)
        self.assertTrue(controller._rest_prompt_acknowledged)
        self.assertEqual(controller._rest_next_prompt_work_s, 40 * 60)
        self.assertFalse(_rest_state(controller)["should_prompt"])

        controller._cont_work_s = controller._rest_next_prompt_work_s
        self.assertTrue(_rest_state(controller)["should_prompt"])

    def test_due_prompt_blocked_by_dnd_is_released_after_dnd(self) -> None:
        controller = _controller()
        controller.state.is_dnd = True
        controller.state.dnd_reason = "auto_fullscreen"
        controller.state.prev_mode_before_auto_dnd = "normal"
        self.assertFalse(_rest_state(controller)["should_prompt"])

        controller._reconcile_auto_dnd(auto_app="", auto_fullscreen=False)

        self.assertTrue(_rest_state(controller)["should_prompt"])


if __name__ == "__main__":
    unittest.main()
