# FROZEN SPEC（交付冻结口径）

更新时间：2026-02-22  
适用分支：FN14（pywebview 主程序）

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

### Debug 模式（`EYECARE_DEBUG=1` 且模块开启）

- 启动链路可见：`DIAG_START -> DIAG_CONTROLLER_READY -> DIAG_FLASK_READY(或 TIMEOUT) -> DIAG_WINDOW_CREATED -> DIAG_GUI_LOOP`。
- `POST /api/debug/notify` 后可见 `DIAG_NOTIFY_SHOW` / `DIAG_NOTIFY_SHOWN`。
- `POST /api/rest/start` 后可见 `DIAG_REST_API_START` / `DIAG_REST_SHOW_ENTER`。
- 调度链路可见 `DIAG_DISPATCH_STAGE`（或别名映射来源事件）。

## 5) 诊断策略约束

- 事件放行策略、别名与模块归属以 `docs/diagnostics/event_codes.yml` 为准。
- 运行时判定逻辑以 `eye_care/diagnostics/policy_engine.py` 为准。
- 文档中对日志行为的描述若与以上两处冲突，以代码与事件字典为准。
