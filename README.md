# EyE Care

EyE Care 是一个 Windows 桌面护眼与应用使用时间统计工具。它会在本地记录前台应用使用时间，并在连续用眼达到阈值后弹出休息提醒和全屏休息遮罩。

当前项目处在 Qt host 迁移后的整理阶段：默认入口使用 PySide6/QWebEngine，旧的 pywebview host 仍保留但不再作为首选运行方式。代码中还有一些历史乱码注释和迁移残留，已在任务清单中单独记录。

## 功能现状

- 前台应用使用时长统计，支持按天、周、月查看。
- 应用分类、显示名覆盖、黑名单和指定应用自动勿扰。
- 连续工作提醒、通知气泡、推迟、立即休息、休息完成记录。
- 全屏休息遮罩，支持多屏。
- 本地 JSONL + WAL 数据存储，启动/退出时合并。
- 设置导入导出、全部数据导入导出。
- 本地 HTTP API 和本地 Web UI。
- Windows 托盘菜单与开机启动配置。

## 快速运行

```bash
pip install -r requirements.txt
python main.py
```

常用参数：

```bash
python main.py --debug
python main.py --data-dir ./user_data_dev
python main.py --no-ui
python main.py --no-ui --api-port 17993
python main.py --host qt
python main.py --host legacy
```

默认数据目录是项目根目录下的 `user_data/`。打包版本会把数据放在 exe 同级目录的 `user_data/`。

## 项目结构

```text
main.py                         程序入口和运行模式选择
eye_care/api/                   Flask 本地 API
eye_care/controller/            采样、提醒、休息和运行状态核心控制器
eye_care/data/                  JSONL/WAL 数据仓库与导入导出
eye_care/config/                配置模型与读写
eye_care/qt/                    默认 Qt 桌面壳
eye_care/bootstrap/             启动常量、DPI、旧 host 支撑
eye_care/ui/                    Web 页面投递、桥接、窗口工具
eye_care/notify/                通知窗口和通知调度
eye_care/rest/                  旧 host 休息遮罩控制器
eye_care/services/              API 服务层抽取
eye_care/diagnostics/           诊断事件、策略和日志分析
eye_care/ui/web/                本地 Web UI、休息页、通知页和静态资源
tests/hang_scenarios/           当前保留的通知挂起回归场景
docs/                           新整理后的项目文档
```

## 文档入口

从 [docs/index.md](docs/index.md) 开始读：

- 架构说明：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 数据与 API：[docs/DATA_AND_API.md](docs/DATA_AND_API.md)
- 测试说明：[docs/TESTING.md](docs/TESTING.md)
- 未完成任务：[docs/TASKS.md](docs/TASKS.md)
- 诊断事件运行时字典：[docs/diagnostics/event_codes.yml](docs/diagnostics/event_codes.yml)

## 测试

当前保留的回归测试只覆盖通知窗口的关键挂起风险：

```bash
pytest -m hang_scenario tests/hang_scenarios -vv
pytest -m "hang_scenario and not long" tests/hang_scenarios -vv
```

这些测试会启动桌面程序，依赖 Windows GUI、PySide6/QWebEngine 和本地端口，不适合作为普通无头单元测试。

## 打包

```bash
build_exe.bat
```

打包配置在 `EyE Care.spec`。依赖由 `requirements.txt` 固定。

