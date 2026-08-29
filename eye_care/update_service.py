"""Manifest-driven download/staging for the desktop auto updater."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

from eye_care.api.common import _parse_semver
from eye_care.version import APP_VERSION


UPDATE_FEED_URL = "https://raw.githubusercontent.com/Suisyokuyuu/Eye-care/main/updates/latest.json"
RELEASES_URL = "https://github.com/Suisyokuyuu/Eye-care/releases/tag/latest"
MAIN_EXE_NAME = "EyE Care.exe"
UPDATER_EXE_NAME = "EyE Care Updater.exe"
MANIFEST_NAME = "update-manifest.json"
MAX_PACKAGE_BYTES = 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 20_000
_CACHE_TTL_S = 6 * 60 * 60
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:\.\d+)?$")


class UpdateError(RuntimeError):
    """An update could not be checked, staged, or launched safely."""


def _directory_is_writable(path: Path) -> bool:
    marker = Path(path) / f".eyecare-update-write-test-{os.getpid()}-{time.time_ns()}"
    try:
        with marker.open("xb"):
            pass
        return True
    except OSError:
        return False
    finally:
        try:
            marker.unlink()
        except OSError:
            pass


def _safe_version(value: object) -> str:
    version = str(value or "").strip().lstrip("vV")
    if not _VERSION_RE.fullmatch(version):
        raise UpdateError("发布版本号格式无效")
    return version


def _github_download_url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password:
        raise UpdateError("发布资源地址不是受信任的 GitHub HTTPS 地址")
    if not parsed.path.startswith("/Suisyokuyuu/Eye-care/releases/download/latest/"):
        raise UpdateError("发布资源地址不属于 EyE Care 官方仓库")
    return url


def _parse_update_feed(data: object, current_version: str) -> dict:
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("product") != "EyE Care":
        raise UpdateError("更新清单格式无效")
    if str(data.get("channel") or "stable") != "stable":
        raise UpdateError("更新清单不是稳定通道")
    latest = _safe_version(data.get("version"))
    package = data.get("package")
    if not isinstance(package, dict):
        raise UpdateError("更新清单缺少 Windows 安装包")
    asset_name = Path(str(package.get("name") or "")).name
    if not asset_name.lower().endswith(".zip") or "windows-x64" not in asset_name.lower():
        raise UpdateError("更新清单中的安装包名称无效")
    asset_url = _github_download_url(package.get("url"))
    digest = str(package.get("sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise UpdateError("更新清单缺少有效的 SHA-256")
    try:
        asset_size = int(package.get("size") or 0)
    except (TypeError, ValueError) as exc:
        raise UpdateError("更新清单中的安装包大小无效") from exc
    if asset_size <= 0 or asset_size > MAX_PACKAGE_BYTES:
        raise UpdateError("更新清单中的安装包大小异常")
    has_update = _parse_semver(latest) > _parse_semver(current_version)
    return {
        "ok": True,
        "current": current_version,
        "latest": latest,
        "has_update": has_update,
        "html_url": str(data.get("release_url") or RELEASES_URL),
        "release_notes": str(data.get("notes") or "")[:8000],
        "asset_name": asset_name,
        "asset_url": asset_url,
        "asset_size": asset_size,
        "asset_sha256": digest,
        "downloadable": has_update,
        "published_at": str(data.get("published_at") or ""),
        "error": "",
    }


def _manifest_paths(manifest: object) -> list[str]:
    if not isinstance(manifest, dict) or manifest.get("schema") != 1 or manifest.get("product") != "EyE Care":
        raise UpdateError("升级包文件清单无效")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise UpdateError("升级包文件清单为空")
    paths: list[str] = []
    for item in raw_files:
        if not isinstance(item, dict):
            raise UpdateError("升级包文件清单格式错误")
        rel = str(item.get("path") or "")
        posix = PurePosixPath(rel)
        bad_part = any(
            not part or part in {".", ".."} or ":" in part or part.rstrip(" .") != part
            for part in posix.parts
        )
        if (
            not rel or "\\" in rel or posix.is_absolute() or bad_part
            or posix.parts[0].lower() == "user_data"
        ):
            raise UpdateError("升级包包含不安全的文件路径")
        paths.append(posix.as_posix())
    if len({path.casefold() for path in paths}) != len(paths):
        raise UpdateError("升级包文件清单包含重复路径")
    if MAIN_EXE_NAME not in paths or UPDATER_EXE_NAME not in paths:
        raise UpdateError("升级包缺少主程序或独立升级器")
    return paths


def validate_staged_package(package_dir: Path, expected_version: str) -> dict:
    """Validate the extracted file manifest and every payload hash."""
    package_dir = Path(package_dir).resolve()
    manifest_path = package_dir / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError("无法读取升级包文件清单") from exc
    version = _safe_version(manifest.get("version"))
    if version != _safe_version(expected_version):
        raise UpdateError("升级包版本与更新清单不一致")
    paths = _manifest_paths(manifest)
    by_path = {str(item["path"]): item for item in manifest["files"]}
    for rel in paths:
        target = (package_dir / Path(*PurePosixPath(rel).parts)).resolve()
        try:
            target.relative_to(package_dir)
        except ValueError as exc:
            raise UpdateError("升级包文件越出暂存目录") from exc
        if not target.is_file():
            raise UpdateError(f"升级包缺少文件：{rel}")
        item = by_path[rel]
        expected_size = int(item.get("size", -1))
        if expected_size < 0 or target.stat().st_size != expected_size:
            raise UpdateError(f"升级包文件大小校验失败：{rel}")
        expected_sha = str(item.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            raise UpdateError(f"升级包文件摘要缺失：{rel}")
        digest = hashlib.sha256()
        with target.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha:
            raise UpdateError(f"升级包文件校验失败：{rel}")
    return manifest


class UpdateService:
    """Check, download and stage an update; a separate process applies it."""

    def __init__(
        self,
        *,
        data_dir: Path,
        install_dir: Path,
        current_version: str = APP_VERSION,
        timeout_s: float = 15.0,
        logger=None,
    ) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.install_dir = Path(install_dir).resolve()
        self.current_version = _safe_version(current_version)
        self.timeout_s = max(2.0, float(timeout_s))
        self.log = logger
        self.update_root = self.data_dir / "updates"
        self.pending_path = self.update_root / "pending-update.json"
        self.result_path = self.update_root / "last-result.json"
        self._cache: Optional[dict] = None
        self._cache_mono = 0.0

    @property
    def can_auto_install(self) -> bool:
        return bool(getattr(sys, "frozen", False) and (self.install_dir / UPDATER_EXE_NAME).is_file())

    @staticmethod
    def _request_json(url: str, timeout_s: float) -> dict:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"EyE-Care/{APP_VERSION}",
                "Cache-Control": "no-cache",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))

    def check_update(self, *, force: bool = False) -> dict:
        now = time.monotonic()
        if not force and self._cache is not None and now - self._cache_mono < _CACHE_TTL_S:
            return dict(self._cache)
        try:
            data = self._request_json(UPDATE_FEED_URL, self.timeout_s)
            result = _parse_update_feed(data, self.current_version)
            self._cache = dict(result)
            self._cache_mono = now
            return result
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return self._remember({
                    "ok": True, "current": self.current_version, "latest": "", "has_update": False,
                    "html_url": RELEASES_URL, "downloadable": False, "error": "",
                }, now)
            message = "GitHub 请求过于频繁，请稍后再试" if exc.code == 403 else f"读取更新清单失败（HTTP {exc.code}）"
            return {"ok": False, "current": self.current_version, "has_update": False, "error": message}
        except (OSError, ValueError, UpdateError, json.JSONDecodeError) as exc:
            if self.log:
                self.log.warning("update check failed: %s", exc)
            return {"ok": False, "current": self.current_version, "has_update": False, "error": str(exc)[:200]}

    def _remember(self, result: dict, now: float) -> dict:
        self._cache = dict(result)
        self._cache_mono = now
        return result

    def _download_file(
        self,
        url: str,
        target: Path,
        *,
        expected_size: int = 0,
        progress: Optional[Callable[[int, int], None]] = None,
        max_bytes: int = MAX_PACKAGE_BYTES,
    ) -> str:
        _github_download_url(url)
        existing = target.stat().st_size if target.is_file() else 0
        if expected_size and existing > expected_size:
            target.unlink(missing_ok=True)
            existing = 0
        digest = hashlib.sha256()
        if existing:
            with target.open("rb") as current:
                for chunk in iter(lambda: current.read(1024 * 1024), b""):
                    digest.update(chunk)
            if expected_size and existing == expected_size:
                if progress:
                    progress(existing, expected_size)
                return digest.hexdigest()
        headers = {"User-Agent": f"EyE-Care/{APP_VERSION}"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(url, headers=headers)
        received = existing
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            status = int(getattr(response, "status", 0) or response.getcode() or 0)
            resumed = bool(existing and status == 206)
            if existing and not resumed:
                # The CDN ignored Range. Start clean instead of appending a second archive.
                existing = 0
                received = 0
                digest = hashlib.sha256()
            header_size = int(response.headers.get("Content-Length") or 0)
            total = expected_size or (existing + header_size)
            if total > max_bytes:
                raise UpdateError("升级包超过允许的最大大小")
            mode = "ab" if resumed else "wb"
            with target.open(mode) as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > max_bytes:
                        raise UpdateError("升级包超过允许的最大大小")
                    output.write(chunk)
                    digest.update(chunk)
                    if progress:
                        progress(received, total)
        if expected_size and received != expected_size:
            raise UpdateError("升级包下载大小与更新清单不一致")
        return digest.hexdigest()

    @staticmethod
    def _safe_archive_member(info: zipfile.ZipInfo) -> PurePosixPath:
        raw = info.filename.replace("\\", "/")
        path = PurePosixPath(raw)
        bad_part = any(
            not part or part in {".", ".."} or ":" in part or part.rstrip(" .") != part
            for part in path.parts
        )
        if not raw or raw.startswith("/") or path.is_absolute() or bad_part:
            raise UpdateError("升级包包含不安全路径")
        if any(part.lower() == "user_data" for part in path.parts):
            raise UpdateError("升级包不得包含 user_data")
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        if unix_mode and stat.S_ISLNK(unix_mode):
            raise UpdateError("升级包不得包含符号链接")
        if info.flag_bits & 0x1:
            raise UpdateError("升级包不得包含加密文件")
        return path

    def _extract_package(self, archive: Path, destination: Path) -> Path:
        try:
            with zipfile.ZipFile(archive, "r") as bundle:
                infos = bundle.infolist()
                if len(infos) > MAX_ARCHIVE_FILES:
                    raise UpdateError("升级包文件数量异常")
                total = sum(max(0, int(info.file_size)) for info in infos)
                if total > MAX_EXTRACTED_BYTES:
                    raise UpdateError("升级包解压后体积异常")
                members = [(info, self._safe_archive_member(info)) for info in infos]
                member_keys = [path.as_posix().casefold() for _info, path in members]
                if len(set(member_keys)) != len(member_keys):
                    raise UpdateError("升级包包含重复文件路径")
                for info, posix in members:
                    target = destination.joinpath(*posix.parts)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(info, "r") as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
        except (zipfile.BadZipFile, EOFError) as exc:
            raise UpdateError("升级包不是完整有效的 ZIP 文件") from exc

        if (destination / MAIN_EXE_NAME).is_file():
            return destination
        roots = [p for p in destination.iterdir() if p.is_dir()]
        if len(roots) == 1 and (roots[0] / MAIN_EXE_NAME).is_file():
            return roots[0]
        raise UpdateError("升级包目录结构无效")

    def download_and_stage(self, release: dict, progress: Optional[Callable[[int, int], None]] = None) -> dict:
        if not release.get("has_update") or not release.get("downloadable"):
            raise UpdateError(release.get("error") or "没有可自动下载的新版")
        version = _safe_version(release.get("latest"))
        asset_name = Path(str(release.get("asset_name") or "")).name
        if not asset_name.lower().endswith(".zip"):
            raise UpdateError("升级资源不是 ZIP 包")
        expected_sha = str(release.get("asset_sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            raise UpdateError("升级包没有可信 SHA-256")

        self.update_root.mkdir(parents=True, exist_ok=True)
        work_dir = self.update_root / f"stage-{version}"
        work_dir.mkdir(parents=True, exist_ok=True)
        partial_archive = work_dir / (asset_name + ".part")
        archive = work_dir / asset_name
        extract_dir = work_dir / "package"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir()
        try:
            actual_sha = self._download_file(
                str(release.get("asset_url") or ""), partial_archive,
                expected_size=max(0, int(release.get("asset_size") or 0)), progress=progress,
            )
            if actual_sha != expected_sha:
                raise UpdateError("升级包 SHA-256 校验失败")
            os.replace(partial_archive, archive)
            package_root = self._extract_package(archive, extract_dir)
            manifest = validate_staged_package(package_root, version)
            archive.unlink(missing_ok=True)
            pending = {
                "schema": 1,
                "version": version,
                "current_version": self.current_version,
                "package_dir": str(package_root),
                "install_dir": str(self.install_dir),
                "created_at": int(time.time()),
                "file_count": len(manifest.get("files") or []),
            }
            temp_pending = self.pending_path.with_suffix(".tmp")
            temp_pending.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp_pending, self.pending_path)
            return {"ok": True, "ready": True, "version": version, "pending": pending}
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            # Preserve the partial archive for the next automatic/manual retry.
            shutil.rmtree(extract_dir, ignore_errors=True)
            raise
        except Exception:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise

    def get_pending(self) -> Optional[dict]:
        try:
            pending = json.loads(self.pending_path.read_text(encoding="utf-8"))
            version = _safe_version(pending.get("version"))
            package_dir = Path(str(pending.get("package_dir") or "")).resolve()
            if _parse_semver(version) <= _parse_semver(self.current_version):
                return None
            validate_staged_package(package_dir, version)
            return pending
        except (OSError, ValueError, json.JSONDecodeError, UpdateError):
            return None

    def read_last_result(self) -> Optional[dict]:
        try:
            result = json.loads(self.result_path.read_text(encoding="utf-8"))
            return result if isinstance(result, dict) else None
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None

    def cleanup_runtime_helpers(self) -> None:
        runtime_dir = self.update_root / "runtime"
        if runtime_dir.is_dir():
            for path in runtime_dir.glob("EyE-Care-Updater-*.exe"):
                try:
                    path.unlink()
                except OSError:
                    pass
        result = self.read_last_result()
        if result and result.get("ok") and result.get("status") == "updated":
            try:
                version = _safe_version(result.get("to_version"))
                completed_stage = (self.update_root / f"stage-{version}").resolve()
                completed_stage.relative_to(self.update_root.resolve())
                shutil.rmtree(completed_stage, ignore_errors=True)
            except (OSError, ValueError, UpdateError):
                pass

    def launch_installer(self) -> dict:
        if not getattr(sys, "frozen", False):
            raise UpdateError("源码运行模式不会覆盖程序文件，请先构建发布版测试升级")
        pending = self.get_pending()
        if not pending:
            raise UpdateError("已下载的升级包不存在或校验失败，请重新下载")
        installed_helper = self.install_dir / UPDATER_EXE_NAME
        if not installed_helper.is_file():
            raise UpdateError("当前版本缺少独立升级器，无法自动安装")
        runtime_dir = self.update_root / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_helper = runtime_dir / f"EyE-Care-Updater-{os.getpid()}-{int(time.time())}.exe"
        shutil.copy2(installed_helper, runtime_helper)
        args = [
            str(runtime_helper),
            "--wait-pid", str(os.getpid()),
            "--source-dir", str(pending["package_dir"]),
            "--target-dir", str(self.install_dir),
            "--data-dir", str(self.data_dir),
            "--from-version", self.current_version,
            "--to-version", str(pending["version"]),
            "--restart-args-json", json.dumps(sys.argv[1:], ensure_ascii=False),
        ]
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            if _directory_is_writable(self.install_dir):
                subprocess.Popen(args, cwd=str(runtime_dir), close_fds=True, creationflags=creationflags)
            elif os.name == "nt":
                import ctypes

                parameters = subprocess.list2cmdline(args[1:])
                result = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", str(runtime_helper), parameters, str(runtime_dir), 0,
                )
                if int(result) <= 32:
                    raise OSError("管理员授权被取消或升级器启动失败")
            else:
                raise OSError("程序目录不可写")
        except OSError as exc:
            runtime_helper.unlink(missing_ok=True)
            raise UpdateError(f"无法启动独立升级器：{exc}") from exc
        return {"ok": True, "launched": True, "version": pending["version"]}
