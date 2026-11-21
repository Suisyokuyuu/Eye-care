"""Install immutable source snapshots from the project's versioned GitHub Releases."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
import uuid
import zipfile

from .portable import RUNTIME, VERSION, atomic_text
from .update_service import (UpdateError, UpdateService, MAX_PACKAGE_BYTES, MAX_EXTRACTED_BYTES,
                             MAX_ARCHIVE_FILES, _parse_semver)
from .update_helper import _wait_for_process

REPO = "Suisyokuyuu/Eye-care"
API = f"https://api.github.com/repos/{REPO}/releases"
WEB = f"https://github.com/{REPO}/releases"
BOOT = "import os,runpy,sys; p=sys.argv.pop(1); sys.argv[0]=p; sys.path.insert(0,os.path.dirname(p)); runpy.run_path(p,run_name='__main__')"


def source_name(version):
    return f"EyE-Care-{version}-source.zip"


def runtime_name(runtime):
    return f"EyE-Care-runtime-{runtime}-Windows-x64.zip"


def github_asset(release, tag, name):
    url = f"{WEB}/download/{tag}/{name}"
    if release.get("tag_name") != tag or release.get("draft"):
        raise UpdateError("发布标签无效或尚未公开")
    for a in release.get("assets", []):
        if a.get("name") == name and a.get("state") == "uploaded" and a.get("browser_download_url") == url:
            digest = str(a.get("digest", "")).removeprefix("sha256:")
            size = a.get("size")
            if re.fullmatch(r"[a-f0-9]{64}", digest) and isinstance(size, int) and 0 < size <= MAX_PACKAGE_BYTES:
                return {"asset_url": url, "asset_name": name, "asset_sha256": digest, "asset_size": size}
    raise UpdateError("发布文件还未就绪，或缺少 GitHub 的 SHA-256 校验值")


def source_file(rel):
    if rel in {"main.py", "updater_main.py", "runtime-id.txt", "source-manifest.json", "README.md",
               "LICENSE", "使用手册.md", "Notion配置指南.html", "docs/notion-report-viewer.html",
               "picture/icon.png", "picture/icon.ico", "picture/screenshot.png",
               "docs/picture/icon.png", "docs/picture/icon.ico", "docs/picture/screenshot.png",
               "docs/Notion配置指南.html", "docs/development.md"}:
        return True
    return rel.startswith("eye_care/") and Path(rel).suffix in {".py", ".qml", ".js", ".wav", ".yml"}


def tree_manifest(folder, version):
    info = json.loads((folder / "source-manifest.json").read_text(encoding="utf-8"))
    runtime = (folder / "runtime-id.txt").read_text(encoding="ascii").strip()
    if info.get("version") != version or info.get("runtime") != runtime or not RUNTIME.fullmatch(runtime):
        raise UpdateError("源码版本或运行库编号不匹配")
    files = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    expected = info.get("files", {})
    if files != set(expected) | {"source-manifest.json"} or not {"main.py", "eye_care/version.py", "runtime-id.txt"} <= files:
        raise UpdateError("源码文件清单不完整")
    for rel, digest in expected.items():
        if not source_file(rel) or hashlib.sha256((folder / rel).read_bytes()).hexdigest() != digest:
            raise UpdateError("源码文件校验失败：" + rel)
    return runtime


def unpack(archive, folder, *, source):
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) > MAX_ARCHIVE_FILES or sum(i.file_size for i in infos) > MAX_EXTRACTED_BYTES:
            raise UpdateError("下载包超出大小限制")
        seen = set()
        for i in infos:
            path = UpdateService._safe_archive_member(i)
            if (any(p in {"", ".", ".."} or os.path.isreserved(p) for p in i.filename.rstrip("/").split("/"))
                    or "\\" in i.filename or path.as_posix().casefold() in seen):
                raise UpdateError("下载包包含无效或重复路径")
            seen.add(path.as_posix().casefold())
            if i.is_dir():
                continue
            if source and not source_file(path.as_posix()):
                raise UpdateError("源码包包含意外文件")
            dest = folder.joinpath(*path.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, dest.open("xb") as out:
                shutil.copyfileobj(src, out)


@contextlib.contextmanager
def install_lock(root):
    import msvcrt
    with (root / ".source-update.lock").open("a+b") as f:
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise UpdateError("另一个 EyE Care 正在更新，请稍后重试") from exc
        try:
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


class SourceUpdateService(UpdateService):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pending_path = self.update_root / "source-pending.json"
        self.result_path = self.update_root / "source-result.json"

    @property
    def can_auto_install(self):
        return (self.install_dir / "current.txt").is_file() and (self.install_dir / "EyE Care.exe").is_file() and (
            Path(sys.executable).resolve().parent.parent == self.install_dir / "runtime")

    @staticmethod
    def _validate_asset_url(url):
        p = urlsplit(url)
        if (p.scheme != "https" or p.netloc != "github.com" or p.query or p.fragment or
                not re.fullmatch(r"/Suisyokuyuu/Eye-care/releases/download/(v[0-9.]+|runtime-[a-f0-9]{16})/EyE-Care-[a-zA-Z0-9.-]+\.zip", p.path)):
            raise UpdateError("更新地址不属于本项目正式发布页")

    def check_update(self, *, force=False):
        now = time.monotonic()
        if not force and self._cache is not None and now - self._cache_mono < 21600:
            return dict(self._cache)
        base = dict(ok=True, current=self.current_version, has_update=False, latest="", downloadable=False,
                    html_url=WEB, release_notes="")
        try:
            data = self._request_json(API + "/latest", self.timeout_s)
            tag = str(data.get("tag_name", ""))
            if tag == "latest" or data.get("prerelease") or data.get("draft"):
                return self._remember(base, now)
            version = tag.removeprefix("v")
            if tag != "v" + version or not VERSION.fullmatch(version):
                raise UpdateError("未识别的正式发布版本")
            newer = _parse_semver(version) > _parse_semver(self.current_version)
            base.update(latest=version, has_update=newer, html_url=f"{WEB}/tag/{tag}",
                        release_notes=str(data.get("body") or "")[:8000])
            if newer:
                base.update(github_asset(data, tag, source_name(version)), downloadable=True)
            return self._remember(base, now)
        except HTTPError as exc:
            if exc.code == 404:
                return self._remember(base, now)
            return {**base, "ok": False, "error": f"GitHub 返回 HTTP {exc.code}"}
        except (OSError, ValueError, UpdateError) as exc:
            return {**base, "ok": False, "error": str(exc)[:200]}

    def _install_asset(self, asset, dest, *, source, progress):
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".download-", dir=dest.parent) as scratch:
            work = Path(scratch)
            archive = work / "payload.zip"
            digest = self._download_file(asset["asset_url"], archive, expected_size=asset["asset_size"], progress=progress)
            if digest != asset["asset_sha256"]:
                raise UpdateError("下载文件 SHA-256 校验失败")
            folder = work / "unpacked"
            folder.mkdir()
            unpack(archive, folder, source=source)
            if source:
                tree_manifest(folder, dest.name)
            elif (not (folder / "pythonw.exe").is_file() or
                  (folder / "runtime-id.txt").read_text(encoding="ascii").strip() != dest.name):
                raise UpdateError("运行库内容与源码声明不一致")
            folder.rename(dest)

    def download_and_stage(self, release, progress=None):
        version = str(release.get("latest") or "")
        if not VERSION.fullmatch(version) or not release.get("downloadable") or _parse_semver(version) <= _parse_semver(self.current_version):
            raise UpdateError("没有可安装的源码更新")
        with install_lock(self.install_dir):
            dest = self.install_dir / "versions" / version
            if not dest.exists():
                self._install_asset(release, dest, source=True, progress=progress)
            runtime = tree_manifest(dest, version)
            libs = self.install_dir / "runtime" / runtime
            if not libs.is_dir():
                tag = "runtime-" + runtime
                meta = self._request_json(API + "/tags/" + tag, self.timeout_s)
                self._install_asset(github_asset(meta, tag, runtime_name(runtime)), libs, source=False, progress=progress)
            if not (libs / "pythonw.exe").is_file() or (libs / "runtime-id.txt").read_text("ascii").strip() != runtime:
                raise UpdateError("便携运行库缺失或损坏")
            self.update_root.mkdir(parents=True, exist_ok=True)
            pending = {"version": version, "from": self.current_version, "install": str(self.install_dir)}
            atomic_text(self.pending_path, json.dumps(pending))
            return pending

    def cleanup_runtime_helpers(self):
        # Versioned folders also serve as the last known working installation.
        pass

    def get_pending(self):
        try:
            plan = json.loads(self.pending_path.read_text("utf-8"))
            version = plan["version"]
            if (plan["install"] == str(self.install_dir) and plan["from"] == self.current_version and
                    VERSION.fullmatch(version) and _parse_semver(version) > _parse_semver(self.current_version)
                    and (self.install_dir / "versions" / version / "source-manifest.json").is_file()):
                return plan
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def launch_installer(self):
        plan = self.get_pending()
        if not self.can_auto_install or not plan:
            raise UpdateError("没有可安装的便携更新")
        app = Path(__file__).resolve().parents[1]
        boot = "import sys,runpy; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module('eye_care.source_update',run_name='__main__')"
        args = [sys.executable, "-I", "-B", "-c", boot, str(app), str(os.getpid()), str(self.data_dir), json.dumps(sys.argv[1:])]
        subprocess.Popen(args, cwd=self.install_dir, close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return {"ok": True, "launched": True, "version": plan["version"]}


def activate(service, args):
    root = service.install_dir
    with install_lock(root):
        plan = service.get_pending()
        current = (root / "current.txt").read_text("ascii").strip()
        if not plan or plan["from"] != current:
            raise UpdateError("版本已切换或待升级记录已过期")
        version = plan["version"]
        app = root / "versions" / version
        runtime = tree_manifest(app, version)
        ready = service.update_root / ("ready-" + uuid.uuid4().hex)
        child = None
        try:
            child = subprocess.Popen([str(root / "runtime" / runtime / "pythonw.exe"), "-I", "-B", "-c",
                                      BOOT, str(app / "main.py"), *args], cwd=root,
                                     env={**os.environ, "EYECARE_TRIAL_READY": str(ready)})
            deadline = time.monotonic() + 60
            while not ready.is_file():
                if (child.poll() is not None and not ready.is_file()) or time.monotonic() >= deadline:
                    raise UpdateError("新版启动未完成，已恢复原版本")
                time.sleep(0.15)
            if ready.read_text("utf-8") != version or child.poll() not in (None, 0):
                raise UpdateError("新版启动确认无效")
            atomic_text(root / "previous.txt", current)
            atomic_text(root / "current.txt", version)
        except BaseException:
            if child is not None and child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
            raise
        finally:
            ready.unlink(missing_ok=True)
        return {"ok": True, "status": "updated", "to_version": version}


def main():
    from .bootstrap.constants import INSTALL_ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("pid", type=int)
    parser.add_argument("data", type=Path)
    parser.add_argument("args")
    options = parser.parse_args()
    service = SourceUpdateService(install_dir=INSTALL_ROOT, data_dir=options.data)
    args = json.loads(options.args)
    _wait_for_process(options.pid)
    try:
        result = activate(service, args)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)[:240]}
        atomic_text(service.result_path, json.dumps(result, ensure_ascii=False))
        service.pending_path.unlink(missing_ok=True)
        subprocess.Popen([str(INSTALL_ROOT / "EyE Care.exe"), *args], cwd=INSTALL_ROOT)
        return 1
    atomic_text(service.result_path, json.dumps(result))
    service.pending_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
