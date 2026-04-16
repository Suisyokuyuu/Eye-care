from __future__ import annotations

from pathlib import Path
from typing import Callable


def _dir_uri(path: Path) -> str:
    return path.resolve().as_uri().rstrip("/") + "/"


def rewrite_static_urls_for_qt(*, html: str, ui_web_dir: Path) -> str:
    mappings = {
        "/assets/": _dir_uri(Path(ui_web_dir) / "assets"),
        "/rest/": _dir_uri(Path(ui_web_dir) / "rest"),
        "/notify/": _dir_uri(Path(ui_web_dir) / "notify"),
    }
    out = html
    for prefix, target in mappings.items():
        out = out.replace(f'"{prefix}', f'"{target}')
        out = out.replace(f"'{prefix}", f"'{target}")
    return out


def render_main_html(
    *,
    index_path: Path,
    inject_bridge_script: Callable[[str], str],
    inject_drag_region: Callable[[str], str] | None = None,
    enable_drag_region_inject: bool = False,
) -> str:
    """Render the main HTML the same way every host sees it."""
    if not index_path.exists():
        raise FileNotFoundError(f"index.html not found: {index_path}")
    html = index_path.read_text(encoding="utf-8")
    html = inject_bridge_script(html)
    if enable_drag_region_inject and callable(inject_drag_region):
        html = inject_drag_region(html)
    return html


def render_main_qt_html(
    *,
    index_path: Path,
    ui_web_dir: Path,
    inject_bridge_script: Callable[[str], str],
    inject_drag_region: Callable[[str], str] | None = None,
    enable_drag_region_inject: bool = False,
) -> str:
    html = render_main_html(
        index_path=index_path,
        inject_bridge_script=inject_bridge_script,
        inject_drag_region=inject_drag_region,
        enable_drag_region_inject=enable_drag_region_inject,
    )
    return rewrite_static_urls_for_qt(html=html, ui_web_dir=ui_web_dir)


def render_qt_subpage_html(*, page_path: Path, ui_web_dir: Path) -> str:
    if not page_path.exists():
        raise FileNotFoundError(f"subpage html not found: {page_path}")
    html = page_path.read_text(encoding="utf-8")
    return rewrite_static_urls_for_qt(html=html, ui_web_dir=ui_web_dir)
