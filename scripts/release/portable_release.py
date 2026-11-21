"""Build Windows packages, source updates and the reusable portable runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from eye_care.portable import VERSION
from eye_care.source_update import REPO, runtime_name, source_name, source_file, tree_manifest
from eye_care.version import APP_VERSION
from scripts.release.package_release import create_archive
from scripts.release.verify_release import verify_archive
from scripts.release.check_packaged_startup import verify_startup
from scripts.release.sync_version import replace_app_version

DIST = ROOT / "dist"
OUT = DIST / "source-releases"
LOCK = Path(__file__).with_name("runtime-lock.json")


def fingerprint():
    canonical = json.dumps(json.loads(LOCK.read_text("utf-8")), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def zip_tree(folder, target, *, runtime=False):
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix=".tmp") as f:
        tmp = Path(f.name)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as z:
            for path in sorted(folder.rglob("*")):
                rel = path.relative_to(folder).as_posix()
                if runtime and rel.startswith(("Lib/site-packages/bin/", "Lib/site-packages/Scripts/")):
                    continue
                if path.is_file():
                    # Rebuilding a release from the same commit yields the same source asset.
                    info = zipfile.ZipInfo(path.relative_to(folder).as_posix(), (2020, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    with path.open("rb") as src, z.open(info, "w") as out:
                        shutil.copyfileobj(src, out, length=1024*1024)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def collect_source(folder, version, *, public_root=None):
    if not VERSION.fullmatch(version):
        raise ValueError("版本格式应为 1.4.0")
    folder.mkdir(parents=True, exist_ok=True)
    names = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                    cwd=ROOT).decode("utf-8").split("\0")
    # Older installed launchers and updaters still expect these source ZIP paths.
    archive_paths = {
        "docs/Notion配置指南.html": "Notion配置指南.html",
        **{f"docs/picture/{name}": f"picture/{name}" for name in ("icon.ico", "icon.png", "screenshot.png")},
    } if public_root is None else {}
    for name in names:
        source = ROOT / name
        target = archive_paths.get(name, name)
        if (not name or not source_file(target) or not source.is_file() or source.is_symlink()
                or (public_root is None and name == "docs/development.md")):
            continue
        is_public = name.startswith("docs/") or name in {"README.md", "LICENSE"}
        dest = (public_root if public_root is not None and is_public else folder) / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    # The fixed launcher in already-installed builds resolves this path.
    shutil.copyfile(folder / "eye_care/updater_main.py", folder / "updater_main.py")
    if public_root is None:
        readme = folder / "README.md"
        text = readme.read_text("utf-8")
        for original, target in archive_paths.items():
            text = text.replace(f"({original})", f"({target})")
        text = text.replace("(docs/development.md)", f"(https://github.com/{REPO}/blob/main/docs/development.md)")
        readme.write_text(text, encoding="utf-8", newline="\n")
    py = folder / "eye_care/version.py"
    py.write_text(replace_app_version(py.read_text("utf-8"), version), encoding="utf-8", newline="\n")
    runtime = fingerprint()
    (folder / "runtime-id.txt").write_text(runtime, encoding="ascii")
    files = {p.relative_to(folder).as_posix():sha(p) for p in sorted(folder.rglob("*")) if p.is_file()}
    info = {"version":version, "runtime":runtime, "files":files}
    (folder / "source-manifest.json").write_text(json.dumps(info, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tree_manifest(folder, version)


def build_source(version):
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        collect_source(Path(tmp), version)
        target = OUT / source_name(version)
        zip_tree(Path(tmp), target)
    return target


def downloaded(item):
    cache = ROOT / "build/portable-downloads"
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / item["file"]
    if dest.is_file() and sha(dest) == item["sha256"]:
        return dest
    with tempfile.NamedTemporaryFile(dir=cache, delete=False, suffix=".download") as f:
        tmp = Path(f.name)
    try:
        with urlopen(item["url"], timeout=120) as stream, tmp.open("wb") as f:
            shutil.copyfileobj(stream, f, length=1024*1024)
        if sha(tmp) != item["sha256"]:
            raise RuntimeError("官方运行库文件校验失败：" + dest.name)
        os.replace(tmp, dest)
        return dest
    finally:
        tmp.unlink(missing_ok=True)


def build_runtime():
    lock = json.loads(LOCK.read_text("utf-8"))
    if os.name != "nt" or sys.version_info[:2] != tuple(map(int, lock["python"].split(".")[:2])) or sys.maxsize < 2**32:
        raise RuntimeError("制作运行库需要 Windows x64 和匹配的 Python 3.14")
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / runtime_name(fingerprint())
    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(downloaded(lock["embed"])) as z:
            z.extractall(root)
        libs = root / "Lib/site-packages"
        wheels = [downloaded(w) for w in lock["wheels"]]
        with tempfile.TemporaryDirectory(dir=OUT) as settings:
            requirements = Path(settings) / "requirements.txt"
            lines = []
            for wheel, item in zip(wheels, lock["wheels"]):
                package, version, _ = wheel.name.split("-", 2)
                lines.append(f"{package}=={version} --hash=sha256:{item['sha256']}")
            requirements.write_text("\n".join(lines), encoding="ascii")
            subprocess.run([sys.executable, "-m", "pip", "--isolated", "install", "--disable-pip-version-check",
                            "--no-index", "--no-deps", "--no-compile", "--require-hashes", "--find-links",
                            str(wheels[0].parent), "--target", str(libs), "-r", str(requirements)], check=True)
        for dll in (libs / "pywin32_system32").glob("*.dll"):
            shutil.copy2(dll, root / dll.name)
        pth = next(root.glob("python*._pth"))
        pth.write_text(pth.name.replace("._pth", ".zip") + "\n.\nLib/site-packages\nLib/site-packages/win32\n"
                       "Lib/site-packages/win32/lib\nLib/site-packages/Pythonwin\nimport site\n", encoding="ascii")
        (root / "runtime-id.txt").write_text(fingerprint(), encoding="ascii")
        subprocess.run([str(root/"python.exe"), "-I", "-B", "-c",
                        "from PySide6 import QtQuick, QtQuickControls2; import yaml,psutil,win32crypt,comtypes.client; from PIL import Image"],
                       cwd=root, check=True)
        zip_tree(root, target, runtime=True)
    return target


def build_windows(version):
    if not VERSION.fullmatch(version):
        raise ValueError("版本号请使用三段数字，例如 1.4.1")
    DIST.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".windows-", dir=DIST) as tmp:
        work = Path(tmp)
        folder = work / "EyE Care"
        app = folder / "versions" / version
        runtime = fingerprint()
        libs = folder / "runtime" / runtime
        collect_source(app, version, public_root=folder)
        runtime_zip = OUT / runtime_name(runtime)
        if not runtime_zip.is_file():
            runtime_zip = build_runtime()
        with zipfile.ZipFile(runtime_zip) as z:
            z.extractall(libs)
        (folder / "current.txt").write_text(version, encoding="ascii")
        csc = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        exe = folder / "EyE Care.exe"
        subprocess.run([str(csc), "/nologo", "/target:winexe", "/platform:x64", "/optimize+",
                        "/reference:System.Windows.Forms.dll", "/utf8output", "/codepage:65001",
                        "/win32icon:"+str(folder/"docs/picture/icon.ico"), "/out:"+str(exe),
                        str(Path(__file__).with_name("Launcher.cs"))], check=True)
        shutil.copy2(exe, folder / "EyE Care Updater.exe")
        archive, checksum = create_archive(folder, work, version)
        verify_archive(archive)
        install_dir = DIST / folder.name
        occupied = install_dir.exists()
        verify_startup(folder)
        if not occupied:
            folder.rename(install_dir)
        os.replace(archive, DIST / archive.name)
        os.replace(checksum, DIST / checksum.name)
    if occupied:
        print(f"已有程序目录保留在 {install_dir}。本次的新程序在 ZIP 中。")
    else:
        print("入口 EXE：", install_dir / exe.name, sep="\n")
    print("完整 ZIP 和校验文件：", DIST / archive.name, DIST / checksum.name, sep="\n")
    return DIST / archive.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("source", "runtime", "runtime-id", "package", "bridge"))
    parser.add_argument("--version", default=APP_VERSION)
    args = parser.parse_args()
    if args.action == "runtime-id":
        print(fingerprint())
    elif args.action == "runtime":
        print(build_runtime())
    elif args.action == "source":
        print(build_source(args.version))
    else:
        build_windows(args.version)


if __name__ == "__main__":
    main()
