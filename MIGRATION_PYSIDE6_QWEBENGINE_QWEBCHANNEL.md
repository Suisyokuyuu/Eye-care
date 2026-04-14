# EyE Care 迁移方案：PySide6 + QWebEngineView + QWebChannel

更新时间：2026-04-14
适用范围：当前 `pywebview + Flask + 本地 HTML/CSS/JS` 架构迁移为 `PySide6 + QWebEngineView + QWebChannel`

## 1. 目标与约束

### 1.1 迁移目标

- 桌面宿主从 `pywebview` 迁移到 `PySide6 + QWebEngineView`
- 前后端通信从 `Flask HTTP API` 迁移到 `QWebChannel`
- 保留现有 HTML/CSS/JS 布局与大部分交互代码
- Python 业务层继续以 `AppController` 为核心，不重写业务规则
- Rest/Notify/Tray/导入导出/图标/设置等现有能力保持可用

### 1.2 硬性约束

- 每一步必须“测试成功后才能进入下一步”
- 每一步只允许替换一个主要变量，避免同时改宿主、通信、页面逻辑
- 每一步都必须保留调试入口、日志、失败回退方案
- 在完全切走 Flask 之前，必须允许旧链路继续运行

### 1.3 不做的事

- 不在迁移过程中重做 UI 设计
- 不在第一阶段引入新的业务功能
- 不在前几步直接删除旧 `pywebview`/Flask 代码
- 不在同一步同时迁移主窗口、通知窗口、休息遮罩窗口

## 2. 对上一版计划的自审结论

上一版计划的方向是对的，但有三个风险需要收紧：

1. “先建 bridge 再引入 Qt 宿主”这一步太宽
   如果同时改前端请求方式和宿主，出问题时很难判断是通信层、资源加载还是宿主行为问题。

2. “迁移 rest 和 notify 页面”不能放在同一个大步骤
   这两个窗口都依赖页面 ready 时序、show/hide、动画与业务确认，应该拆成两个独立关卡。

3. “去掉 Flask”必须放到最后
   只有当主窗口、通知、休息遮罩、静态资源、图标、导入导出都已在 Qt 链路下稳定运行，才允许真正移除 Flask。

因此本方案改为“先收口契约，再抽纯逻辑，再引入 Qt 主窗口，再替换通信，再逐个替换附属窗口，最后下线 Flask”。

此外，结合当前代码现状，还要额外明确四个“容易被低估”的迁移前提：

4. Step 1 必须把“隐藏接口”一起冻结
   不能只盘点主页面显式写出来的 `/api/*` 和少数 `pywebview.api`。
   当前代码里还存在 `/api/auth/token`、`/api/auth/*`、`notify_log`、`notify_action` 兼容别名、标题栏窗口控制接口等“迁移时很容易漏掉”的入口，必须一并纳入白名单。
5. Step 3 不能抽象成“直接打开现有静态 HTML”
   当前 `index.html` 依赖 Flask 路由注入 bridge 脚本、替换 `{{APP_VERSION}}`、提供 `/assets/*` 访问，以及 `auth_bootstrap.js` 首屏请求 `/api/auth/token`。
   因此 Step 3 的真实目标应该是“在 Qt 下复刻当前页面交付方式”，而不是简单地双击本地 `index.html`。
6. Rest/Notify 的风险不只是通信替换，而是宿主能力重建
   这两个窗口当前不仅依赖 ready/show/hide 时序，还依赖 WebView2 native handle、透明样式、acrylic、UI 线程/调度线程分离、多窗口 hwnd 解析等宿主细节。
   所以 Step 7/8 必须显式包含“宿主样式与线程模型对齐”，不能只写成“把 HTTP 或 pywebview.api 改成 QWebChannel”。
7. 打包验证不能完全留到最后
   `QWebEngine` 的 PyInstaller 打包、资源收集与运行时目录结构，必须在 Qt 主窗口壳稳定后尽早做最小 smoke test。
   否则容易出现“开发态运行正常、打包态无法启动”的延迟暴雷。

## 2.1 托盘方案自审结论

关于“参考 Kazumi 风格的自定义托盘”，这里单独给出自审结论，避免和主迁移目标混在一起：

1. `PySide6` 本身就是 Qt 的 Python 绑定
   本方案既然目标是 `PySide6 + QWebEngineView + QWebChannel`，就已经处于 Qt 技术栈内，不存在“用了 PySide6 但避免 Qt”这种说法。

2. 自定义托盘不应该与主窗口迁移并行首发
   当前项目托盘基于 `pystray`，而主迁移要先完成宿主、页面通信、Rest、Notify、资源访问等关键链路。如果在早期同时把托盘改成自绘弹层，会同时引入宿主切换、窗口时序、定位、多屏、DPI、失焦关闭等变量，问题定位成本过高。

3. 托盘迁移应拆成两层
   第一层是“托盘后端迁移”：
   从 `pystray` 切到 `QSystemTrayIcon`，但先保留原生菜单。
   第二层是“托盘 UI 自定义”：
   再从原生菜单切到自定义 Popup 面板，做成 Kazumi 风格的托盘控制面板。

4. 推荐把自定义托盘放在主迁移后半段
   只有在以下能力已稳定后，才进入托盘自定义阶段：
   - Qt 主窗口稳定
   - 主页面 bridge 稳定
   - Rest 稳定
   - Notify 稳定
   - 静态资源与桌面能力稳定

5. 当前难度评估
   - 在现有 `pystray + pywebview` 架构上直接做自定义托盘：难度高
   - 在迁移到 `PySide6` 后，用 `QSystemTrayIcon + 自定义 Popup QWidget/QDialog` 实现：难度中等

结论：

- 自定义托盘应纳入迁移总方案
- 但必须作为“主迁移后半段的独立阶段”
- 不允许与主页面 bridge 替换、Rest 迁移、Notify 迁移同时首发

## 3. 迁移总原则

### 3.1 单步边界原则

每一步只回答一个问题：

- 契约是否被完整识别
- 逻辑是否已脱离 Flask
- Qt 主窗口是否可稳定加载
- 主页面业务通信是否已不依赖 HTTP
- Rest 是否已不依赖 pywebview/Flask
- Notify 是否已不依赖 pywebview/Flask
- 静态资源与桌面能力是否已不依赖 HTTP
- 旧链路是否可以安全移除

### 3.2 可验证原则

每一步都必须有：

- 明确输入
- 明确改动范围
- 明确验收条件
- 明确失败表现
- 明确调试方法
- 明确回滚点

### 3.3 可调试原则

每一步都必须保留以下调试能力：

- Python 日志
- JS console 日志
- bridge 调用日志
- 窗口生命周期日志
- 手工回归清单

## 4. 分阶段迁移步骤

---

## Step 0：建立迁移基线，不改行为

### 目标

先确认当前系统的“可工作的基线”是什么，后续每一步都以它为对照。

### 改动范围

- 不改业务逻辑
- 不改 UI
- 只补文档、日志清单、手工回归清单

### 产出

- 当前 API 契约盘点
- 当前 `pywebview.api` 能力盘点
- 手工回归 checklist
- 启动链路与窗口链路说明

### 必测项

1. 主窗口可打开
2. `/api/snapshot` 正常返回
3. 设置读取与保存正常
4. 立即休息可触发 rest overlay
5. notify 弹窗可出现并可响应操作
6. 导入导出可调用
7. 托盘功能正常

### 通过标准

- 基线 checklist 全部通过
- 后续所有步骤都以该 checklist 为回归标准

### 调试要求

- 明确现有日志位置：`user_data/debug.log`
- 记录现有关键路由与窗口调用点

### 失败处理

- 如果基线本身不稳定，先修基线，再进入 Step 1

### 结果测试

- 结果测试 T0-1：默认入口启动后，`/api/health` 与 `/api/snapshot` 在 60 秒内可稳定返回
- 结果测试 T0-2：按“启动 -> 打开设置 -> 保存设置 -> 立即休息 -> snooze/complete -> 等待 notify -> 托盘显示/隐藏 -> 退出”手工跑通一遍
- 结果测试 T0-3：记录基线日志样本、启动命令、数据目录、debug.log 路径；后续每一步都能拿这组样本对比

---

## Step 1：冻结通信契约，先做“接口清单”而不是重写

### 目标

列出所有前端依赖的 HTTP API 和 `pywebview.api` 方法，形成迁移白名单。

### 改动范围

- 文档
- 可选：增加只读诊断日志
- 不改现有前端业务调用方式

### 需要冻结的接口

- `/api/snapshot`
- `/api/config`
- `/api/rest/start`
- `/api/rest/complete`
- `/api/rest/snooze`
- `/api/dnd`
- `/api/app_details`
- `/api/apps_list`
- `/api/app_settings`
- `/api/app_exclude`
- `/api/blacklist`
- `/api/blacklist_remove`
- `/api/calendar_month`
- `/api/categories`
- `/api/category_names`
- `/api/categories/delete`
- `/api/icon`
- `/api/update/check`
- `/api/open_url`
- `/api/auth/token`
- `/api/auth/*` 中仍需要保留的入口
- `/api/diag/log`
- `/api/debug/*` 中仍需要保留的入口

以及：

- `window.pywebview.api.close_window`
- `window.pywebview.api.minimize_window`
- `window.pywebview.api.maximize_toggle`
- `window.pywebview.api.rest_show_overlay`
- `window.pywebview.api.close_rest_overlay`
- `window.pywebview.api.rest_ready_for_show`
- `window.pywebview.api.notify_log`
- `window.pywebview.api.notify_ready_for_show`
- `window.pywebview.api.notify_window_action`
- `window.pywebview.api.notify_action`
- `window.pywebview.api.export_all`
- `window.pywebview.api.import_all`
- `window.pywebview.api.export_settings`
- `window.pywebview.api.import_settings`

### 必测项

1. 所有现有前端调用都能在清单里找到来源与返回结构
2. 主界面、rest、notify 三类页面的调用分别归类完成

### 通过标准

- 没有“迁移时才发现的新接口”
- 所有桥接点都有输入输出样例

### 调试要求

- 为后续 bridge 统一返回格式定标准：`{ ok, data, error, code }`
- 标记“仅当前兼容存在、后续允许删除”的接口：
  `notify_action` 作为 `notify_window_action` 的兼容别名，
  `/api/auth/*` 与 token 注入链路作为 HTTP 时代的页面启动依赖，
  标题栏窗口控制接口作为桌面宿主能力依赖

### 失败处理

- 若发现接口仍在动态扩散，停止后续迁移，先收口调用入口

### 结果测试

- 结果测试 T1-1：主页面、Rest、Notify 的所有前端调用，都能在 Step 1 契约文档中找到来源、入参、返回结构
- 结果测试 T1-2：至少人工抽查 10 个高频调用点，确认“代码调用 -> 契约文档条目”一一对应
- 结果测试 T1-3：明确哪些接口是正式保留、哪些是兼容遗留；迁移白名单不再继续扩散

---

## Step 2：把 Flask route 逻辑抽成纯 Python service

### 目标

去掉 route 对业务逻辑的直接持有，让 Flask 只做“参数解析 + 响应封装”。

### 改动范围

- 新增 `bridge` 或 `services` 层
- route 调整为薄封装
- 不改前端
- 仍保留 Flask 运行

### 推荐拆分

- `SnapshotService`
- `ConfigService`
- `RestService`
- `StatsService`
- `DesktopService`
- `DiagService`

### 必测项

1. 原 `/api/snapshot` 响应与改造前一致
2. 原 `/api/config` 读写行为一致
3. `/api/rest/*` 结果与守卫行为一致
4. `/api/icon`、导入导出、打开链接行为一致
5. 所有旧页面不需要改动即可正常工作

### 通过标准

- 现有 UI 在 Flask 模式下功能无回归
- 新 service 可以被单元测试或脚本直接调用

### 调试要求

- 每个 service 方法记录输入参数和返回摘要
- route 层只保留极薄的 request/response 转换日志

### 回滚点

- 如果某个 service 拆分导致行为偏差，可单独回滚到原 route 实现，不影响其他步骤

### 结果测试

- 结果测试 T2-1：新增 `services` 包可正常导入，且 route -> service 映射文档完整
- 结果测试 T2-2：在不改前端的前提下，现有 Flask 路径的 Step 0 基线回归全部通过
- 结果测试 T2-3：至少一组 service 骨架能被脚本直接构造和调用，不依赖 Flask request 上下文

---

## Step 3：引入 PySide6 宿主，但先只加载主窗口静态页面

### 目标

先证明 Qt 宿主本身稳定，并能以“与当前页面等价”的方式交付主界面，
但不接正式业务桥，不替换现有入口。

### 改动范围

- 新增 Qt runtime
- 新增独立启动入口
- 主窗口加载当前主页面，但必须先明确页面交付方式
- 先不承接完整业务操作

### 本步必须先回答的问题

- Qt 版本的页面是继续走本地 HTTP 交付，还是改为 `file://` / `qrc:/` / 自定义 scheme
- `inject_bridge_script` 与 `{{APP_VERSION}}` 替换如何在 Qt 路径下继续成立
- `/assets/*` 的绝对路径访问如何兼容
- `auth_bootstrap.js` 依赖的 `/api/auth/token` 在本步是否继续保留

### 本步不要做的事

- 不替换默认 `main.py`
- 不接管 rest/notify
- 不移除 `pywebview`
- 不替换全部前端请求
- 不假设“现有 index.html 可直接当纯静态文件打开”

### 必测项

1. Qt 主窗口可以打开现有 `index.html`
2. HTML/CSS/JS 资源可正常加载
3. JS console 能映射到 Python 日志
4. 页面没有资源 404
5. 页面在 Qt 下无明显布局错乱

### 通过标准

- Qt 壳稳定打开主界面
- 资源加载与页面渲染可重复成功
- 页面交付策略已明确，且不依赖隐式 Flask 注入魔法

### 调试要求

- 记录 `QWebEnginePage.javaScriptConsoleMessage`
- 记录加载事件：`loadStarted/loadProgress/loadFinished`
- 明确资源根目录和 URL 解析策略
- 记录页面启动时使用的是哪一种交付模式：`http_local` / `file` / `qrc` / `custom_scheme`

### 回滚点

- Qt runtime 是新增入口，不影响旧链路，可随时停用

### 额外验证

- 在本步完成后尽快做一次最小打包 smoke test：
  只要求 Qt 主窗口能启动、主页面能打开、静态资源能加载。
  这不是正式发布验收，但必须尽早验证 `QWebEngine` 打包链路可行。
- 若最小打包 smoke test 通过，但仍依赖临时资源拷贝或目录补偿，也必须显式记录。
  当前一个已验证的现实例子是：PyInstaller one-folder 产物的部分资源默认落在 `_internal` 下，
  而运行时代码仍按外层 dist 根目录解析资源；此时可以先接受“最小可跑”，
  但必须把补偿动作、受影响资源和最终收口阶段写进迁移记录。

### 结果测试

- 结果测试 T3-1：使用独立 Qt 入口启动后，主窗口在 60 秒内打开并完成页面首屏渲染
- 结果测试 T3-2：资源面板或日志中不存在主页面关键资源 404，`auth_bootstrap.js`、主 JS、主 CSS 均成功加载
- 结果测试 T3-3：最小打包产物可在测试机器上启动到主页面，不要求可交互完整，但必须能看到主界面
- T3-3 记录要求：若打包产物依赖 `_internal -> 外层 dist` 的资源复制、额外工作目录切换或其他临时补偿，必须随测试结果一并登记，不能视为“打包结构已完全稳定”

---

## Step 4：在 Qt 主窗口接入 QWebChannel，但先只做“探针能力”

### 目标

先验证 `QWebChannel` 通信可靠，再承接正式业务。

### 改动范围

- 新增 `QtBridge` 基础对象
- 前端只接一个最小探针脚本
- 先做 ping/log/version/ready 这类轻量调用

### 推荐最小接口

- `bridge.ping()`
- `bridge.log(level, message, extra)`
- `bridge.getRuntimeInfo()`

### 必测项

1. 页面能成功建立 channel
2. JS 能调用 Python slot
3. Python 能返回 Promise 可消费的数据
4. 错误调用能返回明确错误，而不是页面卡死

### 通过标准

- QWebChannel 链路稳定
- 至少连续多次打开关闭主窗口都能建立连接

### 调试要求

- 增加桥接握手日志：`channel_init -> bridge_ready -> first_call_ok`
- 所有 bridge 方法统一异常包装

### 回滚点

- 仅增加探针，不影响旧业务链路

### 结果测试

- 结果测试 T4-1：连续 10 次“启动 Qt 主窗口 -> 等待 bridge ready -> 调用 ping/log/getRuntimeInfo -> 关闭窗口”全部成功
- 结果测试 T4-2：故意调用一个不存在或非法的 bridge 方法时，前端拿到明确错误，不出现页面冻结
- 结果测试 T4-3：握手日志中至少出现一组完整链路：`channel_init -> bridge_ready -> first_call_ok`

---

## Step 5：替换主页面业务通信，先迁移读接口，再迁移写接口

### 目标

主页面先摆脱对 Flask 的依赖，但只迁移主页面，不碰 rest/notify 窗口。

### 改动范围

- 新增前端 bridge adapter
- 先把主页面的 `/api/*` 映射到 `QWebChannel`
- 保留旧 HTTP fallback

### 顺序

1. 先迁移只读接口
   `snapshot/config/apps_list/app_details/blacklist/calendar_month/category_names`
2. 再迁移写接口
   `config/rest_start/dnd/app_settings/app_exclude/blacklist_remove/categories/delete/open_url`

### 必测项

1. 主页面首次加载能正常拿到 snapshot
2. 轮询刷新正常
3. 设置读取与保存正常
4. 立即休息按钮状态与守卫逻辑正常
5. 图表、分类、应用详情、黑名单页面正常

### 通过标准

- 主页面在 Qt 下不依赖 Flask 也可完整工作
- 主页面仍允许切回 HTTP fallback 进行比对

### 调试要求

- bridge adapter 记录“原始 URL -> bridge 方法”的映射日志
- 每个请求要有 request id，便于前后端对日志

### 回滚点

- 可切回 HTTP fallback
- 主页面 bridge 与旧 HTTP 可并存，问题定位简单

### 结果测试

- 结果测试 T5-1：在 `bridge` 模式下，主页面首次加载、轮询刷新、设置读取、应用详情、黑名单、分类页全部可用
- 结果测试 T5-2：在 `hybrid` 模式下，同一台机器上能切回 HTTP fallback 并得到与 bridge 模式一致的关键结果
- 结果测试 T5-3：主页面日志中不再出现业务性 `/api/*` 调用，或只剩显式允许的 fallback 调用

---

## Step 6：迁移桌面能力，不再依赖 pywebview.api

### 目标

把主页面仍依赖 `pywebview.api` 的能力迁移到 Qt bridge。

### 范围

- 导入/导出
- 设置导入导出
- 打开链接
- 可能的窗口控制接口

### 必测项

1. `export_all` 正常
2. `import_all` 正常
3. `export_settings` 正常
4. `import_settings` 正常
5. 外链打开正常

### 通过标准

- 主窗口在 Qt 下不再需要 `window.pywebview.api`

### 调试要求

- 文件对话框返回值必须落日志
- 失败时返回明确错误码，不允许静默失败

### 回滚点

- 单个能力可以临时保留旧实现，不阻塞其他能力迁移

### 结果测试

- 结果测试 T6-1：导入/导出、设置导入/导出、打开外链、主窗口标题栏控制，在 Qt 路径下全部可用
- 结果测试 T6-2：断开 `window.pywebview.api` 后，主页面仍可完成上述桌面能力调用
- 结果测试 T6-3：所有桌面能力失败时都能返回明确错误，而不是静默无响应

---

## Step 7：迁移 Rest Overlay，单独成关

### 目标

把休息遮罩从 `pywebview` 独立窗口迁到 Qt，多窗口行为与宿主样式能力必须逐项对齐。

### 范围

- Qt rest window
- `rest_ready_for_show`
- `close_rest_overlay`
- rest 页面与主控制器的桥接
- 多屏/坐标/句柄解析
- 透明样式与宿主窗口能力对齐
- 页面 ready 与实际 show 的线程/事件时序对齐

### 本步不要做的事

- 不同时迁移 notify

### 必测项

1. 主页面点击“立即休息”可正常打开 overlay
2. overlay ready 后再 show，避免首帧黑屏
3. 倒计时正常
4. `complete` 正常
5. `snooze` 正常
6. `Esc` 行为正常
7. 多屏情况下窗口显示位置正确

### 通过标准

- Rest 全链路在 Qt 下可独立稳定运行

### 调试要求

- 完整日志链路：
  `rest_window_created -> html_loaded -> channel_ready -> show -> user_action -> hide/destroy`
- 明确记录样式与宿主链路：
  `native_created -> hwnd_resolved -> style_apply_start -> style_apply_ok/fail`

### 回滚点

- Rest 仍可临时保留旧 pywebview 实现，不影响主窗口继续迁移

### 结果测试

- 结果测试 T7-1：从主页面点击“立即休息”，Rest overlay 在主屏和副屏上都能正确出现、倒计时并响应 `Esc`
- 结果测试 T7-2：连续执行 10 轮 `show -> ready -> snooze` 与 10 轮 `show -> ready -> complete`，无黑屏、无残留窗口、无卡死
- 结果测试 T7-3：样式链路日志中不存在持续失败重试；若样式失败，必须看到明确降级或失败原因

---

## Step 8：迁移 Notify Window，单独成关

### 目标

把通知弹窗迁到 Qt，保持 ready/show、action、fade 时序稳定，并重建当前宿主侧透明/样式/线程栅栏。

### 范围

- Qt notify window
- `notify_ready_for_show`
- `notify_window_action`
- notify 日志桥
- ready 栅栏重建
- 透明样式 / acrylic / hwnd 解析对齐
- UI 线程与调度线程的职责边界对齐

### 必测项

1. notify 能正常出现
2. ready 后再 show
3. 自动关闭正常
4. rest/snooze/dismiss 操作正常
5. 通知完成回调与去重逻辑正常
6. 动画与关闭链路无卡死
7. 透明样式失败时可明确降级，不出现“有日志但视觉不生效”的假成功

### 通过标准

- Notify 全链路在 Qt 下可独立稳定运行

### 调试要求

- 完整日志链路：
  `notify_window_created -> html_loaded -> channel_ready -> show -> action/timeout -> hide/destroy`
- 补充宿主侧日志链路：
  `native_created -> form_handle_ready -> webview_ready -> transparent_ready -> acrylic_ready -> first_frame_ok`

### 回滚点

- Notify 仍可独立回退到旧实现，不影响主窗口和 rest

### 结果测试

- 结果测试 T8-1：连续触发 20 次 notify，通知均能出现、自动关闭或响应动作，不残留假死窗口
- 结果测试 T8-2：`rest / snooze / dismiss` 三种动作都至少跑通 5 次，完成回调与去重逻辑正确
- 结果测试 T8-3：透明样式、淡入淡出、ready 栅栏任一失败时，都有明确日志与可见降级，而不是“看似成功但视觉无效”

---

## Step 9：迁移图标与本地资源访问，清掉对 `/api/icon` 和 HTTP 静态服务的依赖

### 目标

去掉主界面和详情页对 HTTP 静态资源服务的剩余依赖。

### 范围

- 图标获取策略
- 本地音效文件访问
- HTML/CSS/JS 资源加载策略

### 推荐方向

- 图标优先走 bridge 返回 data URL 或本地缓存路径
- 音效使用本地资源路径或 Qt 资源访问

### 必测项

1. 应用图标正常显示
2. 图标缓存仍可工作
3. 音效文件能正常播放
4. 静态资源不需要 Flask 路由也可加载

### 通过标准

- 页面资源和图标均不再依赖本地 HTTP server

### 调试要求

- 资源路径解析失败必须打印完整绝对路径与页面 URL

### 回滚点

- 图标与资源加载可单独保留兼容层，不阻塞前面步骤

### 结果测试

- 结果测试 T9-1：断开 Flask 静态资源路由后，主页面、Rest、Notify 仍能加载自身 HTML/CSS/JS
- 结果测试 T9-2：应用列表与详情页图标能稳定显示，缓存命中和缓存失效两条路径都可用
- 结果测试 T9-3：本地音效在至少一次 notify 和一次 rest complete 场景中能正常播放

---

## Step 10：默认入口切到 Qt，旧入口保留一段时间

### 目标

当主窗口、Rest、Notify、桌面能力都已稳定后，再切换默认启动入口。

### 范围

- 修改 `main.py` 默认入口
- 旧 `pywebview` 入口保留为 debug/fallback 入口

### 必测项

1. 默认启动进入 Qt 版本
2. 托盘、主窗口、rest、notify 都正常
3. 原数据目录兼容
4. 无需 Flask 即可运行

### 通过标准

- 日常使用默认走 Qt 路径，旧入口仅用于回退

### 调试要求

- 启动日志必须明确当前运行在 `qt` 还是 `legacy_pywebview`

### 回滚点

- 仍可通过旧入口回退

### 结果测试

- 结果测试 T10-1：默认执行 `main.py` 后进入 Qt 路径，且启动日志明确标记当前宿主
- 结果测试 T10-2：默认入口下完整跑通 Step 0 基线回归一次，不依赖手工切换到 legacy
- 结果测试 T10-3：出现问题时，显式切回旧入口仍可恢复可用

---

## Step 10A：托盘后端迁移到 PySide6/Qt，但先保留原生菜单

### 目标

先把托盘运行时从 `pystray` 迁移到 `QSystemTrayIcon`，但先不做 Kazumi 风格自定义面板。

### 设计边界

- 这是 Qt 技术栈内的托盘后端迁移，不是额外引入新框架
- 只替换托盘实现，不同时重做托盘 UI
- 主窗口、Rest、Notify、主页面通信在本步视为既有稳定能力

### 改动范围

- 新增 Qt TrayController
- 用 `QSystemTrayIcon` 承接托盘图标、点击事件、tooltip、消息通知
- 先使用 `QMenu` 复刻现有菜单项
- 保留现有业务回调语义：
  - 显示主界面
  - 切换模式
  - 立即休息
  - 打开设置
  - 检查更新
  - 打开数据目录
  - 退出

### 本步不要做的事

- 不做自定义弹层面板
- 不做复杂动画
- 不重构主业务控制器

### 必测项

1. 托盘图标正常显示
2. 菜单项完整可用
3. “显示主界面”正常
4. 模式切换正常
5. “立即休息”正常
6. “打开设置”正常
7. “退出”正常
8. 多次显示/隐藏主窗口后，托盘不假死

### 通过标准

- 现有托盘能力在 `QSystemTrayIcon` 下完整复刻
- 不再依赖 `pystray`

### 调试要求

- 托盘点击事件日志
- 菜单 action 触发日志
- 主窗口显隐同步日志
- 退出路径日志

### 回滚点

- 如果 `QSystemTrayIcon` 版本不稳定，可临时回退到旧托盘实现

### 结果测试

- 结果测试 T10A-1：托盘图标稳定显示，菜单项全部可点击，连续 20 次弹出菜单无假死
- 结果测试 T10A-2：通过托盘执行“显示主界面 / 模式切换 / 立即休息 / 打开设置 / 退出”均可用
- 结果测试 T10A-3：应用退出后不残留系统托盘幽灵图标

---

## Step 10B：托盘 UI 升级为 Kazumi 风格自定义 Popup

### 目标

在 Qt 托盘后端稳定后，再把原生菜单升级为自定义托盘面板。

### 设计目标

- 点击托盘图标弹出自定义面板，而不是系统原生右键菜单
- 面板样式与主应用保持一致
- 可承载更丰富的状态和快捷操作

### 推荐实现

- `QSystemTrayIcon` 负责托盘图标与激活事件
- `TrayPopupWidget` 或 `TrayPopupDialog` 负责自定义 UI
- 使用无边框、圆角、阴影、自定义布局
- 失焦关闭
- `Esc` 关闭
- 点击外部关闭

### 推荐展示内容

- 当前模式
- 今日简要统计
- 显示主界面
- 立即休息
- 勿扰/正常/离开切换
- 打开设置
- 退出

### 本步不要做的事

- 不额外引入新业务功能
- 不修改主页面的业务结构

### 主要风险

- Windows 托盘图标位置获取不稳定
- 多屏与 DPI 缩放下定位偏移
- 失焦关闭与点击穿透处理复杂
- 托盘点击、主窗口显示、Popup 显隐三者状态同步容易出错

### 必测项

1. 单击托盘图标可稳定弹出面板
2. 再次点击可关闭面板
3. 点击外部关闭正常
4. `Esc` 关闭正常
5. 多屏情况下位置基本正确
6. 125%/150% 缩放下位置基本正确
7. 面板内模式切换立即生效
8. 面板内“立即休息”正常
9. 应用退出时不残留假死托盘图标

### 通过标准

- 自定义托盘面板在主要桌面场景下稳定可用
- 可以完全替代原生托盘菜单

### 调试要求

- 托盘激活事件日志
- Popup 创建/显示/关闭日志
- 定位坐标日志
- 焦点变化日志

### 回滚点

- 如果自定义 Popup 稳定性不足，可回退到 Step 10A 的 `QSystemTrayIcon + QMenu`

### 结果测试

- 结果测试 T10B-1：单击托盘图标弹出自定义面板，再次点击关闭；连续 20 次操作状态一致
- 结果测试 T10B-2：在 100% / 125% / 150% 缩放与多屏环境下，Popup 定位基本正确，不明显漂移
- 结果测试 T10B-3：Popup 内部的“立即休息 / 模式切换 / 打开设置 / 退出”均可独立完成

---

## Step 11：下线 Flask 与 pywebview，最后做依赖和打包清理

### 目标

真正完成迁移，移除旧依赖和废弃代码。

### 范围

- 移除 Flask server 启动链路
- 移除 `web_routes.py` 的 HTTP 站点职责
- 移除 `auth_bootstrap.js`
- 移除 `pywebview` 宿主相关代码
- 更新 `requirements.txt`
- 更新 `PyInstaller spec`
- 统一打包态资源定位策略，消除 `_internal` 资源外拷或运行时目录补偿

### 必测项

1. 项目不启动本地 HTTP server 也可完整运行
2. 没有 `/api/*` 调用残留
3. 没有 `window.pywebview.api` 调用残留
4. 打包后可运行

### 通过标准

- 旧链路全部移除且无功能回退

### 调试要求

- 全局搜索确认：
  - 不再有业务代码依赖 Flask route
  - 不再有前端业务依赖 `/api/*`
  - 不再有前端依赖 `window.pywebview.api`

### 回滚点

- 此步骤之前必须已经有稳定 Qt 版本
- 真正删除前应保留一个临时分支或 tag

### 结果测试

- 结果测试 T11-1：停止启动本地 HTTP server 后，应用仍可完成 Step 0 基线回归
- 结果测试 T11-2：全局搜索确认业务代码中不再存在 `/api/*` 与 `window.pywebview.api` 的运行时依赖
- 结果测试 T11-3：打包产物在干净环境中可启动、可打开主页面、可触发一次 rest 与一次 notify
- 结果测试 T11-4：打包产物无需手工复制 `_internal` 资源到外层目录，也无需额外修改工作目录；主页面、静态资源、图标、音频与导入导出路径解析全部正确

## 5. 每一步进入下一步的门槛

必须同时满足以下条件，才允许进入下一步：

1. 本步的必测项全部通过
2. Step 0 的基线回归项没有新增失败
3. 日志中没有新的高频未处理异常
4. 本步的调试开关已就位
5. 本步的失败回滚路径已明确

只要有一项不满足，就不能进入下一步。

## 6. 推荐测试策略

### 6.1 自动化测试

优先覆盖纯逻辑层：

- `AppController`
- 新拆出的 service 层
- bridge 参数转换层
- 关键状态机输入输出

### 6.2 手工回归测试

每一步至少回归以下场景：

1. 启动应用
2. 主页面首次加载
3. 轮询刷新
4. 修改设置并保存
5. 触发立即休息
6. rest 完成或 snooze
7. notify 出现并响应
8. 托盘显示/隐藏
9. 导入导出
10. 退出应用

对于 Step 7 / Step 8 / Step 10 之后的版本，除上述手工回归外，还应把现有 `tests/hang_scenarios/`
纳入迁移门槛，至少覆盖：

- `scenario_f_notify_hide`
- `scenario_g_notify_storm`
- `scenario_h_rest_notify_combo`
- `scenario_j_startup_shutdown`
- `scenario_k_notify_ack_repost_guard`

### 6.3 调试开关建议

- `EYECARE_UI_HOST=legacy|qt`
- `EYECARE_BRIDGE_MODE=http|bridge|hybrid`
- `EYECARE_DEBUG_CONSOLE=1`
- `EYECARE_BRIDGE_TRACE=1`

说明：

- `legacy` 用旧 pywebview 宿主
- `qt` 用新 Qt 宿主
- `http` 只走旧 HTTP
- `bridge` 只走新 bridge
- `hybrid` 优先 bridge，保留 HTTP fallback

## 7. 推荐落地顺序

严格按以下顺序推进，不跳步：

1. Step 0 基线
2. Step 1 契约冻结
3. Step 2 route 逻辑下沉
4. Step 3 Qt 主窗口壳
5. Step 4 QWebChannel 探针
6. Step 5 主页面业务通信迁移
7. Step 6 桌面能力迁移
8. Step 7 Rest 迁移
9. Step 8 Notify 迁移
10. Step 9 图标与资源访问迁移
11. Step 10 默认入口切换
12. Step 10A 托盘后端迁移
13. Step 10B 自定义托盘 Popup
14. Step 11 删除旧链路

补充说明：

- Step 3 完成后，不等到 Step 11，先做一次最小打包 smoke test
- Step 7/8 不只验通信，还必须验宿主样式/线程/窗口生命周期链路

## 8.1 阶段结果测试总表

为避免每一步“看起来完成、实际上没有结果”，每个阶段至少要产出一个可判定结果：

- Step 0：基线可重复跑通
- Step 1：契约文档完整且可追溯
- Step 2：service 骨架落地且旧链路无回归
- Step 3：Qt 主窗口壳可独立启动
  注：允许存在“最小打包 smoke 可跑但仍依赖资源外拷”的已知问题，但必须显式记录并挂到 Step 11 收口
- Step 4：QWebChannel 探针握手稳定
- Step 5：主页面业务通信切到 bridge 后可完整使用
- Step 6：桌面能力不再依赖 `pywebview.api`
- Step 7：Rest overlay 全链路迁移完成
- Step 8：Notify 全链路迁移完成
- Step 9：资源与图标不再依赖本地 HTTP
- Step 10：默认入口切到 Qt
- Step 10A：托盘后端切到 Qt
- Step 10B：自定义托盘 Popup 可用
- Step 11：旧链路删除后，应用仍完整可运行

## 8. 当前建议的第一批实际任务

按本方案，第一批实际工作应该只做下面三件事：

1. 产出完整接口契约文档
2. 把 Flask route 逻辑抽成纯 Python service 骨架
3. 新建 Qt runtime 骨架，但不接业务

这三件事做完并测试通过后，才能进入主页面 bridge 替换阶段。

## 9. 本文档自审

### 9.1 这版结果测试的设计原则

- 不依赖现有 `tests/hang_scenarios/` 是否完备
- 每一步至少有一个“做完了就能证明结果存在”的测试
- 尽量避免只测“进程还活着”，而是测“用户能做成某件事”
- 尽量把“技术结果”与“用户结果”同时覆盖

### 9.2 这版结果测试的优点

- 每个阶段都有明确出口，不再只是“建议测一测”
- 能区分“文档产物完成”“宿主能力完成”“业务迁移完成”“打包完成”
- 对 Step 3、Step 7、Step 8、Step 11 这些高风险阶段给了更硬的门槛
- 允许阶段性承认“最小可跑但仍有现实补偿”的中间状态，但要求把补偿动作显式挂账，避免后续阶段忽略真实打包问题

### 9.3 仍然存在的局限

- 其中不少结果测试仍然是“手工可执行门槛”，不是自动化测试
- 多屏、DPI、透明样式、托盘行为这类问题，最终仍需要真实桌面环境验证
- 若后续补了更高质量自动化场景，应让这些自动化场景对齐这里的阶段结果测试，而不是另起一套口径

### 9.4 自审结论

这版补充后的文档，已经比原来更适合作为迁移执行门槛：

- 原来偏“步骤说明”
- 现在补成了“步骤说明 + 阶段结果测试 + 自审约束”

仍建议在真正进入 Step 3 之后，把 T3/T4/T5/T7/T8/T11 逐步转成半自动或自动化脚本；但在那之前，这一版已经足够作为迁移推进时的阶段验收标准。
