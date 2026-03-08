---
title: 测试总览（含卡死场景，适用应用版本 V1.0.3）
---

本目录用于描述 EyE Care 项目的自动化测试设计与现状，实现与规划并存，方便开发、测试和验收人员统一对齐。

> **说明**：本文件以实际测试代码为准（`tests/` 目录）。

### 测试目录结构概览

- **核心测试目录**
  - `tests/`：pytest 测试根目录。
  - `tests/__init__.py`：占位说明，当前主要挂载卡死场景测试包。
  - `tests/hang_scenarios/`：卡死场景相关用例，详见下文。

- **后续规划（尚未落地到代码）**
  - `tests/api/`：REST API 级别用例（鉴权、配置读写、调试路由等）。
  - `tests/ui/`：前端/交互层用例（设置页、rest/notify 交互等），可结合浏览器自动化或前端自测脚本。
  - `tests/regression/`：重要缺陷回归用例。

### 当前已实现的测试能力

- **pytest 集成**
  - 统一使用 pytest 作为测试框架。
  - 卡死场景使用 `@pytest.mark.hang_scenario` 作为标记。
  - 长时压力场景额外使用 `@pytest.mark.long` 标记，便于在 CI 中分组运行。

- **被测应用进程管理（AppRunner）**
  - 定义于 `tests/hang_scenarios/conftest.py`。
  - 负责：
    - 启动 EyE Care 应用（通过 `main.py`）；
    - 为每轮测试创建独立的 `user_data_test_<timestamp>` 目录；
    - 设置调试相关环境变量（如 `EYECARE_DEBUG=1`、`EYECARE_API_PORT`）；
    - 在会话结束时优雅退出/强制终止进程。

- **场景驱动器（ScenarioDriver）**
  - 同样位于 `tests/hang_scenarios/conftest.py`。
  - 当前为“占位骨架”：
    - 按名称 `run_scenario(name: str, timeout_s: float)` 启动应用并等待一段时间；
    - 预留将来根据 `name` 实际调用 HTTP API 或内部控制类的扩展点。

- **卡死检测器（HangDetector）**
  - 位于 `tests/hang_scenarios/conftest.py`。
  - 当前实现（基于 `eye_care.diagnostics.notify_hang_analyzer`）：
    - 解析 `debug.log` 中的 `DIAG_SM_TRANSITION`（notify 状态机迁移）、`DIAG_EXCEPTION`（含 `reason_code`）、`DIAG_METRIC_DISPATCH` / `DIAG_METRIC_NOTIFY` 以及一组关键 ALWAYS_ON 事件；
    - 提供 `wait_healthy_or_timeout(timeout_s, mode="generic"|"notify_hide", require_min_hide_pairs: int|None = None)`：
      - 在给定时间内等待 `debug.log` 产出，否则视为异常；
      - 优先检查 `DIAG_FLASK_TIMEOUT`、`DIAG_NOTIFY_ACK_POST_FAILED` 等 ALWAYS_ON 事件，一旦命中直接视为本轮场景失败（疑似卡死或链路严重降级）；
      - 对 notify HIDING→HIDDEN 链路做健康度检查：若存在仍处于 HIDING 且未匹配到 HIDE_DONE 的会话，或在 `mode="notify_hide"` 下出现耗时超过阈值的 HIDING，会视为疑似卡死；
      - 可选地通过 `require_min_hide_pairs` 要求至少观察到一定数量的 HIDE_REQ/HIDE_DONE 闭环，避免“完全未覆盖核心链路也通过”的假阳性。
  - 后续仍可结合 DEADLOCK_ANALYSIS 与《卡》文档，进一步在此基础上接入更多诊断事件（如 `DIAG_NOTIFY_STAGE` / `DIAG_REST_STAGE` 等），丰富判定信号。

### 卡死场景测试总览

> 详细场景描述见同目录下的 `hang_scenarios.md`。

当前 `tests/hang_scenarios/` 中已经覆盖或预留的场景包括：

- **场景 A：前端 JS 执行阻塞（`test_scenario_a_js_block.py`）**
- **场景 B：样式应用等待超时（`test_scenario_b_style_wait.py`）**
- **场景 C：Controller 就绪等待阻塞（`test_scenario_c_controller_wait.py`）**
- **场景 D：队列任务积压（`test_scenario_d_queue_pressure.py`，带 `@pytest.mark.long`）**
- **场景 E：额外高危常见链路（占位）（`test_scenario_e_high_risk_placeholder.py`）**
- **场景 F：通知隐藏流程卡死（`test_scenario_f_notify_hide.py`）**
- **场景 G：notify 风暴（`test_scenario_g_notify_storm.py`，带 `@pytest.mark.long`）**
- **场景 H：Rest/Notify 组合链路（`test_scenario_h_rest_notify_combo.py`）**
- **场景 I：设置页高频操作 + 导入导出（配置 I/O 压力）（`test_scenario_i_settings_io_pressure.py`）**
- **场景 J：启动与退出边界场景（`test_scenario_j_startup_shutdown.py`）**

这些用例目前多为“占位实现”：通过统一的 `AppRunner + ScenarioDriver + HangDetector` 骨架，保证每个场景在 pytest 层面可以运行，为后续逐步填充具体操作和诊断逻辑打基础。

### 运行方式与分组策略

- **本地调试**
  - 运行全部卡死场景：
    - `pytest -m hang_scenario tests/hang_scenarios -vv`
  - 仅运行短场景（排除长时压力）：
    - `pytest -m "hang_scenario and not long" tests/hang_scenarios -vv`

- **CI 建议分组**
  - 快速冒烟组：
    - 覆盖 A、B、C、G、I、J、K 等单次耗时较短的场景。
  - 夜间长跑组：
    - 覆盖 D、H 以及后续扩展的长时间压力用例。

### 与《卡》计划文档的映射关系

- **已落地的部分**
  - 测试目录结构中的 `tests/hang_scenarios/` 及各场景文件，基本对应《卡》文档中的 A–D、G–K 场景编号。
  - `AppRunner` / `ScenarioDriver` / `HangDetector` 的职责划分与《卡》文档一致，只是当前实现为“最小可用骨架”。

- **尚未完全落地的部分**
  - 针对 `DIAG_METRIC_DISPATCH`、`DIAG_NOTIFY_PIPE`、`DIAG_SM_TRANSITION` 等诊断事件的精细解析逻辑。
  - 与 EXE 黑盒/UI 自动化结合的场景回放（如脚本层的 win automation）。
  - 更丰富的结果采集与失败归档（打包 `user_data` 片段、事件日志等到 CI 附件）。

在后续迭代中，建议优先在现有测试骨架上补齐高风险场景的诊断逻辑，然后再扩展到 EXE 黑盒与更全面的回归组。

