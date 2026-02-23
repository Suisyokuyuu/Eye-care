# Notify 出现后马上消失（历史故障复盘）

更新时间：2026-02-22  
状态：已修复并纳入回归检查

## 1) 现象

在提醒触发后，通知窗短暂出现即消失，表现为“一闪而过”。

## 2) 已确认根因（历史）

### 根因 A：过早标记已提醒

旧流程在 `show()` 返回后立即调用 `on_notify_complete(..., True, ...)`，导致 `mark_rest_notified()` 过早执行，下一轮轮询迅速判定为 blocked。

### 根因 B：同日重复入队

`prompt_key=(local_date, work_bucket)` 在临界秒可能快速变化，队列中出现两个通知任务，第二次 show 覆盖第一次，视觉上像闪退。

### 根因 C：autoHide 与窗口复用时序

旧定时器与窗口复用时序叠加，导致第二次展示时 autoHide 过早触发。

### 根因 D：Layered/alpha 状态未恢复

淡出后未彻底恢复 exstyle，后续 show 处于“可见度异常”状态，只在下一次淡出首帧短暂可见。

## 3) 代码侧已落地修复

- 用户动作回调后才 `on_notify_complete(True)`，避免过早消费。
- `NotificationManager` 对同日 pending 做单任务约束，避免重复 show。
- autoHide 参数做边界保护（1~600），前端每轮 `resetFade` 先清理旧定时器。
- hide/show 链路补齐 layered/exstyle 恢复逻辑。

## 4) 当前正确链路

1. `NotifierService` 轮询快照。
2. `NotificationManager.on_snapshot()` 判定并 `post_notify_show`。
3. GUI 线程执行 `NotifyWindowController.show(...)`。
4. 用户点击 rest/snooze/dismiss 后，bridge 回调 `on_notify_complete(True)`。
5. `mark_rest_notified()` 在步骤 4 之后触发。

## 5) 回归检查建议

- 调用 `POST /api/debug/notify`，确认通知稳定展示，不出现“一闪即关”。
- 连续触发多次提醒，确认同一时间仅有一个 pending notify。
- 二次、三次展示均可见，关闭后不应出现“仅在淡出时闪一下”。
- 检查日志中不存在异常堆栈（特别是 notify fade / layered restore 相关）。

## 6) 备注

本文为历史故障复盘，不作为线程模型与诊断策略的规范来源。规范以以下文档为准：

- `docs/FROZEN_SPEC.md`
- `docs/GUI_DISPATCHER_RULES.md`
- `docs/diagnostics/event_codes.yml`
