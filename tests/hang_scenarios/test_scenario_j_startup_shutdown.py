from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
def test_scenario_j_startup_shutdown(app_runner, scenario_driver, hang_detector):
    """
    场景 J：应用启动与退出边界场景

    目标：
    - 覆盖“启动 -> 等待就绪 -> 立即退出”的快速循环；
    - 在部分循环中插入 Rest/Notify 操作，验证启动/退出边界不会导致挂起。
    """
    app_runner.start_app()
    assert app_runner.wait_for_ready(), "应用未在超时时间内就绪"

    assert scenario_driver.run_scenario("scenario_j_startup_shutdown", timeout_s=8.0)
    ok = hang_detector.wait_healthy_or_timeout(timeout_s=8.0)
    assert ok, "场景 J 检测到疑似卡死"

