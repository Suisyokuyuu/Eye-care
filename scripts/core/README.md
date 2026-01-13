Renew V1.0 - Core (Step 1)

Core 只负责不可动摇的规则：
- idle 判定
- 计时口径：idle / paused 时停止；解除后恢复
- 连续工作阈值：need_break 事件（非强制）
- 跳过本轮：skip_this_round()
- idle 达到 rest_time：视为本轮休息完成，reset_round()

UI / 托盘 / 浮窗 / 数据落盘 都不应该写这些规则，只调用 core 的输入接口并读取 snapshot/events。
