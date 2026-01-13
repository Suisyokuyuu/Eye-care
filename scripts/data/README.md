# data（数据与持久化层）

目标：把“文件结构/JSON/原子写入/导入导出/设备码”都封装起来。

## 你需要知道的只有两件事
- `StatsRepository(base_dir).add_app_seconds(...)` 负责累计
- `repo.save()` 负责落盘（会自动创建目录与文件）

## 设备识别码 device_id 规则（已按我们讨论定稿）
- 只要 `base_dir` 仍存在：device_id 稳定不变
- 用户删掉整个 `base_dir`：device_id 重新生成

## 导入策略（Renew V1.0）
- 同 device_id：拒绝导入
- 同 export_id：拒绝导入（去重）
- 通过：按日期+应用秒数进行累加合并
