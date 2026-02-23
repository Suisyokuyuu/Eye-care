from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
def test_scenario_f_notify_hide(app_runner, scenario_driver, hang_detector):
    """
    场景 F：通知隐藏流程中的卡死

    目标：
    - 复现“notify HIDING 后没有 HIDE_DONE”的高风险链路；
    - 后续结合 debug.log 中的 DIAG_SM_TRANSITION / DIAG_NOTIFY_PIPE 等诊断事件，
      量化 HIDING→HIDDEN 耗时与未闭合 HIDING 会话。

    当前实现：
    - 使用 ScenarioDriver 运行场景 \"scenario_f_notify_hide\"；
    - HangDetector 先用简单超时占位，后续在此基础上扩展状态机健康判定。
    """
    app_runner.start_app()
    assert app_runner.wait_for_ready(), "应用未在超时时间内就绪"

    assert scenario_driver.run_scenario("scenario_f_notify_hide", timeout_s=8.0)
    # 使用 notify_hide 模式，基于 HIDING→HIDDEN 耗时与未闭合 HIDING 会话做专用判定。
    ok = hang_detector.wait_healthy_or_timeout(timeout_s=8.0, mode="notify_hide")
    assert ok, "场景 F 检测到疑似卡死"

