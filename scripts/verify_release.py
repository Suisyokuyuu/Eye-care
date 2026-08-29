"""Verify a release ZIP against its embedded manifest and SHA-256 sidecar."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from eye_care.update_service import MANIFEST_NAME  # noqa: E402
from eye_care.version import APP_VERSION  # noqa: E402


def _hash_stream(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def verify_archive(archive: Path) -> dict:
    archive = Path(archive).resolve()
    if not archive.is_file():
        raise RuntimeError(f"Release archive not found: {archive}")
    prefix = "EyE Care/"
    manifest_member = prefix + MANIFEST_NAME
    with zipfile.ZipFile(archive, "r") as bundle:
        infos = [info for info in bundle.infolist() if not info.is_dir()]
        names = [info.filename.replace("\\", "/") for info in infos]
        if len({name.casefold() for name in names}) != len(names):
            raise RuntimeError("Release ZIP contains duplicate paths")
        if any(not name.startswith(prefix) or ".." in PurePosixPath(name).parts for name in names):
            raise RuntimeError("Release ZIP contains a path outside the product folder")
        try:
            manifest_info = bundle.getinfo(manifest_member)
        except KeyError as exc:
            raise RuntimeError("Release ZIP does not contain update-manifest.json") from exc
        if manifest_info.file_size > 10 * 1024 * 1024:
            raise RuntimeError("Embedded update manifest is unexpectedly large")
        manifest = json.loads(bundle.read(manifest_info).decode("utf-8"))
        if manifest.get("schema") != 1 or manifest.get("product") != "EyE Care":
            raise RuntimeError("Embedded update manifest is invalid")
        raw_files = manifest.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            raise RuntimeError("Embedded update manifest has no files")
        expected_names = {manifest_member}
        for item in raw_files:
            if not isinstance(item, dict):
                raise RuntimeError("Embedded update manifest contains an invalid item")
            rel = str(item.get("path") or "")
            member = prefix + rel
            expected_names.add(member)
            try:
                info = bundle.getinfo(member)
            except KeyError as exc:
                raise RuntimeError(f"Release ZIP is missing {rel}") from exc
            expected_size = int(item.get("size", -1))
            if expected_size < 0 or info.file_size != expected_size:
                raise RuntimeError(f"Release ZIP size check failed for {rel}")
            expected_hash = str(item.get("sha256") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                raise RuntimeError(f"Release manifest digest is invalid for {rel}")
            with bundle.open(info, "r") as stream:
                if _hash_stream(stream) != expected_hash:
                    raise RuntimeError(f"Release ZIP digest check failed for {rel}")
        if set(names) != expected_names:
            extras = sorted(set(names) - expected_names)
            raise RuntimeError(f"Release ZIP contains unlisted files: {extras[:3]}")

    with archive.open("rb") as stream:
        archive_hash = _hash_stream(stream)
    sidecar = archive.with_name(archive.name + ".sha256")
    if sidecar.is_file():
        text = sidecar.read_text(encoding="ascii", errors="strict")
        match = re.search(r"\b([0-9a-fA-F]{64})\b", text)
        if not match or match.group(1).lower() != archive_hash:
            raise RuntimeError("Release SHA-256 sidecar does not match the ZIP")
    return {
        "version": str(manifest.get("version") or ""),
        "files": len(raw_files),
        "size": archive.stat().st_size,
        "sha256": archive_hash,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an EyE Care release archive")
    parser.add_argument("archive")
    args = parser.parse_args(argv)
    archive = Path(args.archive)
    if archive.is_dir():
        archive = archive / f"EyE-Care-{APP_VERSION}-Windows-x64.zip"
    result = verify_archive(archive)
    print(
        "Verified version={version} files={files} bytes={size} sha256={sha256}".format(**result)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
