"""Maintainer BAT and GitHub Actions share the same release packaging commands."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

from .portable_release import (ROOT, OUT, VERSION, build_runtime, build_source,
                               fingerprint, runtime_name, sha)
from eye_care.source_update import BOOT, REPO, github_asset, tree_manifest


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def gh(*args, optional=False):
    cmd = ["gh", *args]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode:
        message = result.stderr.strip()
        if optional and ("HTTP 404" in message or "release not found" in message.lower()):
            return None
        raise RuntimeError(message or "GitHub 命令失败")
    return result.stdout.strip()


def check_version(version):
    if not VERSION.fullmatch(version):
        raise ValueError("版本号请使用三段数字，例如 1.4.1")


def suggested_version(current):
    latest = gh("api", f"repos/{REPO}/releases/latest", optional=True)
    version = str(json.loads(latest)["tag_name"]).removeprefix("v") if latest else ""
    if VERSION.fullmatch(version):
        major, minor, patch = map(int, version.split("."))
        return ".".join(map(str, max((major, minor, patch + 1), tuple(map(int, current.split("."))))))
    return current


def publish(version):
    check_version(version)
    if git("status", "--porcelain"):
        raise ValueError("请先提交并推送要发布的修改，然后重新选择发布。")
    branch = git("branch", "--show-current")
    commit = git("rev-parse", "HEAD")
    ref = git("ls-remote", "--heads", f"https://github.com/{REPO}.git", "refs/heads/"+branch)
    if not branch or not ref or ref.split()[0] != commit:
        raise ValueError("这个提交尚未推到 GitHub 对应分支，请先推送。")
    out = gh("workflow", "run", "source-release.yml", "--repo", REPO, "--ref", branch,
             "-f", "version="+version, "-f", "commit="+commit)
    print(out or "已提交发布任务。")
    print(f"发布进度：https://github.com/{REPO}/actions/workflows/source-release.yml")


def check_candidate(source, runtime_zip, version):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        app = root / "versions" / version
        libs = root / "runtime" / fingerprint()
        with zipfile.ZipFile(source) as z:
            z.extractall(app)
        tree_manifest(app, version)
        with zipfile.ZipFile(runtime_zip) as z:
            z.extractall(libs)
        data = root / "sample-data"
        data.mkdir()
        (data/"config.json").write_text('{"show_onboarding":false,"notion_sync_daily":false,"notion_sync_on_startup":false}')
        probe = subprocess.run([str(libs/"pythonw.exe"), "-I", "-B", "-c", BOOT, str(app/"main.py"),
                                "--startup-check", "--data-dir", str(data)], cwd=root, timeout=60,
                               env={**os.environ, "QT_QPA_PLATFORM":"offscreen", "QT_QUICK_BACKEND":"software"})
        report = json.loads((data / "startup_check.json").read_text("utf-8"))
        if (probe.returncode or not report.get("ok") or report.get("app_version") != version or
                Path(report["source_root"]).resolve() != app.resolve() or
                Path(report["executable"]).resolve() != (libs/"pythonw.exe").resolve()):
            raise ValueError("新版源码和便携运行库启动检查失败")


def ci_release(version, commit):
    check_version(version)
    if not re.fullmatch("[0-9a-f]{40}", commit) or git("rev-parse","HEAD") != commit:
        raise ValueError("发布提交与所选源码不一致")
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REPOSITORY", "").lower() != REPO.lower():
        raise ValueError("正式发布由本项目的 GitHub Actions 执行")
    tag = "v" + version
    if gh("api", f"repos/{REPO}/releases/tags/{tag}", optional=True) is not None:
        raise ValueError("这个正式版本已经发布")
    latest = gh("api", f"repos/{REPO}/releases/latest", optional=True)
    if latest:
        latest_tag = json.loads(latest)["tag_name"].removeprefix("v")
        if VERSION.fullmatch(latest_tag) and tuple(map(int,version.split("."))) <= tuple(map(int,latest_tag.split("."))):
            raise ValueError("正式版本号必须高于当前稳定版")
    existing = git("ls-remote", "--tags", "origin", "refs/tags/"+tag, "refs/tags/"+tag+"^{}")
    if existing and existing.splitlines()[-1].split()[0] != commit:
        raise ValueError("GitHub 上的同名标签已经指向其他提交")
    source = build_source(version)
    key = fingerprint()
    rtag = "runtime-" + key
    runtime = OUT / runtime_name(key)
    rmeta = gh("api", f"repos/{REPO}/releases/tags/{rtag}", optional=True)
    if rmeta:
        expected = github_asset(json.loads(rmeta), rtag, runtime.name)["asset_sha256"]
        if not runtime.is_file() or sha(runtime) != expected:
            gh("release", "download", rtag, "--repo", REPO, "--pattern", runtime.name, "--dir", str(OUT), "--clobber")
        if sha(runtime) != expected:
            raise ValueError("已发布的运行库校验失败")
    else:
        build_runtime()
    check_candidate(source, runtime, version)
    if not rmeta:
        gh("release", "create", rtag, str(runtime), "--repo", REPO, "--target", commit, "--prerelease",
           "--latest=false", "--title", "Windows 运行库 "+key, "--notes", "由 EyE Care 在需要时自动下载。")
    gh("release", "create", tag, str(source), "--repo", REPO, "--target", commit, "--latest",
       "--title", "EyE Care "+tag, "--generate-notes")
    print(f"https://github.com/{REPO}/releases/tag/{tag}")


def main():
    parser = argparse.ArgumentParser(description="在 GitHub Actions 中构建和发布 EyE Care 稳定版")
    parser.add_argument("version")
    parser.add_argument("commit")
    args = parser.parse_args()
    ci_release(args.version, args.commit)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print("发布未完成：", exc, file=sys.stderr)
        raise SystemExit(1)
