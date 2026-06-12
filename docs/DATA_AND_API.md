# 数据与 API

## 数据目录

默认数据目录：

- 源码运行：`./user_data`
- 指定目录：`python main.py --data-dir PATH`
- 打包运行：exe 同级目录下的 `user_data`

主要文件：

```text
config.json                         用户配置
debug.log                           运行日志
app_paths.json                      app_short -> exe_path
app_categories.json                 应用分类映射
exit_state.json                     非干净退出后的待合并标记
minute_usage/minute-YYYY-MM-DD.jsonl 主 usage 数据
events/events-YYYY-MM-DD.jsonl       主事件数据
wal/minutes-YYYY-MM-DD.jsonl         usage WAL
wal/events-YYYY-MM-DD.jsonl          event WAL
app_icons/                           应用图标缓存
transfer_reports/                    导入导出报告
```

## 配置字段

配置模型是 `eye_care.config.models.AppConfig`。重要字段：

- `sample_interval_s`：采样间隔，默认 1 秒。
- `idle_threshold_s`：空闲判定阈值，默认 60 秒。
- `reminder_work_minutes`：连续工作提醒阈值，默认 20 分钟。
- `reminder_rest_seconds` + `reminder_rest_unit`：休息遮罩倒计时。
- `startup_dnd`：启动时进入勿扰。
- `startup_show_main`：启动后显示主窗口。
- `startup_launch_at_login`：开机启动。
- `notify_enabled`：是否启用提醒通知。
- `notify_sound_enabled`：通知音效。
- `notify_auto_hide_seconds`：通知自动隐藏时间。
- `rest_end_sound_enabled`：休息完成音效。
- `app_category_overrides`：应用分类覆盖。
- `app_display_overrides`：应用显示名覆盖。
- `app_auto_dnd_on_focus`：指定应用前台时自动勿扰。
- `blacklist_apps`：不记录的应用。
- `debug_enabled`：debug 路由和更多诊断。
- `sm_notify_v2`：通知状态机实验开关。

## usage 记录

主数据和 WAL 都是 JSONL。minute 记录形态：

```json
{"_schema":"minute@1","minute_start_utc":"2026-06-07T01:00:00Z","local_date":"2026-06-07","apps":{"chrome":32,"code":28}}
```

同一分钟同一应用多次合并时取较稳定的非负秒数。导入导出也会对负数做保护。

## event 记录

事件记录形态：

```json
{"_schema":"event@1","utc_ts":"2026-06-07T01:05:00Z","local_date":"2026-06-07","kind":"rest_complete","payload":{}}
```

事件用于休息统计、跳过统计、模式切换和其他 UI 展示。

## 导入导出

`eye_care.data.transfer` 支持 zip 导入导出：

- 导出格式：`eye_care_export@4`。
- 包含 `_meta.json`、`minute_usage/*.jsonl`、`events/*.jsonl`。
- 导入时校验日期格式，防路径穿越。
- 默认冲突策略是 `merge_conflicts`。
- 导入后调用 `repo.reload_days` 刷新缓存。

## API 速览

只列常用接口，完整实现见 `eye_care/api/routes/`。

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/api/auth/token` | 获取写操作 token |
| GET | `/api/health` | 健康检查 |
| GET | `/api/snapshot` | 首页快照 |
| GET/POST | `/api/config` | 读取/更新配置 |
| GET | `/api/icon?app=APP` | 获取应用图标 |
| GET/POST | `/api/categories` | 分类映射 |
| GET | `/api/category_names` | 分类名列表 |
| POST | `/api/categories/delete` | 删除分类并迁移到其他 |
| GET | `/api/apps_list` | 应用列表 |
| GET | `/api/app_details` | 应用详情 |
| POST | `/api/app_settings` | 更新单应用设置 |
| POST | `/api/app_exclude` | 排除应用并删除统计 |
| GET | `/api/blacklist` | 黑名单 |
| POST | `/api/blacklist_remove` | 移出黑名单 |
| GET | `/api/calendar_month` | 月历数据 |
| POST | `/api/rest/start` | 开始休息 |
| POST | `/api/rest/complete` | 完成休息 |
| POST | `/api/rest/snooze` | 推迟休息 |
| POST | `/api/dnd` | 设置勿扰 |
| POST | `/api/diag/log` | 前端诊断日志 |
| GET | `/api/update/check` | 检查 GitHub release |
| POST | `/api/open_url` | 打开白名单 URL 动作 |

写接口必须带：

```http
X-EYECare-Token: <token>
```

