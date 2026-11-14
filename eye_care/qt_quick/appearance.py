"""Import a local wallpaper only when settings are applied."""
import hashlib
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImageReader


def wallpaper_url(data_dir, relative):
    if not relative:
        return ""
    root = Path(data_dir).resolve()
    path = (root / relative).resolve()
    return QUrl.fromLocalFile(str(path)).toString() if path.is_relative_to(root) and path.is_file() else ""


def import_wallpaper(data_dir, value):
    if not value:
        return ""
    url = QUrl(value)
    if not url.isLocalFile():
        raise ValueError("请选择电脑上的背景图片。")
    source = Path(url.toLocalFile())
    if not source.is_file() or source.stat().st_size > 30 * 1024 * 1024:
        raise ValueError("背景图片不存在或超过 30 MB。")
    reader = QImageReader(str(source))
    size = reader.size()
    if not reader.canRead() or not size.isValid() or size.width() * size.height() > 40_000_000:
        raise ValueError("无法读取该图片，或分辨率过大；请使用 JPG、PNG、WebP 或 BMP。")
    fmt = bytes(reader.format()).decode("ascii").lower()
    if fmt not in ("jpeg", "jpg", "png", "webp", "bmp"):
        raise ValueError("请使用 JPG、PNG、WebP 或 BMP 背景图片。")
    data = source.read_bytes()
    relative = f"backgrounds/{hashlib.sha256(data).hexdigest()[:24]}.{fmt}"
    target = Path(data_dir) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
    return relative
