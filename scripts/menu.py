"""Unified Chinese menu for Windows development and releases."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.release import publish_source, sync_version
from scripts.release.portable_release import build_source, build_windows

DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"


def clean_builds():
    print("将删除 dist、build 和源码缓存。dist 内已有的使用数据先做备份。")
    if input("输入 y 确认清理：").strip().lower() != "y":
        return
    for path in (DIST_DIR, BUILD_DIR):
        if path.resolve() != PROJECT_ROOT / path.name:
            raise RuntimeError(f"已取消清理，路径指向项目外：{path}")
    data = DIST_DIR / "EyE Care" / "user_data"
    if data.is_dir() and any(data.iterdir()):
        backup = PROJECT_ROOT / "dev_data" / "user-data-backups" / str(uuid.uuid4())
        shutil.copytree(data, backup)
        print(f"使用数据已备份，可将内容复制回原来的 user_data：{backup}")
    for path in (DIST_DIR, BUILD_DIR):
        if path.is_dir():
            shutil.rmtree(path)
            print(f"已删除 {path}")
    for folder in ("eye_care", "scripts", "tests"):
        for parent, dirs, _ in os.walk(PROJECT_ROOT / folder):
            dirs[:] = [name for name in dirs if (Path(parent) / name).resolve() == Path(parent) / name]
            if "__pycache__" in dirs:
                dirs.remove("__pycache__")
                shutil.rmtree(Path(parent) / "__pycache__")
    print("清理完成。")


def change_version(version):
    if not version:
        return
    old, new = sync_version.sync(version)
    print(f"版本号：{old} → {new}。旧版打包用的版本信息也已同步。")


def interactive():
    while True:
        if sys.stdin.isatty() and sys.stdout.isatty():
            os.system("cls" if os.name == "nt" else "clear")
        print(f"EyE Care · 版本与发布    当前源码版本 {sync_version.read_app_version()}\n")
        print("1  制作完整 Windows 包")
        print("2  制作源码更新包")
        print("3  发布稳定版到 GitHub")
        print("4  修改本地版本号")
        print("5  清理构建产物")
        print("0  退出")
        try:
            choice = input("\n选择：").strip()
            if choice == "0":
                return
            if choice in ("1", "2", "3"):
                current = sync_version.read_app_version()
                default = publish_source.suggested_version(current) if choice == "3" else current
                version = input(f"版本号（回车使用 {default}）：").strip() or default
                publish_source.check_version(version)
                if choice == "1":
                    build_windows(version)
                elif choice == "2":
                    print(build_source(version))
                else:
                    publish_source.publish(version)
            elif choice == "4":
                change_version(input("新版本号（回车取消）：").strip())
            elif choice == "5":
                clean_builds()
            else:
                print("请输入菜单中的数字。")
            input("\n按回车返回菜单。")
        except (EOFError, KeyboardInterrupt):
            return
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            print("操作未完成：", exc)
            try:
                input("\n按回车返回菜单。")
            except (EOFError, KeyboardInterrupt):
                return


def main():
    parser = argparse.ArgumentParser(description="EyE Care 版本与发布")
    parser.add_argument("action", nargs="?", choices=("package", "bridge", "source", "publish", "version", "status", "help"))
    parser.add_argument("version", nargs="?")
    args = parser.parse_args()
    if not args.action:
        return interactive()
    if args.action == "help":
        return parser.print_help()
    if args.action == "status":
        print(f"源码版本：{sync_version.read_app_version()}")
        return
    if args.action == "version":
        change_version(args.version)
        return
    current = sync_version.read_app_version()
    version = args.version or (publish_source.suggested_version(current) if args.action == "publish" else current)
    publish_source.check_version(version)
    if args.action in ("package", "bridge"):
        build_windows(version)
    elif args.action == "source":
        print(build_source(version))
    else:
        publish_source.publish(version)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print("操作未完成：", exc, file=sys.stderr)
        raise SystemExit(1)
