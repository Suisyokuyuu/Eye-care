from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
def test_scenario_h_rest_notify_combo(app_runner, scenario_driver, hang_detector):
    """
    场景 H：Rest 窗口与 Notify 窗口交替/重叠

    目标：
    - 覆盖 \"Rest → Notify → Rest → Notify\" 等组合链路，对样式链路与 dispatcher 施加综合压力；
    - 确保在数十秒压力下 GUI 线程保持健康，日志中无异常卡死事件。
    """
    app_runner.start_app()
    assert app_runner.wait_for_ready(), "应用未在超时时间内就绪"

    assert scenario_driver.run_scenario("scenario_h_rest_notify_combo", timeout_s=12.0)
    ok = hang_detector.wait_healthy_or_timeout(timeout_s=12.0)
    assert ok, "场景 H 检测到疑似卡死"

