# 开发与发布

在 Windows x64 上安装 Python 3.14，运行 `scripts\dev\install_deps.bat` 安装依赖，然后用 `python main.py` 运行源码。可用 `--data-dir` 指定独立数据目录。

## 用 menu.bat 发版

1. 需要安装包时，选 **1 制作完整 Windows 包**，输入要打包的版本号。ZIP 和 SHA-256 校验文件放在 `dist/`。若 `dist/EyE Care/` 还不存在，也会生成这份可直接打开的程序目录。若已有该目录，保留原目录，本次的新程序从 ZIP 解压。首次安装、重新安装或迁移电脑时，都可以使用完整 ZIP。
2. 日常先提交并推送改动。双击根目录的 `menu.bat`，选 **3 发布稳定版到 GitHub**，确认版本号。维护电脑需要 Git、Python 和已登录的 GitHub CLI。首次使用要把 `.github/workflows/source-release.yml` 提交到默认分支，并在仓库启用 GitHub Actions。
3. GitHub 会对选定的提交制作源码包、验证启动，再创建 `v版本号` 标签和 Release。任务结果可在菜单输出的 Actions 链接查看。选 **2 制作源码更新包** 可在本地先检查 ZIP。
4. Python 或依赖更新时，修改 `scripts/release/runtime-lock.json` 中的官方文件地址、版本和 SHA-256。变更运行库目录的构建方式时递增 `layout`。源码包会写入发布时选择的版本号。

也可以直接运行 `menu.bat source 1.4.1`、`menu.bat package 1.4.0` 或 `menu.bat publish 1.4.1`。用 `menu.bat status` 查看源码版本。

## 从旧版转移数据

1. 在旧版导出数据 ZIP，并从系统托盘退出。
2. 将新的完整 Windows 包解压到独立目录，双击里面的 `EyE Care.exe`，再从工具栏导入数据。若要一并保留原设置，可在首次启动前把旧目录的完整 `user_data` 复制到新目录。换 Windows 用户或电脑时，Notion 密钥需要重新填写。

仍在使用旧版更新服务时，可按原有方式把完整 ZIP 和对应校验文件放到固定的 `latest` Release。已经安装固定入口的用户，可以通过“检查更新”安装发布的源码更新。

## 安装与生成目录

- 完整包里的 `docs/`、`README.md` 和 `EyE Care.exe` 在同一层，图片在 `docs/picture/`。
- `EyE Care.exe` 读取 `current.txt`，使用 `runtime/<编号>/pythonw.exe` 运行 `versions/<版本>/main.py`。使用数据保存在安装根目录的 `user_data`。
- 应用内重启升级时，新版初始化成功后才切换当前版本。启动失败会重新启动原版本。
- `dist/` 存放发布包，`build/startup-checks/` 存放本机打包验收记录。若用菜单清理已有构建且其内有使用数据，可在 `dev_data/user-data-backups/` 找到备份。
- 旧版 PyInstaller 配置和版本资源位于 `scripts/release/legacy/`。完整 Windows 包由固定入口、便携运行库和源码组成。只复制 `EyE Care.exe` 无法运行，需要一起保留旁边的 `runtime` 和 `versions`。
