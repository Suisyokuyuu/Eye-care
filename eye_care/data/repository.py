from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Tuple


# =========================
# 表式数据口径（冻结 v2）
#
# - minute_usage: 以“分钟”为粒度聚合的使用数据（每分钟一条记录），用于后续 Toggl 风格浏览。
# - daily usage / hourly usage：都由 minute_usage 派生（缓存），不再作为导入导出主数据。
# - events: 仍需要独立维护（提醒、模式切换、手动操作等）。
#
# 上层（UI/分析）只依赖 Repository 接口，未来可替换为 SQLite。
# =========================


@dataclass(frozen=True)
class UsageDelta:
    """Seconds added to app_short at utc_ts."""

    app_short: str
    seconds: int
    utc_ts: datetime


@dataclass(frozen=True)
class MinuteUsageRecord:
    """One minute bucket.

    Frozen v2 schema targets JSONL line:
      {"_schema":"minute@1","minute_start_utc":...,"local_date":...,"apps":{app_short:seconds,...}}

    Notes:
      - local_date is local (wall clock) date string YYYY-MM-DD.
      - a day file contains 0..1440 records.
    """

    minute_start_utc: datetime
    local_date: str
    apps: Dict[str, int]


@dataclass(frozen=True)
class EventRecord:
    """One event record."""

    utc_ts: datetime
    local_date: str
    kind: str  # e.g. mode_change/rest_prompt/rest_start/rest_snooze
    payload: Dict[str, Any]


@dataclass(frozen=True)
class DateRange:
    """Local-date inclusive range: YYYY-MM-DD .. YYYY-MM-DD"""

    start_local_date: str
    end_local_date: str


@dataclass(frozen=True)
class TimelineSegment:
    """一段连续分钟桶的汇总，用于 app_details 时间轴。"""

    app: str
    start_utc: datetime
    end_utc: datetime
    seconds: int
    local_date: str


class Repository(Protocol):
    # ---- write ----
    def add_usage(self, delta: UsageDelta) -> None: ...
    def add_minute(self, rec: MinuteUsageRecord) -> None: ...
    def add_event(self, evt: EventRecord) -> None: ...

    # ---- read (fast path) ----
    def get_daily_usage(self, local_date: str) -> Dict[str, int]: ...

    # ---- read (analytics helpers for UI) ----
    # dim: app | category
    def get_usage_range(self, dr: DateRange, dim: str = "app") -> Dict[str, int]: ...
    def get_top(self, dr: DateRange, top_n: int = 10, dim: str = "app") -> List[Tuple[str, int]]: ...

    # Hour: get_hourly_usage = 整点总秒数；get_hourly_breakdown = 每小时的 per-app 分布
    def get_hourly_usage(self, local_date: str) -> Dict[int, int]: ...
    def get_hourly_breakdown(self, local_date: str, dim: str = "app") -> Dict[int, Dict[str, int]]: ...

    # Events
    def get_events(self, local_date: str) -> List[EventRecord]: ...
    def get_events_range(self, dr: DateRange, kind: Optional[str] = None) -> List[EventRecord]: ...

    # M1 app_details：timeline 为连续分钟合并；last_active = 最后有使用记录的分钟桶起始 UTC
    def get_timeline_segments(self, app: str, dr: DateRange) -> List[TimelineSegment]: ...
    def get_app_last_active_utc(self, app: str, dr: DateRange) -> Optional[datetime]: ...

    # M4 黑名单排除：删除该 app 全部 usage 数据（main + wal），events 不删
    def delete_app_data(self, app_short: str) -> None: ...

    # M4 应用列表：返回某 app 的展示用分类（override + app_categories）
    def get_app_category(self, app_short: str) -> str: ...

    # ---- lifecycle ----
    def flush(self) -> None: ...
    def merge(self) -> None: ...
    def close(self) -> None: ...

    # Optional: reload cache for given days after import
    def reload_days(self, local_dates: List[str]) -> None: ...

    # ---- helpers (optional but used by controller/console) ----
    def stats(self) -> Dict[str, Any]: ...
    def exe_sha1(self, exe_path: str) -> str: ...
