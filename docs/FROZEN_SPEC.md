# FROZEN SPEC（交付冻结口径）

更新时间：2026-02-24  
适用分支：应用版本 V1.0.3

## 1) 不可动摇红线

- 线程红线：任何窗口操作（`show/hide/destroy/evaluate_js/Win32 样式`）只能在 GUI 线程执行。
- 调度红线：后台线程只能投递到 `GuiDispatcher`，禁止直连窗口对象。
- notify 链路红线：`NotifierService -> NotificationManager -> dispatcher.post_notify_show -> NotifyWindowController.show`。
- rest 链路红线：`WindowApi.rest_show_overlay -> dispatcher.post_rest_show -> RestWindowController.show_overlay`。
- 业务边界红线：页面只负责展示与动作回传；业务状态仅由 `AppController` 修改。
- 数据红线：主持久化仅 `minute_usage + events`；`timeline_segments` 仅由分钟桶计算。

## 2) 冻结核心文件

以下文件属于核心链路冻结区域，未经评审不得改动：

- `main.py`
- `eye_care/bootstrap/runtime_shell.py`
- `eye_care/ui/app_runtime.py`
- `eye_care/ui/gui_dispatcher.py`
- `eye_care/ui/window_api.py`
- `eye_care/ui/style_coordinator.py`
- `eye_care/notify/notifier_service.py`
- `eye_care/notify/notification_manager.py`
- `eye_care/notify/notify_window_controller.py`
- `eye_care/rest/rest_window_controller.py`
- `eye_care/controller/app_controller.py`
- `eye_care/api/server.py`
- `eye_care/api/routes/*.py`
- `eye_care/data/repository.py`
- `eye_care/data/json_wal_repo.py`
- `docs/diagnostics/event_codes.yml`（运行时依赖）

## 3) 冻结期允许改动

- `docs/` 文档完善与交付修订。
- 非核心可视化文案与样式微调（不改变线程模型、调度链路、数据口径、API 语义）。
- 诊断观测增强（不得改变业务行为）。

## 4) 验收点（按运行模式区分）

### 普通模式（未开启 debug）

- 应用可完整启动和退出，无未捕获异常。
- `debug.log` 可见 ALWAYS_ON 关键锚点，如：
  - `DIAG_APP_START_OK`
  - `DIAG_APP_EXIT_OK`
  - 异常时 `DIAG_EXCEPTION` / `DIAG_UNCAUGHT*`

> **测试/验收运行建议**：  
> - 建议为每轮测试指定独立的数据目录，例如：`python main.py --data-dir ./user_data_test_X`，避免与日常使用的数据混用。  
> - 如需并行运行多个实例/用例，请显式添加 `--no-single` 关闭单实例锁，并为每个实例配置不同的 `--data-dir` 与 `EYECARE_API_PORT` / `--api-port`，避免端口与 user_data 目录冲突。

### Debug 模式（`EYECARE_DEBUG=1` 且模块开启）

**前置条件**：
- 程序以 Debug 模式启动：例如 `python main.py --debug` 或设置环境变量 `EYECARE_DEBUG=1`（需与配置中的 debug 开关一致）。
- 通过 `GET /api/auth/token` 获取当前会话 token，并在**所有写请求**（`POST/PUT/PATCH/DELETE`）的 Header 中附加：
  - `X-EYECare-Token: <token>`

**期望行为**：
- 启动链路可见：`DIAG_START -> DIAG_CONTROLLER_READY -> DIAG_FLASK_READY(或 TIMEOUT) -> DIAG_WINDOW_CREATED -> DIAG_GUI_LOOP`。
- 携带 token 调用 `POST /api/debug/notify` 后，可见 `DIAG_NOTIFY_SHOW` / `DIAG_NOTIFY_SHOWN`。
- 携带 token 调用 `POST /api/rest/start` 后，可见 `DIAG_REST_API_START` / `DIAG_REST_SHOW_ENTER`。
- 调度链路可见 `DIAG_DISPATCH_STAGE`（或别名映射来源事件）。

## 5) 诊断策略约束

- 事件放行策略、别名与模块归属以 `docs/diagnostics/event_codes.yml` 为准。
- 运行时判定逻辑以 `eye_care/diagnostics/policy_engine.py` 为准。
- 文档中对日志行为的描述若与以上两处冲突，以代码与事件字典为准。
