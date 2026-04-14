# Step 1 接口契约清单

更新时间：2026-04-14

本文档是 `MIGRATION_PYSIDE6_QWEBENGINE_QWEBCHANNEL.md` 的 Step 1 落地产物。
目标不是设计新接口，而是把当前实际依赖的接口、页面注入依赖、`pywebview.api` 能力一次性盘清。

适用范围：

- 现有 `pywebview + Flask + 本地 HTML/CSS/JS` 路径
- 主页面 `eye_care/ui/web/index.html`
- Rest 页面 `eye_care/ui/web/rest/*`
- Notify 页面 `eye_care/ui/web/notify/index.html`

约定：

- “正式接口”表示迁移后应提供等价能力
- “兼容接口”表示当前代码仍在用，但后续允许被统一收口
- “调试接口”表示仅用于诊断/测试，不属于最终业务契约核心

## 1. 页面与资源交付依赖

当前页面不是简单的纯静态文件，存在以下运行时交付依赖：

- `/`：主页面入口，读取 `index.html` 后由 Flask 注入 bridge 脚本，并替换 `{{APP_VERSION}}`
  来源：[eye_care/ui/web_routes.py](D:/Coding/Eye-care/eye_care/ui/web_routes.py:28), [eye_care/bootstrap/bridge_inject.py](D:/Coding/Eye-care/eye_care/bootstrap/bridge_inject.py:7)
- `/assets/<path>`：主页面、Rest、Notify 共用静态资源根
  来源：[eye_care/ui/web_routes.py](D:/Coding/Eye-care/eye_care/ui/web_routes.py:46)
- `/rest/` 与 `/rest/<path>`：Rest 页面及其资源
  来源：[eye_care/ui/web_routes.py](D:/Coding/Eye-care/eye_care/ui/web_routes.py:62)
- `/notify/` 与 `/notify/<path>`：Notify 页面及其资源
  来源：[eye_care/ui/web_routes.py](D:/Coding/Eye-care/eye_care/ui/web_routes.py:64)

额外页面启动依赖：

- `index.html` 与 `notify/index.html` 首屏都会加载 `/assets/auth_bootstrap.js`
  来源：[eye_care/ui/web/index.html](D:/Coding/Eye-care/eye_care/ui/web/index.html:6), [eye_care/ui/web/notify/index.html](D:/Coding/Eye-care/eye_care/ui/web/notify/index.html:101)
- `auth_bootstrap.js` 会先请求 `/api/auth/token`，然后为所有写请求自动附加 `X-EYECare-Token`
  来源：[eye_care/ui/web/assets/auth_bootstrap.js](D:/Coding/Eye-care/eye_care/ui/web/assets/auth_bootstrap.js:12)
- 主页面标题栏版本号依赖 `{{APP_VERSION}}` 注入
  来源：[eye_care/ui/web/index.html](D:/Coding/Eye-care/eye_care/ui/web/index.html:39), [eye_care/bootstrap/bridge_inject.py](D:/Coding/Eye-care/eye_care/bootstrap/bridge_inject.py:74)

结论：

- Step 3 不能把“加载现有页面”理解成“直接打开本地 HTML”
- Qt 路径必须显式复刻以上页面交付能力，或提供等价替代

## 2. HTTP 接口契约

### 2.1 页面启动与基础探活

#### `GET /api/health`

- 用途：应用就绪探活
- 返回：`{ "ok": true, "api_version": "..." }`
- 消费方：测试基建、外部探活
- 分类：正式接口
- 来源：[eye_care/api/routes/health.py](D:/Coding/Eye-care/eye_care/api/routes/health.py:8)

#### `GET /api/auth/token`

- 用途：下发当前会话 token，供前端给写请求加 `X-EYECare-Token`
- 返回成功：`{ "token": "..." }`
- 返回失败：`{ "error": "token_not_available", "token": null }` + `500`
- 消费方：`auth_bootstrap.js`
- 分类：正式接口
- 来源：[eye_care/api/routes/auth.py](D:/Coding/Eye-care/eye_care/api/routes/auth.py:9), [eye_care/ui/web/assets/auth_bootstrap.js](D:/Coding/Eye-care/eye_care/ui/web/assets/auth_bootstrap.js:16)

### 2.2 主页面核心业务读取

#### `GET /api/snapshot`

- 用途：主页面快照、轮询刷新、勿扰状态、休息状态、统计总览
- 关键 query：
  - `date=YYYY-MM-DD`
  - `range=day|week|month|custom`
  - `range_start`
  - `range_end`
- 主要返回字段：
  - `api_version`
  - `vm.local_date`
  - `vm.daily_usage`
  - `usage_by_category`
  - `range_daily_usage`
  - `range_usage_by_category`
  - `app_paths`
  - `idle_s`
  - `fg`
  - `state`
  - `rest`
  - `hourly_usage`
  - `stats_*`
  - `range_key`
  - `range_start`
  - `range_end`
  - `timebar_labels`
  - `timebar_keys`
  - `timebar_values`
  - `today_total_seconds`
  - `display_names`
  - `ui_should_prompt`
- 错误：`{ "error": "...", "code": "data_error" }` + `500`
- 消费方：主页面
- 分类：正式接口
- 来源：[eye_care/api/routes/snapshot.py](D:/Coding/Eye-care/eye_care/api/routes/snapshot.py:13), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:2864)

#### `GET /api/config`

- 用途：读取设置页配置
- 返回：`{ "api_version": "...", "config": { ... } }`
- 当前返回字段：
  - `reminder_work_minutes`
  - `reminder_rest_seconds`
  - `reminder_rest_unit`
  - `idle_threshold_s`
  - `theme_name`
  - `startup_dnd`
  - `startup_show_main`
  - `startup_launch_at_login`
  - `notify_enabled`
  - `notify_sound_enabled`
  - `notify_auto_hide_seconds`
  - `rest_end_sound_enabled`
- 错误：`{ "error": "...", "code": "config_error" }` + `500`
- 消费方：主页面设置区
- 分类：正式接口
- 来源：[eye_care/api/routes/config.py](D:/Coding/Eye-care/eye_care/api/routes/config.py:23)

#### `GET /api/apps_list`

- 用途：应用列表页、应用图标/卡片展示
- 返回：`{ "api_version": "...", "apps": [{ "app_short", "display_name", "category" }] }`
- 消费方：主页面应用列表
- 分类：正式接口
- 来源：[eye_care/api/routes/stats.py](D:/Coding/Eye-care/eye_care/api/routes/stats.py:141), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:2014)

#### `GET /api/app_details`

- 用途：应用详情页图表与设置预填
- 关键 query：
  - `app`
  - `date`
  - `days`，默认 `7`，上限 `90`
- 返回：`{ "api_version", "app", "range_start", "range_end", "total_seconds", "daily_seconds", "hourly_seconds_for_date", "timeline_segments", "last_active_utc", "special_settings", "display_name", "display_name_override", "category", "auto_dnd_on_focus" }`
- 常见错误：
  - 缺 `app`：`400`
  - 日期非法：`400`
  - 其他：`{ "error": "...", "code": "data_error" }` + `500`
- 消费方：应用详情页
- 分类：正式接口
- 来源：[eye_care/api/routes/stats.py](D:/Coding/Eye-care/eye_care/api/routes/stats.py:56), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1895)

#### `GET /api/blacklist`

- 用途：读取黑名单列表
- 返回：`{ "api_version": "...", "apps": [{ "app_short", "display_name" }] }`
- 消费方：黑名单页
- 分类：正式接口
- 来源：[eye_care/api/routes/stats.py](D:/Coding/Eye-care/eye_care/api/routes/stats.py:256), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:2701)

#### `GET /api/calendar_month`

- 用途：日历页按月查询有数据的日期
- query：
  - `year`
  - `month`，1..12
- 返回：`{ "api_version", "year", "month", "days_with_data" }`
- 消费方：日历/时间范围切换
- 分类：正式接口
- 来源：[eye_care/api/routes/stats.py](D:/Coding/Eye-care/eye_care/api/routes/stats.py:291), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1146)

#### `GET /api/category_names`

- 用途：分类下拉列表
- 返回：`{ "api_version": "...", "categories": [...] }`
- 消费方：应用详情设置区
- 分类：正式接口
- 来源：[eye_care/api/routes/config.py](D:/Coding/Eye-care/eye_care/api/routes/config.py:289), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1751)

#### `GET /api/categories`

- 用途：读取完整应用分类映射
- 返回：`{ "api_version": "...", "categories": { app_short: category } }`
- 消费方：当前前端未直接检出，但属于现有能力面
- 分类：正式接口
- 来源：[eye_care/api/routes/config.py](D:/Coding/Eye-care/eye_care/api/routes/config.py:261)

#### `GET /api/icon`

- 用途：按 app_short 取图标 PNG
- query：
  - `app`
- 成功：返回 `image/png`
- 常见错误：
  - 缺 `app`：`{ "error": "missing app", "code": "bad_request" }` + `400`
  - app 路径缺失：`{ "error": "app path unknown", "code": "icon_file_missing" }` + `404`
  - 提取失败：`{ "error": "...", "code": "icon_error" }`
- 消费方：主页面多个列表/详情页图标展示
- 分类：正式接口
- 来源：[eye_care/api/routes/config.py](D:/Coding/Eye-care/eye_care/api/routes/config.py:90), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:705)

#### `GET /api/update/check`

- 用途：检查新版本
- 返回成功：`{ "ok", "current", "latest", "has_update", "html_url", "asset_url", "error" }`
- 消费方：设置页更新检查
- 分类：正式接口
- 来源：[eye_care/api/routes/config.py](D:/Coding/Eye-care/eye_care/api/routes/config.py:347), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:2576)

### 2.3 主页面核心业务写入

注意：当前所有 `/api/*` 写请求默认依赖 `auth_bootstrap.js` 自动补的 `X-EYECare-Token`。

#### `POST /api/config`

- 用途：保存设置
- body：`AppConfig` 的白名单字段子集
- 成功：`{ "ok": true, "api_version": "..." }`
- 错误：`{ "error": "...", "code": "config_error" }` + `500`
- 消费方：设置页
- 分类：正式接口
- 来源：[eye_care/api/routes/config.py](D:/Coding/Eye-care/eye_care/api/routes/config.py:47), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1489)

#### `POST /api/dnd`

- 用途：切换勿扰模式
- body：`{ "on": boolean }`
- 返回：`{ "ok": true, "dnd": boolean, "api_version": "..." }`
- 错误：`{ "error": "...", "code": "invalid_params" }` + `500`
- 消费方：主页面勿扰按钮
- 分类：正式接口
- 来源：[eye_care/api/routes/rest.py](D:/Coding/Eye-care/eye_care/api/routes/rest.py:89), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1377)

#### `POST /api/rest/start`

- 用途：开始休息
- 成功：`{ "ok": true, "api_version": "..." }`
- 守卫拦截：`{ "ok": false, "code": "rest_locked", "unlock_in_ms": number, "api_version": "..." }` + `409`
- 异常：`{ "error": "...", "code": "busy" }` + `500`
- 消费方：主页面立即休息、Notify 页面 `rest` 动作
- 分类：正式接口
- 来源：[eye_care/api/routes/rest.py](D:/Coding/Eye-care/eye_care/api/routes/rest.py:21), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1415), [eye_care/ui/web/notify/index.html](D:/Coding/Eye-care/eye_care/ui/web/notify/index.html:177)

#### `POST /api/rest/complete`

- 用途：休息完成
- 成功：`{ "ok": true, "api_version": "..." }`
- 异常：`{ "error": "...", "code": "busy" }` + `500`
- 消费方：Rest 页面
- 分类：正式接口
- 来源：[eye_care/api/routes/rest.py](D:/Coding/Eye-care/eye_care/api/routes/rest.py:57), [eye_care/ui/web/rest/rest.js](D:/Coding/Eye-care/eye_care/ui/web/rest/rest.js:160)

#### `POST /api/rest/snooze`

- 用途：稍后休息
- 成功：`{ "ok": true, "api_version": "..." }`
- 异常：`{ "error": "...", "code": "busy" }` + `500`
- 消费方：Rest 页面、Notify 页面
- 分类：正式接口
- 来源：[eye_care/api/routes/rest.py](D:/Coding/Eye-care/eye_care/api/routes/rest.py:73), [eye_care/ui/web/rest/rest.js](D:/Coding/Eye-care/eye_care/ui/web/rest/rest.js:170), [eye_care/ui/web/notify/index.html](D:/Coding/Eye-care/eye_care/ui/web/notify/index.html:179)

#### `POST /api/app_settings`

- 用途：保存单应用设置
- body：
  - `app_short`
  - 可选 `category`
  - 可选 `display_name`
  - 可选 `auto_dnd_on_focus`
- 成功：`{ "ok": true, "api_version": "..." }`
- 错误：参数缺失 `400`；其他 `500`
- 消费方：应用详情页
- 分类：正式接口
- 来源：[eye_care/api/routes/stats.py](D:/Coding/Eye-care/eye_care/api/routes/stats.py:188), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1840)

#### `POST /api/app_exclude`

- 用途：将应用加入黑名单并删除历史数据
- body：`{ "app_short": string }`
- 成功：`{ "ok": true, "api_version": "..." }`
- 消费方：应用详情页/应用列表
- 分类：正式接口
- 来源：[eye_care/api/routes/stats.py](D:/Coding/Eye-care/eye_care/api/routes/stats.py:234), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1860)

#### `POST /api/blacklist_remove`

- 用途：从黑名单移除应用
- body：`{ "app_short": string }`
- 成功：`{ "ok": true, "api_version": "..." }`
- 消费方：黑名单页
- 分类：正式接口
- 来源：[eye_care/api/routes/stats.py](D:/Coding/Eye-care/eye_care/api/routes/stats.py:270), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:2720)

#### `POST /api/categories`

- 用途：整体保存分类映射
- body：`{ "categories": { ... } }`
- 成功：`{ "ok": true, "api_version": "..." }`
- 消费方：当前前端未直接检出
- 分类：正式接口
- 来源：[eye_care/api/routes/config.py](D:/Coding/Eye-care/eye_care/api/routes/config.py:273)

#### `POST /api/categories/delete`

- 用途：删除分类并将相关应用回退到“其他”
- body：`{ "name": string }`
- 成功：`{ "ok": true, "api_version": "..." }`
- 消费方：分类管理
- 分类：正式接口
- 来源：[eye_care/api/routes/config.py](D:/Coding/Eye-care/eye_care/api/routes/config.py:310), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1732)

#### `POST /api/open_url`

- 用途：打开预定义外链
- body：`{ "action": "release_notes" | "help" }`
- 成功：`{ "ok": true }`
- 参数错误：`400`
- 消费方：设置页
- 分类：正式接口
- 来源：[eye_care/api/routes/config.py](D:/Coding/Eye-care/eye_care/api/routes/config.py:433), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:2597)

#### `POST /api/diag/log`

- 用途：前端 breadcrumb / 硬日志上报
- body 常见字段：
  - `src`
  - `stage`
  - `msg`
  - `ts`
  - `href`
  - `extra`
- 返回：总是尽量返回 `200`，失败也退化为 `{ "ok": false, "error": "..." }`
- 消费方：主页面
- 分类：正式接口
- 来源：[eye_care/api/routes/diag.py](D:/Coding/Eye-care/eye_care/api/routes/diag.py:9), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:3146)

### 2.4 调试接口

以下接口属于调试/测试能力，迁移时应继续保留 debug/fallback 路径，但不应作为正式 bridge 的首批核心能力：

- `POST /api/debug/notify_log`
- `POST /api/debug/notify`
- `POST /api/debug/open_app_detail`
- `GET /api/debug/dispatcher_metric`
- `POST /api/debug/dump_threads`
- `POST /api/shutdown`，仅 `allow_shutdown=True` 时注册

来源：

- [eye_care/api/routes/debug.py](D:/Coding/Eye-care/eye_care/api/routes/debug.py:28)
- [eye_care/api/routes/rest.py](D:/Coding/Eye-care/eye_care/api/routes/rest.py:9)

## 3. `window.pywebview.api` 契约

### 3.1 主窗口与 Rest 相关

#### `close_window()`

- 用途：关闭主窗口；若托盘已启用则退化为 hide
- 返回：无显式返回
- 消费方：主页面标题栏按钮、`window.electronAPI.close`
- 分类：正式接口
- 来源：[eye_care/ui/window_api.py](D:/Coding/Eye-care/eye_care/ui/window_api.py:157), [eye_care/bootstrap/bridge_inject.py](D:/Coding/Eye-care/eye_care/bootstrap/bridge_inject.py:21)

#### `minimize_window()`

- 用途：最小化主窗口
- 返回：无显式返回
- 消费方：主页面标题栏按钮、`window.electronAPI.minimize`
- 分类：正式接口
- 来源：[eye_care/ui/window_api.py](D:/Coding/Eye-care/eye_care/ui/window_api.py:177), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:2786)

#### `maximize_toggle()`

- 用途：最大化/还原主窗口
- 返回：无显式返回
- 消费方：主页面标题栏按钮、`window.electronAPI.maximizeToggle`
- 分类：正式接口
- 来源：[eye_care/ui/window_api.py](D:/Coding/Eye-care/eye_care/ui/window_api.py:186), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:2787)

#### `rest_show_overlay()`

- 用途：请求显示 Rest 遮罩
- 返回：由注入的 `_rest_show_overlay_fn` 决定；未注入时返回 `None`
- 消费方：主页面“立即休息”、`window.electronAPI.restShowOverlay`
- 分类：正式接口
- 来源：[eye_care/ui/window_api.py](D:/Coding/Eye-care/eye_care/ui/window_api.py:134), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1402)

#### `close_rest_overlay()`

- 用途：隐藏 Rest 遮罩
- 返回：`{ "ok": true }`
- 消费方：Rest 页面
- 分类：正式接口
- 来源：[eye_care/ui/window_api.py](D:/Coding/Eye-care/eye_care/ui/window_api.py:209)

#### `rest_ready_for_show(screen_idx)`

- 用途：Rest 页面首帧 ready ACK；后端据此决定何时 show，避免首帧黑屏
- 返回：无显式返回
- 消费方：Rest 页面
- 分类：正式接口
- 来源：[eye_care/ui/window_api.py](D:/Coding/Eye-care/eye_care/ui/window_api.py:115), [eye_care/ui/web/rest/rest.js](D:/Coding/Eye-care/eye_care/ui/web/rest/rest.js:239)

#### `rest_overlay_log(payload)`

- 用途：Rest 页面前端埋点
- 返回：`{ "ok": true|false }`
- 消费方：当前前端未直接检出，但属于现有宿主能力
- 分类：兼容接口
- 来源：[eye_care/ui/window_api.py](D:/Coding/Eye-care/eye_care/ui/window_api.py:221)

### 3.2 导入导出

以下 4 个接口返回结构一致：

- 成功：`{ "status": "ok", ... }`
- 用户取消：`{ "status": "cancel" }`
- 失败：`{ "status": "error", "error": "..." }`

#### `export_all()`

- 用途：导出完整数据
- 成功附加字段：`path`
- 分类：正式接口
- 来源：[eye_care/ui/window_api.py](D:/Coding/Eye-care/eye_care/ui/window_api.py:232), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1606)

#### `import_all()`

- 用途：导入完整数据
- 成功附加字段：`path`, `result`
- 分类：正式接口
- 来源：[eye_care/ui/window_api.py](D:/Coding/Eye-care/eye_care/ui/window_api.py:269), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1634)

#### `export_settings()`

- 用途：导出设置 JSON
- 成功附加字段：`path`
- 分类：正式接口
- 来源：[eye_care/ui/window_api.py](D:/Coding/Eye-care/eye_care/ui/window_api.py:295), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1620)

#### `import_settings()`

- 用途：导入设置 JSON
- 成功附加字段：`path`
- 分类：正式接口
- 来源：[eye_care/ui/window_api.py](D:/Coding/Eye-care/eye_care/ui/window_api.py:321), [eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1649)

### 3.3 Notify 专用桥接

#### `notify_ready_for_show()`

- 用途：Notify 页面 ACK，表示 CSS/DOM/首帧已就绪，可开始淡入
- 返回：无显式返回
- 消费方：Notify 页面
- 分类：正式接口
- 来源：[eye_care/ui/desktop_integrations.py](D:/Coding/Eye-care/eye_care/ui/desktop_integrations.py:67), [eye_care/ui/web/notify/index.html](D:/Coding/Eye-care/eye_care/ui/web/notify/index.html:140)

#### `notify_window_action(action)`

- 用途：Notify 页面通知宿主执行窗口行为，如 `rest` / `snooze` / `dismiss`
- 返回：无显式返回
- 注意：业务动作本身仍先通过 HTTP `/api/rest/*` 完成，桥只负责窗口行为
- 消费方：Notify 页面
- 分类：正式接口
- 来源：[eye_care/ui/desktop_integrations.py](D:/Coding/Eye-care/eye_care/ui/desktop_integrations.py:48), [eye_care/ui/web/notify/index.html](D:/Coding/Eye-care/eye_care/ui/web/notify/index.html:185)

#### `notify_action(action)`

- 用途：`notify_window_action` 的兼容别名
- 消费方：Notify 页面兼容分支
- 分类：兼容接口
- 来源：[eye_care/ui/desktop_integrations.py](D:/Coding/Eye-care/eye_care/ui/desktop_integrations.py:55), [eye_care/ui/web/notify/index.html](D:/Coding/Eye-care/eye_care/ui/web/notify/index.html:187)

#### `notify_log(payload)`

- 用途：Notify 前端硬日志上报，同时也是部分 ready 判断的 fallback 信号
- 返回：无显式返回
- 消费方：Notify 页面
- 分类：正式接口
- 来源：[eye_care/ui/desktop_integrations.py](D:/Coding/Eye-care/eye_care/ui/desktop_integrations.py:59), [eye_care/ui/window_runtime.py](D:/Coding/Eye-care/eye_care/ui/window_runtime.py:84), [eye_care/ui/web/notify/index.html](D:/Coding/Eye-care/eye_care/ui/web/notify/index.html:124)

## 4. 注入脚本与前端兼容层

当前除 `window.pywebview.api` 外，还存在一层被 Flask 注入的前端兼容对象：

### `window.electronAPI`

由 `inject_bridge_script()` 注入，当前提供以下方法：

- `isElectron`
- `close()`
- `minimize()`
- `maximizeToggle()`
- `getSnapshot(params)`
- `getCalendarMonth(year, month)`
- `restStart()`
- `restComplete()`
- `restSnooze()`
- `restShowOverlay()`
- `dndSet(on)`
- `exportAll()`
- `importAll()`

来源：[eye_care/bootstrap/bridge_inject.py](D:/Coding/Eye-care/eye_care/bootstrap/bridge_inject.py:19)

备注：

- 这是现有前端兼容层，不是新的正式平台接口设计
- 迁移到 Qt 后，可继续保留同名 adapter，也可统一折叠到新的 bridge facade，但必须先决定是否兼容该命名

### `window.__EYECARE_BRIDGED__`

- 用途：前端自检是否已被运行时注入 bridge
- 来源：[eye_care/bootstrap/bridge_inject.py](D:/Coding/Eye-care/eye_care/bootstrap/bridge_inject.py:66)
- 分类：兼容接口

## 5. 页面到接口的依赖映射

### 主页面

依赖：

- `/api/auth/token`
- `/api/snapshot`
- `/api/config` `GET/POST`
- `/api/dnd`
- `/api/rest/start`
- `/api/icon`
- `/api/calendar_month`
- `/api/app_details`
- `/api/apps_list`
- `/api/app_settings`
- `/api/app_exclude`
- `/api/blacklist`
- `/api/blacklist_remove`
- `/api/category_names`
- `/api/categories/delete`
- `/api/update/check`
- `/api/open_url`
- `/api/diag/log`
- `window.pywebview.api.rest_show_overlay`
- `window.pywebview.api.export_all`
- `window.pywebview.api.import_all`
- `window.pywebview.api.export_settings`
- `window.pywebview.api.import_settings`
- `window.pywebview.api.minimize_window`
- `window.pywebview.api.maximize_toggle`
- `window.pywebview.api.close_window`

来源：[eye_care/ui/web/assets/app.js](D:/Coding/Eye-care/eye_care/ui/web/assets/app.js:1377)

### Rest 页面

依赖：

- `/api/auth/token`
- `/api/rest/complete`
- `/api/rest/snooze`
- `window.pywebview.api.rest_ready_for_show`

来源：[eye_care/ui/web/rest/rest.js](D:/Coding/Eye-care/eye_care/ui/web/rest/rest.js:160)

### Notify 页面

依赖：

- `/api/auth/token`
- `/api/rest/start`
- `/api/rest/snooze`
- `window.pywebview.api.notify_log`
- `window.pywebview.api.notify_ready_for_show`
- `window.pywebview.api.notify_window_action`
- `window.pywebview.api.notify_action`

来源：[eye_care/ui/web/notify/index.html](D:/Coding/Eye-care/eye_care/ui/web/notify/index.html:124)

## 6. Step 1 结论

本次盘点确认了三个迁移约束：

1. 当前前端依赖的不只是 `/api/*`，还依赖页面注入、`auth_bootstrap.js`、`window.pywebview.api` 与 `window.electronAPI` 兼容层。
2. `notify_action`、`notify_log`、标题栏窗口控制能力、`/api/auth/token` 都是实际使用中的契约，不能在迁移文档里省略。
3. Step 5/6/7/8 做 bridge 替换时，必须按“主页面 / Rest / Notify / 页面交付层”四层分别迁移，不能把它们混成一个“前后端通信替换”动作。

## 7. 后续建议

Step 2 之前建议新增两类配套材料：

- 一个 `HTTP -> service` 映射表，明确每个 route 后面要下沉到哪个 service
- 一个 `HTTP/pywebview -> Qt bridge` 映射表，明确每个前端调用将来对应哪个 `QWebChannel` 方法
