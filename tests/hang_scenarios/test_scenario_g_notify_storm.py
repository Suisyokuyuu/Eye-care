from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
@pytest.mark.long
def test_scenario_g_notify_storm(app_runner, scenario_driver, hang_detector):
    """
    场景 G：频繁通知 show/hide 交错（notify 风暴）

    目标：
    - 验证在高频 notify show/hide 下不会触发新的 HIDING 卡死或 GUI 停摆；
    - 后续可通过 Diagnostics 进一步观察 _hide_in_progress 是否长时间保持 True。
    """
    app_runner.start_app()
    assert app_runner.wait_for_ready(), "应用未在超时时间内就绪"

    assert scenario_driver.run_scenario("scenario_g_notify_storm", timeout_s=15.0)
    # 仍复用 notify_hide 逻辑，以 HIDING 耗时与未闭合会话作为回归判定基础。
    ok = hang_detector.wait_healthy_or_timeout(timeout_s=15.0, mode="notify_hide")
    assert ok, "场景 G 检测到疑似卡死"

