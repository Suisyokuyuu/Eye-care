# Step 2 路由到 Service 映射

更新时间：2026-04-14

本文档承接 Step 1 的接口契约盘点，目标是把当前 Flask route 的职责映射到后续 service 层。
本阶段先做“职责收口”和“骨架命名”，不要求一次性把所有 route 改写完。

原则：

- route 只保留参数解析、鉴权依赖、HTTP 状态码与响应封装
- service 承接业务逻辑、repo 访问、controller 调用、文件系统副作用
- 一个 route 只对应一个主 service 方法
- 允许一个 service 方法内部调用其他 service 的辅助方法，但不要让 route 再跨层拼装业务

## 1. Service 划分

### `SnapshotService`

负责主页面快照、统计聚合、时间范围组装。

对应 route：

- `GET /api/snapshot`

### `ConfigService`

负责配置读写、分类管理、图标读取、更新检查、外链动作。

对应 route：

- `GET /api/config`
- `POST /api/config`
- `GET /api/icon`
- `GET /api/categories`
- `POST /api/categories`
- `GET /api/category_names`
- `POST /api/categories/delete`
- `GET /api/update/check`
- `POST /api/open_url`

### `RestService`

负责休息相关业务状态变更与守卫。

对应 route：

- `POST /api/rest/start`
- `POST /api/rest/complete`
- `POST /api/rest/snooze`
- `POST /api/dnd`
- `POST /api/shutdown`（debug only）

### `StatsService`

负责应用详情、应用列表、黑名单与日历数据。

对应 route：

- `GET /api/app_details`
- `GET /api/apps_list`
- `POST /api/app_settings`
- `POST /api/app_exclude`
- `GET /api/blacklist`
- `POST /api/blacklist_remove`
- `GET /api/calendar_month`

### `DesktopService`

负责与桌面宿主耦合的本地能力。

当前先承接以下现有能力的未来归属，不要求本阶段改 route：

- `window.pywebview.api.close_window`
- `window.pywebview.api.minimize_window`
- `window.pywebview.api.maximize_toggle`
- `window.pywebview.api.rest_show_overlay`
- `window.pywebview.api.close_rest_overlay`
- `window.pywebview.api.rest_ready_for_show`
- `window.pywebview.api.export_all`
- `window.pywebview.api.import_all`
- `window.pywebview.api.export_settings`
- `window.pywebview.api.import_settings`
- `window.pywebview.api.notify_ready_for_show`
- `window.pywebview.api.notify_window_action`
- `window.pywebview.api.notify_log`

### `DiagService`

负责 UI breadcrumb、调试开关、线程 dump、dispatcher 指标等。

对应 route：

- `POST /api/diag/log`
- `POST /api/debug/notify_log`
- `POST /api/debug/notify`
- `POST /api/debug/open_app_detail`
- `GET /api/debug/dispatcher_metric`
- `POST /api/debug/dump_threads`
- `GET /api/health`
- `GET /api/auth/token`

说明：

- `health` / `auth_token` 更偏 runtime 支撑，不是业务逻辑
- 这里先并入 `DiagService`，后续如果需要可拆成 `RuntimeService`

## 2. route 层保留职责

无论何时切 service，以下职责仍保留在 route 层：

- 读取 `request.args`
- 读取 `request.get_json()`
- 读取 request headers / remote_addr / user-agent
- 转换为 service 输入参数
- 决定 HTTP 状态码
- 返回 `jsonify(...)` 或 `send_file(...)`

不要下沉到 service 的职责：

- 直接依赖 Flask `request`
- 直接返回 Flask `Response`
- 在 service 内部偷偷读全局 request 上下文

## 3. 推荐迁移顺序

### 第一批：最容易下沉

- `SnapshotService`
- `RestService`
- `DiagService.diag_log`
- `StatsService.apps_list`
- `StatsService.blacklist_get`

特点：

- HTTP 形态简单
- 输入参数较少
- UI 覆盖面高，容易验证

### 第二批：副作用较多

- `ConfigService.post_config`
- `StatsService.app_settings`
- `StatsService.app_exclude`
- `StatsService.blacklist_remove`
- `ConfigService.categories_delete`

特点：

- 会写配置或 repo
- 更需要回归验证

### 第三批：宿主/平台耦合高

- `ConfigService.icon`
- `ConfigService.update_check`
- `ConfigService.open_url`
- `DesktopService.*`

特点：

- 依赖文件系统、Windows、浏览器、对话框、宿主线程
- 应该在前两批稳定后再推进

## 4. 当前骨架约定

本阶段新增的 service 骨架应满足：

- 构造函数统一接收 `ServiceContext`
- 每个 service 文件只放一个主 service 类
- 方法命名尽量与 route 语义一致，不直接绑 HTTP 动词
- 可以先只建方法签名和文档，不强行接入现有 route

## 5. 下一步接线建议

完成骨架后，建议按以下方式逐个改 route：

1. route 先创建 service 输入 DTO 或普通 dict
2. 调用 service 方法
3. 保持原返回结构不变
4. 每次只迁一个 route 文件
5. 每迁完一个 route 文件就回归 Step 0 基线
