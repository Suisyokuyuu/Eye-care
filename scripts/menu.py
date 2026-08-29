"""EyE Care 版本 / 打包菜单（由项目根目录的 menu.bat 拉起）。

----------------------------------------------------------------------
为什么中文界面放在这里、而不是直接写在 menu.bat 里
----------------------------------------------------------------------
cmd.exe 解析含多字节字符的 .bat 是不可靠的：它按字节块读文件、却按字符数重新
定位，遇到中文就会错位，命令被从中间截断、尾巴当成命令执行。日文（CP932）环境
实测报错长这样::

    'ASCII縲・REM' は、内部コマンドまたは外部コマンド... として認識されていません。

那个碎片来自一行 **REM 注释**的中间——所以「中文只放 echo 里」「不放进 () 块」
都不够，唯一可靠的规则是 **.bat 里一个非 ASCII 字节都不能有**（注释也算）。
存 UTF-8 再加 `chcp 65001` 修不好：chcp 只改控制台代码页，改不了 cmd 读文件时
的定位逻辑。

因此 menu.bat 保持纯 ASCII，只负责把控制权交给本文件；Python 按真正的 UTF-8
解码源码，没有这个毛病。（Video 2 Knowledge 的 menu.bat 是同一思路，只不过交给
PowerShell；这里改用 Python——打包本来就要 Python，且逻辑可以写单测。）

菜单项：
  [1] 修改版本号     调 sync_version.py，同时写 version.py 与 version_info.txt
  [2] 打包 exe       可顺便改版本号，然后转发给 scripts/build_exe.bat
  [3] 清理构建产物   删 dist/ build/，再转发给 scripts/clear_pycache.bat
  [4] 发布自动更新   调 publish_release.py，启动 GitHub Actions
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_version as sv  # noqa: E402  （同目录脚本，插完 path 才能 import）

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_BAT = PROJECT_ROOT / "scripts" / "build_exe.bat"
CLEAN_BAT = PROJECT_ROOT / "scripts" / "clear_pycache.bat"
PUBLISH_SCRIPT = PROJECT_ROOT / "scripts" / "publish_release.py"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"

LINE = "=" * 60


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _info(msg: str) -> None:
    print(f"[i] {msg}")


def _ok(msg: str) -> None:
    print(f"[√] {msg}")


def _warn(msg: str) -> None:
    print(f"[!] {msg}")


def _err(msg: str) -> None:
    print(f"[X] {msg}")


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _pause() -> None:
    print()
    try:
        input("按回车返回菜单")
    except (EOFError, KeyboardInterrupt):
        pass


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def _header(title: str) -> None:
    _clear()
    print(LINE)
    print(f"  {title}")
    print(LINE)
    print()


def _current_version() -> str:
    try:
        return sv.read_app_version()
    except Exception:
        return "?"


def _run_bat(path: Path) -> int:
    """转发给既有的 .bat（那两个都是纯 ASCII，可以安全调用）。

    用 cmd /c 起，让它自己的 pause 正常工作；返回退出码。
    """
    if not path.exists():
        _err(f"缺少文件：{path}")
        return 1
    try:
        return subprocess.call(["cmd", "/c", str(path)], cwd=str(PROJECT_ROOT))
    except OSError as exc:
        _err(f"无法运行 {path.name}：{exc}")
        return 1


def _sync(new_version: str | None) -> bool:
    """调 sync_version 落版本号；打印结果，返回是否成功。"""
    try:
        old, new = sv.sync(new_version)
    except sv.VersionError as exc:
        _err(str(exc))
        return False
    except OSError as exc:
        _err(f"写入失败：{exc}")
        return False

    if old == new:
        _info(f"版本号 {new}，已重新生成 version_info.txt")
    else:
        _ok(f"版本号 {old} -> {new}，version.py 与 version_info.txt 均已更新")
    return True


# ---------------------------------------------------------------------------
# 1) 修改版本号
# ---------------------------------------------------------------------------

def action_set_version() -> None:
    _header("修改版本号")
    print(f"  当前版本：{_current_version()}")
    print("  格式示例：1.4.0（可省略开头的 v；写成 1.4 会自动补成 1.4.0）")
    print()
    print("  版本号真源是 eye_care\\version.py。")
    print("  version_info.txt（exe 属性里的版本号）由脚本自动生成，不用手改。")
    print()

    new_version = _ask("请输入新版本号，直接回车取消: ")
    if not new_version:
        return

    print()
    if _sync(new_version):
        print("    程序内「检查更新」和 exe 属性都会用这个版本号。")
    _pause()


# ---------------------------------------------------------------------------
# 2) 打包 exe
# ---------------------------------------------------------------------------

def action_build() -> None:
    _header("打包 exe")
    print(f"  当前版本：{_current_version()}")
    print()

    new_version = _ask("要顺便改版本号吗？输入新版本号，直接回车沿用当前版本: ")
    print()
    if new_version:
        if not _sync(new_version):
            print()
            _err("版本号同步失败，已终止打包。")
            _pause()
            return
        print()

    # 打包实现只有 build_exe.bat 一份，这里只做转发，避免两处逻辑各自漂移。
    # 它内部会再同步一次版本号，所以直接运行它也不会出现版本对不上。
    _info(f"开始打包（以下是 {BUILD_BAT.name} 的输出）...")
    print()
    rc = _run_bat(BUILD_BAT)
    print()
    if rc == 0:
        _ok(f"打包结束（版本 {_current_version()}）。")
        print(f"    产物：{DIST_DIR / 'EyE Care'}")
        print(f"    发布包：{DIST_DIR / f'EyE-Care-{_current_version()}-Windows-x64.zip'}")
        print("    校验值：同名 .zip.sha256 文件")
        print('    可以右键 "EyE Care.exe" → 属性 → 详细信息，核对版本号。')
    else:
        _err(f"打包失败（退出码 {rc}），请看上面的报错。")
    _pause()


# ---------------------------------------------------------------------------
# 3) 清理构建产物
# ---------------------------------------------------------------------------

def action_clean() -> None:
    _header("清理构建产物")
    print("  将删除：dist\\、build\\、以及所有 __pycache__ 目录。")
    _warn("dist\\EyE Care\\user_data 里如果有数据也会一并删除。")
    print()

    if _ask("确认删除吗？输入 y 回车: ").lower() != "y":
        return

    print()
    import shutil

    for d in (DIST_DIR, BUILD_DIR):
        if d.exists():
            try:
                shutil.rmtree(d)
                _info(f"已删除 {d}")
            except OSError as exc:
                _err(f"删除 {d} 失败：{exc}")

    _run_bat(CLEAN_BAT)
    print()
    _ok("清理完成。")
    _pause()


# ---------------------------------------------------------------------------
# 4) 发布自动更新
# ---------------------------------------------------------------------------

def action_publish() -> None:
    _header("发布自动更新")
    print("  将启动 GitHub Actions，在固定 latest Release 中发布新版本。")
    print("  不需要、也不会创建按版本命名的 Tag。")
    print()
    if not PUBLISH_SCRIPT.exists():
        _err(f"缺少文件：{PUBLISH_SCRIPT}")
        _pause()
        return
    try:
        rc = subprocess.call([sys.executable, str(PUBLISH_SCRIPT)], cwd=str(PROJECT_ROOT))
    except OSError as exc:
        _err(f"无法运行发布脚本：{exc}")
        _pause()
        return
    if rc != 0:
        _err(f"发布启动器执行失败（退出码 {rc}）。")


# ---------------------------------------------------------------------------
# 主菜单
# ---------------------------------------------------------------------------

MENU_ITEMS = (
    ("1", "修改版本号      同时写 version.py 与 version_info.txt", action_set_version),
    ("2", "打包 exe        可顺便改版本号，打包前自动同步", action_build),
    ("3", "清理构建产物    删除 dist / build / __pycache__", action_clean),
    ("4", "发布自动更新    启动 GitHub Actions，无需手动 Tag", action_publish),
)


def main() -> int:
    # CP932 等非 UTF-8 控制台下，直接 print 中文会抛 UnicodeEncodeError。
    # menu.bat 已设 PYTHONIOENCODING/PYTHONUTF8，这里再兜一层（也便于单独运行本脚本）。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    while True:
        _clear()
        print(LINE)
        print("  EyE Care - 版本与打包")
        print(LINE)
        print()
        print(f"  项目目录：{PROJECT_ROOT}")
        print(f"  解释器：  {sys.executable}")
        print(f"  当前版本：{_current_version()}")
        print()
        for key, label, _ in MENU_ITEMS:
            print(f"  [{key}] {label}")
        print("  [0] 退出")
        print()

        choice = _ask("请输入序号后回车: ")
        if choice == "0":
            return 0
        if not choice:
            continue

        for key, _, action in MENU_ITEMS:
            if choice == key:
                action()
                break
        else:
            print()
            _warn(f"没有这个选项：{choice}")
            _pause()


if __name__ == "__main__":
    raise SystemExit(main())
