"""Standalone, stdlib-only updater implementation run after the app exits."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path, PurePosixPath


MAIN_EXE_NAME = "EyE Care.exe"
MANIFEST_NAME = "update-manifest.json"
PRESERVED_ROOTS = {"user_data"}


class ApplyError(RuntimeError):
    pass


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _safe_rel(value: object) -> Path:
    source = str(value or "")
    if "\\" in source:
        raise ApplyError("manifest contains a non-canonical path")
    raw = source.replace("\\", "/")
    posix = PurePosixPath(raw)
    bad_part = any(
        not part or part in {".", ".."} or ":" in part or part.rstrip(" .") != part
        for part in posix.parts
    )
    if not raw or posix.is_absolute() or bad_part:
        raise ApplyError("manifest contains an unsafe path")
    if posix.parts[0].lower() in PRESERVED_ROOTS:
        raise ApplyError("manifest attempts to replace preserved user data")
    return Path(*posix.parts)


def _load_manifest(root: Path, *, required: bool) -> tuple[dict, list[Path]]:
    path = root / MANIFEST_NAME
    if not path.is_file() and not required:
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ApplyError("cannot read update manifest") from exc
    if data.get("schema") != 1 or data.get("product") != "EyE Care" or not isinstance(data.get("files"), list):
        raise ApplyError("invalid update manifest")
    if any(not isinstance(item, dict) for item in data["files"]):
        raise ApplyError("invalid file entry in update manifest")
    paths = [_safe_rel(item.get("path")) for item in data["files"]]
    if len({path.as_posix().casefold() for path in paths}) != len(paths):
        raise ApplyError("duplicate file path in update manifest")
    if Path(MAIN_EXE_NAME) not in paths:
        raise ApplyError("update manifest does not contain the main executable")
    return data, paths


def _validate_payload(root: Path, manifest: dict, paths: list[Path]) -> None:
    by_path = {_safe_rel(item.get("path")): item for item in manifest["files"]}
    for rel in paths:
        source = root / rel
        if not source.is_file():
            raise ApplyError(f"staged file is missing: {rel}")
        item = by_path[rel]
        try:
            expected_size = int(item.get("size", -1))
        except (TypeError, ValueError) as exc:
            raise ApplyError(f"invalid staged file size: {rel}") from exc
        if expected_size < 0 or source.stat().st_size != expected_size:
            raise ApplyError(f"staged file size check failed: {rel}")
        expected = str(item.get("sha256") or "").lower()
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise ApplyError(f"invalid staged file digest: {rel}")
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ApplyError(f"staged file digest check failed: {rel}")


def _wait_for_process(pid: int, timeout_s: int = 30) -> None:
    if pid <= 0:
        raise ApplyError("invalid parent process id")
    if os.name != "nt":
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.2)
        raise ApplyError("application did not exit in time")
    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return
    try:
        result = ctypes.windll.kernel32.WaitForSingleObject(handle, timeout_s * 1000)
        if result == 0x00000102:
            raise ApplyError("application did not exit in time")
        if result != 0:
            raise ApplyError("failed while waiting for application exit")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.update-{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temp)
        os.replace(temp, target)
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def _prune_empty_parents(path: Path, stop: Path) -> None:
    current = path.parent
    while current != stop:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def apply_update(source_dir: Path, target_dir: Path, data_dir: Path, from_version: str, to_version: str) -> dict:
    source = Path(source_dir).resolve()
    target = Path(target_dir).resolve()
    data = Path(data_dir).resolve()
    if source == target or not source.is_dir() or not target.is_dir():
        raise ApplyError("invalid source or target directory")
    if not (target / MAIN_EXE_NAME).is_file():
        raise ApplyError("target directory is not an EyE Care installation")
    try:
        data.relative_to(target)
    except ValueError:
        pass
    else:
        if data.name.lower() != "user_data":
            raise ApplyError("data directory inside install directory is not the protected user_data folder")

    new_manifest, new_paths = _load_manifest(source, required=True)
    old_manifest, old_paths = _load_manifest(target, required=False)
    if str(new_manifest.get("version") or "") != str(to_version):
        raise ApplyError("staged version does not match requested version")
    _validate_payload(source, new_manifest, new_paths)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_root = data / "updates" / "backups" / f"{from_version}-{stamp}"
    old_manifest_path = target / MANIFEST_NAME
    if old_manifest_path.is_file():
        backup_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_manifest_path, backup_root / MANIFEST_NAME)
    new_by_path = {_safe_rel(item.get("path")): item for item in new_manifest["files"]}
    old_by_path = {
        _safe_rel(item.get("path")): item for item in old_manifest.get("files", []) if isinstance(item, dict)
    }
    changed = {
        rel for rel in new_paths
        if rel not in old_by_path
        or str(old_by_path[rel].get("sha256") or "") != str(new_by_path[rel].get("sha256") or "")
        or not (target / rel).is_file()
        or (target / rel).stat().st_size != int(new_by_path[rel].get("size", -1))
    }
    stale_paths = set(old_paths) - set(new_paths)
    touched = sorted(changed | stale_paths, key=lambda p: p.as_posix().lower())
    existed: set[Path] = set()
    for rel in touched:
        current = target / rel
        if current.is_file():
            existed.add(rel)
            backup = backup_root / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current, backup)

    applied: list[Path] = []
    try:
        # Libraries/resources first and the launcher last: a partially copied package is never launched.
        ordered = sorted(changed, key=lambda p: (p.name.lower() == MAIN_EXE_NAME.lower(), p.as_posix().lower()))
        for rel in ordered:
            _atomic_copy(source / rel, target / rel)
            applied.append(rel)
        for rel in sorted(stale_paths, key=lambda p: len(p.parts), reverse=True):
            stale = target / rel
            if stale.is_file():
                stale.unlink()
                _prune_empty_parents(stale, target)
        _atomic_copy(source / MANIFEST_NAME, target / MANIFEST_NAME)
    except Exception as exc:
        rollback_errors: list[str] = []
        for rel in reversed(touched):
            current = target / rel
            backup = backup_root / rel
            try:
                if rel in existed:
                    _atomic_copy(backup, current)
                elif current.is_file():
                    current.unlink()
            except Exception as rollback_exc:
                rollback_errors.append(f"{rel}: {rollback_exc}")
        if old_manifest and (backup_root / MANIFEST_NAME).is_file():
            try:
                _atomic_copy(backup_root / MANIFEST_NAME, target / MANIFEST_NAME)
            except Exception:
                pass
        else:
            try:
                (target / MANIFEST_NAME).unlink(missing_ok=True)
            except OSError:
                pass
        suffix = f"; rollback errors: {' | '.join(rollback_errors[:5])}" if rollback_errors else ""
        raise ApplyError(f"update copy failed: {exc}{suffix}") from exc

    return {
        "ok": True,
        "status": "updated",
        "from_version": from_version,
        "to_version": to_version,
        "updated_files": len(changed),
        "backup_dir": str(backup_root),
        "finished_at": int(time.time()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EyE Care standalone updater")
    parser.add_argument("--wait-pid", type=int, required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--target-dir", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--from-version", required=True)
    parser.add_argument("--to-version", required=True)
    parser.add_argument("--restart-args-json", default="[]")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir).resolve()
    result_path = data_dir / "updates" / "last-result.json"
    pending_path = data_dir / "updates" / "pending-update.json"
    target_dir = Path(args.target_dir).resolve()
    try:
        restart_args = json.loads(args.restart_args_json)
        if not isinstance(restart_args, list) or any(not isinstance(item, str) for item in restart_args):
            raise ValueError
    except (json.JSONDecodeError, ValueError, TypeError):
        restart_args = []
    try:
        _wait_for_process(args.wait_pid)
        result = apply_update(
            Path(args.source_dir), target_dir, data_dir,
            str(args.from_version), str(args.to_version),
        )
        pending_path.unlink(missing_ok=True)
        _write_json(result_path, result)
        subprocess.Popen([str(target_dir / MAIN_EXE_NAME), *restart_args], cwd=str(target_dir), close_fds=True)
        return 0
    except Exception as exc:
        result = {
            "ok": False,
            "status": "rolled_back",
            "from_version": str(args.from_version),
            "to_version": str(args.to_version),
            "error": str(exc)[:1000],
            "finished_at": int(time.time()),
        }
        try:
            _write_json(result_path, result)
        except Exception:
            pass
        try:
            executable = target_dir / MAIN_EXE_NAME
            if executable.is_file():
                subprocess.Popen([str(executable), *restart_args], cwd=str(target_dir), close_fds=True)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
