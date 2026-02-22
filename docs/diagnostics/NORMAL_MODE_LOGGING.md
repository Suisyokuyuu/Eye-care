# 普通启动模式下的日志内容（最终口径）

更新时间：2026-02-22

适用条件：未开启 debug（`EYECARE_DEBUG` 关闭，且配置未启用 debug）。

## 1) 输出位置

- 始终写入：`data_dir/debug.log`（RotatingFileHandler，约 1MB，保留 5 份）
- 控制台输出：仅当 `EYECARE_CONSOLE_LOG=1` 时开启

## 2) 诊断事件放行规则

普通模式下，仅 `policy=ALWAYS_ON` 的 canonical 事件会被策略引擎放行。

当前 ALWAYS_ON 事件：

- `DIAG_APP_START_OK`
- `DIAG_APP_EXIT_OK`
- `DIAG_FLASK_TIMEOUT`
- `DIAG_DISPATCH_ILLEGAL`
- `DIAG_DISPATCH_REJECT`
- `DIAG_NOTIFY_STYLE_APPLY_FAIL`
- `DIAG_REST_OVERLAY_CREATE_FAIL`
- `DIAG_REST_GUARD_UNLOCK`
- `DIAG_REST_GUARD_BLOCK`
- `DIAG_STOP_TICK_JOIN`
- `DIAG_REPO_CLOSE_FAIL`
- `DIAG_EXIT_STATE_WRITE`
- `DIAG_EXCEPTION`
- `DIAG_UNCAUGHT`
- `DIAG_UNCAUGHT_THREAD`
- `DIAG_UNKNOWN_EVENT`
- `DIAG_SM_REJECT`
- `DIAG_SM_DEFER`

## 3) 普通模式下不会记录的典型事件

以下需要 debug 模式与模块开关：

- 启动细节：`DIAG_START`、`DIAG_CONTROLLER_READY`、`DIAG_FLASK_READY`、`DIAG_GUI_LOOP` 等
- notify/rest 调试链路：`DIAG_NOTIFY_SHOW`、`DIAG_NOTIFY_SHOWN`、`DIAG_REST_API_*`、`DIAG_REST_SHOW_ENTER`
- 阶段事件：`DIAG_NOTIFY_STAGE`、`DIAG_REST_STAGE`、`DIAG_STYLE_STAGE`、`DIAG_DISPATCH_STAGE`、`DIAG_API_STAGE`
- 指标事件：`DIAG_METRIC_*`

## 4) 非诊断常规日志

除诊断事件外，常规 `logging`（`INFO/WARNING/ERROR`）也会写入 `debug.log`。  
这些日志不经过诊断策略引擎。

## 5) 实务判断

若你在普通模式看不到某个 `DIAG_*`：

1. 先查该事件在 `event_codes.yml` 的 `policy`。
2. 若为 `DEBUG_ONLY`，需开启 `EYECARE_DEBUG=1` 并启用对应模块。
3. 若为历史别名，先看是否映射到 `*_STAGE`（普通模式会被过滤）。

参考：

- `docs/diagnostics/event_codes.yml`
- `eye_care/diagnostics/policy_engine.py`
