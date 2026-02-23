# DATA SPEC（交付终版）

更新时间：2026-02-22

## 1) 存储布局

主数据目录（相对 `data_dir`）：

- `minute_usage/minute-YYYY-MM-DD.jsonl`
- `events/events-YYYY-MM-DD.jsonl`
- `wal/minutes-YYYY-MM-DD.jsonl`
- `wal/events-YYYY-MM-DD.jsonl`

辅助文件（非主统计源）：

- `config.json`
- `app_paths.json`
- `app_categories.json`
- `exit_state.json`
- `import_log.json`

## 2) 主数据 schema

### minute_usage（`minute@1`）

每行 JSON：

- `_schema`: `minute@1`
- `minute_start_utc`: UTC ISO8601（`Z`）
- `local_date`: `YYYY-MM-DD`
- `apps`: `{ app_short: seconds_in_this_minute }`

口径说明：

- 按分钟桶聚合，秒级增量由 `add_usage()` 进入当前分钟累积。
- 分钟切换或 `close()` 时落 WAL，再由 `merge()` 合并进主文件。

### events（`event@1`）

每行 JSON：

- `_schema`: `event@1`
- `utc_ts`: UTC ISO8601（`Z`）
- `local_date`: `YYYY-MM-DD`
- `kind`: 事件类型（如 `rest_begin` / `rest_complete` / `rest_snooze` / `mode_set`）
- `payload`: JSON object

## 3) 派生数据（不单独持久化）

以下均由 `minute_usage` / `events` 计算：

- `daily_usage`（`get_daily_usage`）
- `hourly_usage` / `hourly_breakdown`
- `usage_range` / `top`
- `timeline_segments`（`get_timeline_segments`）
- `app_last_active_utc`

关键约束：`timeline_segments` 不落独立存储。

## 4) API 数据口径（与当前代码一致）

### `GET /api/snapshot`

核心字段：

- `vm.local_date`
- `vm.daily_usage`
- `range_daily_usage`
- `usage_by_category` / `range_usage_by_category`
- `rest`（运行时状态）
- `state`（`is_paused/is_dnd/force_idle/auto_idle`）
- `hourly_usage` 与统计字段

说明：`range=week|month|custom` 时，`range_daily_usage` 为范围聚合。

### `GET /api/app_details?app=<app_short>&date=<YYYY-MM-DD>&days=<N>`

核心字段：

- `daily_seconds`（范围内逐日）
- `hourly_seconds_for_date`（仅 `date` 当天）
- `timeline_segments`（仅 `date` 当天）
- `last_active_utc`（`days` 范围内）

### 其他与数据相关接口

- `GET /api/apps_list`
- `POST /api/app_settings`
- `POST /api/app_exclude`
- `GET /api/blacklist`
- `POST /api/blacklist_remove`
- `GET/POST /api/categories`
- `POST /api/categories/delete`

> **鉴权说明（与代码保持一致）**：  
> - 所有写接口（`POST/PUT/PATCH/DELETE`）在代码层都通过 `X-EYECare-Token` Header 做鉴权，Token 由 `GET /api/auth/token` 提供。  
> - 本节仅列数据口径与字段，不再重复展开鉴权逻辑；实际调用时需确保 Header 携带正确的 `X-EYECare-Token`，否则会返回 401 或被拒绝。

## 5) 一致性与恢复

- `flush()`：将内存 WAL 缓冲刷入 WAL 文件。
- `merge()`：将 WAL 合并到主文件并截断 WAL。
- `close()`：幂等，最终分钟封口并 merge。
- 启动时若 `exit_state.need_merge=true`，`AppController` 会先补做 `merge()`。

### 5.1 WAL 幂等边界说明（长期口径）

前因：`rest_complete` 等事件在异常退出/重启/重复触发场景下，可能出现 WAL 重放；为避免重复入账，`json_wal_repo.merge()` 引入了 `minutes + events` 的幂等合并策略。  
后果：统计稳定性显著提升，但该策略是“工程可接受边界”，不是无限制的全历史严格去重。

- `minutes` 语义前提：
`minute_usage` 每行代表“该分钟桶的 app 秒数快照值（snapshot）”，不是增量 delta。  
因此同 `(local_date, minute_start_utc)` 合并时按 app 取 `max`，用于抵抗重复回放。

- `minutes` 内存口径：
`minutes` 合并是“流式读取 + 单日内存聚合”。不会全量 `read_text()`，但会在内存中持有单日聚合结构（约 1440 分钟桶量级，取决于 app 数）。这是当前可接受折中。

- `events` 去重口径：
`events` 使用“主文件尾部窗口 + WAL 批内”近端去重，不保证全历史严格幂等。该策略优先保证运行时成本可控和常见重复回放可抑制。

- 尾部窗口估算口径：
尾读窗口按 `max_lines * 200 bytes` 估算，长行场景可能读不足、短行场景可能读偏多。属于可接受启发式参数，可按现场数据分布调优（例如提高估算系数）。
