"""通过 GitHub Actions 发布 EyE Care 自动更新。"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "Suisyokuyuu/Eye-care"
WORKFLOW = "release.yml"
ACTIONS_URL = f"https://github.com/{REPOSITORY}/actions/workflows/{WORKFLOW}"


def _run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
        check=False,
    )


def _output(args: list[str]) -> str:
    result = _run(args, capture=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise RuntimeError(message or f"命令执行失败：{' '.join(args)}")
    return result.stdout.strip()


def _pause() -> None:
    try:
        input("\n按回车退出")
    except (EOFError, KeyboardInterrupt):
        pass


def _current_version() -> str:
    try:
        return _output([sys.executable, "scripts/sync_version.py", "--show"])
    except RuntimeError:
        return "?"


def _next_version(current: str, bump: str, custom: str) -> str:
    if custom:
        return custom
    if not re.fullmatch(r"\d+\.\d+\.\d+", current):
        return "由 GitHub 计算"
    major, minor, patch = map(int, current.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _ensure_publish_ready(gh: str) -> None:
    if _output(["git", "branch", "--show-current"]) != "main":
        raise RuntimeError("当前不是 main 分支。请切换到 main 后重新运行。")
    if _output(["git", "status", "--porcelain", "--untracked-files=all"]):
        raise RuntimeError("工作区还有未提交文件。请先提交后重新运行。")

    print("\n正在检查 GitHub 登录状态……")
    auth = _run([gh, "auth", "status"])
    if auth.returncode != 0:
        raise RuntimeError("GitHub CLI 尚未登录。请先运行：gh auth login")

    print("正在同步远程 main 状态……")
    fetch = _run(["git", "fetch", "--quiet", "origin", "main"])
    if fetch.returncode != 0:
        raise RuntimeError("无法读取远程 main，请检查网络和 Git 凭据。")
    counts = _output(["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"])
    parts = counts.split()
    if parts != ["0", "0"]:
        raise RuntimeError(
            "本地 main 与 GitHub main 不一致。请先执行 git pull 或 git push，确认同步后再发布。"
        )


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    current = _current_version()
    print("=" * 62)
    print("  EyE Care - 发布自动更新")
    print("=" * 62)
    print(f"\n当前版本：{current}")
    print("\n  [1] patch  修复版本，例如 1.3.2 -> 1.3.3")
    print("  [2] minor  功能版本，例如 1.3.2 -> 1.4.0")
    print("  [3] major  大版本，例如 1.3.2 -> 2.0.0")
    print("  [4] 自定义版本")
    print("  [0] 取消")

    try:
        choice = input("\n请选择发布类型：").strip()
    except (EOFError, KeyboardInterrupt):
        return 0
    if choice in {"", "0"}:
        print("已取消，没有运行 GitHub Actions。")
        return 0

    mapping = {"1": "patch", "2": "minor", "3": "major", "4": "patch"}
    if choice not in mapping:
        print("[X] 无效选项。")
        _pause()
        return 2
    bump = mapping[choice]
    custom = ""
    if choice == "4":
        custom = input("请输入完整版本号（例如 2.0.0）：").strip().lstrip("v")
        if not re.fullmatch(r"\d+\.\d+\.\d+", custom):
            print("[X] 版本号格式错误，必须是 X.Y.Z。")
            _pause()
            return 2

    notes = input("更新说明（可以直接回车留空）：").strip()
    next_version = _next_version(current, bump, custom)
    print("\n即将执行：")
    print(f"  目标版本：{next_version}")
    print(f"  更新说明：{notes or '未填写'}")
    print("  发布通道：固定 latest Release（不会创建版本 Tag）")
    print("\nGitHub 将运行测试、打包、上传，并更新 updates/latest.json。")
    if input("确认发布？输入 y 回车：").strip().lower() != "y":
        print("已取消，没有运行 GitHub Actions。")
        return 0

    gh = shutil.which("gh")
    if not gh:
        print("\n[i] 检测到你使用 GitHub Desktop，没有安装 GitHub CLI。")
        print("GitHub Desktop 不包含 gh 命令，因此改用浏览器发布模式。")
        print("\n请先确认 GitHub Desktop 已经 Push 当前代码，然后在打开的页面中：")
        print("  1. 点击 Run workflow")
        print(f"  2. Version increment 选择 {bump}")
        if custom:
            print(f"  3. Optional exact version 填写 {custom}")
        else:
            print("  3. Optional exact version 留空")
        print(f"  4. Optional short update notes 填写：{notes or '留空'}")
        print("  5. 再点击绿色 Run workflow")
        print(f"\n发布页面：{ACTIONS_URL}")
        try:
            opened = webbrowser.open(ACTIONS_URL)
        except webbrowser.Error:
            opened = False
        if opened:
            print("\n[√] 已尝试在默认浏览器中打开发布页面。")
        else:
            print("\n[!] 无法自动打开浏览器，请复制上面的地址访问。")
        print("发布完成后，在 GitHub Desktop 中执行 Fetch origin / Pull origin。")
        _pause()
        return 0

    try:
        _ensure_publish_ready(gh)
    except RuntimeError as exc:
        print(f"\n[X] 发布前检查失败：{exc}")
        _pause()
        return 1

    print("\n正在启动 GitHub Actions……")
    command = [
        gh,
        "workflow",
        "run",
        WORKFLOW,
        "--repo",
        REPOSITORY,
        "--ref",
        "main",
        "--field",
        f"bump={bump}",
        "--field",
        f"custom_version={custom}",
        "--field",
        f"notes={notes}",
    ]
    result = _run(command)
    if result.returncode != 0:
        print("\n[X] GitHub Actions 启动失败，请查看上面的 gh 错误。")
        _pause()
        return result.returncode or 1

    print("\n[√] 发布任务已启动。无需手动创建或填写 Tag。")
    print(f"进度页面：{ACTIONS_URL}")
    print("任务完成后运行 git pull，同步自动写回的新版本号和 manifest。")
    _pause()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
