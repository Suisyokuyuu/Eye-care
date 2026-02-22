from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional


def build_ui_page_url(api_port: int, page: str = "main") -> str:
    p = str(page or "main").strip().lower()
    if p == "rest":
        return f"http://127.0.0.1:{int(api_port)}/rest/"
    if p == "notify":
        return f"http://127.0.0.1:{int(api_port)}/notify/"
    return f"http://127.0.0.1:{int(api_port)}/"


def mount_ui_site_routes(
    app,
    *,
    ui_web_dir: Path,
    index_path: Path,
    inject_bridge_script: Callable[[str], str],
    inject_drag_region: Optional[Callable[[str], str]] = None,
    enable_drag_region_inject: bool = False,
) -> None:
    """Mount all user-visible pages from one site root."""
    from flask import Response, abort, send_from_directory

    def serve_index():
        if not index_path.exists():
            return Response("index.html not found", status=404, mimetype="text/plain")
        raw = index_path.read_text(encoding="utf-8")
        html = inject_bridge_script(raw)
        if enable_drag_region_inject and callable(inject_drag_region):
            html = inject_drag_region(html)
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    def _serve_subdir(subdir: str, path: str = "index.html"):
        target = Path(ui_web_dir) / str(subdir)
        if not target.exists():
            abort(404)
        try:
            return send_from_directory(str(target), path)
        except Exception:
            abort(404)

    def serve_assets(path):
        assets_dir = Path(ui_web_dir) / "assets"
        if not assets_dir.exists():
            abort(404)
        try:
            response = send_from_directory(str(assets_dir), path)
            if path.endswith((".js", ".css", ".woff", ".woff2", ".ttf", ".eot", ".svg")):
                response.headers["Cache-Control"] = "public, max-age=31536000"
            elif path.endswith((".png", ".jpg", ".jpeg", ".gif", ".ico")):
                response.headers["Cache-Control"] = "public, max-age=86400"
            return response
        except Exception:
            abort(404)

    app.add_url_rule("/", "index", serve_index)
    app.add_url_rule("/assets/<path:path>", "assets", serve_assets)
    app.add_url_rule("/rest/", "rest_index", lambda path="index.html": _serve_subdir("rest", path), defaults={"path": "index.html"})
    app.add_url_rule("/rest/<path:path>", "rest_assets", lambda path: _serve_subdir("rest", path))
    app.add_url_rule("/notify/", "notify_index", lambda path="index.html": _serve_subdir("notify", path), defaults={"path": "index.html"})
    app.add_url_rule("/notify/<path:path>", "notify_assets", lambda path: _serve_subdir("notify", path))
