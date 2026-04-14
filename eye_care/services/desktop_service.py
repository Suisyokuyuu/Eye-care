from __future__ import annotations

from .context import ServiceContext


class DesktopService:
    """Future home for host-coupled desktop/window capabilities.

    Target capabilities:
    - pywebview window controls
    - rest overlay show/hide/ready
    - import/export dialogs
    - notify bridge callbacks
    """

    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    def close_main_window(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: desktop extraction not wired yet")

    def minimize_main_window(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: desktop extraction not wired yet")

    def maximize_toggle_main_window(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: desktop extraction not wired yet")

    def show_rest_overlay(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: desktop extraction not wired yet")

    def close_rest_overlay(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: desktop extraction not wired yet")

    def mark_rest_ready(self, *, screen_idx: int) -> dict:
        raise NotImplementedError("Step 2 skeleton only: desktop extraction not wired yet")

    def export_all(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: desktop extraction not wired yet")

    def import_all(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: desktop extraction not wired yet")

    def export_settings(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: desktop extraction not wired yet")

    def import_settings(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: desktop extraction not wired yet")
