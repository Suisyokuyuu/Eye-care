# EyE Care — 项目记忆

> 本文件是 **EyE Care 项目专属** 的记忆/说明，跟随本 repo。
> 与全局记忆（`~/.claude/.../memory/`）以及其它项目的记忆**完全独立**：
> 不要把本项目的事实写进全局记忆，也不要把其它项目的事实写进这里。

## 项目身份
- **EyE Care**：Windows 桌面护眼 + 应用使用时长统计工具。
- 远程：`github.com/Suisyokuyuu/Eye-care.git`。
- **开发环境是 Linux 工作区副本**（挂载为 `/workspace/Eye-care`），**不是**实际运行 App 的 Windows 机器：
  本机没有 Qt/PySide6，QML 与 Win32/UIA 相关改动一律跑不起来，只能过 `py_compile` + 纯逻辑测试，
  运行期必须在 Windows 上实测。改动发生在这份副本里，需经 git 或手动拷贝同步回 Windows。

## 技术栈 / 架构要点（QML 迁移已收尾，2026-06-15 剥离旧版）
- 桌面宿主：**PySide6 / Qt Quick（QML）**，唯一入口 `main.py --host qt` → `eye_care/qt/runtime_shell.py:run_qt_shell`。
  **已彻底移除 QWebEngine / Flask / web SPA / pywebview**（曾是 ~4GB RSS 内存元凶）。
- 主窗口：`QQmlApplicationEngine` 加载 `eye_care/qt_quick/qml/AppShell.qml`（无边框 QQuickWindow）。
  仪表盘左右栏 + 设置/黑名单/应用详情/更新/日历全部是 QML 覆盖层 + 专用数据桥（`eye_care/qt_quick/*_bridge.py`）。
- 数据流：`controller`（同步建于主线程）→ services → `build_shell_bridges(controller, persist=True)` 装配 7 个桥，
  经 `setContextProperty` 喂 QML（无 HTTP 中转）。桥对象全部 `QQmlEngine.setObjectOwnership(CppOwnership)` 防 JS GC。
- 宿主桥 `QtHostBridge`（runtime_shell 内）：只承载与 desktop 强耦合的几件事——导入/导出文件对话框、关闭动作落盘、
  `startRest`/`showRestOverlay`。QML 直接调用上下文属性 `shellHost`（`doToolbarAction/requestRest/quitApp`）比 Python 连 QML 信号更可靠。
- notify 气泡 / rest 全屏遮罩：QML 原生（`qt_quick/notify_overlay.py`/`rest_overlay.py`），Python 回调收尾，无 channel 握手。
- 仪表盘刷新：10s `QTimer` 调 `left/right.refresh()`；渲染**原地更新**（count-based Repeater + 索引读值 + 签名跳过），不重建 delegate。
- 声音：`eye_care/assets/*.wav`（从原 ui/web/assets 迁出）；图标：`ConfigService.get_icon`（`win_icon_extract`，含 temp 兜底）。
- 保留的 `eye_care/api/common.py` 仅是 services 共用的纯数据助手（`_state_dict/_stats_for_date/_timebars_*`），**与 Flask 无关**。
- 打包：PyInstaller，`EyE Care.spec` 用 `('eye_care','eye_care')` 整目录打包（含 `qml/` 与 `assets/`）。
  hiddenimports 收 QtQml/QtQuick/QtQuickControls2（触发钩子收 Controls.Basic/Shapes/Effects 插件）；已去 QtWebEngine/webview/Flask。

## 进行中的工作
### 性能优化（用户主诉）
- 症状：多点几个页面后内存涨到 ~2G；切回主页 CPU 瞬间打满（疑似单核长任务）。
- 初步判断：内存堆积大概率在 **Chromium renderer 子进程**（DOM / Chart 实例 / 事件监听器未释放）；
  CPU 峰值像切页时一次同步 long task + 图表重排。

#### 已交付：可视化性能分析 HUD（仅 debug 模式）— 2026-06-12
- 后端 `eye_care/diagnostics/perf_sampler.py`：psutil 遍历主进程+各 WebEngine 子进程，按 `--type=` 分类
  （main/renderer/gpu/...）报 RSS/CPU%，CPU 用增量，单例 `get_perf_sampler()`，psutil 缺失降级不崩。
- bridge：`QtBridgeProbe.getPerfSample()` 槽。
- 注入开关 `perf_hud_enabled`：`--debug` / `EYECARE_DEBUG=1` / `EYECARE_PERF_HUD=1` 任一启用；
  主页 `loadFinished` 后注入 `eye_care/ui/web/assets/perf_hud.js`。
- HUD（`perf_hud.js`）：可拖动半透明面板 + 折线，指标含 各进程/总 RSS、JS Heap、FPS、DOM 节点(Δ)、
  Chart 实例、Δ监听器、LongTask ms、CPU 总%、进程表；按钮 标记/清零/导出JSON；
  自动给 `appTab/categoryTab/dayTab/weekTab/monthTab/calendarBtn` 点击打标记；`Ctrl+Shift+P` 开关。
#### 已确诊（HUD 实测，2026-06-13）
- 实测轨迹：点 tab 几轮，**Renderer RSS 260MB → 4.2GB 一路只涨不回**（每次切页 +50~400MB），
  而 **JS Heap 全程平在 ~10MB、DOM 全程 ~1000 节点、Chart 实例封顶 4 个**。
- 结论：**渲染进程原生/GPU 内存泄漏，不是 JS 泄漏**。病根是 `app.js` 里 `categoryTab`/`appTab`
  点击 handler 每次 `destroy()`+`initXxxChart()` 重建图表 → 反复销毁/新建 canvas 的 GPU 后备
  缓冲被 Chromium 留住不还给 OS。另抓到 LongTask=51ms（切回时的同步长任务 = CPU 单核峰值）。

#### 已修复（2026-06-13）
- `app.js` 两个 tab handler：**实例已存在就不再 destroy/重建，改为复用单例**（仅置
  `__needXxxEnterAnim`，数据由随后的 `requestImmediateRefresh` → `update('none')` 原地刷新）。
  `initAppChart()` 加 `if(!appChartInstance)` 守卫（canvas 已有实例时 `new Chart` 会被 Chart.js 拒绝）。
- 复测结果：tab 切换 +几百MB → ~+50MB（有效但不够）。**新主因浮现**：用户指出"内存加进去
  就释放不出来"，HUD 实测 Renderer RSS 单调只涨不降。

#### 第二轮根因 + 修复（2026-06-13）
- **真凶：全屏模态的 `backdrop-blur`**。`index.html` 里 ~11 个模态都是 `fixed inset-0 ...
  backdrop-blur-sm`（整窗口背景模糊）。打开日历一下 **Renderer +747MB 而 DOM 仅 +108 节点**
  （747MB÷108≈6.9MB/节点，不可能是 DOM）——是 Chromium 为全屏 backdrop blur 分配的 GPU 合成层
  纹理，且关闭模态后不归还。
- **修复**：去掉 `index.html` 所有模态的 `backdrop-blur-sm`/`backdrop-blur`，保留 `bg-black/70`
  变暗遮罩（视觉几乎无差，GPU 合成层尖峰消除）。`.glass-effect` 持久 blur 是死 CSS（index.html
  0 引用），无关。
- **新增 Chromium flags 钩子** `dpi_console.configure_webengine_flags()`（main.py 早于 Qt 调用），
  全 env 门控、默认不改行为：`EYECARE_DISABLE_GPU=1`（A/B 验证 GPU 合成假设）、
  `EYECARE_LOW_MEM=1`（低内存模式更激进回收）、`EYECARE_CHROMIUM_FLAGS=...`（自定义）。
- 复测：日历首开尖峰 747MB→75MB（模糊修复有效 ✓），但 **Renderer RSS 仍单调爬到 2.7GB**，
  且有半随机大跳（切"周"也能 +892MB）= Chromium 合成器按需分配光栅 tile 内存、池化不归还。
  **核心遗留问题 = 渲染进程原生内存"只涨不还"，非某行 JS 泄漏。**

#### GPU 内存配额（2026-06-13）
- `configure_webengine_flags()` 默认加 `--force-gpu-mem-available-mb=512`（超预算即驱逐 GPU 资源，
  封住合成池无限涨）。`EYECARE_GPU_MEM_MB=N`(0 关) / `EYECARE_LOW_MEM=1`(小 tile+关程序缓存) /
  `EYECARE_DISABLE_GPU=1` 可调。预期：把峰值压住，不是磁平。

#### 架构判断（关键，待用户决策）
- 根因是**用 QWebEngine(整个 Chromium) 渲染一个常驻托盘小工具**——baseline 就 200MB+，合成内存
  还只涨不还。原生 Qt(QML/Quick + QtCharts) 做同样的仪表盘/列表/设置/日历只需 ~50–150MB 且平稳。
- **后端(controller/services/data/probes/notify/bridge)与 UI 无关、可整体复用**；迁移只重写
  `eye_care/ui/web` 视图层为 QML。一次性大工程，但能永久消除这一类内存问题。
- 短期：GPU 配额 + 去模糊 + 图表复用 先止血。是否启动 QML 迁移 = 待用户拍板。
- **评估文档已出**：`docs/qml_migration_assessment.md`（后端 ~7500 行零重写、bridge 44 个 Slot 即
  契约可直接喂 QML；web 视图 ~6600 行重写；~6–8 人周；建议先迁 rest/notify 做试点）。用户已选"评估
  QML 迁移"方向。

### 后台 Web 调试台 + 杂项修复（2026-06-12）
四项 bugfix（QML 迁移之前）：
1. **分类卡片布局对齐应用卡片**：分类卡（`renderCategory*`，app.js ~345）原来用临时
   Tailwind `flex items-center justify-between p-3` + `w-10`图标 + `w-24`进度条，与应用卡的
   `app-list-row`（三段栅格 `minmax(0,1fr) 86px 44px`）不齐。已改为复用 `app-card app-list-card
   category-card` + `app-list-*` 同一套类（图标里放 `<i class="fa">` 而非 img）。分类卡仍带
   `category-card`+`data-category` 供点击委托（categoryListContainer 上，不与 appListContainer
   的 `.app-card` 委托冲突）。`index.html` categoryView 饼图右侧也对齐 appView：`text-4xl/mb-6/
   space-y-4` → `text-2xl/mb-3/space-y-1`。
2. **性能分析改为「后台 Web 调试台」**：页内 HUD（perf_hud.js）退役，默认不再注入（占用程序内
   QWebEngine 渲染）。改由 **Flask 同进程**新端点 `GET /api/debug/console` 提供独立页面
   `eye_care/ui/web/debug_console.html`，debug 时用系统默认浏览器自动打开（独立进程渲染，零占用
   程序内渲染）。psutil 采样走 `GET /api/debug/perf`（Flask 与 Qt 同进程，读同一棵进程树，数据
   与原 HUD 一致：主/renderer/gpu 各进程 RSS+CPU、总量、sparkline）。遗留页内 HUD 仅
   `EYECARE_PERF_HUD_INPAGE=1` 时注入。`EYECARE_DEBUG_CONSOLE_AUTOOPEN=0` 关自动开。
3. **统一调试控制台（日志合并 + 调试动作）**：调试台左性能/右日志+动作。日志走
   `GET /api/debug/logs?offset=N`（按字节增量 tail data_dir/debug.log，处理轮转，首拉只回末
   400 行）；server.py 的 HTTP 追踪 after_request 已把 `/api/debug/{logs,perf,console}` 排除，
   避免刷爆日志 + logs 端点读自身日志的自喂循环。动作按钮接既有/新增端点：触发通知
   `POST /api/debug/notify`、自然通知链路 `POST /api/debug/trigger_natural_notify`(新)、通知调试
   日志开关 `/api/debug/notify_log`、抓线程栈 `/api/debug/dump_threads`、打开应用详情
   `/api/debug/open_app_detail`。后端早有 bridge slot `triggerDebugNotify/triggerNaturalNotify/
   showNotifyProbe`（runtime_shell），但前端无入口——现由调试台 HTTP 路径承载。写动作需
   `X-EYECare-Token`，调试台页面由 `/api/debug/console` 服务端注入 token（占位
   `__EYECARE_DEBUG_TOKEN__`）。debug 路由仅 `is_debug_enabled()` 时注册，故 run_qt_shell 入口
   对 `--debug` 兜底 `os.environ.setdefault("EYECARE_DEBUG","1")`（早于 setup_logging 的首次
   is_debug 缓存）。
4. **debug 不再弹 cmd 黑窗**：`run_debug.bat` 改用 `pythonw.exe`(无控制台) + `start` 立即返回；
   去掉 `EYECARE_DEBUG_CONSOLE=1`/`EYECARE_CONSOLE_LOG=1`（日志改走 debug.log + 调试台）。
   spec 本就 `console=False`，exe 无窗；黑窗只来自 .bat 的 python.exe 控制台。

### QML 迁移 — 进行中（2026-06-12 起）
用户已备份，正式启动迁移。按 `docs/qml_migration_assessment.md` 路线，**第 1 步=notify/rest 浮层试点**。
新增包 `eye_care/qt_quick/`（与旧 web 栈并存，渐进替换）：
- `qml/NotifyOverlay.qml`：原生 QML 复刻 notify 浮层（无边框/置顶/Tool/透明，卡片含圆点+「休息提醒」
  +✕、消息、稍后/立刻休息按钮，opacity Behavior 淡入淡出）。契约：Python 读写 `messageText`/
  `cardVisible`，监听 `actionTriggered(name)`（rest/snooze/dismiss）。
- `notify_overlay.py`：`QmlNotifyOverlay` 宿主——QQmlApplicationEngine 加载 QML、右下角定位
  (400×160, margin 24)、Acrylic（复用 `ui/win_effects.WinEffects.enable_acrylic`, tint 0xBB101826）、
  自动隐藏 QTimer、动作转回调。仅视图宿主，不碰业务。
- `preview.py`：独立预览启动器 `python -m eye_care.qt_quick.preview`（不依赖事件链，单测观感/桥路；
  点按钮在控制台打印动作并重弹，反复测试）。
**约束**：本机无法跑 Qt/QML（开发环境是 Linux 无 E: 盘），迁移走「小步可独立运行 → 用户在 Windows
跑 → 反馈运行期问题 → 迭代」。
**进度**：① ✅ 用户跑 preview 验过观感/亚克力（毛玻璃 OK，与旧版几乎无差）。② ✅ 已接入真实 notify
触发链——`runtime_shell` 新增 `QmlNotifyAdapter`（包 `QmlNotifyOverlay`，暴露与旧 `NotifyOverlayWindow`
一致接口：notify_ready 恒 True/notify_visible/active_prompt_key/active_extra/show_notify/hide_notify）；
`_ensure_notify_window` 默认建 QML 适配器（创建失败兜底回退 web 版），env `EYECARE_NOTIFY_WEB=1` 可强制旧
web 版排障。QML 动作 rest/snooze/dismiss 经 `_on_action` 走与 `notifyWindowAction` 同一业务链：
`normalize_notify_window_action` → `_notify_complete(prompt_key, extra)` →（rest 时）`bridge.showRestOverlay()`。
调试台「触发弹窗」与自然链路均经 `notify_dispatcher.post_notify_show → _handle_notify_task`，故都已换成 QML 版。
③ ✅ rest 全屏遮罩已迁 QML。新增 `qml/RestOverlay.qml`（全屏无边框透明 + Acrylic tint 0x33101826;
极淡暗底 + 居中卡片：休息中/倒计时/提示/「稍后」;全屏 MouseArea 吃掉非稍后点击防穿透;Esc=稍后）
+ `rest_overlay.py`（`QmlRestOverlay` 每屏一实例,墙钟驱动 250ms 刷 timeText,到点自动 complete;
暴露与旧 `RestOverlayWindow` 同名接口 rest_ready 恒 True/rest_started/show_overlay/hide_overlay/isVisible/
screen_idx)。`runtime_shell._ensure_rest_overlays` 默认建 QML 池(失败兜底回退 web),env `EYECARE_REST_WEB=1`
强制旧版。业务收尾 `_qml_rest_finish(reason)` 合并 web 版 snooze/complete + closeRestOverlay 语义:
complete→`controller.rest_complete()`+放提示音、snooze→`controller.rest_snooze()`,随后关全部遮罩 +
`controller.notify_rest_closed()`。show 入口仍统一走 `showRestOverlay→_ensure_rest_overlays`,故 notify
「立刻休息」及其它路径都已换 QML。独立预览 `python -m eye_care.qt_quick.preview_rest`。
④ ✅ 打包已处理：`EyE Care.spec` hiddenimports 增 `PySide6.QtQml`/`PySide6.QtQuick`（触发 PySide6
PyInstaller 钩子收集 QtQuick/QtQml 运行时插件 + qml 模块，含 QtQuick.Effects 的 MultiEffect）及
`eye_care.qt_quick.*`；`.qml` 源随 `('eye_care','eye_care')` 整目录已进包。QML 插件随 PySide6 wheel
提供，requirements 无需加包（仅补注释）。**未在本机验打包**（Linux 无 Qt），首次打包后需确认 QML 起得来。
rest 卡片投影：web `.rest-card` 原有 `box-shadow 0 18px 60px rgba(0,0,0,0.45)`，QML 初版漏了，已用
`layer.effect: MultiEffect{shadowEnabled; shadowColor #73000000; blurMax 48; shadowBlur 1; vOffset 18}` 补回。
notify+rest 两块 web 视图(`ui/web/notify`、`ui/web/rest`)QML 全量替换、稳定后可移除。
**遗留（非本次迁移）**：用户反馈主界面"整体阴影感比以前少了"（web 侧，与 QML 迁移无关），待查 web CSS
box-shadow，用户称稍后细说。

**第 2 步=主仪表盘（2026-06-13 起）。** 2026-06-13 复测日志（user_data/debug.log）再次印证评估诊断：
切图表 Tab 时 renderer RSS 200MB→峰值 4GB，期间 jsHeap 恒 ~10MB（取不到值的占位）、DOM ~1000、
charts=4、listenerDelta 稳定——**JS 层不漏，全是 QtWebEngine 渲染 Chart.js canvas 的原生分配 +
GC 滞后**；RSS 会周期性断崖回落到 ~200-400MB（非无限漏，但峰值危险）。元凶集中在 `categoryTab`/
`appTab`/`calendarBtn`（两张甜甜圈 + 日历），每进一次 +400~700MB。图表实例本身是复用的（缺失才重建，
平时 `chart.update()`），不漏实例。
- 先做**技术选型命门验证**（图表是内存元凶，也是迁移成败关键）：`eye_care/qt_quick/qml/DoughnutStress.qml`
  + `preview_charts.py`，用 QtCharts `PieSeries`（holeSize 0.72 复刻 cutout 72%）高频 churn（每 150ms
  清空+重建 6 片 + 入场动画），独立运行 `python -m eye_care.qt_quick.preview_charts`，盯任务管理器看
  内存是否随重建次数持续增长。**通过=QtCharts 不漏，放心推进；不通过=改 QML Canvas 手绘。**
  → **2026-06-13 验证通过**：250 次重建内存稳在 ~60MB（对比 web 版同等操作 4GB）。QtCharts 选型确定，
  内存问题从架构上根除。`DoughnutStress.qml`/`preview_charts.py` 为一次性验证脚手架（仍可 `run_preview.bat charts` 跑），
  迁移稳定后可删。
- 进行中：左栏复刻预览 `eye_care/qt_quick/qml/LeftPanelPreview.qml` + `preview_left_panel.py`（**mock 数据**）。
  通用启动器 `run_preview.bat [target]`（双击=菜单选择，默认 shell；或带参 shell/dashboard/settings/left/right/rest/charts；
  自动挑装了 PySide6 的解释器，优先 `D:\Python`）。**2026-06-14 整理**：原先一堆 per-target 双击 bat
  （run_shell/dashboard/right/settings/charts_preview.bat）已全部删除，统一并入 `run_preview.bat` 一个（带菜单）。
  **第一版凭印象搭，被用户打回（tab/日历按钮样式不符、饼图"太 tk 风"丢质感、卡片观感差）→ 教训：必须抠
  web 真实 CSS 逐项还原，不能凭记忆近似。** 第二版按真实样式重写：
  - tab 还原：`.tab-active`=底部 2px 蓝下划线+蓝字、`.tab-inactive`=灰字 hover 白（**不是**蓝色填充块，
    第一版做错了）；日/周/月=外圈 border 分段控件，激活项同样下划线+蓝字。
  - 日历/翻页按钮=`.btn-ghost`（透明底 / hover bg-white/10 / 圆角），非独立描边方块。
  - **饼图：QtCharts→Canvas→Qt Quick Shapes（两次迭代）**：`DoughnutChart.qml`。
    · QtCharts 出局：PieSlice 只接受纯色，无法做径向渐变+per-slice 阴影（="太 tk 风"根因之一）。
    · Canvas 版也被打回："还是很 tk、动画也没有"。根因诊断：①Canvas 在 HiDPI 屏(dpr 1.25/2)默认不按
      设备像素放大渲染→边缘发糊(塑料感主因)；②`NumberAnimation on anim` value-source 写法 + 手动 restart
      导致入场动画没跑。
    · **最终=Qt Quick Shapes（矢量 GPU 渲染，天然 HiDPI 锐利）**：每片一个 Shape+ShapePath，`PathAngleArc`
      画环形扇区，`RadialGradient` 原生径向渐变(focal rO*0.07 .95→0.7处.8→外缘.55)，progress 属性驱动
      sweep 扫出 + 整体 Scale 0.92→1 + 淡入(入场动画)，hoverOffset 沿角平分线 Translate+Behavior 缓动。
      切 tab/数据更新重播入场(复刻 web chartViewEnter)。
    · 入场动画改 `NumberAnimation{target;property}` + `Component.onCompleted: start()`，确定会跑。
    · **用户验后两轮微调（已采纳）**：(a) 常态**去掉描边**(strokeWidth 0)——矢量锐利下整圈白边=丑白框，
      靠 `gapDeg` 间隙分隔即可；hover 才上 1.5px 淡白(#47ffffff≈0.28，近似 hoverGlow，Shapes 无 shadow)。
      (b) 入场缓动 OutCubic→**InOutCubic**(加速渐入渐出)。(c) `gapDeg` 1.2°→**0.8°**(锐利下更精致)。
    **QtCharts 内存验证(60MB)的结论仍成立，但主仪表盘饼图最终走 Shapes，既不依赖 QtCharts 也不用 Canvas。**
  - 日历按钮图标：web 是 FontAwesome `fa-calendar-o`，项目只有 woff/woff2(Qt 对 woff 支持不保险)，故 emoji
    📅 被打回后改用**矢量 Rectangle 拼线框日历图标**(`CalBtn`)，不赌字体加载。
  - 应用卡片按 custom.css `.app-list-row` 还原：grid `minmax(0,1fr) 86px 44px`、meter 全圆角 6px 高深底
    `#0B1120`、名 14px/.96 白 + 时长竖排其下、百分比 44px 右对齐。
  - ✅ **饼图观感定稿**(用户："有那味道了")后 → **接数据桥**(2026-06-13)：
    新增 `eye_care/qt_quick/left_panel_bridge.py` `LeftPanelBridge(QObject)`——把 `/api/snapshot` payload
    转成左栏 QML 可直接绑定的 view-model：`pieModel`([{name,value,r,g,b}])、`appList`、`topLines`(Top5)、
    `totalText`/`summaryTitle`/`dateText`，`@Slot` setView(app|category)/setPeriod(day|week|month)/refresh，
    数据变 emit `dataChanged`。**唯一一份转换实现，生产/预览共用，差异只在数据源**(provider(range_key)→dict)：
    预览用 mock snapshot、生产换成调 `SnapshotService.get_snapshot`。颜色/时长 1:1 移植 web：`BASE_PALETTE`
    + FNV-1a `_hash32` + 色相避让 `pickColorAvoidingNear` + 同 key 同色缓存、`format_work_time`。数据选择复刻
    app.js：应用视图 day=vm.daily_usage/range=range_daily_usage(+display_names/app_paths 解析名、strip .exe)、
    分类视图 usage_by_category/range_usage_by_category(key=分类名)；day 总时长优先 today_total_seconds；
    dateLabel 日=今日/日期、周月=MM-DD~MM-DD。
    QML 改为读 contextProperty `leftPanelBridge`(去掉内联 mock/palette)，颜色随每条 r/g/b 取，tab 调
    setView/setPeriod，`Connections.onDataChanged` 重播饼图入场。`preview_left_panel.py` 构造 bridge+mock
    provider 并 setContextProperty。**纯逻辑已在 Linux 用 PySide6.QtCore stub 验过**(_hash32 与 JS 逐位一致、
    format/色相避让/视图周期切换/同 key 跨周期颜色稳定全绿)；QML 绑定仍需 Windows 跑 `run_preview.bat` 验。
  - ✅ **接数据后第一轮尺寸对齐**(2026-06-13，对照 index.html)：① 列表滚动条原是 Controls 默认条(=tk 样式)，
    改 `ThemedScrollBar`(继承 ScrollBar，自定义 contentItem/background)复刻 web `.scrollbar-theme`：8px 细、
    thumb rgba(59,130,246,.45)/hover .7/active(96,165,250,.85)、track rgba(15,23,42,.4) radius4；列表右侧留 16px
    给条。**根因补充(第二轮)**：第一版自定义没生效——`import QtQuick.Controls` 在 Windows 默认走原生 Windows 样式，
    会画原生(tk 样)滚动条且不完全吃自定义 contentItem。修法=改 `import QtQuick.Controls.Basic`(Basic 样式完整
    尊重自定义外观)。**打包 hiddenimports 需含 `PySide6.QtQuick.Controls.Basic`**(不只 Controls)。② 饼图偏小主因=`rOuter` 之前 `-hoverOffset-2`(=-20)把环径砍小一圈→改 `min/2-4`(接近 web radius 95%)、
    hoverOffset 18→14(靠 Item 不裁剪弹进留白，不再为它预留)；盒子 200→216(web md:w-52=208 略放大)、chart row
    spacing 20→24+上下 margin。③ tab 尺寸对齐 web：应用/分类 `px-4 py-2 text-sm`→implicitWidth txt+32/高 36；
    日/周/月 `px-3 py-1.5 text-xs`→txt+24/高 30，激活下划线改满格宽(复刻 border-b-2)。**第二轮**：日/周/月再放大
    (font13/txt+30/高 34，分段框高 34、分隔线 20)；两组 tab 选中态加柔和蓝光阴影(active Text 上挂 `MultiEffect`
    shadowColor #803b82f6/blur .7/vOffset 1，深底上发光比暗影可读)——此为用户偏好，超出 web 原样。
  - **选色查证结论(已确认 1:1)**：web 饼图色=`colorForKeyInContext`(FNV-1a hash%调色板 + `pickColorAvoidingNear`
    色相避让 + 同 key 全局缓存)；径向渐变 `makeRadialGradient` 三段 alpha=**0.95 / base(0.8) / 0.55**。bridge 的
    `_color_for_key` 与 DoughnutChart 的 RadialGradient stops 均已与之逐项对齐，本机 stub 测试通过，无需再改。
  - ✅ **右栏复刻 + 接数据桥**(2026-06-13)：新增 `right_panel_bridge.py` `RightPanelBridge`(同构 Left：唯一转换、
    生产/预览共用、复用 left_panel_bridge 的颜色/时长工具；`__init__` 可传共享 `color_cache`→左右栏跨面板同 app 同色)。
    产出：时段柱状图 view-model(`barLabels`/`barSeries`[{name,r,g,b,values[]}]/`yMax`/`yTicks`[{sec,label}]/`useHours`)、
    `top4`、KPI 文案(`totalText`/`focusText`/`rateText`/`rangeLabel`/`continuousText`/`reminderText`/`durationText`/
    `doneText`/`skipText`)；`setPeriod`/`refresh`。数据契约对照 api/common.py `_timebars_for_day/_range`：
    timebar_values[行][key下标]，keys=top5+「其他」，day=24 小时桶/week=周一~日/month=按日；Y 轴刻度复刻 app.js
    (≥3h 用小时单位否则分钟，step/suggestedMax 同公式)。**KPI 时长格窄**(用户反馈『11小时19分钟』快溢出)→
    今日屏幕时间/最长专注/已连续用眼统一用紧凑 `format_work_time_compact`=『X时X分』(去掉小时/分钟字)，
    任意时长/窗口都不超；完成率本就是『78%』短的。Top4 行较宽，仍用 full `format_work_time`。
    新增 `qml/TimeBarChart.qml`——**矢量 Rectangle 堆叠柱**(非 Canvas，HiDPI 锐利)：Y 轴网格线+刻度、x 标签抽稀、
    每段圆角2+竖向渐变(0.85→0.5)、progress 0→1 从底部生长入场(InOutCubic)；左上角单位标注替代 web 每刻度重复"分钟"。
    `qml/RightPanelPreview.qml`(Window)：上=屏幕时间统计(panel-gradient + panel-inner 图表卡 + Top4)、下=
    dashboard 卡片(4 KPI + 整宽 4 小项，复刻 custom.css `.dashboard-card*`)+ 立刻休息(btn-primary 整宽 46 高/圆角12/
    primary#3b82f6 hover secondary#1e40af)。`preview_right_panel.py`(mock snapshot 含 timebar/stats/rest) 经
    `run_preview.bat eye_care.qt_quick.preview_right_panel` 跑。**纯逻辑已 stub 验过**(刻度/单位切换/maxStack≤yMax/
    series 长度对齐/Top4/KPI 全绿)；QML 渲染待 Windows 验。
  - ✅ **抽成可复用组件 + 合并仪表盘**(2026-06-13)：把两栏内容从各自的 Window 预览抽成 `qml/LeftPanel.qml`/
    `qml/RightPanel.qml`(Item，宿主注入 `property var bridge`；外壳不自带 margin 由宿主控留白；RightPanel 多
    `signal restRequested()` 给「立刻休息」)。`LeftPanelPreview.qml`/`RightPanelPreview.qml` 退化为薄壳 Window
    (内嵌组件 + 注入 contextProperty bridge)。新增 `qml/DashboardPreview.qml`——左右栏并排,复刻 web `<main>`
    `grid-cols-[1.1fr_1fr] gap-3`(Layout.preferredWidth 110/100,spacing 12)；`preview_dashboard.py` 建两个
    bridge **共享同一 color_cache**(→同 app 跨饼图/列表/柱状图/Top4 同色) + 单一 mock provider(复用右栏 mock 再补
    分类聚合/今日总时长)喂两栏。启动：`run_preview.bat dashboard`。**stub 验过**：
    单一 payload 喂两栏、5 个公共 app 跨面板颜色全一致、分类视图、日/周/月联动全绿。
  - ✅ **跨栏联动高亮 + 周期联动**(2026-06-13，用户反馈)：① 周期 bug：日/周/月 tab 只在左栏，原只调左 bridge→
    右栏不动。修：LeftPanel 切周期发 `signal periodSelected(period)`，Dashboard 接住同步 `rightPanelBridge.setPeriod`。
    ② 高亮联动(复刻 web statsHighlightKey，**按 app 名**匹配，pure-QML 无新增 Python)：DoughnutChart 加
    `highlightName`(外部驱动→对应扇区弹出+发光，effectiveIndex=鼠标优先否则名字匹配)+ `signal hovered(name)`
    (onHoveredIndexChanged 外发)；TimeBarChart 加 `highlightName`(非该系列 opacity→0.3)+ 每段 MouseArea
    `hovered(name)`；Left/RightPanel 各 `property highlightKey`(入)/`signal highlight`(出)，饼图/柱状图/应用卡片
    (卡片高亮=蓝调底+蓝描边，复刻 .card-focus)互发；DashboardPreview 用一个 `hlKey` 把两栏串起来；单栏预览自环。
  - ✅ **接生产 step1：真实数据源 + 轮询**(2026-06-13)：新增 `qt_quick/dashboard_data.py`——`make_provider(controller,log)`
    (复用外壳已有 controller，外壳整合用) + `build_readonly_source(data_dir,log)`(新建 `_ReadOnlyController`：
    no-op 掉构造期仅有的两处写副作用——`_apply_exit_state_need_merge` WAL merge、`_load_app_paths` 落盘，
    可与运行中的正式 app 共存只读)。provider(range_key)=`SnapshotService.get_snapshot({"range":rk})`，返回完整
    payload(左右栏共用)。`preview_dashboard.py` 默认**优先真实数据**(env `EYECARE_DATA_DIR` 或 `PROJECT_ROOT/user_data`，
    与正式 app 同目录；无数据/失败回退 mock；`EYECARE_PREVIEW_MOCK=1` 强制 mock) + **10s 轮询**(real 模式开，
    复刻 web SNAPSHOT_POLL_MS)。**动画分离**：bridge 加 `resetAnim` 信号(仅 setView/setPeriod 发)，QML 改成
    `onResetAnim→playEnter`(不再 onDataChanged)，故 10s 轮询只更新数据、不反复重播入场动画。
  - ✅ **接生产 step1 修 bug**(2026-06-13，用户实测)：① QML 报 `Cannot read property X of null`——`bridge` 注入
    存在构造顺序瞬时 null。修：LeftPanel/RightPanel 的 `property var bridge` 改 **`required property var bridge`**
    (required 在子绑定求值前就位)。② 真实数据被回退成 mock——原 `has_data` 探测「今天为空就回退」，但数据文件
    可能是历史某天/今天还没用→误判。修：`_resolve_provider` 改成**只要 controller 构造成功就用真实**(今天空也用，
    可切周/月看历史)，仅目录缺失/构造失败才回退；并打印今日/本周总时长。注：若实测今日+本周都=0，多半是
    `PROJECT_ROOT/user_data` 不是正式 app 实际写入的目录(如跑的是打包 exe，数据在 exe 同级 user_data)→
    用 env `EYECARE_DATA_DIR` 指到真实目录。
  - ✅ **接生产 step1 再修**(2026-06-13，第二次实测：数据其实读到了但显示空)：根因=**默认显示「日=系统今天」，
    而数据是历史某天**(实测系统 06-14、数据在 06-13)→当天空白；且我探测用 `stats_total_seconds`(永远是当天值)
    打日志，误显示「本周=0」。修：① 预览**自动锚定到最近有数据的那天**——`dashboard_data.latest_data_date()`
    扫 `minute_usage/minute-*.jsonl` 取最新日期，`make_provider` 支持 `provider(rk, date)`，预览 `lambda rk: base(rk, anchor)`
    固定锚点，today_str 也设为锚点→日期标签显示「今日」。② app_paths 每次等 2s 超时(×4)——上一版把 `_load_app_paths`
    no-op 掉，漏了置位 `_app_paths_loaded` 事件→`get_app_paths` 反复 2s 超时(启动白等~8s)。修：override 里直接
    `self._app_paths_loaded.set()`(跳过加载，名称走 display_names 兜底)+ `_persist_app_paths` no-op。③ 一条 layout
    告警：tab 行分段控件用了 `anchors.verticalCenter`(布局子项)→改 `Layout.alignment: Qt.AlignVCenter`。
  - ✅ **窗口外壳骨架(step4 准备)**(2026-06-13)：澄清依赖——真正替换 QWebEngine 主窗要 settings/modals/标题栏
    都迁好(step3)，否则会丢掉这些。故先搭**外壳框架**：`qml/AppShell.qml`——无边框 Window(`Qt.FramelessWindowHint`)
    + 自定义标题栏(logo 渐变方块+矢量眼睛、EyE Care/护眼应用/版本、窗口控制 —/▢/✕：hover 白底、关闭红底；
    拖拽=titlebar 铺底 MouseArea `startSystemMove`、双击最大化切换)+ 工具栏(设置/导入/导出/应用设置/黑名单/检查更新
    ghost 按钮，**先发 `signal toolbarAction(name)`**，动作待接)+ 内嵌仪表盘(复用 LeftPanel/RightPanel，含高亮联动
    /周期同步/立刻休息)。`preview_app_shell.py`(复用 preview_dashboard 的 `_resolve_provider` 真实数据+锚定+10s 轮询，
    注入 appVersion=eye_care.version.APP_VERSION)。启动：`run_preview.bat shell`。
    **未做**：工具栏按钮动作(=step3 设置/弹窗)、窗口边缘 resize(frameless 需 startSystemResize，later polish)、
    真正塞进 runtime_shell 替换 web 主窗(step4，待 step3 完成)。
  - ✅ **外壳还原四改**(2026-06-13，用户反馈)：① **星空背景**(原版有，漏了)——`qml/StarField.qml` 复刻
    web `createStars()`：大星45(1.2-3.2px/op.5-.9/闪烁)+中星180+小星320(静态)，随机分布；仅大星 twinkle
    (SequentialAnimation op↔op*0.45，~45 个省性能)；铺在 AppShell 最底。② **工具栏小图标**——`qml/ToolIcon.qml`
    矢量复刻 cog/download/upload/grid(th-large)/ban/refresh(不赌字体/不用 emoji，Shapes 画刷新弧+齿轮)，
    ToolBtn 改 icon+label(px-3/text-xs/icon mr-1.5 间距 6)。③ **tab 样式之前做反了**——按 custom.css(覆盖版)
    重做：应用/分类=`PillTab`(选中浅蓝底 pill radius10 + **白字** + 顶部 2px 蓝条 inset，非下划线蓝字)；
    日/周/月=深色圆角容器(bg rgba(15,23,42,.45)+border-white/10)+`SegCell`(选中浅蓝底+#60A5FA 字+**底部** 2px
    蓝条，无分隔线)。④ **去掉"锚定到昨天"**——`_resolve_provider` 不再锚最近数据日，按正式 app 行为显示**今天**
    (今天空可切周/月看历史)。日历按钮维持现状(用户认可)。
  - ✅ **外壳精修五改**(2026-06-13，用户反馈)：① **背景渐变蓝**(之前纯黑)——`qml/AppBackground.qml`：竖向渐变
    slate-900`#0f172a`→dark-400`#070D19`→`#050a12` + 顶部中央蓝色径向辉光`#1e3a5f@.6`(Shapes RadialGradient) + 星空；
    AppShell 改用它(色值取 tailwind：dark-400/300/200=#070D19/#0B1120/#0F172A)。② **tab 圆角/选中框**(custom.css 复核)：
    QML `clip` 只裁矩形→分段控件首/末格高亮露方角；改用 **Qt6.7+ 逐角圆角**(`topLeftRadius` 等)：SegCell 加 `cellPos`
    (first/mid/last)端格高亮按 rr=9 圆角；PillTab 顶部蓝条加 `topLeftRadius/topRightRadius:10` 跟随 pill。③ **工具栏对齐**：
    bg→dark-300/50`#800B1120`、高 40→46、按钮高 30→34/字 12→13/图标 14、标题栏 bg→dark-300`#0B1120`、标题字 13/11→14/12。
    ④ **日历按钮放大**(跟随日/周/月)：CalBtn 24→28、图标 `scale:1.18`；日期 pill 高 30→34/字 14。⑤ 数据已还原今天(见上)。
    **依赖注意**：逐角圆角需 Qt≥6.7(PySide6 6.11 OK)；打包 hiddenimports 已含 Shapes/Effects/Controls.Basic。
  - ✅ **外壳精修五改·二轮**(2026-06-13，用户反馈)：① **应用/分类→圆按钮组**：PillTab 外再包 rounded-xl(radius12)+
    p-0.5(x/y:2) 圆角容器(bg`#330f172a`+border`#14ffffff`)，两枚 pill(radius10)概念上同心嵌套，整体成圆按钮组(复刻 .view-tabs)。
    ② **最大化按钮方框尺寸不对**：WinBtn 弃字体字形(□/❐ 渲染过小)，改 `kind`(min/max/restore/close)**纯矢量**绘制——
    min=底横线、max=11×11 方框、restore=双层方框、close=两条斜线 X。③ **工具栏文字加粗**：ToolBtn label `font.weight:DemiBold`。
    ④ **导入/导出图标重画**：ToolIcon download/upload 弃旋转矩形拼箭头(歪)，改 Shapes ShapePath(RoundCap/Join)画竖杆+V/^箭头+托盘底线。
    ⑤ **柱状图高亮闪断**：同一柱内纵向滑过相邻段时「旧段发""晚于新段发name」→高亮被清空，移出才恢复。改去掉逐段 MouseArea，
    用**单一顶层 MouseArea + `segAt(mx,my)` 命中测试**(按 x 定柱、按累计高度定段)，`onPositionChanged` 连续报告、`onExited` 清空。
  - ✅ **step3·设置页迁 QML**(2026-06-13)：复刻 web `#settingsModal`。
    - `qml/SettingsPage.qml`：全屏变暗(`#b3000000`)+居中卡片(dark-200`#0F172A` rounded-xl12 p-8 宽460,高随正文自适应+窗口封顶+Flickable 滚动)。
      **控件全自定义**贴暗色主题(不赌原生)：NumField(.input-primary 风格 TextField+IntValidator,失焦/回车 clamp)、Check(自绘方框+Shapes 勾)、
      Select(.input-primary 外观+自绘 Popup 下拉)、FooterBtn(btn-primary/secondary)、ThemedSB(.scrollbar-theme)。
      项目齐 web：无操作暂停(3..300)、开机自启/启动勿扰/启动显主界面、关闭行为(ask/min/quit)、启用休息提醒(开关控休息组显隐)、
      休息间隔(1..600分)、休息时长(数值+秒/分,min 时 *60)、通知显示时长(0..600)、通知提示音、休息结束提示音。
      `required property var bridge`+`open`+`closed()`；打开 load() 填充、应用 applyAndClose() 收集 payload。
    - `settings_bridge.py`：`SettingsBridge(loader,saver)` 暴露 `config` map + `apply(payload)`(`sanitize()` clamp 口径 1:1 复刻 app.js)+`reload()`；
      `build_settings_io(controller,*,persist,log)` 造 (loader,saver)——persist=True(生产)落盘 save_config+on_config_updated+(自启变更)set_launch_at_login；
      persist=False(预览)**沙箱**只 log。`cfg_to_dict` 含 close_action(web get_config 漏返,这里补)。已用 /tmp/pstub 验证 clamp/沙箱/落盘三路。
    - 接线：AppShell「设置」按钮→`settingsPage.open=true`(内嵌 SettingsPage 覆盖层,读 contextProperty `settingsBridge`)；
      `preview_app_shell._build_settings_bridge()` 造桥(真 cfg/默认 AppConfig，恒沙箱)。独立预览 `qml/SettingsPreview.qml`+`preview_settings.py`
      （`run_preview.bat settings`）。
    - **接外壳待办**：step4 把 AppShell 装进 runtime_shell 时,settingsBridge 用 `build_settings_io(shell controller, persist=True)`(真落盘)。
  - ✅ **step3·黑名单页迁 QML**(2026-06-14)：复刻 web `#blacklistModal`(max-w-2xl)。
    - `qml/BlacklistPage.qml`：变暗+卡片(宽 min(parent-48,672)/高 min(parent-48,600))；说明文案 + ListView(panel-inner 行:显示名+app_short+「移除」)
      + 空态「黑名单为空」+「关闭」。移除用**行内二次确认**(移除→确定移除/取消，替代 web confirm 弹窗)。组件 GhostBtn(accent/danger 文字按钮)/FooterBtn/ThemedSB。
    - `blacklist_bridge.py`：`BlacklistBridge(loader,remover)` 暴露 `items`([{appShort,displayName}]) + `remove(appShort)`(**乐观更新**：先删内存列表发信号、再调 remover，
      沙箱预览也能即时反映) + `reload()`。`build_blacklist_io(controller,*,persist,log)`：persist=True 从 cfg.blacklist_apps 删+save_config；False=沙箱只 log。
      口径对齐 StatsService.get_blacklist/remove_from_blacklist。已 /tmp/pstub 验沙箱(cfg 不动)+落盘两路。
    - 接线：AppShell「黑名单」按钮→`blacklistPage.open=true`(读 contextProperty `blacklistBridge`)；`preview_app_shell._build_blacklist_bridge()`
      (真 cfg 空则塞示例 2 条，恒沙箱)。独立预览 `qml/BlacklistPreview.qml`+`preview_blacklist.py`(`run_preview.bat blacklist`)。
    - **接外壳待办**：step4 用 `build_blacklist_io(shell controller, persist=True)`；移除后还需触发左栏刷新(web 移除后 refreshLeftPanelForViewDate)。
  - ✅ **step3·剩余设置/弹窗一口气迁完**(2026-06-14)：应用设置+详情 / 检查更新 / 导入导出选择 / 日历选日期。**后端直接复用
    StatsService/ConfigService**(读操作只读安全；写操作 persist=False 沙箱拦截，exclude_app 破坏性绝不在预览跑)。所有写一律沙箱。
    - **应用设置+详情**：`apps_bridge.py`(`AppsBridge` + `build_apps_io(controller,*,persist,log)`)——`appsList`/`categories`/`detail`
      属性 + `reload/openDetail/saveDetail/addCategory/excludeApp`；`build_apps_io` 包 StatsService(get_apps_list/update_app_settings/
      exclude_app/get_app_details)+ConfigService(get_category_names)。**不在构造期 reload**(get_apps_list 扫 90 天，页面打开再拉，免拖慢启动)。
      `qml/AppSettingsPage.qml`(搜索+应用卡片列表，点→openApp)+`qml/AppDetailPage.qml`(左:24h 柱图 HourlyChart；右:类别下拉(可加新类 Popup+输入)/
      显示名/前台自动勿扰/排除计时(行内二次确认)/取消·应用)。详情 z=110 叠在列表 z=100 上。
    - **检查更新**：`update_bridge.py`(`UpdateBridge` + `build_update_io`)——网络调用放**后台线程**，结果经 `_resultReady` Signal(QueuedConnection)
      回主线程更新 `message`/`busy`/`hasUpdate`/`htmlUrl`；复用 ConfigService.check_update(controller 可为 None)。`qml/UpdatePage.qml`(打开即 check，
      有更新→前往下载+关闭，否则只关闭，含 busy 转圈)。
    - **导入/导出**：`qml/ChoicePage.qml`(通用二选一小窗，无 bridge)——外壳设 title/label1/label2，选择发 `chosen(1|2)`→`root.toolbarAction`
      (exportAll/exportSettings/importAll/importSettings)。**实际文件 IO 属 host，step4 接**(web 是 desktopHostCall)。
    - **日历选日期**：`calendar_bridge.py`(`CalendarBridge` + `build_calendar_io`)——单月网格(周一开头,6x7)+有数据日子标点，
      `prev/next/select/reload` + `monthTitle/cells/selectedDate/weekHeaders`；复用 StatsService.get_calendar_month。`qml/CalendarPage.qml`
      (深蓝渐变主题，选中蓝底/今天蓝框/有数据蓝点)。**左右栏桥加 `setDate(date)`**(锚定日期，provider 按需降级单参/双参)；
      LeftPanel 加 `calendarRequested` 信号(日历按钮触发)；外壳:日历按钮→开 CalendarPage，确定→`left/right.setDate(iso)`。
      ⚠️ web 是双月范围选择，这里按「锚定日 + 日/周/月 tab」模型简化为**单日选择**(周/月由 period tab 决定)。
    - 接线：AppShell 工具栏 设置/黑名单/应用设置/检查更新/导入/导出 + 左栏日历按钮 全部接上对应覆盖层；`preview_app_shell` 用
      `_readonly_controller()`(**构造一次，多桥复用**)建全部桥(真→真后端沙箱；mock→示例数据)，set 7 个 contextProperty。
      **均已 /tmp/pstub 验证桥逻辑**(apps openDetail/save body/exclude 乐观删；update 三态文案+openUrl；calendar 网格/翻月/选中/标点)。
    - **接外壳待办**(step4)：各桥 persist=True 真落盘；ChoicePage 的 exportAll 等接 host 文件对话框；setDate 后日期导航 ◀▶(±1 天，待加)。
  - ✅ **外壳精修·三轮**(2026-06-14，用户 7 点反馈)：① **卡片去渐变改扁平**——左栏 app-list-row / AppSettingsPage /
    BlacklistPage 卡片原是纵向渐变(#99..→#d9..)显凹凸，改单色 `#bf162032`(normal)/`#cc0b1120`(hover)/`#263b82f6`(focus)，
    复刻原版 panel-inner 扁平观感。② **黑名单布局**——卡片不再 fillHeight 撑成大空框：ColumnLayout 锚 top 不 fill、卡片
    `height=body.implicitHeight+64` 跟随内容、ListView `preferredHeight=min(contentHeight, h-300)`、行高 48→44、间距收紧。
    ③ **顶栏星空**——标题栏 `#0B1120`→`#b30B1120`(0.70)、工具栏 0.5→`#730B1120`(0.45)，让 AppBackground 星空透出整条顶栏
    (复刻 web 工具栏 dark-300/50 透星)。④ **左右栏渐变统一**——RightPanel 两块面板原用 `#f2..#fa..` 显右栏顶发黑，改成与
    LeftPanel 同一组 `#26344b→#1c2637→#121a28→#141e2d`(顶亮向下渐深)。⑤ **关闭确认弹窗**——新增 `qml/CloseConfirmPage.qml`
    (复刻 #closeWindowModal：最小化到托盘/退出程序+记住选择)；WinBtn close→`root.requestClose()` 按 `settingsBridge.config.close_action`
    (ask 弹窗/minimize/quit)分流；记住选择→`toolbarAction("closeAction:"+action)` 待 host 持久化。⑥ **左栏卡片点击进详情**——
    LeftPanel 加 `appActivated(key,isCategory)` 信号(行 MouseArea onClicked)；app→`appsBridge.openDetail`+AppDetailPage；
    category→新增 `qml/CategoryDetailPage.qml`(客户端按 category 过滤 appsList，点 app 再进详情)。left_panel_bridge 的 appList
    项补 `key`/`isCategory`；apps_bridge.openDetail 首次进详情若类别未载则补载。⑦ **应用详情图表改逐日**——原是 24h
    HourlyChart(错)，改 `DailyChart`：复刻 web appTimeChart 用 `daily_seconds` 按 range_start..range_end 逐日柱(渐变+柱顶分钟数
    +底端 baseline 分割线+日期标签+空态)；apps_bridge.detail 新增 `daily` 序列(`_daily_series`)，保留 path 显示。
  - ✅ **外壳精修·四轮**(2026-06-14，用户 6 点反馈)：① **窗口默认拉高** 760→880(min 600→680)，左栏应用列表/右栏屏幕时间统计
    各自 fillHeight 自然变高。② **屏幕时间统计 Y 轴单位**——原只在左上角一个"分钟"(丑)，改**每个刻度两行**(数值+「分钟/小时」，
    复刻 web `ticks.callback` 返回 `[String(m),'分钟']`)；`TimeBarChart` 补 `useHours` 属性(原引用未声明=永远"分钟"的 bug)，
    RightPanel 传 `bridge.useHours`；刻度/ x 标签字号 9→11，axisW 30→40。③ **右栏卡片标题字号**——KPI label 11→13(value 18→19,
    卡高 60→64)、SmallCell label 11→13(value 14→15,行卡高 56→60)。④ **应用详情入场动画**——卡片 `scale 0.95→1`(OutCubic)+
    page 渐显；`DailyChart` 加 `progress 0→1` 柱高生长动画，`load()` 调 `playEnter()` 每次打开/换应用重播。⑤ **所有弹窗渐入渐出**——
    9 个覆盖层统一 `visible:opacity>0.01 / opacity:open?1:0 / Behavior on opacity`(170ms)。⑥ **日历范围选择**(复刻 web，原只单选)——
    `calendar_bridge` 加 `_start/_end` 范围态:`select` 先点开始(清结束)→再点结束(早于起点则交换)，新增 `rangeStart/rangeEnd/rangeLabel`
    属性+`reset()`，cells 补 `inRange/rangeStart/rangeEnd` 标记；`CalendarPage` 加范围提示+当前选择+清空按钮，网格画**范围连接带**
    (中间整格/端点半边)，确定发 `pickedRange(start,end)`；外壳:同天→`setDate`，跨天→`setRange`。**左右栏桥加 `setRange(start,end)`**
    (置 `_range`→`_recompute` 走 `provider("custom",None,rs,re)`；切日/周/月或单日选择则清 `_range`)；`make_provider` 的 provider 补
    `range_start/range_end`(SnapshotService 支持 `range="custom"`)。mock provider 不支持范围→TypeError 降级不崩。**均 stub 验证**
    (范围交换/翻月标记；setRange custom 调用、setPeriod/setDate 清范围、旧 mock 降级)。
  - ✅ **前端精修·五轮(2026-06-14，用户改口「你来吧前端都改好」→ 本人全做完)**：
    1. **屏幕时间统计图(`TimeBarChart.qml`)**：`padTop` 8→18(顶部刻度线不再贴边)；刻度数字 11→12 Medium、"分钟"单位 8→10、配色提亮(`#cf`/`#8c`)。
    2. **窗口压扁(`AppShell.qml`)**：height 880→820、minimumHeight 680→620(左栏列表区/右栏统计区随 `fillHeight` 同步压缩)。
    3. **应用详情图(`AppDetailPage.qml` DailyChart 重做)**：加**左侧分钟刻度轴**(niceMax 漂亮上限 + 5 档刻度)+**横向网格线**(`#0dffffff`，同屏幕时间统计图)+左上"分钟"单位；柱顶分钟数 9→11 DemiBold、日期标签 9→11 Medium；柱高改用 `(分钟/niceMax)*plotH` 留顶部余量。**删掉 `Item{Layout.fillHeight:true}` 弹簧**——排除键紧跟「前台自动勿扰」(复刻 web `space-y-4`+`pt-2`，无大间隙)。
    4. **日历(`CalendarPage.qml`)**：标题 16→18 Bold、说明 11→13、范围标签 12→14 DemiBold、清空 13→14、周表头 11→12。
    5. **工具栏(`AppShell.qml` ToolBtn)**：文字 13 DemiBold→15 Bold、ToolIcon `scale 1.28` 放大、按钮 height 34→40、工具栏条 46→52。
    - 验证：四个 QML 文件括号配平 OK、无残留旧引用(`maxV` 已全替)。**待用户 Windows `run_preview.bat shell` 目视确认。**
  - 🔧 **step4 起步·生产装配工厂**(2026-06-14)：新增 `qt_quick/shell_integration.py` —— `build_shell_bridges(controller,*,persist,log,today,color_cache)`
    用**真实 controller** 一次造齐 7 个桥 + provider(`make_provider`)，返回 dict（key 与 AppShell.qml 的 contextProperty 同名，
    已校验完全一致）。预览(persist=False 沙箱)与生产(persist=True 真落盘)共用这一套，差别只在 persist。`preview_app_shell` 已重构：
    有真实 controller → 走工厂(persist=False)，无 → 仍走 mock 示例分支。`CONTEXT_PROPERTY_NAMES` 供接线核对。
  - ✅ **step4 真接外壳·灰度完成**(2026-06-14，`eye_care/qt/runtime_shell.py`)：**完全加法式，默认 web 主窗一行未动**；`EYECARE_QML_SHELL=1` 才走 QML。
    - 实现要点(`_try_create_qml_shell()`，紧邻 `window = MainWindow()` 前)：
      ① **时序**：controller 在服务线程里**先于** Flask 创建(`ui/app_runtime.py` _run：L77 建 controller→L88 回调→L106 才建 Flask)，`wait_flask_ready` 返回时 controller 必非空 → 故在建窗口处同步取 `controller` 即可，无需等回调；None 时 `log.warning` 回退 web。
      ② `QQmlApplicationEngine` 加载 `qml/AppShell.qml`(顶层 `Window`，自带 `visible:true`，**不用** QQuickWidget 嵌入，省掉 DWM/nativeEvent 那套)。桥经 `build_shell_bridges(controller, persist=True)` 装配，`setContextProperty(CONTEXT_PROPERTY_NAMES)`。
      ③ `root.toolbarAction` → 复用**同款 `QtBridgeProbe`** 实例(`host_bridge`，存 `qt_bridge_ref`)的 `exportAll/exportSettings/importAll/importSettings`(内部走 `_create_file_dialog_safe`，**不依赖 web view**)；`closeAction:<x>`→`host_bridge.setCloseAction()`(写 cfg + `_save_config`)。
      ④ AppShell 新增 root 信号 `restRequested()`(右栏「立刻休息」emit)→ host 调 `host_bridge.startRest()`(走 `services.rest.start_rest`)+`showRestOverlay()`(复用 `_ensure_rest_overlays`+`_show_ready_rest_overlays`，rest/notify 仍是独立 web 窗)。
      ⑤ 10s `QTimer` → `left/right.refresh()`。engine/bridges/poll/host_bridge 存 `_qml_refs` 防 GC。
      - **共享函数 QML 兼容补丁(仅这两处)**：`_show_main_window`(`hasattr(window,'page')` 分支：QML 走 `visibility()/show/raise_/requestActivate`)、`_quit_from_tray`(QML 无 `setWindowOpacity`→跳过淡出直接 `_shutdown+app.quit`)。`_fade_in_main_window` 仅 web 触发。
    - 验证：`py_compile runtime_shell.py` OK、AppShell.qml 配平 OK、`refresh()`/probe 各方法存在性已核。
  - ✅ **step4·二轮：托盘原生接线 + shellHost 可靠化**(2026-06-14，用户反馈「看不到托盘 / 立刻休息没反应」)：
    - **根因判断**：① 「立刻休息没反应」≈ Python 连 QML 信号(`root.restRequested.connect`)在目标机不生效；② 「看不到托盘」≈ QML 窗短暂无可见窗口时被 `quitOnLastWindowClosed=True` 顺手退掉。
    - **修法(都用最稳方案)**：
      ① **改用上下文属性桥 `shellHost`**(`_ShellHost(QObject)`：`doToolbarAction(str)/requestRest()/quitApp()`，`setContextProperty` 必须在 `engine.load` 前)。AppShell 新增 `hostReady`(`typeof shellHost!=='undefined'` 守卫，预览无则回退信号)+ `fireToolbar/fireRest/fireQuit` 统一出口；导入导出/关闭确认/立刻休息全改走 `fire*`。信号 connect 仅留兜底。
      ② **`app.setQuitOnLastWindowClosed(False)`**(仅 QML 分支)：托盘应用关最后一窗不退进程；退出统一走 `shellHost.quitApp→_quit_from_tray→_shutdown+app.quit`。
      ③ **托盘原生分支**：`_start_rest_from_tray/_open_settings/_check_update_from_tray` 加 `if _qml_active()` → 休息走 `_qml_start_rest`(=`host_bridge.startRest+showRestOverlay`)、设置/更新走 `_show_main_window+QMetaObject.invokeMethod(root,"openSettings"/"openUpdate")`(AppShell 加 `openSettings/openAppSettings/openBlacklist/openUpdate` 函数)。
      ④ **通知开关实时联动**：`settingsBridge.configChanged` → `_reconcile_notifier()` 按 `cfg.notify_enabled` 起/停 `NotifierService`(web 路径本无此联动，一并补)。设置其余项本就经 SettingsBridge(persist=True) 落盘+`on_config_updated`+`set_launch_at_login` 生效。
    - **仍待**：frameless **resize**(`startSystemResize`)；休息/通知覆盖层目前仍可走 web(已有 `rest_use_qml`/`QmlRestOverlay` 开关，未默认开)。
  - ✅ **step4·三轮：真机实测后修 4 处**(2026-06-14，用户跑 `run_qml_shell.bat` 后反馈)：
    1. **设置改休息时长不生效**：根因 = `SettingsPage.qml` 的 `NumField` 仅 `onEditingFinished` 提交，点「应用」时输入框未失焦→送旧值。改 `onTextChanged` 输入即提交。`settings_bridge` saver(persist=True)加 `[settings] 已落盘` 日志便于核。改完后 `_rest_duration_seconds()` 读 cfg 即新值。
    2. **左栏 ◀▶（上一天/下一天）没接**：`LeftPanel.qml` 两个 `GhostBtn` 原无 `onClicked`。左右桥各加 `@Slot(int) stepDay(delta)`(按当前锚定日期 ±delta 天，清 range)；LeftPanel 加 `signal stepDay(int)`，AppShell `onStepDay` 同步 `leftPanelBridge.stepDay+rightPanelBridge.stepDay`。
    3. **应用卡片图标消失**：QML 一直只画首字母色块，没接真实图标。新增 `shell_integration._build_icon_resolver`(复用 `ConfigService.get_icon` → base64 `data_url`，exe 路径有效时命中 `app_icons/<sha1>.png` 缓存)；`LeftPanelBridge(icon_resolver=...)` 给 appList 项加 `icon`(带 `_icon_cache`，分类项空)；`LeftPanel.qml` 用 `Image{source:modelData.icon}`(`data:` URL，QML 原生支持) + 首字母兜底。预览 mock 路径无 resolver→兜底。
    4. **`rest_lock_immediate` 刷 ERROR**：`startRest` 里锁 web 按钮的 `_run_main_js` 在 QML 无 `.page`。`_run_main_js` 加 `if _qml_active(): return`(静默)。
    - **日志说明**：`DIAG_SM_REJECT | machine=rest_entry_guard ... COOLDOWN_EXPIRE from/to=UNLOCKED` 是后端冷却定时器在已解锁态重复触发的**良性拒绝**(连点立刻休息触发)，非本次改动引入，可忽略。
  - ✅ **step4·四轮：声音开关 + notify 渐隐残影 + apps 图标**(2026-06-14)：
    1. **休息结束提示音关了还响**：`_play_rest_end_sound` 原不查开关(web 靠 JS `__rest_end_sound_enabled` 闸门，QML 直调绕过)。函数开头加 `cfg.rest_end_sound_enabled` 检查。
    2. **通知提示音开了没声音**：`notify_bubble_softer.wav` **全代码库从未被引用**——通知音从没接。新增 `_play_notify_sound()`(gated by `notify_sound_enabled`)，在 `_try_show_pending_notify` 显示通知后调用。
    3. **notify 渐隐黑残影**(老问题复发)：根因 = 亚克力暗底在**窗口**上，`hide_notify` 只淡 `card`(QML 内 Rectangle)、窗口本身不淡 → setVisible(false) 前留暗块。`NotifyOverlay.qml` 给 `Window` 加 `opacity: cardVisible?1:0` + 200ms Behavior(< Python 230ms 后 setVisible(false))，整窗连亚克力一起淡。
    4. **应用设置页卡片图标**：`apps_bridge.build_apps_io` 加 `_icon_for`(复用 `ConfigService.get_icon`，带 `_icon_cache`)，`list()` 给每项注 `icon`；`AppSettingsPage.qml` 卡片改 `Image{source:modelData.icon}`+首字母兜底。
    - **设置各项接口审计**：startup_*/idle/work_minutes/auto_hide/close_action 经 saver 的 `on_config_updated`+`set_launch_at_login` 生效；notify_enabled 三轮已接实时联动；rest_seconds/unit 经 `_rest_duration_seconds` 读 cfg；两个 sound 本轮补齐。全闭环。
  - ✅ **step4·五轮：黑名单图标 / 滚动穿透 / 刻度丢线 / 工具栏白字**(2026-06-14)：
    1. **黑名单卡片图标**：`blacklist_bridge.build_blacklist_io` loader 给每项加 `icon`(`_icon_for` 复用 `ConfigService.get_icon`+缓存)；`BlacklistPage.qml` 加图标块(原本没有头像)。
    2. **浮层背景滚动穿透**：9 个浮层(AppDetail/AppSettings/Blacklist/Calendar/CategoryDetail/Choice/CloseConfirm/Settings/Update)的全屏变暗 MouseArea 加 `onWheel: wheel.accepted=true`，吃掉滚轮，背后 ListView 不再跟滚。弹窗内自身 ListView 仍可滚(在 MouseArea 之上先消费)。
    3. **详情图刻度丢线(如 cmd 缺"2分钟")**：根因 = `Math.round(niceMax*i/4)` 在 niceMax 不被 4 整除时把 2.5→3 丢掉"2"。改为 `niceMax = step*tickCount`，step 取漂亮整数 1/2/5/10(`step = nice(ceil(maxMin/4))`)，刻度 `step*i` 恒为整数等距，不丢线。
    4. **工具栏选项全白**：`AppShell.qml` ToolBtn 文字+ToolIcon tint 常态 `#cbd5e1`→`#ffffff`。
    - **tabby 图标取不到（已修，纠正前一条误判）**：根因不是抽取层限制，而是 `ConfigService.get_icon` 与 web 的 `/api/icon` 路由**两套不对等实现**——`/api/icon` 在 `exe_sha1` 缺失(exe>64MB 触发 sha1 跳过 / 读取受限，如 tabby)时有**临时文件兜底**(照样提取直接返回、不写缓存)，`ConfigService.get_icon` 缺这段→直接 return error。证据：tabby 不在 `icon_index.json`(从未缓存)。**修法**：给 `ConfigService.get_icon` 末尾补与路由一致的 temp 提取兜底。三个图标解析器(左栏/apps/黑名单)都走它，一并受益。
  - ✅ **step4·六轮：无边框拖边缩放 + tabby 图标兜底**(2026-06-14)：
    - **缩放**：`AppShell.qml` 加 `Item{z:200}` 内置 7 个 `ResizeZone`(MouseArea，`onPressed: root.startSystemResize(edges)`)——四边+左上/左下/右下角；顶边让出右侧 150px、右边缘 topMargin 36，避开窗口控制按钮；右上角不放。QML 原生 `startSystemResize`，与已用的 `startSystemMove` 同族。
    - tabby 图标兜底见上一条(ConfigService.get_icon temp 兜底)。
    - **迁移收尾状态**：QML 模式(`EYECARE_QML_SHELL=1`)下功能全齐、零 QWebEngine 窗口、可缩放。**唯一剩余 = 决策项**：把 QML 设默认(翻 `EYECARE_QML_SHELL` 默认值) + 退役 2000 行 web 主窗代码 + 去 QtWebEngine 依赖。建议多跑几天确认无回归再翻默认、最后删码。
  - ✅ **step4·七轮：历史文件清理 + 构建检查 + 使用手册**(2026-06-14)：
    - **删除脚手架**：9 个 `preview_*.py` + 6 个 `*Preview.qml`/`DoughnutStress.qml`（迁移期 dev 预览，生产零引用，多为未跟踪→rm）+ `check_css.py`（dev 一次性、硬编码外部路径，git rm -f）。
    - **bat 整合**：删 `run_preview.bat`(预览启动器) + `run_debug.bat`(旧 web 调试)；**唯一运行入口 = `run_qml_shell.bat`**(=QML 外壳 + `--debug` + `--no-single`，可见控制台；`run_qml_shell.bat web` 切旧 web 对比)。保留 `install_deps.bat`/`clear_pycache.bat`/`build_exe.bat`。
    - **构建检查**：`EyE Care.spec` 正常（整包打 `eye_care/` 含 `qml/`，hiddenimports 含 QtQml/QtQuick/notify_overlay/rest_overlay）。**发现 `version_info.txt` 缺失**(spec/build_exe 必需，曾在 commit `ec9c0e1` 被删且未跟踪)→ 已从 `ec9c0e1~1` 恢复到工作区(未重新 git add，按需提交)。`webview` hiddenimport 待退役 web 壳后再去。
    - **使用手册**：新增 `docs/使用手册.md`(面向最终用户，随 spec 的 `('docs','docs')` 打包进 dist)。
    - 清理了留存文件里指向已删 preview 的注释/docstring(`__init__`/shell_integration/left_panel_bridge/rest_overlay/LeftPanel.qml/AppShell.qml)。全包 `py_compile` 通过。
  - ✅ **step4·八轮：偶发"重绘只剩一条"闪烁**(2026-06-14)：
    - **排查结论**：数据无丢失——repo `get_daily_usage/get_hourly_usage/get_usage_range` 全在 `self._lock` 内、返回 `dict(...)` 拷贝；debug.log 无并发异常/`provider failed`。属 **QML 视图瞬态**：10s 轮询每拍把 `appList/pieModel/barSeries/top4/yTicks` 等 QVariantList 整体替换 → 绑定的 ListView/Repeater 整体拆建 delegate，极少帧被捕捉到中途 = "只剩一条"，下拍自愈。
    - **修法(零风险)**：渲染结果**可见内容不变就不换对象/不发信号**。**关键坑**：比较签名必须**排除原始秒数**——`modelData.sec` 在左栏列表/`barSeries.values` 是每拍都涨的原始秒，若纳入比较则跳过永不命中(等于没修)。
      - `left_panel_bridge`：`_render` 末尾算可见签名 `sig=(每项(name,dur,round(pct),icon)+总时长文案+标题+日期)`，与 `self._render_sig` 相等则 `return`(不 emit)；不含 sec(列表不用它，饼图角度按 1% 粒度足够)。
      - `right_panel_bridge`：KPI 文本每拍要变不能整体跳过，故只在**可见内容**真变时才换对象——`bar_series` 按**分钟粒度**签名 `(name,rgb,tuple(v//60))` 比较、`top4`/`y_ticks` 全等比较；KPI 照常 emit，但 barSeries 保持同一对象 → TimeBarChart Repeater 不重建。
      - 效果：重建从"每 10s"降到"仅跨分钟/换序/增减项时"(约 6×↓)，闪烁概率随之骤降。
    - **根因补充(用户实测)**：抖动只在**启动后 ~10s 第一次刷新**那一拍出现一次(应用路径/显示名异步加载完成→列表内容首次真变→模型整体替换→Repeater/ListView 拆建 delegate→闪一帧)，之后被签名跳过挡住。
    - **根治(对齐原版 Chart.js `.update()` 的原地更新思路)**：原版饼/柱图用 `chart.update()` 原地刷新、从不销毁;QML 里 **TimeBarChart 本就是"按数量计 Repeater + 索引读值"**(不重建)，但 **DoughnutChart 饼图 Repeater 绑数组 `root.segments`、左栏 ListView 绑数组 `appList`** → 一换就整体重建 = 抖动源。已改为：
      - `DoughnutChart`：`Repeater{ model: root.segments.length }` + `readonly property var modelData: root.segments[index]` → 扇区数不变时 segments 换新数组只重算绑定(角度/颜色)、不销毁 Shape。
      - `LeftPanel` 列表：`ListView{ model: panel.bridge.appCount }`(新增 `appCount` 属性) + 委托 `modelData: appList[index]` → 条数不变时刷新不重置、行原地更新。
      - 仅当**条数变化**(增删应用)才重建一次，属罕见且可接受。top4/topLines(4-5 项)暂留。
    - 上面的"签名跳过"仍保留(减少无谓 emit)，与原地更新叠加。
  - 🐛 **bug：切日期回今天 → 满屏 `Cannot read property X of null`(panel.bridge 全 null) + 列表只剩 1 卡片**(2026-06-14)：
    - **根因**：PySide6 QML 对象所有权——桥虽被 Python(`_qml_refs`)持有，但作为 `panel.bridge` 属性值暴露给 QML 后被标 JavaScriptOwnership；某次交互(开日历分配大量 JS 对象)触发 QML 的 JS GC 时**误回收桥对象** → `panel.bridge` 变 null，所有绑定报 null、ListView 卡死残留。(`STOP_TICK_JOIN` 是上次退出噪声，非本因。)
    - **修法**：`_try_create_qml_shell` 里对每个桥 + shell_host 显式 `QQmlEngine.setObjectOwnership(obj, CppOwnership)`(provider 是函数，isinstance 守卫跳过)——告诉 QML 这些归 Python 管、永不 GC。+ 保险：`LeftPanel` ListView `model`/delegate 加 `panel.bridge ?` null 守卫。
    - **经验**：凡 Python 建的 QObject 经 setContextProperty/属性暴露给 QML，都应设 `CppOwnership`，否则 JS GC 可能回收导致间歇性 null。
  - ✅ **bug 终极真因：日历"切回今天"只剩 1 卡片(repo 缓存淘汰丢实时数据)**(2026-06-15，靠 `left.render` 诊断日志锁定)：
    - **证据**：日志显示同一 `date=今天` 的 `items` 在 **1↔3↔4 反复跳**(非范围、非数据自然增长)。
    - **根因**(`data/json_wal_repo.py`)：`add_usage` 只把今天用量累积进**内存 `_daily_cache`**(不写文件)；`_load_day_into_cache` 重载时**先清空再只从磁盘 minute+WAL 文件重建**(漏掉内存里未落盘的增量+当前未结算分钟)；`_load` 仅在某天**不在缓存**(被淘汰)时触发。`MAX_CACHE_DAYS=7`，但**打开日历 `get_calendar_month` 逐日加载整月(~30 天)撑爆缓存 → 今天被 LRU 淘汰** → 关日历后读今天触发**部分重载** → 应用数塌成 1，之后 add_usage 再慢慢长回 → 解释反复跳。
    - **修法**：`_evict_oldest_day` **绝不淘汰今天**(改为找最旧的非今天日子淘汰；只剩今天则停)。今天的实时 daily 缓存永不被磁盘重载冲掉。已模拟验证：加载整月后今天仍在缓存。
    - 附带：`CalendarBridge.reload` 补全遗留半选(防"上次选 X→这次点今天"被当成范围)；`left.render` INFO 诊断日志暂留(确认后可删)。
  - 🛈 **前一轮误判记录**：曾以为是 ① 签名比较含原始秒数 ② PySide JS GC 回收桥(CppOwnership) ③ 日历范围记忆——前两项是有效的健壮性改进保留，但都不是本 bug 真因；`Cannot read property of null` 经确认是**退出时**关机噪声(无害)。
  - 🐛 **(旧)日历"切回今天"分析**(2026-06-14，部分作废)：
    - 上一条的 `Cannot read property X of null` 经用户确认是**退出时**的关机噪声(桥销毁、QML 未拆)→ 无害，非本因。CppOwnership 仍保留(防 JS GC，正确)。
    - **真因 = 日历范围选择有"记忆"**：CalendarBridge `__init__` start=end=今天(完整对)。① 开日历选别的天→`select` 走"新起点"分支→start=other,end=**None**(半选)，OK→setDate(other)✓，但残留 end=None。② 再开选今天→因 end=None(不完整)→走"补结束"分支→变成**范围 other→今天**→OK 走 `setRange` 而非 setDate→触发跨天查询→显示非今天数据(看着像"只剩1卡")。
    - **修法**：`reload()`(每次打开日历调)里把遗留半选补全 `if start and not end: end=start`→新点选从完整态开始→单击=单日。已用状态机复刻验证：修后两次单击都→setDate。
    - 另加 `left.render` INFO 诊断日志(view/period/range/date/items)便于后续核查。
    - ⚠️ **测试入口**：托盘/休息/设置落盘只在**真应用**生效。`preview_app_shell`(`run_preview.bat shell`)是**沙箱**(无托盘/无休息/设置不落盘，日志带「预览沙箱」)——永远测不到这些。测真功能用新建的 **`run_qml_shell.bat`**(=`main.py --host qt --debug --no-single` + `EYECARE_QML_SHELL=1`，可见控制台+日志)；`run_qml_shell.bat web` 跑旧 web 外壳对比。真应用日志关键字：`qt.qml_shell.*` / `qt.tray.*`。
  - 待办：① 用户 Windows 验证外壳(`run_preview.bat shell`)：背景渐变蓝+星空、tab 圆角无露方角、工具栏图标/字号、
    日历按钮大小、标题栏拖拽缩放；
    及合并仪表盘(`run_preview.bat dashboard`)真实数据/10s 刷新/联动；② ~~**step3**~~ ✅ **全部迁完**(设置/黑名单/应用设置+详情/
    检查更新/导入导出/日历)——待用户 Windows 验 `run_preview.bat shell` 走一遍工具栏每个按钮 + 左栏日历；
    ③ 日期导航 ◀▶(±1 天，setDate 已就绪，按钮事件待接)；
    ③ **接外壳**——把 DashboardPreview 等价物用 QQmlApplicationEngine 加载进 `runtime_shell` 替换/并存 QWebEngine
    主窗(provider 用 `make_provider(外壳 controller)`、「立刻休息」`restRequested`→`showRestOverlay`、参照 notify/rest
    适配器 env 兜底套路)。下面这条历史待办的 ③④ 已细化到这里。【历史细节↓】③ **接生产**——mock provider 换成真
    `SnapshotService.get_snapshot`(已确认 `AppController(data_dir)`+repo 构造只读无副作用、无线程/锁，可安全在
    预览里用真实数据)、10s 轮询调 refresh、「立刻休息」接 `showRestOverlay`；④ **接外壳**——`runtime_shell.py`
    现以 QWebEngine 托管主窗,需用 QQmlApplicationEngine 加载 DashboardPreview(或等价) 替换/并存(参照 notify/rest
    适配器 env 兜底套路)。（高亮联动已完成，见上。）
- 打包：主仪表盘真正用上时，`EyE Care.spec` hiddenimports 需补 `PySide6.QtQuick.Controls` +
  **`PySide6.QtQuick.Controls.Basic`**（ScrollBar，且强制 Basic 样式才吃自定义外观）、`PySide6.QtQuick.Shapes`
  （饼图）、`PySide6.QtQuick.Effects`（选中 tab 阴影 MultiEffect）。饼图走 Shapes，**不再需要 QtCharts**
  （`DoughnutStress`/`preview_charts` 仅一次性验证脚手架，可删）。

  - ✅ **剥离旧版代码（2026-06-15，用户「代码备份好了，开始剥离」）**：QML 已稳定，正式退役整套 web/Flask 栈。
    - **runtime_shell.py 重写**（2307→~900 行）：删 `MainWindow`(QWebEngineView 主窗)、web 版 `RestOverlayWindow`/
      `NotifyOverlayWindow`/`LoggingWebPage`、三段 `*_bridge_script`/`probe_script`(QWebChannel 引导 JS)、`QtBridgeProbe`
      的 ~25 个 web 数据/窗控 slot。`EYECARE_QML_SHELL` 门控去掉——QML 成唯一路径，无 web 回退。`QtBridgeProbe`
      瘦身为 `QtHostBridge`(只剩 export/import×4 + setCloseAction + startRest + showRestOverlay)。`_ensure_notify_window`/
      `_ensure_rest_overlays` 去掉 web 兜底分支。`_show_main_window`/`_quit_from_tray`/托盘动作去掉 web/QML 二分支。
    - **启动解耦 Flask**：不再起 `start_backend_services`+Flask；controller 改为**主线程同步创建**(start() 自带后台线程，很快返回)，
      随后直接装配 QML。debug 控制台(Flask `/api/debug/console`)随之移除。
    - **删除文件**：`eye_care/ui/web/`(20MB SPA)、`web_routes.py`、`page_delivery.py`、`window_runtime.py`、`window_api.py`、
      `app_runtime.py`、`desktop_integrations.py`、`bootstrap/bridge_inject.py`、`api/server.py`、`api/auth.py`、`api/routes/`(整目录)、
      `diagnostics/perf_sampler.py`(WebEngine 子进程采样)。**保留 `api/common.py`**(纯数据助手，services 依赖) + `api/__init__.py`。
    - **抽出/迁移**：`_create_file_dialog_safe`(tkinter 文件对话框) 从 window_api 抽到新 `eye_care/ui/file_dialog.py`；
      两个 `.wav` 从 `ui/web/assets/` 迁到 `eye_care/assets/`，constants 新增 `ASSETS_DIR`(去掉 `UI_WEB_DIR`/`UI_INDEX_PATH`/
      `ENABLE_DRAG_REGION_INJECT`/`HEALTH_*`)。`json_wal_repo` 去掉对 `api.routes.stats._invalidate_app_details_cache` 的
      失效调用(目标随 Flask 删除，本就 try/except ImportError no-op)。
    - **依赖/构建**：`dpi_console.configure_webengine_flags` 删除；`main.py` 去掉 `--no-ui --api-port` 的 Flask 分支、`--api-port` 参数、
      `DEFAULT_API_PORT` import(常量保留供注释)。`requirements.txt` 去 flask 全家桶 + 全代码库未引用的 win10toast。
      `EyE Care.spec` 去 `webview`/QtWebEngine* hiddenimports，补 `QtQuickControls2`(Pillow 仍未显式列入 requirements，沿用原状)。`run_qml_shell.bat` 去掉 `EYECARE_QML_SHELL`
      与 `web` 对比模式。`使用手册.md` 去掉 web 对比说明。
    - **验证**：全包 `compileall` 通过；10 个后端关键模块(含 runtime_shell)在 **Linux 无 PySide6** 环境 import 全绿(证明顶层无
      QWebEngine/Flask 残留依赖)。**QML 渲染/运行期仍需用户 Windows `run_qml_shell.bat` 实测**(本机不能跑 Qt)。
    - `left.render` 诊断日志从 `log.info` **降级为 `log.debug`**(不再刷正常日志，`--debug` 仍可见)。
  - ✅ **纯净打包准备(2026-06-15，第二次备份后)**：
    - **spec 瘦身**：`datas` 从 `('eye_care','eye_care')`(整源码树 + `__pycache__`，~冗余) 改为**只打按路径加载的资源**——
      `('eye_care/qt_quick/qml',...)` + `('eye_care/assets',...)`(声音)。Python 代码已编译进 PYZ，不必再带源码。
      `docs` 只打 `使用手册.md`(不带 ARCHITECTURE/DATA_AND_API 等开发文档)；去掉 `requirements.txt` 数据项。
      `hiddenimports` 显式补全 7 个桥 + shell_integration + dashboard_data(多为函数内延迟 import，保险被收进 PYZ)。
    - **qml 双路径**：notify/rest 浮层经 `__file__` 相对(→ `_internal/eye_care/qt_quick/qml`)，AppShell 经 `PROJECT_ROOT`(→外层)；
      datas 落 `_internal`，外层副本由 `build_exe.bat` 的 `xcopy _internal\eye_care → 外层` 复制。两路径都有 qml。
    - **build_exe.bat**：打包前先清 `__pycache__`；外层只复制 eye_care(现仅 qml+assets)/docs(仅手册)/icon/README，
      **不再往 dist 塞 install_deps.bat 与 requirements.txt**(独立 exe 用不到)。
    - 已核：spec 语法 OK(忽略 BOM)、7 个 datas 资源路径全部存在、QML 零 file-based 图片/字体引用、无 importlib 动态导入。
    - **删 `tests/` + `pytest.ini`**：`tests/hang_scenarios/` 全部经 Flask HTTP(`/api/health`/`/api/config`/`/api/debug/notify`/
      `/api/auth/token`)驱动真实 app——Flask 随迁移删除后这些端点全没了，测试 100% 失效且只能 Windows GUI 跑，故移除。
      `pytest.ini` 仅为这些 hang_scenario marker 存在，一并删。`diagnostics/notify_hang_analyzer.py` +
      `tools/notify_hang_detector.py`(独立 debug.log 分析 CLI)保留，但其 `flask_timeout_count` 指标已失去意义。
    - **bat 收进 `scripts/`**：build_exe / run_qml_shell / install_deps / clear_pycache 四个移入 `scripts/`，
      每个开头 `cd /d "%~dp0.."` 回到项目根再跑（build_exe 的 `DISTDIR=%CD%\dist\...`、clear_pycache 的 `ROOT=%CD%`）。
    - **version_info.txt**：是**构建期** PE 版本资源（spec `EXE(version=...)` 嵌进 exe 属性：FileVersion 1.0.3 等），
      非运行期资源 → 从 `datas` 移除（文件仍留根目录供构建；运行期版本号读 `eye_care/version.py`）。两处版本号(它 + version.py)发版都要改。
    - **使用手册位置修正**：`使用手册.md` 实际在**项目根**(spec 却写 `docs/使用手册.md`)→ 移进 `docs/`，手册内 bat 引用改 `scripts\`。
    - **README 重写**：原内容描述 web/Flask/pywebview/`--host legacy`/已删 tests，全过时 → 按 QML-only 现状重写(结构/参数/打包)。
    - 根目录现状(整洁)：`CLAUDE.md docs/ eye_care/ EyE Care.spec icon.ico icon.png main.py README.md requirements.txt scripts/ user_data/ version_info.txt`。

### 构建工具链
#### 版本号单一真源 + menu.bat（2026-07-29，用户："以后不用手动维护 version_info.txt"）
- **真源 = `eye_care/version.py` 的 `APP_VERSION`**；`version_info.txt`（PyInstaller 写进 exe「属性→详细信息」的
  构建期输入）改为**生成物，勿手改**。生成器 `scripts/sync_version.py`：
  `python scripts/sync_version.py [X.Y.Z]`（带参=改版本再生成，不带参=按现值重新生成，`--show`=只打印）。
  版本号接受 `1.4` / `1.4.0` / `1.4.0.2`（自动补零到四段），拒绝 `1.4.0-beta` 等非纯数字段。
- **顺带修掉一个真 bug**：`APP_VERSION` 原为 `"1.3"`（两段），而 `api/common._parse_semver` 只认
  `^\d+\.\d+\.\d+` → 解析成 `(0,0,0)` → **检查更新永远显示"有新版本"**。故 `app_version_str()` 强制写满三段，
  现为 `"1.3.0"`；测试里锁死"仓库版本号必须三段 + 两个文件必须同步"（漏跑同步会直接测试失败）。
- **入口 `menu.bat`（项目根，双击运行）= 纯 ASCII shim + `scripts/menu.py`（中文界面全在这里）**。
  菜单：[1] 修改版本号 [2] 打包 exe（可顺便改版本，打包前必同步）[3] 清理 dist/build/__pycache__。
- **⚠️ 血的教训：.bat 里一个非 ASCII 字节都不能有，注释里也不行。**
  cmd.exe 按字节块读文件、却按字符数重新定位，中文会让解析位置错乱：行被从中间截断、尾巴当命令执行。
  中间做过一版「UTF-8 不带 BOM + `chcp 65001` + 中文只写 echo 里 + 不放进 `()` 块」的纯中文 .bat，
  **用户日文（CP932）环境实测直接炸**：
  `'ASCII縲・REM' は、内部コマンドまたは外部コマンド... として認識されていません。`
  ——那个碎片来自一行 **REM 注释**的中间。所以"中文只放 echo""不放 () 块"这类规避规则**全是错的**，
  `chcp 65001` 也修不好（它只改控制台代码页，改不了 cmd 读文件的定位逻辑）。唯一可靠解法 = .bat 纯 ASCII，
  中文搬进按真正 Unicode 解析源码的脚本。Video 2 Knowledge 的 menu.bat 就是这么干的（它交给 PowerShell；
  本项目用户不要 PowerShell，改交给 Python——打包本就依赖 Python，且逻辑能写单测）。
  `menu.bat` 只设 `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`（CP932 控制台下 print 中文会 UnicodeEncodeError）+
  找解释器 + 转发；`menu.py` 里再 `stream.reconfigure(encoding="utf-8")` 兜一层。
  **护栏**：`tests/test_bat_encoding.py` 断言 menu.bat / build_exe.bat / clear_pycache.bat 零非 ASCII 字节、无 BOM、
  goto 目标齐全——以后谁往这些 .bat 里塞中文，测试立刻红。
- **同轮把另外两个含中文的 .bat 也改成纯 ASCII**（2026-07-29，用户："都修一下"）：
  `install_deps.bat`（原 204 个非 ASCII 字节，中文还在 `( )` 块里）、`run_qml_shell.bat`（原 249 个，中文在 REM 头）。
  两者提示改英文，与本就是纯 ASCII 的 `build_exe.bat`/`clear_pycache.bat` 一致。顺带：
  ① install_deps 原来只认 `venv\` 或写死的 `D:\Python\python.exe`，现改成与 menu.bat 同一套候选顺序
  （venv → .venv → D:\Python → PATH python → py），且流程改 `:label`+`goto`（原来 `set` 在 `( )` 块里，是延迟展开的经典坑）；
  ② 两者都补 `PYTHONIOENCODING=utf-8`（原先只有 `PYTHONUTF8=1`，CP932 控制台下打中文日志仍可能 UnicodeEncodeError）。
  **护栏范围已扩到项目内全部 .bat**（`tests/test_bat_encoding.py` 用 glob 自动发现根目录 + scripts\ 下的 .bat，
  新加的自动纳入；另有一条断言确保 glob 不会因目录变动空转）。已做反向验证：往任一 .bat 塞一个中文字符，
  测试立即失败并指出文件、行号、字节值。
- **打包实现只有 `scripts/build_exe.bat` 一份**，menu.bat 的 [2] 只是 `call` 转发（早期 ps1 版把打包逻辑抄了第二份，
  是维护隐患，已消除）；清理复用 `clear_pycache.bat`。`build_exe.bat` 打包前也调一次 `sync_version.py`
  （不再检查 version_info.txt 是否存在——它现在是生成的），保证绕过菜单直接打包同样不会版本漂移。
- 测试 149 → 170（新增 `tests/test_sync_version.py` 21 个：格式解析/渲染内容/只替换赋值行/tmpdir 往返/
  仓库两文件同步自检）。

### 功能新增
#### 全屏勿扰 + notify 置顶修复（2026-06-24，用户主诉）
- **notify 气泡被遮**：`NotifyOverlay.qml` 本就有 `Qt.WindowStaysOnTopHint`，但它只压普通窗口；同处 topmost band
  的另一个置顶窗口（无边框全屏应用 / 别家置顶提示）可能排在其上。修：`notify_overlay.py` 新增 `_raise_topmost()`——
  每次 `show_notify` 弹出时先 `raise_()` 再 Win32 `SetWindowPos(HWND_TOPMOST, …, SWP_NOACTIVATE)` 重新抢占 band 顶部，
  `NOACTIVATE` 不抢焦点。失败静默降级（非 Windows 不受影响）。**DirectX 独占全屏游戏**合成器层盖一切 topmost——靠下面的全屏勿扰直接不弹兜底。
- **全屏勿扰**：沿用既有「M4 自动勿扰（指定 app 前台→勿扰）」范式新增一条平行触发（`dnd_reason="auto_fullscreen"`）。
  - 检测：`probes/win_fullscreen.py`（+ 跨平台入口 `probes/fullscreen.py`，非 Win 恒 False）——前台窗口矩形完整覆盖所在显示器
    (rcMonitor，含任务栏)即判全屏。**排除**桌面/Shell 类名(Progman/WorkerW/Shell_TrayWnd 等) + **本进程自身窗口**(休息全屏遮罩/
    最大化主窗，按 pid==os.getpid())。「最大化≠全屏」(最大化尊重 rcWork、不盖任务栏)。
  - 控制器：`app_controller._tick_loop` 在 M4 块后加 `auto_fullscreen` 块——进全屏→进勿扰(记进入前模式)，退全屏/关开关→恢复。
    **只管自身 reason**，手动勿扰(reason=manual)/app 自动勿扰(先行、优先)互不干扰；退出时若休息已到清 `_rest_notified`/
    `_rest_next_prompt_work_s` 允许立即重提醒(与 app 勿扰一致)。`_current_mode()` 只看 is_dnd→托盘/UI 自动显示「勿扰」，无需改。
  - 配置：`AppConfig.fullscreen_dnd: bool=True`（**默认开启**），打通 `settings_bridge`(keys/sanitize bool/cfg_to_dict 兜底 True)+`config_service`(get/update)。
    缺省口径默认开：QML load `c.fullscreen_dnd !== false`、各 getattr 兜底 True——老配置文件无此键时也按开启。
  - 设置页：`SettingsPage.qml`「关闭行为」分割线下方加 **「全屏时自动勿扰」** 开关 + 说明(property/load/_buildPayload 同步)。
- **遗留约束**：本机 Linux 无 Qt，7 个改动 .py 仅过 `py_compile`；**运行期需 Windows 实测**——①全屏游戏/视频时托盘切勿扰、退出恢复；
  ②notify 能压过其它置顶窗口。`set_dnd`(仅 rest_service 调，未清 dnd_reason)的既有口径未变，UI/托盘走 `set_run_mode`(清 reason)无回归。

#### 浏览器 domain 统计（2026-07-19，新功能，多代理协作实现）
- **功能**：左栏新增「浏览器」第三页签（与应用/分类并列）——前台是浏览器时经 **UIA 读地址栏 URL → 立即提取 domain**
  （隐私：完整 URL 只存在于 worker 线程调用栈内，不落任何持久层/日志含 debug 级），按 domain 累计秒数，
  复用左栏饼图/列表/配色/Top10 管线展示 + domain favicon。设置页新增「记录浏览器数据（仅域名）」开关
  `record_browser_enabled`（**默认关**，开启才显示页签并采集；关闭后已有数据保留）。
- **设计决策**（用户拍板）：domain 保留子域仅剥一层 `www.`；favicon 从站点自身抓（`/favicon.ico`→HTML `<link rel=icon>`，
  urllib 无新网络依赖）；拿不到 URL 的秒**丢弃**不计入 domain 维度（app 维度照常）→ 浏览器视图总时长 ≤ 应用视图浏览器时长属预期；
  Firefox best-effort，Chromium 系（chrome/msedge/brave/vivaldi/opera）为主目标。
- **采集**：`probes/win_browser_url.py` `BrowserUrlWatcher`（comtypes 手写 UIA，COM 全延迟到 daemon worker 线程内，
  MTA）——定位 `FindFirst(Descendants, ControlType==Edit(50004) AND IsValuePatternAvailable)` 读 ValueValue(30045)，
  不依赖本地化 Name；地址栏有键盘焦点=正在输入→跳过采样；inactive 零 UIA 调用、active 2s 采样、按 hwnd 缓存 Edit 元素、
  同 hwnd 连续 3 次失败降频 10s。`probes/browser_url.py` 跨平台入口：非 Windows/无 comtypes → no-op watcher。
  controller：`_maybe_record_domain(fg_short, sec_add, now_utc)`（在 `_tick_loop` add_usage 块内调用，与黑名单门控天然一致；
  tick 每拍先 `set_active(False)` 再按需置 True，防休息/空闲残留 active）。浏览器判定用 `BROWSER_APP_SHORTS` 精确匹配
  （utils/url_domain.py，勿用 `_cat_of` 子串匹配）。
- **domain 提取**：`utils/url_domain.py` `extract_domain`（纯函数）——拒空白/非 http(s) scheme（chrome:// about: 等）/
  无点裸词（搜索词）；无 scheme 补 `//` 再 urlsplit；去端口/userinfo/尾点、剥一层 www.；IPv4 允许、localhost 拒。
- **存储**：平行 JSONL——主 `user_data/minute_domains/domains-YYYY-MM-DD.jsonl` + WAL 同名（schema `domain_minute@1`,
  `{"domains":{domain:sec}}`）。`_merge_minute_row_into`/`_merge_one_type` 已**参数化 field/schema**（原硬编码 "apps"/"minute@1"，
  不参数化会 merge 丢 domains）。独立分钟累加器/`_domain_daily_cache`（并入 LRU 淘汰，今天永不淘汰）/惰性 mkdir
  （从未开启则目录不存在、读返回 {} 零开销）。重开进程时若目录存在则预载今天 domain 缓存（防重启后累加覆盖已落盘数据，
  与 app 维度同理）。API：`DomainDelta` + `add_domain_usage/get_daily_domain_usage/get_domain_usage_range`。
- **favicon**：`services/favicon_service.py` `FaviconService`——单 worker daemon 线程 + 队列去重；urllib timeout 4s/
  限读 512KB，失败解析首页 `<link rel=icon>`；ICO→PNG 用 **QImage**（worker 线程严禁 QPixmap），64px 落
  `user_data/domain_icons/<sha1>.png` + icon_index.json；**负缓存** `next_retry_ts=now+min(6h×fail_count,7天)`；
  QImage/PySide6 import 全在函数内（Linux 无 Qt 可 import 本模块）。失败兜底=QML 首字母圆块（现成）。
- **展示**：snapshot 增 `record_browser_enabled`/`browser_domains`/`range_browser_domains`（关=零 repo 调用）；
  left_panel_bridge `setView("browser")` 三值、`browserEnabled` Property、browser 分支复用渲染管线（项带 `isDomain`）、
  `_domain_icon_for`（同 `_icon_for` 缓存+重试上限模式）；**渲染签名 sig 已含 browserEnabled**（不含则开关翻转被签名跳过
  吞掉 dataChanged、页签显隐不更新——已修勿回退）。LeftPanel.qml：第三 PillTab（visible 绑 browserEnabled）、
  开关翻关自动跳回应用页签、domain 行不进详情页（isDomain 守卫）。runtime_shell：
  `settingsBridge.configChanged.connect(leftPanelBridge.refresh)`（设置点应用后页签**即时**显隐，不等 10s 轮询）；
  shutdown 时 `_faviconService.stop()`（FaviconService 非 QObject，放 bridges dict key `_faviconService` 防 GC，
  不在 CONTEXT_PROPERTY_NAMES、不 setContextProperty）。
- **打包**：requirements 加 `comtypes==1.4.11`；spec hiddenimports 加 comtypes/comtypes.client + 三个新模块
  （hooks-contrib 有 comtypes 钩子处理 frozen 下 gen 缓存，首启稍慢属正常）。打包后确认 `imageformats/qico.dll` 在
  （不在则 favicon 全走首字母兜底，不崩）。
- **🐛 已修：COM 初始化时序 bug（用户实测「装了 comtypes 仍采不到」的根因，勿回退）**：初版 worker 先手动
  `ole32.CoInitializeEx(MTA)` 再 `import comtypes`——comtypes **在 import 时**就会对当前线程按 `sys.coinit_flags`
  （默认 STA）CoInitializeEx，同线程 MTA→STA = `RPC_E_CHANGED_MODE`，import 直接抛异常且每 2s 重试每次都炸，
  探针永久哑掉（日志仅 debug 级「UIA 创建失败」）。**正确顺序（现实现）**：首次 import comtypes 前设
  `sys.coinit_flags = 0`（MTA）→ import（comtypes 自己初始化）→ 再显式 `comtypes.CoInitializeEx(0)` 确保**本线程**
  已初始化（import 可能发生在别的线程），`RPC_E_CHANGED_MODE` 容忍（STA 也能跑 UIA）。同轮顺带：
  `GetForegroundWindow.restype=c_void_p`（x64 防截断）、创建/采样失败日志带 repr/错误类型（创建阶段无 URL，安全）。
  临时验证脚本 `tools/check_browser_url.py` 已随用户 Windows 验证通过后**删除**（2026-07-19；scripts/ 只放 bat。
  日后再需排障可临时重写：make_browser_watcher(带 DEBUG logger)+set_active(True)+循环打印 get_domain 即可）。
- ✅ **取值改双路径：文档元素优先、地址栏兜底 + 地址栏几何校验**（2026-07-29，用户主诉「浏览器用了一个多小时但网站合计对不上」）：
  - **病根**：只读地址栏 Edit → 地址栏"不在场"就整段丢秒（`_maybe_record_domain` 拿不到 domain 直接丢弃）。
    丢秒来源按影响排序：①**全屏/F11/PWA 窗口地址栏控件不存在 → 100% 丢**（看一小时全屏视频 = 该站 0 秒，最可能的主因）；
    ②地址栏有键盘焦点主动跳过且不刷时间戳 → 6s 后全丢；③切回浏览器头 1~3s 探针刚唤醒；
    ④连续失败降频 10s > `get_domain` 过期线 6s；⑤**读到空串也 `_hwnd_fail=0`**，缓存元素失效后永久哑掉。
  - **主路径改为文档元素**（`_read_document_domain`/`_find_document`）：ControlType=Document 且有 Value 模式，
    其 Value = 当前页 URL。**全屏时文档元素依然存在** → 前 4 项一次性解决；且文档 Value 永远是已打开的地址、
    不可能是用户没输完的搜索词，隐私上优于读地址栏。候选取树序第一个非 offscreen 者：pre-order 保证外层文档
    排在内嵌 iframe 之前（不会把广告 iframe 域名当站点），IsOffscreen 滤掉 Firefox 留在树里的后台标签页文档。
    元素按 hwnd 缓存；跨文档导航会销毁旧元素→读值抛异常→即时作废重找，另加 `_DOC_CACHE_TTL_S=120s` 兜底重找
    （防"元素已脱离却仍返回旧 URL"；取值偏大是因为重找要 FindAll 走一遍子树，大页面开销不小）。
  - **地址栏几何校验（隐私护栏，勿删）**：`FindFirst(Edit AND IsValuePatternAvailable)` 命中的**未必是地址栏**——
    页内搜索框/登录框同样满足，会读到用户正在输入的内容。改 `FindAll` + `_is_address_bar` 逐个校验：
    只认**贴窗口顶部 ≤160px + 宽 ≥120 + 高 ≤90** 的控件（页内输入框在文档区，据此排除）；取不到 BoundingRectangle
    一律判否（证明不了是地址栏就不读）。不依赖本地化 Name、不依赖各浏览器不稳定的 AutomationId。
  - **失败语义修正**：两个读取器统一返回 `(ok, domain)`——`ok=False`=硬失败(找不到元素/COM 异常)才计入降频；
    `ok=True, domain=""`=读到了但非 http(s) 内部页，不算失败；地址栏输入中返回 `(True,"")` 主动跳过。
  - **自查扫出并修掉的三处（勿回退）**：
    ① **文档元素找不到时的负缓存** `_DOC_RETRY_AFTER_S=30s`：「有地址栏但无文档元素」的窗口（渲染进程无障碍未就绪）
    地址栏采得成功→失败计数被清零→永不降频 → 会每 2s 白扫一遍整棵子树。负缓存期内跳过扫描直接走兜底；
    换 hwnd 立即清零重试。TTL 到期时同时把 `_cache_doc` 置 None（原来只是绕过，旧 COM 元素引用一直留着）。
    ② **几何校验阈值改 DPI 无关**：顶边偏移上限取 `max(160, 控件高度×5)`——offset/height 比值与缩放无关
    （地址栏 ≈1.5~3 倍行高，页内输入框十几倍），否则 200%/300% 缩放 + Firefox 多层工具栏会误杀真地址栏；
    `_ADDR_MAX_HEIGHT` 90→140（300% 下地址栏本身就有约 96px，原值会误杀）。
    ③ **地址栏缓存元素静默空读自愈** `_EDIT_MAX_EMPTY_READS=5`：元素脱离通常抛 E_ELEMENTNOTAVAILABLE（已即时作废），
    但也可能只是返回空串——连续空读到阈值就作废重找。这才真正修掉「读到空串被当成功→探针永久哑掉」。
  - **隐私**：模块 docstring 新增**读取属性白名单**（ControlType/IsValuePatternAvailable 仅作查找条件；
    BoundingRectangle 几何校验；IsOffscreen 滤后台页；HasKeyboardFocus 判输入中；Value 唯一取值项）——
    **改本文件必须同步维护该清单，只减不增；尤其绝不读 Name**（页面标题/窗口标题，比域名敏感得多）。
    落盘内容一字未变，仍只有 domain。
  - **遗留**：Linux 无法验 UIA，双路径仅过纯逻辑测试（假元素驱动）。**Windows 待验**：全屏看视频几分钟后
    网站合计要跟着涨；Chrome/Edge/Firefox 各验一次文档元素确实吐 URL；大页面(Gmail/Figma)下 CPU 无感知上涨。
    未动的已知项：`_DOWNGRADE_INTERVAL_S(10s) > get_domain 过期线(6s)`——新语义下降频只在"确实无值可读"时发生，影响已很小。
- **测试**：tests/ 从 7 → 77 个全绿（url_domain 29 / domain_repo 8 / favicon_parse 20 / browser_tick 5 /
  left_panel_browser 8）。Linux 仅测纯逻辑+stub；**Windows 实测清单**（①UIA 独立验证已于 2026-07-19 通过，
  脚本已删）：②`scripts/run_qml_shell.bat`：默认无页签→设置勾选+应用→页签立即出现、
  取消立即消失且跳回应用；Chrome/Edge 浏览→按 domain 累计（www 剥、子域留）、日/周/月/日历正常;favicon 数十秒内出现、
  无 favicon 站点稳定首字母；**隐私抽查 user_data/ 与 debug.log grep 不到完整 URL/标题**；地址栏输入中不产生搜索词域名；
  非浏览器前台 watcher 零活动、CPU 无感知上涨;打包 exe 复测。

#### 右栏时段柱状图/Top4 跟随左栏视图维度（2026-07-19，用户反馈：切分类/浏览器时右栏应显示对应数据）
- **链路**：LeftPanel 新 `signal viewSelected(view)`（onViewTabChanged 同时发）→ AppShell `onViewSelected` →
  `rightPanelBridge.setDim(view)`（归一化 bro*/cat*/app，仿 setPeriod，变了才 recompute+resetAnim）→
  `_recompute` 三处 provider 调用带 `dim=self._dim`（keyword-only；桥内沿用 TypeError 降级先例兼容旧签名 provider）→
  `dashboard_data.provider(..., *, dim="app")` → snapshot `query["dim"]`。
- **snapshot**：dim 合法值 app/category/browser 否则 app；**browser 且 record_browser_enabled 关 → 回退 app**；
  payload 带 `timebar_dim`（回退后实际值）。右桥以 `timebar_dim` 为有效维度 `eff_dim`，保证柱图与 Top4 一致。
- **数据源分流**（api/common.py `_timebars_for_day/_range` 参数化 dim）：app=`get_daily_usage`/`get_hourly_breakdown`；
  category=`get_usage_range(...,"category")`/`get_hourly_breakdown(...,"category")`；browser=`get_daily_domain_usage`/
  **新增 `get_hourly_domain_breakdown`**（json_wal_repo，同构 get_hourly_breakdown 读 minute_domains 主+WAL,
  目录不存在返回 {} 零开销）/`get_domain_usage_range`。「其他」桶逻辑不变。
- **Top4 跟随维度**（browser=domains 名原样、跳过 resolve_app_name/short_name 的 app 名解析;category=usage_by_category）；
  KPI 卡/rest 卡保持全局不随 dim。**签名坑同款处理**：`series_sig` 与新增 `top4_sig` 均并入 eff_dim,
  切维度即使数据恰好相同（含空↔空）也强制重绘。开关翻关自动回退链成立：LeftPanel 跳回 viewTab 0 →
  viewSelected("app") → setDim("app")，零额外代码。
- 测试 77 → **96 全绿**（timebars dim 7 / snapshot dim 4 / setDim 6 / repo hourly domain 2，新文件 tests/test_timebar_dim.py）。
  Windows 待验：三视图切换右栏柱图/Top4 同步、颜色与左栏一致（共享 color_cache 按名字配色）、周/月/日历范围下同样跟随。
- 同日杂项：使用手册补浏览器统计/维度联动/隐私说明/FAQ 与「全屏勿扰」漏写项；临时脚本 tools/check_browser_url.py 删除。

#### 浏览器站点归并 + 站点详情设置（2026-07-19，用户需求：子域名默认合并、Google 三件套独立、可配置）
- **核心架构（勿动）**：采集/存储照旧存**完整子域名**（url_domain/win_browser_url/json_wal_repo 写路径零改动），
  归并**只发生在展示层读取处** → 独立名单/显示名任何变更**立即回溯全部历史**。
- **`utils/site_rules.py`**（纯 stdlib）：`registrable_domain`（内置 `_MULTI_SUFFIXES` 多段后缀表，com.cn/co.uk/github.io 等；
  IPv4/单标签原样）；`site_key(host, independent)` 独立名单**最长后缀匹配**（防 `mail.google.com.evil.com` 仿冒，已验归 evil.com）；
  `merge_domain_usage` 按 site_key 求和。
- **配置**：`site_independent_hosts`（default_factory 预置 drive/photos/mail.google.com；**store.py 加载 loop 故意不列它**——
  loop 只给缺键补默认，列了会把旧配置强制成 `[]` 盖掉非空默认；JSON 已有键含 `[]` 原样采用，清空可持久化）；
  `site_display_overrides`（key=site_key，与 app_display_overrides 同等待遇，进 store/导入导出 loop）。config_service get/update 对称。
- **归并应用点**（硬规则：**数据/颜色/图标键统一 site_key，显示名只在最终打标签处套**，防左右栏颜色图标错位）：
  snapshot_service（browser_domains/range + payload 带 `site_display_overrides`）、api/common `_timebars_*` browser 分支
  daily/hourly/range 三处、left_panel_bridge（label 套 override、icon/color 按 site_key）、right_panel_bridge（Top4/series 同理）。
- **UI**：`sites_bridge.py`（`sitesBridge`，仿 apps_bridge 的 build_sites_io+persist 沙箱模式；90 天扫描懒加载）；
  AppSettingsPage 顶部「应用/网站」PillTab（仅 browserEnabled 显示，QML 属性名用 **`sitesRef`** 避开 contextProperty
  同名自引用坑）；新 `SiteDetailPage.qml`（显示名编辑 + 子站点勾选「独立统计」，裸主域名行不给勾选框）；
  LeftPanel 域名卡片解除 guard → `siteActivated(siteKey)` → AppShell 开详情。变更刷新链：
  `sitesBridge.configApplied.connect(left/rightPanelBridge.refresh)`（runtime_shell ~L1128）。
- **已知行为**：主站点详情里勾选某子域名 → 该行立即「搬家」成站点列表里的独立站点，取消须进它自己的详情页（自洽，手册已写）。
- 测试 96 → **122 全绿**（test_site_rules 11 / test_sites_feature 15）。spec hiddenimports 补 sites_bridge+site_rules。
  Windows 待验：网站页签显隐、归并展示、勾选独立/取消回溯即时生效、显示名左右栏同步、左栏点卡进详情、设置导入导出带新字段。

#### 离开自动结算失灵排查 + 全屏勿扰去抖（2026-06-27，用户主诉「离开 60s 没自动结算」）
- **背景**：「离开超过阈值自动结算休息」逻辑在 `app_controller._tick_loop`（idle≥`max(idle_threshold_s, reminder_rest_seconds)`
  时调 `rest_complete()` 清零连续用眼）。用户反馈时灵时不灵。
- **bug 1：边沿触发被勿扰吃掉**（已修，治标）。原判定是**边沿触发** `prev_idle<th and idle>=th`，且 `not is_dnd` 才结算。
  若 idle 跨过阈值那一拍正处勿扰（尤其下面的全屏勿扰），这一拍被挡掉、边沿被消费；之后 `prev_idle` 已 ≥th 永不再「跨过」，
  勿扰解除也补不上。**改为电平触发 + 一次性闩锁**：新增 `_rested_settled`，条件 `idle>=rested_idle_th and not _rested_settled
  and not(paused/force_idle/dnd)` 即结算并置闩；`idle<idle_th`（用户恢复操作）时清闩。故勿扰一解除、只要人还没回来，
  下一拍即可补结算。
- **bug 2（真凶）：全屏勿扰狂跳**（已修，治本）。`events/*.jsonl` 实测 06-24 起 `auto_fullscreen` 模式 `mode_set` 翻转 **214 次**
  （每 1~20s 一次 dnd↔normal）。根因：`is_foreground_fullscreen()` 在前台短暂切换（通知/游戏内浮层/alt-tab 一闪）时抖动 →
  dnd 反复横跳 → 刷爆事件日志 + 狂闪托盘 + 把 auto-settle 边沿吃掉。**修法**：`_tick_loop` 全屏块加**迟滞去抖**——
  连续同向计数 `_fs_true_streak`/`_fs_false_streak` + 稳定判定 `_fs_stable`，进入要连续 `FULLSCREEN_ENTER_TICKS=2` 拍、
  退出要连续 `FULLSCREEN_LEAVE_TICKS=4` 拍（退出更钝，吃掉瞬时非全屏）。实测翻转 214→0。
- **诊断日志**：tick 里加 `debug: auto-settle eval idle=.. prev_idle=.. idle_th=.. rested_th=.. settled=.. dnd/force_idle/paused/resting`
  （吃 `--debug`/`EYECARE_DEBUG`，节流 5s、idle≥3 才打）。`_auto_settle_diag_ts` 节流戳。**保留**（平时不出，排障用）。
- **最终定性（非 bug，idle 检测天生局限）**：诊断日志实测 idle 是 **~30s 锯齿波**（`3→8→…→28→归零`，封顶 28 到不了 60）。
  代码全仓无 `SendInput/mouse_event/keybd_event/SetCursorPos`，**App 自己不造输入**——是系统层面每 ~30s 收到一次输入事件。
  Windows 上不少后台程序与外设会周期性注入合成输入（播放器防息屏、部分驱动/外设的心跳、远程桌面会话保活等），
  而 `GetLastInputInfo` **无法区分真人操作与合成输入** → idle 被反复清零，够不到阈值。
  **同一份 log 两种情况都印证**：有注入源的会话 idle 封顶 28、不结算；无注入源的会话
  idle 干净爬到 168、`settled=True` 正常结算。结论=先排查环境里的输入注入源，不上底层钩子。
  **遗留可选项**：若要「存在输入注入源时离开也能结算」，需上 `WH_KEYBOARD_LL`/`WH_MOUSE_LL` 底层钩子只认真实硬件输入、
  丢弃 `LLKHF_INJECTED` 合成输入（改动较大，未做）。
- **顺带修：`event_codes.yml` 缺失**。`docs/` 被删时连 `docs/diagnostics/event_codes.yml` 一起删，但 `policy_engine` 运行期仍按
  此路径加载 → 每次启动 ERROR + 策略引擎降级 → 所有诊断事件刷 `DIAG_UNKNOWN_EVENT` 告警（spec 还留着 `hiddenimports=['yaml']`，
  证明是误删）。**修法**：从 git `ec9c0e1` 取出该文件，**作为后端的一环**落到 `eye_care/diagnostics/event_codes.yml`（不再回 docs/）；
  `policy_engine._find_event_codes_path()` 改为优先读模块同目录（旧 docs/ 路径留作兼容兜底）；`EyE Care.spec` 的 `datas` 增打
  `('eye_care/diagnostics/event_codes.yml', 'eye_care/diagnostics')`。实测启动 ERROR + 那批告警消失。
- **遗留约束**：本机 Linux 无 Qt，改动（`app_controller.py`/`policy_engine.py`/`EyE Care.spec` + 新增 yml）仅过 `py_compile` 与
  纯逻辑驱动测试（用真实 `AppController` + mock 探针，三场景：基础/边界 59s/全屏去抖全绿）。**用户已 Windows 实跑确认**：
  去抖翻转=0、idle 无注入源时爬过 60 触发结算（`settled=True`）。

#### 〔历史·已作废〕模态视觉：纯变暗（web 时代，index.html 已删）
- 全屏 `backdrop-blur` 已去（内存元凶）。曾试卡片级磨砂(.modal-frost)，但**深色背景下磨砂几乎不可见**，
  用户决定不要——**已回退**：模态只剩 `bg-black/70` 纯变暗，calendar-picker-panel 恢复不透明、无 blur。
  index.html 现 0 处 backdrop-blur / 0 处 modal-frost。
