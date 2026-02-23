# DIAG 事件映射摘要（交付版）

更新时间：2026-02-24（适用应用版本 V1.0.2）

## 1) 事实来源

- 运行时字典：`docs/diagnostics/event_codes.yml`
- 策略引擎：`eye_care/diagnostics/policy_engine.py`

本文为摘要说明；最终判定以代码与字典为准。

## 2) canonical 事件策略（当前）

### ALWAYS_ON（普通模式可见）

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

### DEBUG_ONLY（仅 debug + 模块开启）

- 启动细节：`DIAG_START`、`DIAG_CONTROLLER_INIT`、`DIAG_CONTROLLER_READY`、`DIAG_FLASK_READY`、`DIAG_WINDOW_CREATED`、`DIAG_GUI_LOOP`、`DIAG_PYWEBVIEW_*`
- notify/rest/style/dispatch/api 细粒度阶段事件（`*_STAGE`、`DIAG_NOTIFY_SHOW`、`DIAG_REST_API_*`、`DIAG_REPO_CLOSE_OK` 等）
- 指标：`DIAG_METRIC_*`

## 3) 关键别名映射（节选）

- `DIAG_WINDOW_CREATE -> DIAG_WINDOW_CREATED`
- `DIAG_FLASK_WAIT -> DIAG_CONTROLLER_INIT`
- `DIAG_FLASK_LISTEN -> DIAG_CONTROLLER_INIT`
- `DIAG_SYS_TRANSPARENCY -> DIAG_START`
- `DIAG_NOTIFY_*PIPE*/M0/READY/... -> DIAG_NOTIFY_STAGE`
- `DIAG_REST_OVERLAY_LOG / DIAG_REST_SHOW_COOLDOWN / DIAG_APPLY_BOUNDS ... -> DIAG_REST_STAGE`
- `DIAG_HTTP / DIAG_UI_LOG / DIAG_SNAPSHOT_HIT -> DIAG_API_STAGE`
- `DIAG_DISPATCH_POST / WINDOW_OP / DRAIN / UNKNOWN / TRAY_* -> DIAG_DISPATCH_STAGE`

说明：代码中的历史事件码会先映射到 canonical，再由策略决定是否落盘。

## 4) 模块开关口径

debug 模块集合：`notify, rest, repo, dispatch, api, style, runtime, tray`

默认 debug 模块：`notify, repo`

仅当 `EYECARE_DEBUG=1`（或配置开启 debug）时，模块开关才生效。

## 5) 异常与未知事件

- 未登记事件不会静默丢失：策略层会按窗口节流输出 `DIAG_UNKNOWN_EVENT`。
- `DIAG_EXCEPTION` 采用 `reason_code` 节流：同一原因窗口内仅首条带完整堆栈。
