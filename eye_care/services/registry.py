from __future__ import annotations

from dataclasses import dataclass
from logging import Logger
from typing import Any

from .config_service import ConfigService
from .context import ServiceContext
from .desktop_service import DesktopService
from .diag_service import DiagService
from .rest_service import RestService
from .snapshot_service import SnapshotService
from .stats_service import StatsService


@dataclass(frozen=True)
class ServiceRegistry:
    """Central place to construct and discover migration-era services."""

    ctx: ServiceContext
    snapshot: SnapshotService
    config: ConfigService
    rest: RestService
    stats: StatsService
    desktop: DesktopService
    diag: DiagService


def build_service_registry(*, controller: Any, log: Logger, window_api: Any | None = None) -> ServiceRegistry:
    """Build the service registry without changing current route behavior."""

    ctx = ServiceContext(controller=controller, log=log, window_api=window_api)
    return ServiceRegistry(
        ctx=ctx,
        snapshot=SnapshotService(ctx),
        config=ConfigService(ctx),
        rest=RestService(ctx),
        stats=StatsService(ctx),
        desktop=DesktopService(ctx),
        diag=DiagService(ctx),
    )
