from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
def test_scenario_f_notify_hide(app_runner, scenario_driver, hang_detector):
    """A single debug notification should auto-hide without getting stuck."""

    app_runner.start_app()
    assert app_runner.wait_for_ready(), "App did not become ready before timeout"

    assert scenario_driver.run_scenario("scenario_f_notify_hide", timeout_s=8.0)
    assert hang_detector.wait_healthy_or_timeout(timeout_s=8.0, mode="notify_hide")

