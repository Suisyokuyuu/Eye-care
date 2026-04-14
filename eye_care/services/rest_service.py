from __future__ import annotations

from eye_care.api.common import API_VERSION
from eye_care.diagnostics import diag

from .context import ServiceContext, ServiceError


class RestService:
    """Home for rest state transitions and DND-related business logic.

    Target routes:
    - POST /api/rest/start
    - POST /api/rest/complete
    - POST /api/rest/snooze
    - POST /api/dnd
    - POST /api/shutdown
    """

    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx

    def start_rest(self, *, headers: dict, remote_addr: str | None) -> dict:
        controller = self.ctx.controller
        log = self.ctx.log

        guard = controller.get_rest_start_guard_status()
        if not guard.get("start_enabled", True):
            unlock_ms = int(guard.get("start_unlock_in_ms", 0))
            reason = str(guard.get("start_block_reason", "") or "rest_entry_locked")
            diag.emit(
                "DIAG_REST_GUARD_BLOCK",
                log,
                "休息开始被拦截(守卫锁)",
                reason_code=reason,
                unlock_in_ms=unlock_ms,
            )
            raise ServiceError(
                "rest entry locked",
                code="rest_locked",
                http_status=409,
                payload={"ok": False, "code": "rest_locked", "unlock_in_ms": unlock_ms, "api_version": API_VERSION},
            )

        try:
            ip = headers.get("X-Forwarded-For") or remote_addr
            ua = headers.get("User-Agent", "")
            src = headers.get("X-Eyecare-Source", "")
            diag.emit("DIAG_REST_API_START", log, "休息开始请求入口", src=src, ip=ip, ua=ua[:120])
        except Exception as e:
            from eye_care.diagnostics import log_exception_summary

            log_exception_summary(log, "DIAG_EXCEPTION", "rest_start 请求头/埋点", "仅记录", detail=str(e)[:200], reason_code="E_API_REST_EMIT")

        controller.rest_start()
        controller.notify_rest_entered()
        return {"ok": True, "api_version": API_VERSION}

    def complete_rest(self, *, headers: dict, remote_addr: str | None) -> dict:
        log = self.ctx.log
        controller = self.ctx.controller
        try:
            ip = headers.get("X-Forwarded-For") or remote_addr
            ua = headers.get("User-Agent", "")
            src = headers.get("X-Eyecare-Source", "")
            diag.emit("DIAG_REST_API_COMPLETE", log, "休息完成请求入口", src=src, ip=ip, ua=ua[:120])
        except Exception as e:
            from eye_care.diagnostics import log_exception_summary

            log_exception_summary(log, "DIAG_EXCEPTION", "rest_complete 请求头/埋点", "仅记录", detail=str(e)[:200], reason_code="E_API_REST_EMIT")
        controller.rest_complete()
        return {"ok": True, "api_version": API_VERSION}

    def snooze_rest(self, *, headers: dict, remote_addr: str | None) -> dict:
        log = self.ctx.log
        controller = self.ctx.controller
        try:
            ip = headers.get("X-Forwarded-For") or remote_addr
            ua = headers.get("User-Agent", "")
            src = headers.get("X-Eyecare-Source", "")
            diag.emit("DIAG_REST_API_SNOOZE", log, "休息推迟请求入口", src=src, ip=ip, ua=ua[:120])
        except Exception as e:
            from eye_care.diagnostics import log_exception_summary

            log_exception_summary(log, "DIAG_EXCEPTION", "rest_snooze 请求头/埋点", "仅记录", detail=str(e)[:200], reason_code="E_API_REST_EMIT")
        controller.rest_snooze()
        return {"ok": True, "api_version": API_VERSION}

    def set_dnd(self, *, on: bool) -> dict:
        self.ctx.controller.set_dnd(bool(on))
        return {"ok": True, "dnd": bool(on), "api_version": API_VERSION}

    def shutdown(self) -> dict:
        self.ctx.controller.stop()
        return {"ok": True, "api_version": API_VERSION}
