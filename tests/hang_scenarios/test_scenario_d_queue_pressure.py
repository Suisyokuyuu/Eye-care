from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
@pytest.mark.long
def test_scenario_d_queue_pressure(app_runner, scenario_driver, hang_detector):
    """
    场景 D：队列任务积压

    目标：
    - 在“任务风暴”场景下验证 GUI 不会完全停摆，或至少在几秒内恢复；
    - 结合 DIAG_METRIC_DISPATCH 等指标评估 queue_len 与调度推进情况（后续扩展）。

    当前实现：
    - 使用 ScenarioDriver 运行占位场景 \"scenario_d_queue_pressure\"，给予更长超时；
    - HangDetector 以较长简单超时作为第一道“未明显卡死”门槛。
    """
    app_runner.start_app()
    assert app_runner.wait_for_ready(), "应用未在超时时间内就绪"

    assert scenario_driver.run_scenario("scenario_d_queue_pressure", timeout_s=10.0)
    ok = hang_detector.wait_healthy_or_timeout(timeout_s=10.0)
    assert ok, "场景 D 检测到疑似卡死"

