from __future__ import annotations

from dataclasses import dataclass
from logging import Logger
from typing import Any


class ServiceError(Exception):
    """Domain-level error raised by services for route-layer translation."""

    def __init__(self, message: str, *, code: str, http_status: int = 500, payload: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = int(http_status)
        self.payload = payload or {}


@dataclass(frozen=True)
class ServiceContext:
    """Shared runtime dependencies for future service-layer extraction."""

    controller: Any
    log: Logger
    window_api: Any | None = None
