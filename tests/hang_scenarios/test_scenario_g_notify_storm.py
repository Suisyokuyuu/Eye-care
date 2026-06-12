from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
@pytest.mark.long
def test_scenario_g_notify_storm(app_runner, scenario_driver, hang_detector):
    """Repeated debug notifications should not leave notify in HIDING."""

    app_runner.start_app()
    assert app_runner.wait_for_ready(), "App did not become ready before timeout"

    assert scenario_driver.run_scenario("scenario_g_notify_storm", timeout_s=15.0)
    assert hang_detector.wait_healthy_or_timeout(timeout_s=15.0, mode="notify_hide")

