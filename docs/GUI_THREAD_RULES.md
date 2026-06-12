# GUI 线程规则

EyE Care 的桌面窗口、透明样式和 WebView 操作都必须尽量回到 GUI 线程执行。这个规则适用于 Qt host 和 legacy pywebview host。

## 基本原则

- 后台线程可以采样、写数据、发起调度请求。
- 窗口 show/hide、透明样式、Win32 hwnd 样式修改、WebView JS 注入应通过 GUI dispatcher 或 Qt signal 回到 GUI 线程。
- 不要在 GUI 线程做长时间 IO、网络请求或阻塞等待。
- 不要从任意后台线程直接调用窗口对象。

## 允许的短等待泵

`eye_care/ui/style_coordinator.py` 中仍保留了极小范围的 `WinFormsApp.DoEvents()`：

- 只在 legacy/WinForms 样式应用等待中使用。
- 单次等待窗口约 0.4 秒。
- 只用于等待 Win32 样式操作完成或透明窗口 ready。
- 超时后必须降级或失败，不能无限等待。

这不是通用模式。新增代码应优先使用 dispatcher、Qt signal、事件回调或超时 timer。

## 诊断要求

涉及窗口状态的路径应尽量记录：

- 请求阶段。
- hwnd 是否拿到。
- 样式应用是否成功或降级。
- show/hide 是否闭合。
- 超时 reason code。

通知窗口和休息遮罩的挂起回归测试依赖这些诊断信号判断是否卡在中间态。

