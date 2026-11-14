# 开发与打包

面向维护者；用户操作见根目录的 README 和使用手册。

源码运行需要 Python 3.12+：安装 `requirements.txt` 后执行 `python main.py`。`--data-dir <目录>` 指定独立数据目录；`--debug` 开启日志。必要的回归检查使用 `python -m unittest discover -s tests`。

双击 `menu.bat`：1 打包，2 修改版本号，3 清理构建产物。版本唯一来源为 `eye_care/version.py`；`version_info.txt` 由 `python scripts/sync_version.py` 生成，发布者属性从该脚本配置读取。普通版本属性不是数字签名，不能消除 Windows 的“发布者未知”。Windows 代码签名与 SmartScreen 信誉见 [微软官方说明](https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation)。

打包会先保留现有运行数据，使用隔离数据检查真实 EXE 的主界面、同步页和设置页，再生成 ZIP 与 SHA-256。运行数据、密钥、日志及用户背景图不进入发布 ZIP；示例图片使用项目根目录的 screenshot.png。

GitHub 使用固定的 latest Release。上传成对的版本 ZIP 与 .sha256 后再移除旧资产，客户端按 ZIP 文件名判断版本。源码测试通过不代表新 EXE 或真实 Notion 链路已验收。
