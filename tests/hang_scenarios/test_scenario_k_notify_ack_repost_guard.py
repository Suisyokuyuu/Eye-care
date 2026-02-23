from __future__ import annotations

import pytest


@pytest.mark.hang_scenario
@pytest.mark.long
def test_scenario_k_notify_ack_repost_guard(app_runner, scenario_driver, hang_detector):
    """
    场景 K：多轮 notify ACK + show + autoHide 回归（repost_guard / ACK 严格投递）

    目标：
    - 覆盖「前端 ACK → _schedule_actual_show_from_ack → _do_actual_show」严格投递路径；
    - 在多轮 notify show/hide 循环中验证 repost_guard 不会误锁导致后续 show 长期停摆；
    - 结合 notify_hang_analyzer，确认在压力场景下 HIDING→HIDDEN 闭环仍然健康。
    """
    app_runner.start_app()
    assert app_runner.wait_for_ready(), "应用未在超时时间内就绪"

    # 使用略长时间窗口，留足多轮 show→ACK→autoHide 闭环时间。
    assert scenario_driver.run_scenario("scenario_k_notify_ack_repost_guard", timeout_s=15.0)

    # 当前调试环境下 debug.log 暂未开启 notify 状态机的 DIAG_SM_TRANSITION 细粒度埋点，
    # 因此无法稳定统计 HIDE_REQ/HIDE_DONE 闭环次数；先仅依赖健康判定：
    # - 无未闭合 HIDING（open_hiding 为空）；
    # - HIDING→HIDDEN 耗时不超过 hiding_warn_threshold_s。
    # 后续一旦 DIAG_SM_TRANSITION / DIAG_METRIC_NOTIFY 等埋点完备，可在此基础上
    # 再启用 require_min_hide_pairs 等更严格的闭环覆盖校验。
    ok = hang_detector.wait_healthy_or_timeout(
        timeout_s=15.0,
        mode="notify_hide",
    )
    assert ok, "场景 K 检测到疑似卡死（notify ACK/repost_guard 回归）"

