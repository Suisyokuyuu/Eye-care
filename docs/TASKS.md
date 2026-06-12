# 未完成任务清单

这个清单只记录本次阅读项目时发现的未完成、未解决或需要回头确认的事情。

## P0：影响可用性

- 修复 UI 文案乱码。
  - `eye_care/ui/web/index.html` 大量中文已经损坏，用户界面会直接显示乱码。
  - 托盘菜单和 Qt host 部分字符串也有乱码。
- 明确 Qt host 与 legacy host 的边界。
  - 默认已经是 Qt host，但 legacy pywebview 仍保留大量窗口控制代码。
  - 需要决定是继续双 host 兼容，还是冻结 legacy 并逐步删除。

## P1：影响维护和测试

- 清理代码注释乱码。
  - 多数 Python 文件的中文注释已损坏，影响维护。
  - 建议优先清理 `AppController`、`JsonWalRepository`、通知/休息窗口控制器。
- 拆分 `eye_care/qt/runtime_shell.py`。
  - 该文件同时承担后端启动、主窗口、通知窗口、休息遮罩、托盘、桥接和探针脚本，体积过大。
- 补齐非 GUI 单元测试。
  - 当前保留测试全部依赖 Windows GUI，缺少可快速运行的仓库、配置、API 服务层单元测试。
- 梳理服务层迁移。
  - `services/` 已存在，但控制器仍包含大量业务和状态逻辑。
  - 需要确认 route -> service -> controller 的长期分层。

## P2：行为和产品细节

- `NotifierService._run_loop` 在 controller 为空时可能引用未初始化的 `extra`。
  - Qt host 通常会先设置 controller，但代码本身不够稳。
- 更新检查依赖 GitHub 最新 release。
  - 需要明确失败时 UI 文案和缓存策略。
- `debug_enabled`、`EYECARE_DEBUG`、`--debug` 三者的关系需要写入配置/运行规范。
- `sm_notify_v2` 是实验开关。
  - 需要决定是否默认启用、移除 legacy 分支，或继续并行维护。
- `event_codes.yml` 是运行时依赖。
  - 需要检查其中事件说明是否也存在乱码，避免长期难以维护。

## P3：文档后续

- 为用户补一份“界面使用说明”。
  - 本次主要整理工程文档；UI 文案乱码未修复前，不适合写详细用户手册。
- 为开发者补完整 API 示例。
  - 当前 `DATA_AND_API.md` 只给接口速览。
- 为发布补 checklist。
  - 包括依赖安装、打包、启动验证、数据目录迁移、日志检查。

