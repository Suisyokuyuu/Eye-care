from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
def test_scenario_c_controller_wait(app_runner, scenario_driver, hang_detector):
    """
    场景 C：Controller 就绪等待阻塞

    目标：
    - 导入/导出操作在 controller 未就绪时，最多是可控阻塞（约 5 秒），不会导致长时间卡死。

    当前实现：
    - 使用 ScenarioDriver 运行占位场景 \"scenario_c_controller_wait\"；
    - HangDetector 用简单超时判断代替对 _wait_controller 细节的解析。
    """
    app_runner.start_app()
    assert app_runner.wait_for_ready(), "应用未在超时时间内就绪"

    assert scenario_driver.run_scenario("scenario_c_controller_wait", timeout_s=5.0)
    ok = hang_detector.wait_healthy_or_timeout(timeout_s=5.0)
    assert ok, "场景 C 检测到疑似卡死"

