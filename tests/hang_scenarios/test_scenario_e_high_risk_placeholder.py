from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
def test_scenario_e_high_risk_placeholder(app_runner, scenario_driver, hang_detector):
    """
    场景 E：额外高危常见链路（占位）

    用于承载新增但尚未在 DEADLOCK_ANALYSIS 中单独成章的高危卡死场景，
    例如某些特定配置组合或历史缺陷回归链路。
    """
    app_runner.start_app()
    assert app_runner.wait_for_ready(), "应用未在超时时间内就绪"

    assert scenario_driver.run_scenario("scenario_e_high_risk_placeholder", timeout_s=8.0)
    ok = hang_detector.wait_healthy_or_timeout(timeout_s=8.0)
    assert ok, "场景 E 检测到疑似卡死"

