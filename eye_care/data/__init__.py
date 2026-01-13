"""Data & persistence layer (Renew Step2).

对外只提供“读/写/导入/导出/合并”的能力：
- 上层不需要知道文件结构、路径、JSON 细节
- 设备识别码 device_id 在 data 目录存在期间稳定不变
"""
