"""版本号单一真源工具：`eye_care/version.py` → 生成 `version_info.txt`。

`version_info.txt` 是**构建期产物**（PyInstaller 把它写进 exe 的「属性 → 详细信息」），
以前要手工维护、极易和 `version.py` 对不上。现在它由本脚本生成，不要再手改。

用法::

    python scripts/sync_version.py            # 按 version.py 现有版本重新生成 version_info.txt
    python scripts/sync_version.py 1.4.0      # 改版本号，再重新生成
    python scripts/sync_version.py --show     # 只打印当前版本，不写任何文件

版本号格式：`X.Y.Z`（可写 `X.Y` 或 `X.Y.Z.B`，会自动补零到四段）。
**建议至少写满三段**——检查更新用的 `api/common._parse_semver` 只认 `\\d+\\.\\d+\\.\\d+`，
两段的 `1.3` 会被解析成 `(0,0,0)`，导致任何线上版本都被判成"有新版本"。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERSION_PY = PROJECT_ROOT / "eye_care" / "version.py"
VERSION_INFO = PROJECT_ROOT / "version_info.txt"

# exe 属性里的固定字段（与版本号无关的部分）。要改公司名/版权年份就改这里。
COMPANY_NAME = "EyE Care"
FILE_DESCRIPTION = "EyE Care - Eye Care Reminder"
INTERNAL_NAME = "EyE Care"
LEGAL_COPYRIGHT = "Copyright © 2026"
ORIGINAL_FILENAME = "EyE Care.exe"
PRODUCT_NAME = "EyE Care"
# 语言/代码页：0804=简体中文，04b0=1200(Unicode)。两处必须成对。
LANG_CODEPAGE = "080404b0"
TRANSLATION = "[2052, 1200]"

_APP_VERSION_RE = re.compile(r'^(APP_VERSION\s*=\s*)(["\']).*?\2', re.MULTILINE)
_VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}$")


class VersionError(ValueError):
    """版本号格式错误（供调用方区分于其它异常）。"""


def parse_version(raw: str) -> tuple[int, int, int, int]:
    """`"v1.4"` / `"1.4.0"` / `"1.4.0.2"` → `(1, 4, 0, 0)` 四元组（不足补零）。"""
    s = str(raw or "").strip()
    s = re.sub(r"^[vV]", "", s)
    if not _VERSION_RE.match(s):
        raise VersionError(
            f"版本号格式不正确：{raw!r}（应为 1.4 / 1.4.0 / 1.4.0.2 这样的数字段）"
        )
    parts = [int(p) for p in s.split(".")]
    parts += [0] * (4 - len(parts))
    return tuple(parts)  # type: ignore[return-value]


def app_version_str(parts: tuple[int, int, int, int]) -> str:
    """写进 `version.py` 的版本号：取前三段（`_parse_semver` 要求满三段）。"""
    return ".".join(str(p) for p in parts[:3])


def file_version_str(parts: tuple[int, int, int, int]) -> str:
    """写进 exe 属性的版本号：四段。"""
    return ".".join(str(p) for p in parts)


def read_app_version() -> str:
    """从 `version.py` 读出当前 APP_VERSION 字面量。读不到抛 VersionError。"""
    text = VERSION_PY.read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        raise VersionError(f"{VERSION_PY} 里找不到 APP_VERSION")
    return m.group(1)


def replace_app_version(source: str, version: str) -> str:
    """把源码里的 `APP_VERSION = "..."` 换成新版本号，其余内容（含注释）原样保留。"""
    new_source, n = _APP_VERSION_RE.subn(
        lambda m: f'{m.group(1)}"{version}"', source, count=1
    )
    if n != 1:
        raise VersionError("version.py 里没有找到 APP_VERSION 赋值行")
    return new_source


def render_version_info(parts: tuple[int, int, int, int]) -> str:
    """按版本号渲染 version_info.txt 全文（PyInstaller 的 VSVersionInfo 结构）。"""
    vers = ", ".join(str(p) for p in parts)
    fv = file_version_str(parts)
    return f"""# UTF-8
# 本文件由 scripts/sync_version.py 生成，请勿手改。
# 改版本号：双击项目根目录的 menu.bat，或运行 python scripts/sync_version.py X.Y.Z
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({vers}),
    prodvers=({vers}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'{LANG_CODEPAGE}',
          [
            StringStruct(u'CompanyName', u'{COMPANY_NAME}'),
            StringStruct(u'FileDescription', u'{FILE_DESCRIPTION}'),
            StringStruct(u'FileVersion', u'{fv}'),
            StringStruct(u'InternalName', u'{INTERNAL_NAME}'),
            StringStruct(u'LegalCopyright', u'{LEGAL_COPYRIGHT}'),
            StringStruct(u'OriginalFilename', u'{ORIGINAL_FILENAME}'),
            StringStruct(u'ProductName', u'{PRODUCT_NAME}'),
            StringStruct(u'ProductVersion', u'{fv}')
          ]
        )
      ]
    ),
    VarFileInfo(
      [
        VarStruct(u'Translation', {TRANSLATION})
      ]
    )
  ]
)
"""


def sync(new_version: str | None = None) -> tuple[str, str]:
    """把版本号落到两个文件。返回 (旧 APP_VERSION, 新 APP_VERSION)。

    `new_version=None` 表示不改版本、只按现值重新生成 version_info.txt。
    """
    old = read_app_version()
    parts = parse_version(new_version if new_version is not None else old)
    new = app_version_str(parts)

    if new != old:
        source = VERSION_PY.read_text(encoding="utf-8")
        VERSION_PY.write_text(replace_app_version(source, new), encoding="utf-8")

    VERSION_INFO.write_text(render_version_info(parts), encoding="utf-8")
    return old, new


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="同步版本号：version.py（真源）→ version_info.txt（生成物）"
    )
    ap.add_argument("version", nargs="?", help="新版本号，如 1.4.0；省略则只重新生成")
    ap.add_argument("--show", action="store_true", help="只打印当前版本号，不写文件")
    args = ap.parse_args(argv)

    try:
        if args.show:
            print(read_app_version())
            return 0
        old, new = sync(args.version)
    except VersionError as exc:
        print(f"[X] {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"[X] 写入失败：{exc}", file=sys.stderr)
        return 2

    if old == new:
        print(f"[i] 版本号 {new}，已重新生成 version_info.txt")
    else:
        print(f"[√] 版本号 {old} -> {new}，version.py 与 version_info.txt 均已更新")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
