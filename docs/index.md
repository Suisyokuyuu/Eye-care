# Docs Index（交付终版）

更新时间：2026-02-24  
适用范围：应用版本 V1.0.2

## 文档说明

本目录为交付前最终文档集。若文档与代码冲突，以代码实现为准。

## 阅读顺序（建议）

1. `docs/FROZEN_SPEC.md`（冻结红线与验收口径）
2. `docs/ARCHITECTURE.md`（启动链路、线程与边界）
3. `docs/DATA_SPEC.md`（数据存储与 API 数据口径）
4. `docs/GUI_DISPATCHER_RULES.md`（GUI 调度约束）
5. `docs/diagnostics/event_codes.yml`（诊断事件字典，运行时依赖）
6. `docs/diagnostics/NORMAL_MODE_LOGGING.md`（普通模式日志行为）
7. `docs/diagnostics/DIAG_EVENT_MAPPING.md`（事件映射与别名摘要）
8. `docs/CHANGELOG_FREEZE.md`（冻结期文档变更记录）
9. `docs/ROADMAP.md`（下版本功能规划）

## 交付检查提醒

- 运行模式与日志策略必须以 `docs/diagnostics/event_codes.yml` + `eye_care/diagnostics/policy_engine.py` 为准。
- API 路由以 `eye_care/api/routes/*.py` 为准。
- 数据存储结构以 `eye_care/data/json_wal_repo.py` 为准。
