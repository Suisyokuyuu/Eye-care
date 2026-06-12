# 架构说明

## 启动链路

`main.py` 是唯一入口，负责解析参数、确定数据目录、启动 API/headless 或桌面模式。

- `--no-ui --api-port PORT`：只启动 `AppController` 和 Flask API。
- `--no-ui`：启动控制器并保持后台采样，不开放指定端口 API。
- 默认桌面模式：进入 `eye_care.qt.run_qt_shell`（Qt host，唯一桌面壳）。

Qt host 启动后会：

1. 初始化日志到 `data_dir/debug.log`。
2. 创建 `AppController`。
3. 启动控制器采样线程。
4. 在后台启动 Flask API 和本地 Web 静态站点。
5. 创建主窗口、通知窗口桥接、休息遮罩桥接和托盘菜单。
6. 启动 `NotifierService` 轮询控制器快照。

> **注**：Legacy pywebview host 已于 v1.1 移除。`--host` 参数仅接受 `qt`，保留参数仅为向后兼容。

## 核心模块

`AppController` 是当前核心状态机和采样中心：

- 读取和保存 `AppConfig`。
- 调用 Windows probe 获取前台应用和空闲时间。
- 统计应用使用秒数。
- 维护连续工作时间、休息 due/notified/snooze/resting 状态。
- 处理正常、勿扰、离开、自动 idle、指定应用自动勿扰等运行模式。
- 向 `JsonWalRepository` 写入 usage 和事件。

`JsonWalRepository` 负责本地数据：

- 当前分钟先写入内存和 WAL。
- 周期性 flush。
- 退出或 checkpoint 时 merge 到主 JSONL 文件。
- 支持每日缓存、范围查询、app/category 汇总、事件查询和 app 数据删除。

`services/` 是迁移中的服务层：

- `SnapshotService`
- `ConfigService`
- `RestService`
- `StatsService`
- `DesktopService`
- `DiagService`

路由层正在逐步改为调用这些服务，但控制器仍承担大量业务逻辑。

## UI 与桌面壳

主 UI 位于 `eye_care/ui/web/index.html`，静态资源在 `eye_care/ui/web/assets/`。

Qt host 使用 `QWebEngineView` 加载主页面，并通过 `QWebChannel` 暴露桥接对象。休息遮罩和通知窗口各自创建独立的透明置顶窗口。前端通过 `window.pywebview.api` 兼容层与 Qt 桥接通信。

## 本地 API

Flask 只监听 `127.0.0.1`。写操作要求 `X-EYECare-Token`，token 由 `/api/auth/token` 提供。主要路由分组：

- `auth.py`：token。
- `health.py`：健康检查。
- `snapshot.py`：首页快照。
- `config.py`：配置、图标、分类、更新检查。
- `stats.py`：应用详情、列表、黑名单、日历。
- `rest.py`：休息、推迟、勿扰。
- `diag.py`：前端诊断日志。
- `debug.py`：仅 debug 模式注册。

## 诊断

诊断事件通过 `eye_care.diagnostics.diag_events.emit` 进入策略引擎。策略引擎会读取 `docs/diagnostics/event_codes.yml`，决定事件是否在普通模式输出、是否节流、属于哪个模块。

通知挂起测试会读取 `debug.log`，使用 `eye_care.diagnostics.notify_hang_analyzer` 检查通知状态机是否出现未闭合的 `HIDING` 状态或关键失败事件。
