"""
高危卡死场景自动化测试（基于 pytest）。

说明：
- 测试通过白盒方式启动 Eye Care（main.py 或内部入口），并通过 HTTP API/内部控制类驱动场景；
- 通过 HangDetector 结合 debug.log 中的 DIAG_METRIC_DISPATCH 等诊断信号判断是否存在 GUI 线程卡死/队列卡死。
"""

