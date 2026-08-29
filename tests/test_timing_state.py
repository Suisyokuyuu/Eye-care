from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from eye_care.controller.app_controller import AppController, ControllerState
from eye_care.qt_quick.rest_overlay import QmlRestOverlay


class _OneTickStop:
    def __init__(self) -> None:
        self._checks = 0

    def is_set(self) -> bool:
        self._checks += 1
        return self._checks > 1


class _Watcher:
    def __init__(self) -> None:
        self.active: list[bool] = []

    def set_active(self, value: bool) -> None:
        self.active.append(bool(value))


class _Repo:
    def __init__(self) -> None:
        self.usage = []

    def add_usage(self, delta) -> None:
        self.usage.append(delta)

    def flush(self) -> None:
        pass


def _controller(*, work_s: int = 0) -> AppController:
    c = AppController.__new__(AppController)
    c.cfg = SimpleNamespace(
        sample_interval_s=1.0,
        idle_threshold_s=60,
        reminder_rest_seconds=20,
        reminder_work_minutes=1,
        app_auto_dnd_on_focus={"game": True},
        fullscreen_dnd=True,
        record_browser_enabled=False,
    )
    c.state = ControllerState()
    c._lock = threading.RLock()
    c._stop = _OneTickStop()
    c._tick_mono_last = time.monotonic() - 1.1
    c._tick_accum = 0.0
    c._last_flush = time.monotonic()
    c._last_checkpoint = time.monotonic()
    c._last_app_paths_persist = time.monotonic()
    c._checkpoint_inflight = False
    c._checkpoint_lock = threading.Lock()

    c._last_idle_s = 0
    c._prev_idle_s = 0
    c._last_fg_short = ""
    c._last_count_app = ""
    c._app_paths = {}
    c._session_inactive_since_mono = 0.0
    c._idle_probe_failed_since_mono = 0.0
    c._last_screen_activity_mono = 0.0
    c._auto_idle_entered_at = 0.0
    c._auto_idle_min_duration = 0.0
    c._auto_idle_entry_idle = -1
    c._fs_true_streak = 0
    c._fs_false_streak = 0
    c._fs_stable = False

    c._cont_work_s = work_s
    c._rest_ack_work_s = 0
    c._rest_cycle = 0
    c._rest_due = False
    c._rest_notified = False
    c._rest_snooze_until = 0.0
    c._rest_next_prompt_work_s = 0
    c._rest_prompt_acknowledged = False
    c._is_resting = False
    c._rested_settled = False
    c._rest_blocked_last = False
    c._rest_block_reason_last = ""

    c._debug_notify = False
    c._debug_last_log_ts = 0.0
    c._debug_last_tick_log_ts = 0.0
    c._auto_settle_diag_ts = 0.0
    c._browser_watcher = _Watcher()
    c.repo = _Repo()

    c._emit_event = lambda **_kwargs: None
    c._maybe_record_domain = lambda *_args: None
    c._cleanup_app_paths_runtime = lambda: 0
    c._persist_app_paths = lambda: None
    c._compensate_auto_idle_on_exit_rest = lambda: None
    c._ensure_app_paths_loaded = lambda timeout=2.0: None
    c.get_rest_start_guard_status = lambda: {
        "start_enabled": True,
        "start_unlock_in_ms": 0,
        "start_block_reason": "",
    }
    c.is_blacklisted = lambda _app: False
    return c


def _run_tick(c: AppController, *, interactive: bool, idle: int | None, app: str, fullscreen: bool = False) -> None:
    fg = SimpleNamespace(app_short=app, exe_path=f"C:/{app}.exe")
    with (
        patch("eye_care.controller.app_controller.is_user_session_interactive", return_value=interactive),
        patch("eye_care.controller.app_controller.get_idle_seconds_checked", return_value=idle),
        patch("eye_care.controller.app_controller.get_foreground", return_value=fg),
        patch("eye_care.controller.app_controller.is_foreground_fullscreen", return_value=fullscreen),
        patch("eye_care.controller.app_controller.time.sleep", return_value=None),
    ):
        c._tick_loop()


class TimingStateTests(unittest.TestCase):
    def test_rest_countdown_does_not_drop_a_second_immediately(self) -> None:
        self.assertEqual(QmlRestOverlay._fmt(19.01), "00:20")
        self.assertEqual(QmlRestOverlay._fmt(19.0), "00:19")
        self.assertEqual(QmlRestOverlay._fmt(-0.01), "00:00")

    def test_auto_dnd_game_keeps_counting_after_keyboard_idle(self) -> None:
        c = _controller(work_s=58)

        _run_tick(c, interactive=True, idle=600, app="game")

        self.assertTrue(c.state.is_dnd)
        self.assertEqual(c.state.dnd_reason, "auto_app")
        self.assertFalse(c.state.auto_idle)
        self.assertGreaterEqual(c._cont_work_s, 59)
        self.assertEqual([d.app_short for d in c.repo.usage], ["game"])

    def test_idle_threshold_is_not_doubled_by_activity_tracking(self) -> None:
        c = _controller(work_s=30)
        _run_tick(c, interactive=True, idle=59, app="editor")

        c._stop = _OneTickStop()
        c._tick_mono_last = time.monotonic() - 1.1
        # 测试循环不真的 sleep；补上两拍之间经过的 1 秒。
        c._last_screen_activity_mono -= 1.1
        _run_tick(c, interactive=True, idle=60, app="editor")

        self.assertTrue(c.state.auto_idle)
        self.assertEqual(c._cont_work_s, 0)
        self.assertEqual(c._rest_cycle, 1)
        self.assertEqual(len(c.repo.usage), 1)

    def test_due_game_prompt_is_released_when_auto_dnd_ends(self) -> None:
        c = _controller(work_s=59)
        _run_tick(c, interactive=True, idle=600, app="game")
        self.assertTrue(c._rest_due)
        self.assertFalse(c._get_runtime_extra()["rest"]["should_prompt"])

        c._stop = _OneTickStop()
        c._tick_mono_last = time.monotonic() - 1.1
        _run_tick(c, interactive=True, idle=600, app="editor")

        self.assertFalse(c.state.is_dnd)
        self.assertFalse(c.state.auto_idle)
        self.assertTrue(c._get_runtime_extra()["rest"]["should_prompt"])

    def test_fullscreen_dnd_counts_and_releases_due_prompt_after_debounce(self) -> None:
        c = _controller(work_s=58)
        c.cfg.app_auto_dnd_on_focus = {}

        # 进入全屏需连续两拍；第一拍仍有键鼠输入，第二拍即使键鼠已 idle 也应计时。
        _run_tick(c, interactive=True, idle=0, app="player", fullscreen=True)
        c._stop = _OneTickStop()
        c._tick_mono_last = time.monotonic() - 1.1
        _run_tick(c, interactive=True, idle=600, app="player", fullscreen=True)

        self.assertTrue(c.state.is_dnd)
        self.assertEqual(c.state.dnd_reason, "auto_fullscreen")
        self.assertTrue(c._rest_due)
        self.assertEqual([d.app_short for d in c.repo.usage], ["player", "player"])
        self.assertFalse(c._get_runtime_extra()["rest"]["should_prompt"])

        # 退出全屏需连续四拍，离开后应恢复正常并释放到期提醒。
        for _ in range(4):
            c._stop = _OneTickStop()
            c._tick_mono_last = time.monotonic() - 1.1
            _run_tick(c, interactive=True, idle=600, app="editor", fullscreen=False)

        self.assertFalse(c.state.is_dnd)
        self.assertFalse(c.state.auto_idle)
        self.assertTrue(c._get_runtime_extra()["rest"]["should_prompt"])

    def test_remote_disconnect_stops_usage_immediately(self) -> None:
        c = _controller(work_s=30)
        c._session_inactive_since_mono = time.monotonic() - 10

        _run_tick(c, interactive=False, idle=0, app="game")

        self.assertFalse(c.state.session_interactive)
        self.assertTrue(c.state.auto_idle)
        self.assertEqual(c._cont_work_s, 30)
        self.assertEqual(c.repo.usage, [])

    def test_idle_probe_failure_is_not_treated_as_recent_input(self) -> None:
        c = _controller(work_s=30)

        _run_tick(c, interactive=True, idle=None, app="editor")

        self.assertTrue(c.state.auto_idle)
        self.assertEqual(c._cont_work_s, 30)
        self.assertEqual(c.repo.usage, [])

    def test_remote_disconnect_long_enough_completes_rest(self) -> None:
        c = _controller(work_s=59)
        c._rest_due = True
        c._session_inactive_since_mono = time.monotonic() - 61

        _run_tick(c, interactive=False, idle=0, app="game")

        self.assertEqual(c._cont_work_s, 0)
        self.assertFalse(c._rest_due)
        self.assertEqual(c._rest_cycle, 1)
        self.assertEqual(c.repo.usage, [])

    def test_suspend_sized_unobserved_gap_is_not_attributed_as_usage(self) -> None:
        c = _controller(work_s=59)
        c._rest_due = True
        c._tick_mono_last = time.monotonic() - 61

        _run_tick(c, interactive=True, idle=0, app="editor")

        self.assertEqual(c._cont_work_s, 0)
        self.assertFalse(c._rest_due)
        self.assertEqual(c.repo.usage, [])

    def test_auto_idle_never_releases_a_due_prompt(self) -> None:
        c = _controller(work_s=60)
        c._rest_due = True
        c.state.auto_idle = True

        self.assertFalse(c._get_runtime_extra()["rest"]["should_prompt"])

    def test_noninteractive_session_never_releases_a_due_prompt(self) -> None:
        c = _controller(work_s=60)
        c._rest_due = True
        c.state.session_interactive = False

        self.assertFalse(c._get_runtime_extra()["rest"]["should_prompt"])


if __name__ == "__main__":
    unittest.main()
