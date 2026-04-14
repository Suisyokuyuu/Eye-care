from __future__ import annotations

from .context import ServiceContext


class DiagService:
    """Home for runtime support, diagnostics, and debug-only helpers.

    Target routes:
    - GET /api/health
    - GET /api/auth/token
    - POST /api/diag/log
    - POST /api/debug/*
    """

    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    def health(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: diag extraction not wired yet")

    def get_auth_token(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: diag extraction not wired yet")

    def ui_diag_log(self, *, payload: dict, headers: dict, remote_addr: str | None) -> dict:
        raise NotImplementedError("Step 2 skeleton only: diag extraction not wired yet")

    def set_notify_debug(self, *, on: bool) -> dict:
        raise NotImplementedError("Step 2 skeleton only: diag extraction not wired yet")

    def trigger_debug_notify(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: diag extraction not wired yet")

    def open_debug_app_detail(self, *, app_key: str) -> dict:
        raise NotImplementedError("Step 2 skeleton only: diag extraction not wired yet")

    def get_dispatcher_metric(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: diag extraction not wired yet")

    def dump_threads(self) -> dict:
        raise NotImplementedError("Step 2 skeleton only: diag extraction not wired yet")
