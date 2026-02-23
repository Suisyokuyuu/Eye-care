from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
def test_scenario_b_style_wait(app_runner, scenario_driver, hang_detector):
    """
    场景 B：样式应用等待超时

    目标（见卡死方案文档）：
    - 多次 Rest 窗口 show/hide，不应导致 GUI 长时间阻塞；
    - 即便触发样式等待超时，也能快速降级。

    当前实现：
    - 使用 ScenarioDriver 运行占位场景 \"scenario_b_style_wait\"，仅做时间占位；
    - 通过 HangDetector 的简单超时判断作为“未明显卡死”的基础校验。
    """
    app_runner.start_app()
    assert app_runner.wait_for_ready(), "应用未在超时时间内就绪"

    assert scenario_driver.run_scenario("scenario_b_style_wait", timeout_s=5.0)
    ok = hang_detector.wait_healthy_or_timeout(timeout_s=5.0)
    assert ok, "场景 B 检测到疑似卡死"

