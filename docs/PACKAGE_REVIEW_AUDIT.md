# 打包前复核审计（待人工复核）

**生成时间**：2026-02-22  
**用途**：标记旧代码参与、旧注释、遗留兼容项，供打包前人工复核。**不直接清理**，复核后再决定是否修改/删除。

---

## 一、旧代码 / Legacy 参与标记

以下为代码中仍参与或影响行为的 legacy/兼容逻辑，需复核是否保留。

| 文件 | 行号 | 内容摘要 | 复核建议 |
|------|------|----------|----------|
| `eye_care/notify/notify_window_controller.py` | 59 | `Phase 2: Notify 显式状态机开关（默认 False，legacy 行为）` | 状态机开关，默认 legacy，行为合理 |
| `eye_care/notify/notify_window_controller.py` | 992, 1042, 1185 | `# Legacy 行为` | 分支逻辑，保留 legacy 路径 |
| `eye_care/controller/app_controller.py` | 44 | `DEPRECATED: is_paused 已废弃，永远为 False，保留字段兼容旧版 API` | 兼容旧 API，保留 |
| `eye_care/controller/app_controller.py` | 830 | `DEPRECATED: is_paused 已废弃，删除恢复分支` | 已删除分支，注释可保留 |
| `eye_care/config/models.py` | 48 | `Notify 显式状态机开关：默认关闭（legacy 行为）` | 配置说明 |
| `eye_care/diagnostics/policy_engine.py` | 16 | `回滚：设为 1 时跳过路由，始终放行（与旧行为一致）` | EYECARE_DIAG_LEGACY 开关 |
| `eye_care/diagnostics/policy_engine.py` | 22-23 | `_warn_legacy_if_enabled()` | legacy 开关告警 |
| `eye_care/diagnostics/policy_engine.py` | 68, 83, 91, 156, 160 | `deprecated` 占位符与放行逻辑 | 策略引擎配置 |
| `eye_care/data/transfer.py` | 472 | `Import export file (.zip or legacy .json)` | 兼容旧 .json 导入 |
| `eye_care/ui/state_machines/notify_machine.py` | 4 | `SM_NOTIFY_V2=False 时保持 legacy 行为` | 状态机说明 |
| `eye_care/ui/state_machines/__init__.py` | 2 | `状态机影子层（Phase 1）：仅记录迁移与 REJECT/DEFER，不驱动行为` | 模块说明 |
| `eye_care/ui/state_machines/types.py` | 2 | `状态机公共类型（Phase 1 影子模式）` | 模块说明 |

---

## 二、旧注释 / 待复核注释

以下注释可能过时或表述不清，需人工复核后决定是否精简/更新。

| 文件 | 行号 | 内容摘要 | 复核建议 |
|------|------|----------|----------|
| `eye_care/notify/notify_window_controller.py` | 978 | `新 session 必须重置 ACK 状态，避免旧 session 的 ACK 让本 session 直接放行（P1 收尾）` | 含 P1 收尾，可简化为业务说明 |
| `eye_care/notify/notify_window_controller.py` | 1255 | `兜底用 title token 查找（旧逻辑）` | 兜底逻辑说明 |
| `eye_care/data/json_wal_repo.py` | 789 | `Only for logging parity with old code` | 英文日志对等注释，可保留或删除 |
| `eye_care/bootstrap/runtime_shell.py` | 742 | `# NOTE: rest/notify 逻辑已迁移至 rest_controller、notify_controller` | 历史迁移说明，可保留 |
| `eye_care/config/models.py` | 47 | `# ---- 状态机升级开关（Phase 2）----` | Phase 2 标记 |

---

## 三、Phase / 阶段标记注释

以下为开发阶段标记（Phase 1/2、P1 收尾等），交付后可考虑是否删除阶段前缀。

| 文件 | 行号 | 内容摘要 |
|------|------|----------|
| `eye_care/notify/notify_window_controller.py` | 59, 108, 679, 885, 892, 898, 974, 981, 1029, 1108, 1123, 1170, 1178 | Phase 2 / SM_NOTIFY_V2 相关注释 |
| `eye_care/ui/state_machines/notify_machine.py` | 75 | `Phase 2 新增：显式状态机裁决方法` |
| `scripts/phase2_blackbox_smoke.py` | 3 | `Phase 2 blackbox smoke tests` |
| `scripts/phase2_acceptance_observability.py` | 3, 13, 372 | `Phase 2 可观测性验收` |

---

## 四、兜底 / 兼容 / 临时注释

以下为兜底、兼容、临时等实现说明，多数为合理设计说明，复核后可保留。

| 文件 | 行号 | 内容摘要 |
|------|------|----------|
| `eye_care/notify/notify_window_controller.py` | 302, 308, 310, 446, 921, 1092, 1255, 1279 | loaded 兜底、late_set、title token 兜底等 |
| `eye_care/controller/app_controller.py` | 560 | 兜底：若因时序导致 _rest_due 未置位 |
| `eye_care/api/routes/config.py` | 187 | 缓存失败时使用临时文件 |
| `eye_care/api/routes/stats.py` | 147, 158 | 兜底扫 30 天、分类表兜底 |
| `eye_care/notify/notification_manager.py` | 70-71 | threshold_s / work_bucket |
| `eye_care/ui/desktop_integrations.py` | 15, 55 | 兜底/调试入口、兼容别名 |
| `eye_care/data/transfer.py` | 359 | utf-8-sig 兼容 BOM |
| `scripts/phase2_blackbox_smoke.py` | 255 | 兜底：API 不可用时仅校验已有文件 |

---

## 五、双 AI 评审综合结论

综合两份 AI 评审结果，形成统一执行建议。

### 5.1 不建议删（有明显行为/兼容风险）

| 项 | 位置 | 风险说明 |
|----|------|----------|
| **is_paused 字段链路** | app_controller.py (44)、common.py (19)、DATA_SPEC.md (71) | 破坏现有 state 返回结构与诊断字段口径，接口兼容风险 |
| **sm_notify_v2 开关与 Notify legacy 分支** | models.py (49)、runtime_shell.py (542)、notify_window_controller.py (59, 992, 1042, 1185) | 当前默认 False，直接删 legacy 路径等于强制切行为，可能引入通知状态机回归 |
| **EYECARE_DIAG_LEGACY 回滚开关** | policy_engine.py (16, 22-23, 68, 83, 91, 156, 160) | 删后失去紧急放行回滚手段，运维/排障风险 |
| **兜底/容错逻辑** | notify_window_controller.py (302, 308, 310, 446, 921, 1092, 1255, 1279)、app_controller.py (560)、config.py (187)、desktop_integrations.py (15, 55) 等 | 合理设计，保证复杂场景下系统稳健运行 |

**结论**：以上代码与逻辑全部保留。

---

### 5.2 可删，但必须联动修改（否则会出问题）

| 项 | 位置 | 联动要求 |
|----|------|----------|
| **legacy .json 导入支持** | transfer.py (472)、window_api.py (280) | 若删除后端分支，必须同步：① UI 文件选择器过滤掉 .json；② 文档说明不再支持 .json 导入。否则用户仍可选 .json 但导入失败（“可选不可用”） |

**结论**：若无老用户需 .json 迁移，可删；删除时务必同步改 UI 过滤与文档。

---

### 5.3 可直接删（仅注释/文案，不影响运行）

| 文件 | 行号 | 内容 | 操作 |
|------|------|------|------|
| `notify_window_controller.py` | 59, 108, 679, 885, 892, 898, 974, 981, 1029, 1108, 1123, 1170, 1178 | Phase 2 / SM_NOTIFY_V2 阶段标记 | 删除阶段前缀，保留业务说明 |
| `notify_window_controller.py` | 978 | P1 收尾描述 | 简化为业务说明，如“新 session 必须重置 ACK 状态，避免旧 session 的 ACK 让本 session 直接放行” |
| `notify_window_controller.py` | 1255 | “兜底用 title token 查找（旧逻辑）” | 删除“旧逻辑”等过时表述，可保留“兜底用 title token 查找” |
| `json_wal_repo.py` | 789 | Only for logging parity with old code | 删除 |
| `config/models.py` | 47 | # ---- 状态机升级开关（Phase 2）---- | 删除阶段标记 |
| `ui/state_machines/__init__.py` | 2 | 状态机影子层（Phase 1）… | 删除 Phase 1 标记 |
| `ui/state_machines/types.py` | 2 | 状态机公共类型（Phase 1 影子模式） | 删除 Phase 1 标记 |
| `scripts/phase2_blackbox_smoke.py` | 3 | Phase 2 blackbox smoke tests | 删除阶段标记 |
| `scripts/phase2_acceptance_observability.py` | 3, 13, 372 | Phase 2 可观测性验收 | 删除阶段标记 |
| `notify_machine.py` | 75 | Phase 2 新增：… | 删除阶段前缀 |

**结论**：以上为纯注释/文案，删除或简化不影响运行，可提升代码整洁度。

---

### 5.4 执行优先级建议

1. **高优先级（低风险）**：执行 5.3 中“可直接删”的注释清理。
2. **中优先级（需决策）**：若确认无 .json 老用户，再执行 5.2 的 legacy .json 删除及联动修改。
3. **不执行**：5.1 中所有项保持不动。

---

## 六、复核结论（综合版）

- **旧代码参与**：is_paused、sm_notify_v2、EYECARE_DIAG_LEGACY、兜底逻辑等，全部保留。
- **legacy .json**：可删，但必须同步 UI 过滤与文档；否则保留。
- **阶段标记注释**：Phase 1/2、P1 收尾等可直接删或简化，不影响运行。
- **兜底/兼容注释**：容错逻辑的设计说明建议保留；“旧逻辑”“logging parity”等过时表述可删。

---

## 七、文档变更记录

- 2026-02-22：初版扫描，生成待复核标记
- 2026-02-22：综合双 AI 评审，形成分级执行建议（5.1–5.4）
- 2026-02-22：已执行 5.3 注释清理（Phase 1/2、P1 收尾、logging parity 等）
 