from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
def test_scenario_a_js_block(app_runner, scenario_driver, hang_detector):
    """
    场景 A：前端 JS 执行阻塞（高风险）

    当前为占位用例：
    - 启动应用（debug 模式）；
    - 简单等待一段时间，视为“未出现明显卡死”。

    后续可按计划：
    - 在测试模式下注入 window.testLongJs(5000)；
    - 通过后端触发一次 evaluate_js；
    - 使用 HangDetector 监控 GUI 调度是否在预期时间内恢复。
    """
    app_runner.start_app()
    assert app_runner.wait_for_ready(), "应用未在超时时间内就绪"

    # 目前仅用简单超时占位，后续扩展 HangDetector 逻辑
    ok = hang_detector.wait_healthy_or_timeout(timeout_s=5.0)
    assert ok, "场景 A 检测到疑似卡死"

