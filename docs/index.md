# EyE Care 文档索引

更新时间：2026-06-07

这套文档按当前代码重新整理，旧的乱码迁移文档已删除。文档只描述现在能从代码确认的事实；迁移残留、缺口和疑似问题放在任务清单里。

## 推荐阅读顺序

1. [项目总览](../README.md)
2. [架构说明](ARCHITECTURE.md)
3. [数据与 API](DATA_AND_API.md)
4. [GUI 线程规则](GUI_THREAD_RULES.md)
5. [测试说明](TESTING.md)
6. [未完成任务清单](TASKS.md)

## 运行时相关文档

- [诊断事件字典](diagnostics/event_codes.yml)：运行时会读取这个 YAML，不能随意删除。

## 当前边界

- 默认桌面壳是 Qt host：`python main.py --host qt`。
- legacy pywebview host 仍在代码中，主要用于迁移兼容。
- UI 文案和大量历史注释存在编码损坏，属于后续修复任务。
- 回归测试不是完整覆盖，目前只保留通知窗口挂起相关的有效集成测试。
