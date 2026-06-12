# 测试说明

## 当前测试策略

原来的回归测试目录里有大量“启动应用、等待几秒、扫描日志”的场景。它们没有独立触发具体行为，重复度高，失败时也很难定位问题。已经删除。

当前只保留真正会驱动关键风险路径的通知窗口挂起回归：

- `test_scenario_f_notify_hide.py`
  - 设置短自动隐藏时间。
  - 调用 `/api/debug/notify` 触发通知。
  - 检查通知 `HIDING -> HIDDEN` 是否闭合。
- `test_scenario_g_notify_storm.py`
  - 高频触发通知。
  - 检查通知 show/hide 压力下是否卡在 `HIDING`。
  - 标记为 `long`。
- `test_scenario_k_notify_ack_repost_guard.py`
  - 多轮通知 show、ACK、autoHide。
  - 覆盖 ACK 后重复投递和重入保护。
  - 标记为 `long`。

共享 fixture 在 `tests/hang_scenarios/conftest.py`：

- `AppRunner`：启动和停止 EyE Care。
- `ScenarioDriver`：调用本地 HTTP API 驱动场景。
- `HangDetector`：读取 `debug.log` 并调用 `notify_hang_analyzer`。

## 运行方式

```bash
pytest -m hang_scenario tests/hang_scenarios -vv
pytest -m "hang_scenario and not long" tests/hang_scenarios -vv
pytest -m "hang_scenario and long" tests/hang_scenarios -vv
```

## 环境要求

这些测试是 Windows GUI 集成测试，不是无头单元测试。

需要：

- Windows 10/11。
- Python 依赖安装完成。
- PySide6/QWebEngine 可用。
- 本地端口可用，默认测试端口为 `8765`。
- 能启动桌面窗口和透明置顶窗口。

## 已删除测试

以下场景已删除，因为它们缺少有效刺激，只能作为重复的启动/日志检查：

- A：JS block 占位。
- B：style wait 占位。
- C：controller wait 占位。
- D：queue pressure 占位。
- E：high risk placeholder。
- H：rest/notify combo 占位。
- I：settings IO pressure 占位。
- J：startup/shutdown 占位。

后续如果要恢复，建议先把场景驱动做实，例如明确调用 API、桥接方法或前端自动化，并给出可观测断言。

## 建议新增覆盖

- 纯单元测试：`AppConfig` clamp、JSONL merge、导入导出路径校验。
- API 测试：token 校验、配置更新、snapshot shape、rest start guard。
- 数据仓库测试：minute 合并、WAL 重放、退出恢复。
- UI 自动化：主页面基本加载、设置弹窗、应用详情、休息页倒计时。
- 打包冒烟：PyInstaller 产物启动、数据目录位置、静态资源加载。

