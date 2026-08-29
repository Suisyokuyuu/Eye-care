"""Create the updater manifest, release ZIP and SHA-256 sidecar."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from eye_care.update_service import (  # noqa: E402
    MAIN_EXE_NAME,
    MANIFEST_NAME,
    UPDATER_EXE_NAME,
)
from eye_care.version import APP_VERSION  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_name(version: str) -> str:
    if not version or any(ch not in "0123456789." for ch in version):
        raise RuntimeError(f"Invalid release version: {version}")
    return f"EyE-Care-{version}-Windows-x64.zip"


def build_manifest(package_dir: Path, version: str = APP_VERSION) -> dict:
    root = Path(package_dir).resolve()
    if not (root / MAIN_EXE_NAME).is_file():
        raise RuntimeError(f"Missing {MAIN_EXE_NAME} in {root}")
    if not (root / UPDATER_EXE_NAME).is_file():
        raise RuntimeError(f"Missing {UPDATER_EXE_NAME} in {root}")
    files = []
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix().lower()):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        rel = PurePosixPath(path.relative_to(root).as_posix())
        if rel.parts[0].lower() == "user_data":
            continue
        if path.is_symlink():
            raise RuntimeError(f"Release package cannot contain a symlink: {rel}")
        files.append({"path": rel.as_posix(), "size": path.stat().st_size, "sha256": _sha256(path)})
    return {"schema": 1, "product": "EyE Care", "version": version, "files": files}


def write_manifest(package_dir: Path, version: str = APP_VERSION) -> Path:
    root = Path(package_dir).resolve()
    manifest_path = root / MANIFEST_NAME
    payload = build_manifest(root, version)
    temp = manifest_path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, manifest_path)
    return manifest_path


def create_archive(package_dir: Path, output_dir: Path, version: str = APP_VERSION) -> tuple[Path, Path]:
    root = Path(package_dir).resolve()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    write_manifest(root, version)
    archive_name = package_name(version)
    archive = output / archive_name
    temp = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(root.rglob("*"), key=lambda p: p.as_posix().lower()):
            if not path.is_file():
                continue
            rel = PurePosixPath(path.relative_to(root).as_posix())
            if rel.parts[0].lower() == "user_data":
                continue
            bundle.write(path, (PurePosixPath("EyE Care") / rel).as_posix())
    os.replace(temp, archive)
    digest = _sha256(archive)
    checksum = output / (archive_name + ".sha256")
    checksum.write_text(f"{digest}  {archive_name}\n", encoding="ascii")
    return archive, checksum


def write_update_feed(
    archive: Path,
    feed_path: Path,
    *,
    version: str,
    notes: str = "",
) -> Path:
    archive = Path(archive).resolve()
    feed_path = Path(feed_path).resolve()
    if archive.name != package_name(version) or not archive.is_file():
        raise RuntimeError("Release archive is missing or has an unexpected name")
    payload = {
        "schema": 1,
        "product": "EyE Care",
        "channel": "stable",
        "version": version,
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "release_url": "https://github.com/Suisyokuyuu/Eye-care/releases/tag/latest",
        "notes": str(notes or "").strip(),
        "package": {
            "name": archive.name,
            "url": f"https://github.com/Suisyokuyuu/Eye-care/releases/download/latest/{archive.name}",
            "size": archive.stat().st_size,
            "sha256": _sha256(archive),
        },
    }
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    temp = feed_path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, feed_path)
    return feed_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare an EyE Care auto-update release package")
    parser.add_argument("package_dir", nargs="?", default=str(PROJECT_ROOT / "dist" / "EyE Care"))
    parser.add_argument("--version", default=APP_VERSION)
    parser.add_argument("--archive", action="store_true")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "dist"))
    parser.add_argument("--feed-output", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)
    if args.archive:
        archive, checksum = create_archive(Path(args.package_dir), Path(args.output_dir), args.version)
        print(f"Prepared {Path(args.package_dir).resolve() / MANIFEST_NAME}")
        print(f"Created {archive}")
        print(f"Created {checksum}")
        if args.feed_output:
            feed = write_update_feed(archive, Path(args.feed_output), version=args.version, notes=args.notes)
            print(f"Created {feed}")
    elif args.feed_output:
        raise RuntimeError("--feed-output requires --archive")
    else:
        manifest = write_manifest(Path(args.package_dir), args.version)
        print(f"Prepared {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
