# ARCHITECTURE（交付终版）

更新时间：2026-02-22

## 1) 启动链路（代码事实）

1. `main.py` 解析参数并调用 `run_pywebview_shell()`（默认 UI 模式）。
2. `start_backend_services()` 在 `services_init` 线程内完成：
   - 创建并启动 `AppController`（含 `tick_loop`）。
   - 创建 Flask App，挂载 UI 站点路由（`/`、`/rest/`、`/notify/`）和 `/api/*`。
3. 主线程调用 `wait_flask_ready()` 探活，随后 `webview.create_window()` 创建主窗口。
4. 组装 UI 基础设施：`GuiDispatcher`、`WindowApi`、`RestWindowController`、`NotifyWindowController`。
5. 创建并启动 `NotificationManager` + `NotifierService`（后台轮询 `snapshot_today(mark_prompted=False)`）。
6. 异步启动托盘初始化线程 `tray_init`。
7. 进入 `webview.start(..., func=_on_webview_start)`：GUI loop 持续 `dispatcher.run_pending()` 消费任务。

## 2) 模块职责边界

### Notify 链路

- 判定来源：`AppController._get_runtime_extra()` 生成 `rest.should_prompt`。
- 调度去重：`NotificationManager.on_snapshot()` 负责冷却、去重、入队。
- 展示执行：`NotifyWindowController.show(...)` 仅负责窗口展示与样式。
- 业务确认：`mark_rest_notified()` 仅在用户操作（rest/snooze/dismiss）后通过回调触发。

### Rest 链路

- API 入口：`/api/rest/start|complete|snooze`。
- 展示入口：`WindowApi.rest_show_overlay()` -> `dispatcher.post_rest_show()` -> `RestWindowController.show_overlay()`。
- 状态写入：`AppController` 统一管理 rest 状态（开始、完成、snooze、守卫冷却）。

## 3) 线程模型（交付口径）

- GUI 线程：唯一可执行窗口操作（show/hide/destroy/evaluate_js/Win32 样式）。
- `services_init`：后台初始化 Controller + Flask。
- `tick_loop`：采样前台应用、累计 usage、维护 rest 状态机、定时 flush/checkpoint。
- `notifier_service`：按周期拉取快照并触发通知入队判断。
- `tray_init` / tray 内部线程：托盘菜单生命周期。
- `checkpoint`：后台 merge 线程。
- `notify_fade_*` / `rest_fade_*`：短生命周期渐入渐出线程，仅做动画计算+投递。

结论：后台线程可执行业务逻辑，但不得直接操作窗口对象。

## 4) 生命周期

### 运行期

- GUI loop 每帧消费 dispatcher 队列。
- `tick_loop` 每秒采样并持续写入仓储缓存与 WAL。
- `NotifierService` 独立轮询，不直接调用窗口 API。

### 退出期（`_request_exit`）

1. `stop_event.set()`。
2. `dispatcher.stop()` 关闭新任务入队。
3. 顺序执行：`notifier_service.stop()` -> `controller.stop()` -> `tray.stop()`。
4. 销毁 rest/notify 窗口并释放单实例锁。
5. `webview.start()` 自然返回，进程正常退出（无 `os._exit` 强退）。

## 5) UI/API 拓扑

- UI 页面：`/`（主页面）、`/rest/`（休息页）、`/notify/`（通知页）。
- API：`/api/*`，由同一 Flask 进程提供。
- 前端业务交互：统一走 HTTP `/api/*`。
- `pywebview.api`：仅承担窗口能力与导入导出等本地能力桥接。
