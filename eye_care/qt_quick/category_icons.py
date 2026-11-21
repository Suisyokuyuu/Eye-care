"""Built-in and user-selected icons for the local category view."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot

from eye_care.bootstrap.constants import ASSETS_DIR
from eye_care.portable import atomic_text


PRESETS = (
    ("game", "游戏"), ("browser", "浏览器"), ("chat", "通讯"), ("code", "开发"),
    ("art", "创作"), ("media", "媒体"), ("office", "办公"), ("reading", "阅读"),
    ("tools", "工具"), ("files", "文件"), ("music", "音乐"), ("video", "视频"),
    ("study", "学习"), ("calendar", "计划"), ("rest", "休息"), ("sparkle", "其他"),
)
DEFAULTS = {name: key for key, name in PRESETS}
DEFAULTS.update({"系统": "tools", "娱乐": "game", "未分类": "sparkle", "工作": "office"})
_PNG_PREFIX = "data:image/png;base64,"
_MAX_IMAGE_BYTES = 12 * 1024 * 1024


class CategoryIcons(QObject):
    changed = Signal()

    def __init__(self, data_dir: Path, *, persist: bool):
        super().__init__()
        self._path = Path(data_dir) / "category-icons.json"
        self._persist = persist
        self._assets = {key: (ASSETS_DIR / "category_icons" / f"{key}.png").as_uri()
                        for key, _ in PRESETS}
        self._load_failed = False
        try:
            with self._path.open(encoding="utf-8") as stream:
                saved = json.load(stream)
            if not isinstance(saved, dict):
                raise ValueError("category icons data is not a map")
            self._selected = {
                name: icon for name, icon in saved.items()
                if isinstance(name, str) and isinstance(icon, str) and
                (icon in self._assets or (icon.startswith(_PNG_PREFIX) and len(icon) <= 160_000))
            }
        except FileNotFoundError:
            self._selected = {}
        except (OSError, ValueError):
            self._selected = {}
            self._load_failed = True

    @Property("QVariantList", constant=True)
    def presets(self) -> list:
        return [{"key": key, "name": name, "source": self._assets[key]} for key, name in PRESETS]

    @Slot(str, result=str)
    def selected(self, category: str) -> str:
        return self._selected.get(category, DEFAULTS.get(category, "sparkle"))

    @Slot(str, result=str)
    def icon(self, category: str) -> str:
        value = self.selected(category)
        return value if value.startswith(_PNG_PREFIX) else self._assets[value]

    def _save(self, category: str, value: str) -> str:
        if not category.strip():
            return "请先选中一个分类。"
        if self._load_failed:
            return "无法读取已有的分类图标设置。"
        updated = dict(self._selected)
        if value:
            updated[category] = value
        else:
            updated.pop(category, None)
        if updated == self._selected:
            return ""
        if self._persist:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                atomic_text(self._path, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
            except OSError:
                return "无法保存分类图标，请检查数据目录是否可写。"
        self._selected = updated
        self.changed.emit()
        return ""

    @Slot(str, str, result=str)
    def select(self, category: str, preset: str) -> str:
        if preset and preset not in self._assets:
            return "找不到这个预设。"
        return self._save(category, preset)

    def import_image(self, category: str, path: Path) -> str:
        from PIL import Image, ImageOps
        try:
            path = Path(path)
            if path.drive.startswith("\\\\"):
                return "请选择本机图片。"
            with path.open("rb") as stream:
                encoded = stream.read(_MAX_IMAGE_BYTES + 1)
            if len(encoded) > _MAX_IMAGE_BYTES:
                return "请选择不超过 12 MB 的图片。"
            with Image.open(io.BytesIO(encoded), formats=("PNG", "JPEG", "WEBP", "BMP")) as source:
                if source.width * source.height > 16_000_000:
                    return "图片尺寸太大，请换一张较小的图片。"
                image = ImageOps.exif_transpose(source).convert("RGBA")
                image.thumbnail((112, 112), Image.Resampling.LANCZOS)
                result = Image.new("RGBA", (128, 128))
                result.alpha_composite(image, ((128-image.width)//2, (128-image.height)//2))
                output = io.BytesIO()
                result.save(output, "PNG")
        except (OSError, ValueError, Image.DecompressionBombError):
            return "无法读取图片，请选择 PNG、JPG、WebP 或 BMP。"
        url = _PNG_PREFIX + base64.b64encode(output.getvalue()).decode("ascii")
        return self._save(category, url)

    @Slot(str, result="QVariantMap")
    def chooseImage(self, category: str) -> dict:
        # Qt ships with the portable runtime and can use the native Windows picker.
        from PySide6.QtWidgets import QFileDialog
        name, _ = QFileDialog.getOpenFileName(None, "选择分类图标", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not name:
            return {"cancelled": True}
        return {"error": self.import_image(category, Path(name))}
