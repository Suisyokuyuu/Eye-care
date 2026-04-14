from __future__ import annotations

from pathlib import Path
from typing import Callable


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
