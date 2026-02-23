from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
def test_scenario_i_settings_io_pressure(app_runner, scenario_driver, hang_detector):
    """
    场景 I：设置页高频操作 + 导入导出（配置 I/O 压力）

    目标：
    - 同时施压前端设置页（evaluate_js + 样式变更）和后端配置 I/O（_wait_controller + JSON WAL）；
    - 观察是否有锁竞争或长时间阻塞。
    """
    app_runner.start_app()
    assert app_runner.wait_for_ready(), "应用未在超时时间内就绪"

    assert scenario_driver.run_scenario("scenario_i_settings_io_pressure", timeout_s=12.0)
    ok = hang_detector.wait_healthy_or_timeout(timeout_s=12.0)
    assert ok, "场景 I 检测到疑似卡死"

