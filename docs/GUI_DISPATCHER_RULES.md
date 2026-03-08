# GUI 调度规则（Dispatcher 唯一入口）

更新时间：2026-02-24（适用应用版本 V1.0.3）

## 1) 核心原则

- 业务层所有“在 GUI 线程执行”的窗口操作，只能通过 `GuiDispatcher` 投递。
- 后台线程禁止直接调用窗口对象（包括 `show/hide/destroy/evaluate_js/Win32 样式`）。
- `BeginInvoke` 仅允许作为局部实现细节，不得扩散成新的业务入口。

## 2) DoEvents 白名单

规则：禁止在白名单之外新增 `DoEvents`。

当前白名单仅两处（`eye_care/ui/style_coordinator.py`）：

- `_apply_step` 中第一处限时等待（约 `#L307`）
- `_apply_step` 中第二处限时等待（约 `#L565`）

用途：在已由 dispatcher 调起的样式应用流程内，等待 WinForms `BeginInvoke` 完成时泵消息，避免同步死锁。

## 3) BeginInvoke 允许场景

新增 `BeginInvoke` / `begin_invoke` 必须满足以下之一：

1. dispatcher 任务内部的二次切换  
   例如样式流程中，任务已在 GUI loop 中执行，再切到 WinForms UI 上下文。

2. native UI 访问的单一收口  
   对 WebView2/CoreWebView2 等必须在 WinForms 线程访问的对象，允许在一个集中函数内封装 `BeginInvoke`。

禁止：在多个业务模块散落直接调用 `native.BeginInvoke` 形成“并行入口”。

## 4) Notify 侧现状（历史兼容）

`eye_care/notify/notify_window_controller.py` 内仍存在 `BeginInvoke` 用于 native 线程上下文兼容（如 `_post_gui`、`_post_to_native_ui`、`_do_show_ui` 部分流程）。

当前约束：

- 不再新增新的直连调用点。
- 新逻辑优先 `dispatcher.post(...)`。
- 仅在确有 native 线程约束时保留 `BeginInvoke`。

## 5) Code Review 检查项

- 是否存在后台线程直接触窗？
- 新增 `BeginInvoke` 是否说明了必要性与收口位置？
- 是否在退出路径正确处理 `dispatcher.stop()` 后的拒绝投递？
- 是否破坏 notify/rest 统一投递链路？
