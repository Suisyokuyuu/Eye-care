"""Qt Quick (QML) 前端 — 渐进式迁移自 QWebEngine。

主窗(AppShell)、仪表盘左右栏、设置/黑名单/应用/日历、休息+通知浮层全部原生 QML；
经 EYECARE_QML_SHELL=1 灰度启用。后端 bridge/controller/services 完全复用，仅视图层换成 QML。
"""
