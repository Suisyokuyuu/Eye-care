# CHANGELOG FREEZE

## 2026-02-22（移除托盘调试菜单项）

类型：用户界面清理

### 本次更新

- 移除托盘菜单中的"抓取线程栈"调试功能选项
- 底层实现（`hang_dump.py`）和 API 接口（`/api/debug/dump_threads`）保留，供内部调试使用

### 说明

- 该功能为调试用途，不应出现在用户可见的菜单中
- 诊断事件字典中的 `E_HANG_DUMP_FAILED` 等事件码保持不变

---

## 2026-02-22（打包前文档与阶段性清理）

类型：文档与阶段性产物清理

### 本次更新

- 新增 `docs/PACKAGE_REVIEW_AUDIT.md`：打包前复核审计，标记旧代码参与、旧注释、Phase 标记、兜底/兼容注释，供人工复核（不直接清理）。
- 更新 `docs/index.md`：补充 PACKAGE_REVIEW_AUDIT 阅读顺序，更新时间。
- 全量更新常驻文档更新时间至 2026-02-22：
  - `docs/ARCHITECTURE.md`、`docs/DATA_SPEC.md`、`docs/FROZEN_SPEC.md`
  - `docs/GUI_DISPATCHER_RULES.md`
  - `docs/diagnostics/NORMAL_MODE_LOGGING.md`、`docs/diagnostics/DIAG_EVENT_MAPPING.md`、`docs/diagnostics/NOTIFY_APPEAR_DISAPPEAR.md`
- 清理阶段性文档：
  - 删除 `审计计划完成度分析_2026.md`
  - 删除 `审计问题修复(修正版)_1537e850.plan.md`

### 说明

- 仅文档与阶段性产物变更；不涉及业务代码。
- `AUDIT_REPORT_2026-02-22.md` 保留于项目根目录，作为审计记录。

---

## 2026-02-21（文档终审交付）

类型：文档交付级修订（不改业务代码）

### 本次更新

- 全量复审并重写以下文档，使其与当前代码一致：
  - `docs/index.md`
  - `docs/ARCHITECTURE.md`
  - `docs/DATA_SPEC.md`
  - `docs/FROZEN_SPEC.md`
  - `docs/GUI_DISPATCHER_RULES.md`
  - `docs/diagnostics/DIAG_EVENT_MAPPING.md`
  - `docs/diagnostics/NORMAL_MODE_LOGGING.md`
  - `docs/diagnostics/NOTIFY_APPEAR_DISAPPEAR.md`
- 修正冻结验收口径中对 `ALWAYS_ON/DEBUG_ONLY` 的错误假设，明确普通模式与 debug 模式的差异。
- 修正文档内失效路径与过时内容（不存在文件、已变更流程）。
- 统一声明：诊断策略以 `docs/diagnostics/event_codes.yml` + `eye_care/diagnostics/policy_engine.py` 为准。
- 补充 `docs/DATA_SPEC.md` 的 WAL 幂等边界说明（分钟快照语义、minutes 单日聚合内存口径、events 近端去重边界、tail 窗口估算边界）。

### 影响

- 仅文档变更；不涉及运行逻辑、API 行为和数据格式改动。

---

## 2026-02-21（代码审查清理）

类型：功能改动（代码审查清理）

### 本次改动

- 删除开发调试文档：
  - `AUTO_IDLE_DIAG_REPORT.md`
  - `CODE_HEALTH_REPORT_2026-02-20_ANALYSIS.md`
  - `CODE_HEALTH_REPORT_2026-02-20.md`
  - `DIAG_MIGRATION_DISPUTE_REPORT.md`
  - `DIAG_PLAYBOOK.md`
  - `EMPTY_EXCEPTION_AND_DICT_GAP_AUDIT.md`
  - `LEGACY_UNUSED_SCAN_REPORT_2026-02-20.md`
  - `PHASE2_NEW_AI_GUIDE.md`
  - `STATE_MACHINE_UPGRADE_GUIDE.md`
- 更新 `docs/index.md`，移除对已删除文档的引用
- 更新 `docs/FROZEN_SPEC.md`，将禁词文档指向 `docs/diagnostics/NORMAL_MODE_LOGGING.md`
- 更新 `.gitignore`，添加 `user_data/diagnostics/` 忽略规则

### 说明

- 本次清理仅删除开发调试产物，保留终版架构/数据/调度文档。
- `user_data/diagnostics/debug_session.log` 属于 debug 模式产物，普通用户不生成。
