---
title: 卡死场景测试说明（hang_scenarios，适用应用版本 V1.0.2）
---

本文件聚焦 `tests/hang_scenarios/` 目录下的卡死场景测试设计，基于当前测试代码整理，并参考《卡》计划文档（`.cursor/plans/卡_9678f5ad.plan.md`）中的场景定义与目标。

> **原则**：描述以现在的实际代码为准；若计划文档与实现存在差异，以本说明和测试代码为权威来源。

### 公共基础能力

- **AppRunner**
  - 位置：`tests/hang_scenarios/conftest.py`
  - 职责：
    - 通过 `main.py` 启动 EyE Care 应用；
    - 为每次运行创建独立的 `user_data_test_<timestamp>_<pid>_<uniq>` 目录，降低并发/快速重跑时的数据目录复用概率；
    - 设置 `EYECARE_DEBUG`、`EYECARE_API_PORT` 等环境变量；
    - 在测试会话结束时终止/杀掉子进程。
  - `wait_for_ready` 基于 `GET /api/health` 的 HTTP 探活，并要求返回体中包含 `{"ok": true}`，避免仅以“进程存活”作为就绪判据。

- **HangDetector**
  - 位置：`tests/hang_scenarios/conftest.py`
  - 当前能力（基于 `eye_care.diagnostics.notify_hang_analyzer`）：
    - 始终根据当前 AppRunner.data_dir 解析 `debug.log`；
    - 提供 `wait_healthy_or_timeout(timeout_s, mode="generic"|"notify_hide", require_min_hide_pairs=None|int)`：
      - 在给定时间内等待 `debug.log` 出现；
      - 使用 `analyze_debug_log_file` 解析 DIAG_SM_TRANSITION / DIAG_METRIC_* / 与简化淡出链路相关的 DIAG_EXCEPTION；
      - 如存在未闭合 HIDING（open_hiding），或 HIDING→HIDDEN 耗时超过 `hiding_warn_threshold_s`，视为疑似卡死。
    - 其中 `mode="notify_hide"` 聚焦 notify HIDING→HIDDEN 闭环健康度，`require_min_hide_pairs` 可用于要求至少观测到一定数量的 HIDE_REQ/HIDE_DONE 闭环。

- **ScenarioDriver**
  - 位置：`tests/hang_scenarios/conftest.py`
  - 核心接口：`run_scenario(name: str, timeout_s: float) -> bool`
  - 通用行为：
    - 如有需要先启动应用并等待 `/api/health` 就绪；
    - 通过 `POST /api/diag/log` 记录场景起始埋点（需携带 `X-EYECare-Token`）。
  - 已实现的按场景分支逻辑（摘录）：
    - `scenario_f_notify_hide`：
      - 通过 `POST /api/config` 将 `notify_auto_hide_seconds` 临时调低（例如 3 秒）；
      - 触发一次 `POST /api/debug/notify`，随后在剩余窗口内保持 idle，交给前端 autoHide 推进 HIDE_REQ/HIDE_DONE 闭环。
    - `scenario_g_notify_storm`：
      - 同样临时调低 auto-hide；
      - 窗口前半段以约 0.2 秒间隔连续触发 `POST /api/debug/notify`（模拟 notify 风暴），后半段完全 idle，为 autoHide 与 HIDING→HIDDEN 闭环留出空间。
    - `scenario_k_notify_ack_repost_guard`：
      - 临时调低 auto-hide；
      - 在 timeout 窗口前 60% 时间内以约 0.8 秒间隔多轮触发 `POST /api/debug/notify`，放大“前端 ACK → `_schedule_actual_show_from_ack` → `_do_actual_show`”路径的覆盖；
      - 若整个主动 show 段一次 notify 都未成功触发，则直接视为场景失败，避免假阳性。
  - 其余场景暂以“就绪后 sleep 一段时间”的占位实现，后续可继续替换为更高保真度的 HTTP/控制类调用。

### 场景一览与设计目标

#### 场景 A：前端 JS 执行阻塞（高风险）

- **文件**：`test_scenario_a_js_block.py`
- **pytest 标记**：`@pytest.mark.hang_scenario`
- **当前实现**：
  - 启动应用，等待 ready；
  - 调用 `hang_detector.wait_healthy_or_timeout(timeout_s=5.0)` 作为粗粒度健康检查。
- **设计目标（来自《卡》与 DEADLOCK_ANALYSIS）**：
  - 在测试模式下注入“长 JS”函数（例如 `window.testLongJs(5000)`）；
  - 通过后端触发一次 `evaluate_js`，模拟前端执行阻塞；
  - 使用 HangDetector 基于 `DIAG_METRIC_DISPATCH` 判断 GUI 调度在合理时间内是否恢复。

#### 场景 B：样式应用等待超时

- **文件**：`test_scenario_b_style_wait.py`
- **pytest 标记**：`@pytest.mark.hang_scenario`
- **当前实现**：
  - 使用 `ScenarioDriver.run_scenario("scenario_b_style_wait", timeout_s=5.0)` 作为占位执行；
  - 之后通过 `hang_detector.wait_healthy_or_timeout(5.0)` 做超时判断。
- **设计目标**：
  - 复现多次 Rest 窗口 show/hide，在样式应用链路上施加压力；
  - 验证样式等待机制不会导致 GUI 长时间阻塞，即使触发超时也能快速降级；
  - 后续结合样式相关诊断日志做更细粒度的健康评估。

#### 场景 C：Controller 就绪等待阻塞

- **文件**：`test_scenario_c_controller_wait.py`
- **pytest 标记**：`@pytest.mark.hang_scenario`
- **当前实现**：
  - `ScenarioDriver.run_scenario("scenario_c_controller_wait", timeout_s=5.0)`；
  - `hang_detector.wait_healthy_or_timeout(5.0)`。
- **设计目标**：
  - 在 controller 初始化被人为延迟时，立即触发导入/导出等操作；
  - 验证这些操作最多造成可控阻塞（约 5 秒），不会演化为长时间卡死；
  - 将来结合 `_wait_controller` 相关诊断信息做更精细的判断。

#### 场景 D：队列任务积压

- **文件**：`test_scenario_d_queue_pressure.py`
- **pytest 标记**：`@pytest.mark.hang_scenario`、`@pytest.mark.long`
- **当前实现**：
  - `ScenarioDriver.run_scenario("scenario_d_queue_pressure", timeout_s=10.0)`；
  - `hang_detector.wait_healthy_or_timeout(10.0)`。
- **设计目标**：
  - 构造“任务风暴”，向 GUI dispatcher 投递大量任务；
  - 通过 `DIAG_METRIC_DISPATCH` 中的 `queue_len`、`dispatch_ms_last` 等字段评估：
    - 队列高水位是否能在合理时间内回落；
    - GUI 调度是否持续推进，而非长期停摆。

#### 场景 E：额外高危常见链路（占位）

- **文件**：`test_scenario_e_high_risk_placeholder.py`
- **pytest 标记**：`@pytest.mark.hang_scenario`
- **当前实现**：
  - `ScenarioDriver.run_scenario("scenario_e_high_risk_placeholder", timeout_s=8.0)`；
  - `hang_detector.wait_healthy_or_timeout(8.0)`。
- **设计目标**：
  - 为尚未在 DEADLOCK_ANALYSIS 中单独成章、但被认为高危的历史缺陷或配置组合预留容器；
  - 后续可将这些场景具体化为可重放脚本。

#### 场景 F：通知隐藏流程中的卡死

- **文件**：`test_scenario_f_notify_hide.py`
- **pytest 标记**：`@pytest.mark.hang_scenario`
- **当前实现**：
  - `ScenarioDriver.run_scenario("scenario_f_notify_hide", timeout_s=8.0)`；
  - `hang_detector.wait_healthy_or_timeout(timeout_s=8.0, mode="notify_hide")`。
- **设计目标**：
  - 复现“notify HIDING 后没有 HIDE_DONE”的高风险链路；
  - 结合 `DIAG_SM_TRANSITION`、`DIAG_NOTIFY_PIPE` 等诊断事件：
    - 量化 HIDING→HIDDEN 耗时；
    - 识别未闭合的 HIDING 会话与潜在卡死。

#### 场景 G：频繁通知 show/hide 交错（notify 风暴）

- **文件**：`test_scenario_g_notify_storm.py`
- **pytest 标记**：`@pytest.mark.hang_scenario`、`@pytest.mark.long`
- **当前实现**：
  - `ScenarioDriver.run_scenario("scenario_g_notify_storm", timeout_s=15.0)`；
  - `hang_detector.wait_healthy_or_timeout(15.0)`。
- **设计目标**：
  - 模拟高频 notify show/hide 的“风暴”场景；
  - 确保不会触发新的 HIDING 卡死或 GUI 停摆；
  - 后续通过诊断信号观察 `_hide_in_progress` 是否长时间保持 True。

#### 场景 H：Rest 窗口与 Notify 窗口交替/重叠

- **文件**：`test_scenario_h_rest_notify_combo.py`
- **pytest 标记**：`@pytest.mark.hang_scenario`
- **当前实现**：
  - `ScenarioDriver.run_scenario("scenario_h_rest_notify_combo", timeout_s=12.0)`；
  - `hang_detector.wait_healthy_or_timeout(12.0)`。
- **设计目标**：
  - 复现 Rest 与 Notify 窗口在短时间内交替/重叠的组合链路；
  - 检查在数十秒压力下：
    - GUI 线程是否保持健康；
    - 日志中是否存在异常卡死相关事件。

#### 场景 I：设置页高频操作 + 导入导出（配置 I/O 压力）

- **文件**：`test_scenario_i_settings_io_pressure.py`
- **pytest 标记**：`@pytest.mark.hang_scenario`
- **当前实现**：
  - `ScenarioDriver.run_scenario("scenario_i_settings_io_pressure", timeout_s=12.0)`；
  - `hang_detector.wait_healthy_or_timeout(12.0)`。
- **设计目标**：
  - 同时对前端设置页和后端配置 I/O 施压：
    - 前端：频繁切换 tab/主题/语言（大量 `evaluate_js` 与样式更新）；
    - 后端：循环执行“导出配置 / 导入配置”等操作。
  - 观察是否出现锁竞争或长时间阻塞。

#### 场景 J：应用启动与退出边界场景

- **文件**：`test_scenario_j_startup_shutdown.py`
- **pytest 标记**：`@pytest.mark.hang_scenario`
- **当前实现**：
  - `ScenarioDriver.run_scenario("scenario_j_startup_shutdown", timeout_s=8.0)`；
  - `hang_detector.wait_healthy_or_timeout(8.0)`。
- **设计目标**：
  - 多轮执行“启动 → 等待就绪 → 立即退出”的快速循环；
  - 在部分循环中插入 Rest/Notify 操作；
  - 观察启动和退出边界时是否存在挂起风险。

### 使用建议与后续扩展

- **如何新增一个卡死场景用例**
  - 在 `tests/hang_scenarios/` 下新增 `test_scenario_<x>_*.py`，并：
    - 使用 `@pytest.mark.hang_scenario` 标记；
    - 复用 `app_runner`、`scenario_driver`、`hang_detector` 三个 fixture；
    - 根据场景特点选择是否加 `@pytest.mark.long`。
  - 在本文件中补充该场景的说明，保持文档与代码同步。

- **逐步增强现有场景**
  - 先保持当前“占位”实现，保证回归时至少能覆盖“应用能正常启动并在一定时间内不明显卡死”；
  - 随着诊断能力完善，逐个场景替换 `ScenarioDriver` 的占位逻辑为真实操作链路；
  - 在 `HangDetector` 中为核心场景（如 A、D、G、H）优先接入诊断事件解析。

通过上述方式，可以在不影响当前代码结构的前提下，逐步将《卡》文档中的卡死场景设计落地为可执行、可回归、可度量的自动化测试集。

