# EyE Care

**Windows 护眼提醒 + 应用使用时长统计工具**

在后台安静地记录你每天用了哪些程序、用了多久，在你连续盯屏达到阈值后弹出休息提醒，帮你养成定期休息的习惯。使用记录只保存在本地；网络仅用于获取网站图标（启用浏览器统计时）和检查软件更新。

---

## 功能

- **使用时长统计** — 自动追踪各前台应用的使用时间，按日 / 周 / 月查看，支持任意日期区间
- **休息提醒** — 连续用眼达到设定时长后弹出右下角通知气泡，可「立刻休息」或「跳过本轮」
- **全屏休息遮罩** — 支持多屏，倒计时结束后自动退出
- **自动更新** — 后台检查、下载并校验新版，确认后自动重启完成升级，失败会恢复旧文件

---

## 快速开始

### 下载使用

前往固定的 [`latest` Release](../../releases/tag/latest) 下载最新版 Windows x64 ZIP，解压后双击 `EyE Care.exe`，无需安装 Python 或任何依赖。后续版本由程序自动下载。

### 从源码运行

```bash
git clone https://github.com/Suisyokuyuu/Eye-care.git
cd Eye-care
pip install -r requirements.txt
python main.py
```

常用启动参数：

```bash
python main.py --debug          # 显示调试日志
python main.py --data-dir ./dev_data   # 指定数据目录
python main.py --no-single      # 允许多实例（开发时用）
```

### 改版本号 / 打包

双击项目根目录的 **`menu.bat`**：

| 选项 | 说明 |
|------|------|
| `[1] 修改版本号` | 写 `eye_care/version.py`，并自动重新生成 `version_info.txt` |
| `[2] 打包 exe` | 可顺便改版本号；产出 `dist/EyE Care/`、版本化 ZIP 和 SHA-256 |
| `[3] 清理构建产物` | 删除 `dist/`、`build/`、所有 `__pycache__` |

版本号的唯一真源是 `eye_care/version.py`；`version_info.txt`（exe 属性里显示的版本）
是生成物，**不要手改**。命令行等价写法：

```bash
python scripts/sync_version.py 1.4.0   # 改版本号并重新生成
python scripts/sync_version.py         # 只按现有版本重新生成
```

### 发布新版（无需创建版本 Tag）

仓库使用 `updates/latest.json` 作为唯一更新清单，GitHub Release 只保留一个永久的
`latest` Tag。客户端不读取 Tag 判断版本。

1. 将代码提交并推送到 `main`。
2. 打开 GitHub 仓库的 **Actions → Publish rolling Windows release → Run workflow**。
3. 选择 `patch`、`minor`、`major`，也可以输入指定版本和更新说明。

流水线会自动运行测试、修改版本号、构建程序与独立升级器、生成版本化 ZIP 和
SHA-256、上传到固定 `latest` Release，最后才提交 `updates/latest.json`。不要手动编辑
该清单，也不需要为每个版本创建 Tag。

首次运行前，请在仓库 **Settings → Actions → General → Workflow permissions** 中允许
GitHub Actions 读写仓库内容。工作流第一次发布时会创建唯一的 `latest` Tag/Release，
以后只更新其中的资产。

---

## 界面预览

![EyE Care 主界面](screenshot.png)

---

## 使用手册

详见 [`使用手册.md`](使用手册.md)，包含：

- 主界面各区域说明
- 休息提醒配置
- 系统托盘操作
- 数据备份与迁移
- 常见问题解答

---

## 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11（x64） |
| 运行环境 | 打包版无需额外安装；源码版需 Python 3.12+ |

---

## 技术栈

- **Python 3.12** + **PySide6**（Qt 6）
- **Qt Quick / QML** 原生 UI
- 本地 JSONL + WAL 数据存储
- PyInstaller 打包

---

## 许可证

[MIT](LICENSE)

---
