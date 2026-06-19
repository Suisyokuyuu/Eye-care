import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict, defaultdict, deque
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

from eye_care.diagnostics.diag_events import log_exception_summary
from .repository import DateRange, EventRecord, MinuteUsageRecord, Repository, TimelineSegment, UsageDelta

log = logging.getLogger(__name__)


def _parse_local_date(s: str):
    """Parse YYYY-MM-DD or malformed YYYY-MMDD to date. Raises on invalid."""
    try:
        return datetime.fromisoformat(s).date()
    except ValueError as e:
        # Keep fallback parse for malformed front-end payloads; log at low frequency.
        log_exception_summary(
            log,
            "DIAG_EXCEPTION",
            "parse local date primary format",
            "degrade_continue",
            detail=f"s={s!r} err={str(e)[:80]}",
            reason_code="E_REPO_PARSE_LOCAL_DATE",
        )
    # 前端可能传 2026-0204（缺月日间连字符）
    if len(s) == 9 and s[4] == "-" and s[5:7].isdigit() and s[7:9].isdigit():
        normalized = f"{s[:5]}{s[5:7]}-{s[7:9]}"
        return datetime.fromisoformat(normalized).date()
    raise ValueError(f"Invalid isoformat string: {s!r}")


def _iso_z(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso_z(s: str) -> datetime:
    # Supports trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


# LRU 缓存最大天数
MAX_CACHE_DAYS = 7

# WAL 合并幂等：去重常量
_MAX_DEDUP_LINES = 1000


def _safe_int_nonneg(v) -> int:
    """安全转非负整数"""
    try:
        return max(0, int(v))
    except Exception:
        return 0


def _sha1s(s: str) -> str:
    """计算字符串的 SHA1 十六进制摘要"""
    return hashlib.sha1(s.encode("utf-8", errors="replace")).hexdigest()


def _canonical_json_hash(line: str) -> str:
    """计算规范化 JSON 字符串的哈希"""
    try:
        obj = json.loads(line)
        canon = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return _sha1s(canon)
    except Exception:
        return _sha1s(line)


def _make_dedup_key(line: str, schema_type: str) -> str:
    """
    返回稳定 key，解析失败也有兜底，不丢行。
    - event: event_id 优先；否则 ts+kind+payload_hash
    - minute: 用规范化 JSON 哈希
    """
    try:
        obj = json.loads(line)
        if schema_type == "event":
            eid = obj.get("event_id") or obj.get("id") or obj.get("uuid")
            if eid:
                return f"eid:{eid}"
            ts = str(obj.get("utc_ts", ""))
            kind = str(obj.get("kind", ""))
            payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
            payload_hash = _sha1s(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return f"evt:{ts}:{kind}:{payload_hash}"
        if schema_type == "minute":
            return f"min:{_canonical_json_hash(line)}"
    except Exception:
        pass
    return f"raw:{_sha1s(line)}"


def _iter_tail_lines(path: Path, max_lines: int):
    """流式读取文件尾部最多 max_lines 行（用于近端去重）
    [非阻断边界] 估算方式为 max_lines * 200 字节，可能存在偏差但影响有限
    """
    if not path.exists():
        return []
    approx_bytes = max_lines * 200
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        start = max(0, size - approx_bytes)
        f.seek(start)
        data = f.read().decode("utf-8-sig", errors="replace").splitlines()
    if start > 0 and data:
        data = data[1:]  # 丢弃可能截断的首行
    return data[-max_lines:]


def _merge_minute_row_into(merged: dict, rec: dict) -> None:
    """将一条 minute 记录合并到 merged 字典中，同一时间戳下每个 app 取 max 秒数"""
    ts = str(rec.get("minute_start_utc", ""))
    local_date = str(rec.get("local_date", ""))
    if not ts or not local_date:
        return
    key = (local_date, ts)
    slot = merged.setdefault(
        key, {"_schema": "minute@1", "minute_start_utc": ts, "local_date": local_date, "apps": {}}
    )
    apps = rec.get("apps") if isinstance(rec.get("apps"), dict) else {}
    for app, sec in apps.items():
        appk = str(app).strip()
        if not appk:
            continue
        oldv = _safe_int_nonneg(slot["apps"].get(appk, 0))
        newv = _safe_int_nonneg(sec)
        slot["apps"][appk] = max(oldv, newv)


class JsonWalRepo(Repository):
    """JSONL repository (minute_usage + events) with WAL + periodic merge.

    Layout:
      user_data/
        minute_usage/minute-YYYY-MM-DD.jsonl
        events/events-YYYY-MM-DD.jsonl
        wal/
          minutes-YYYY-MM-DD.jsonl
          events-YYYY-MM-DD.jsonl

    Runtime model:
      - Tick(1s) updates daily cache immediately (fast UI).
      - Minute buckets are finalized on minute boundary and appended to WAL.
      - merge() consolidates WAL into main files and truncates WAL.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.dir_minutes = self.data_dir / "minute_usage"
        self.dir_events = self.data_dir / "events"
        self.dir_wal = self.data_dir / "wal"
        self.dir_minutes.mkdir(parents=True, exist_ok=True)
        self.dir_events.mkdir(parents=True, exist_ok=True)
        self.dir_wal.mkdir(parents=True, exist_ok=True)

        # App -> Category mapping (editable by user)
        self._cat_path = self.data_dir / "app_categories.json"
        self._app_categories: Dict[str, str] = {}
        self._category_overrides: Dict[str, str] = {}  # M4 config 覆盖，由 controller 注入
        self._load_app_categories()

        # Fast path caches (LRU via OrderedDict)
        self._daily_cache: OrderedDict[str, Dict[str, int]] = OrderedDict()
        self._hourly_cache: OrderedDict[str, Dict[int, int]] = OrderedDict()
        self._events_cache: OrderedDict[str, List[EventRecord]] = OrderedDict()
        # 缓存：get_app_last_active_utc 结果，key: (app_key, start_local_date, end_local_date)，最大条目数 100
        self._last_active_cache: OrderedDict[tuple, Optional[datetime]] = OrderedDict()
        self._LAST_ACTIVE_CACHE_MAX_SIZE = 100

        # Current minute accumulator
        self._cur_minute_start_utc: datetime | None = None
        self._cur_minute_local_date: str | None = None
        self._cur_apps: Dict[str, int] = defaultdict(int)

        # WAL in-memory buffers (write-behind). Keys are local_date.
        self._wal_minutes: DefaultDict[str, List[str]] = defaultdict(list)
        self._wal_events: DefaultDict[str, List[str]] = defaultdict(list)

        # Thread safety: tick loop + checkpoint + UI all touch caches/WAL.
        self._lock = threading.RLock()

        # Lifecycle: close() is idempotent (only first call does finalize + merge).
        self._closed = False

        # DIAG_METRIC_REPO
        self._last_flush_ok_ts: float = 0.0
        self._last_close_ok_ts: float = 0.0
        self._merge_fail_count: int = 0
        self._close_durations_ms: deque = deque(maxlen=300)
        self._last_close_ms: float = 0.0

        # Warm today cache so UI shows existing data immediately
        today = datetime.now().astimezone().date().isoformat()
        try:
            self._load_day_into_cache(today)
        except Exception:
            log.exception("repo: preload today failed")

    def _load_app_categories(self) -> None:
        """Load app->category mapping. 文件不存在时创建空 {}，未命中则走内置启发式（见 _cat_of）。"""
        try:
            if not self._cat_path.exists():
                self._cat_path.write_text("{}", encoding="utf-8")
                self._app_categories = {}
                return

            raw = json.loads(self._cat_path.read_text(encoding="utf-8") or "{}")
            if isinstance(raw, dict):
                # normalize keys to lowercase short names
                self._app_categories = {str(k).lower(): str(v) for k, v in raw.items() if v is not None}
            else:
                self._app_categories = {}
        except Exception:
            log.exception("repo: load app_categories failed")
            self._app_categories = {}

    def set_category_overrides(self, overrides: Dict[str, str]) -> None:
        """M4：由 controller 注入 config.app_category_overrides，_cat_of 优先用此。"""
        self._category_overrides = dict(overrides) if overrides else {}

    def _cat_of(self, app: str) -> str:
        if not app:
            return "其他"

        key = app.lower().strip()

        # 0) M4 单应用分类覆盖优先
        hit = self._category_overrides.get(key)
        if hit:
            return hit

        # 1) 用户映射（app_categories.json）
        hit = self._app_categories.get(key)
        if hit:
            return hit

        # 2) 启发式：按常见关键字归类（尽量稳定、可解释）
        # 浏览器
        if any(x in key for x in ("chrome", "edge", "msedge", "firefox", "opera", "brave", "vivaldi")):
            return "浏览器"

        # 通讯
        if any(x in key for x in ("wechat", "weixin", "qq", "discord", "telegram", "slack", "teams")):
            return "通讯"

        # 开发
        if any(
            x in key
            for x in (
                "code",
                "vscode",
                "pycharm",
                "idea",
                "clion",
                "webstorm",
                "androidstudio",
                "devenv",
                "goland",
                "datagrip",
            )
        ):
            return "开发"

        # 办公
        if any(x in key for x in ("word", "winword", "excel", "powerpnt", "wps", "notion", "obsidian")):
            return "办公"

        # 媒体（播放器/音乐/视频）
        if any(x in key for x in ("vlc", "mpv", "potplayer", "spotify", "music", "video", "player")):
            return "媒体"

        # 创作（绘画/建模/剪辑）
        if any(
            x in key
            for x in (
                "photoshop",
                "illustrator",
                "clipstudio",
                "csp",
                "krita",
                "blender",
                "premiere",
                "afterfx",
            )
        ):
            return "创作"

        # 游戏：平台/反作弊/常见厂商关键字（这里宁愿漏判，也不要乱判）
        if any(
            x in key
            for x in (
                "steam",
                "epic",
                "battle",
                "origin",
                "riot",
                "uplay",
                "ea",
                "unity",
                "unreal",
                "genshin",
                "valorant",
                "league",
                "dota",
                "csgo",
                "cs2",
                "overwatch",
            )
        ):
            return "游戏"

        return "其他"

    def get_app_categories(self) -> Dict[str, str]:
        """返回 app_short -> category 映射（供 API/UI 读写）。"""
        with self._lock:
            return dict(self._app_categories)

    def get_app_category(self, app_short: str) -> str:
        """M4：返回该 app 的展示用分类（override 优先，再 app_categories，再启发式）。"""
        return self._cat_of(app_short or "")

    def save_app_categories(self, mapping: Dict[str, str]) -> None:
        """保存分类映射到 app_categories.json 并刷新内存。"""
        with self._lock:
            normalized = {str(k).lower().strip(): str(v).strip() for k, v in (mapping or {}).items() if v is not None and str(v).strip()}
            self._app_categories = normalized
            self._cat_path.parent.mkdir(parents=True, exist_ok=True)
            self._cat_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------- paths ----------------
    def _minutes_path(self, day: str) -> Path:
        return self.dir_minutes / f"minute-{day}.jsonl"

    def _events_path(self, day: str) -> Path:
        return self.dir_events / f"events-{day}.jsonl"

    def _wal_minutes_path(self, day: str) -> Path:
        return self.dir_wal / f"minutes-{day}.jsonl"

    def _wal_events_path(self, day: str) -> Path:
        return self.dir_wal / f"events-{day}.jsonl"

    # ---------------- low level IO ----------------
    def _append_lines(self, path: Path, lines: List[str]) -> Tuple[int, int]:
        if not lines:
            return 0, 0
        payload = "".join(l + "\n" for l in lines)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(payload)
            return len(payload.encode("utf-8")), len(lines)
        except Exception as e:
            # Keep buffers; caller will retry later
            log.warning("repo.append_lines failed: path=%s err=%s", str(path), e)
            return 0, 0

    def _read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        out: List[Dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    out.append(json.loads(line))
        except Exception:
            log.exception("repo.read_jsonl failed: %s", str(path))
        return out

    # ---------------- cache builders ----------------
    def _apply_minute_record_to_cache(self, rec: Dict[str, Any]) -> None:
        day = rec.get("local_date")
        if not day:
            return
        apps: Dict[str, int] = rec.get("apps") or {}

        # 回放保护: clamp apps 值到 >= 0
        d = self._daily_cache.setdefault(day, defaultdict(int))  # type: ignore
        for a, s in apps.items():
            try:
                d[a] = max(0, d[a] + int(s))
            except Exception as e:
                log_exception_summary(log, "DIAG_EXCEPTION", "repo apps clamp", "degrade_continue", detail=str(e)[:200], reason_code="E_REPO_BAD_APPS_SKIP")
                continue

        # Hourly total (整体按 clamp 后 apps 求和)
        try:
            mu = _parse_iso_z(rec["minute_start_utc"])
            h = mu.astimezone().hour
            hc = self._hourly_cache.setdefault(day, defaultdict(int))  # type: ignore
            # 先 clamp apps 再 sum，避免负值进入小时聚合
            hc[h] = max(0, hc[h] + int(sum(max(0, int(x)) for x in apps.values())))
        except Exception as e:
            log_exception_summary(log, "DIAG_EXCEPTION", "repo fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_REPO_FALLBACK")

    def _load_day_into_cache(self, day: str) -> None:
        # reset then rebuild from disk (main + wal)
        self._daily_cache[day] = defaultdict(int)  # type: ignore
        self._hourly_cache[day] = defaultdict(int)  # type: ignore
        self._events_cache.pop(day, None)

        for rec in self._read_jsonl(self._minutes_path(day)):
            self._apply_minute_record_to_cache(rec)
        for rec in self._read_jsonl(self._wal_minutes_path(day)):
            self._apply_minute_record_to_cache(rec)

        # events
        evts: List[EventRecord] = []
        for rec in self._read_jsonl(self._events_path(day)) + self._read_jsonl(self._wal_events_path(day)):
            try:
                evts.append(
                    EventRecord(
                        utc_ts=_parse_iso_z(rec["utc_ts"]),
                        local_date=rec["local_date"],
                        kind=rec["kind"],
                        payload=rec.get("payload") or {},
                    )
                )
            except Exception as e:
                log_exception_summary(log, "DIAG_EXCEPTION", "repo events parse", "degrade_continue", detail=str(e)[:200], reason_code="E_REPO_BAD_EVENT_SKIP")
                continue
        self._events_cache[day] = evts

    # ---------------- writes ----------------
    def _finalize_current_minute(self) -> None:
        if self._cur_minute_start_utc is None or not self._cur_apps:
            self._cur_apps = defaultdict(int)
            return
        day = self._cur_minute_local_date or self._cur_minute_start_utc.astimezone().date().isoformat()
        rec = {
            "_schema": "minute@1",
            "minute_start_utc": _iso_z(self._cur_minute_start_utc),
            "local_date": day,
            "apps": dict(self._cur_apps),
        }
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        self._wal_minutes[day].append(line)

        # Try immediate durable write (minute boundary safety). If fail, buffer stays.
        self._flush_minutes_day(day)

        self._cur_apps = defaultdict(int)

    def _flush_minutes_day(self, day: str) -> None:
        buf = self._wal_minutes.get(day)
        if not buf:
            return
        written_bytes, written_lines = self._append_lines(self._wal_minutes_path(day), buf)
        if written_lines:
            del buf[:written_lines]
            log.debug("repo.flush.minutes: day=%s lines=%s bytes=%s", day, written_lines, written_bytes)

    def _flush_events_day(self, day: str) -> None:
        buf = self._wal_events.get(day)
        if not buf:
            return
        written_bytes, written_lines = self._append_lines(self._wal_events_path(day), buf)
        if written_lines:
            del buf[:written_lines]
            log.debug("repo.flush.events: day=%s lines=%s bytes=%s", day, written_lines, written_bytes)

    def add_usage(self, delta: UsageDelta) -> None:
        with self._lock:
            # Handle minute boundary finalize
            ts = delta.utc_ts.astimezone(timezone.utc)
            minute_start = ts.replace(second=0, microsecond=0)
            local_day = minute_start.astimezone().date().isoformat()

            if self._cur_minute_start_utc is None:
                self._cur_minute_start_utc = minute_start
                self._cur_minute_local_date = local_day
            elif minute_start != self._cur_minute_start_utc:
                self._finalize_current_minute()
                self._cur_minute_start_utc = minute_start
                self._cur_minute_local_date = local_day

            # Update fast daily cache immediately (写入保护: clamp to >= 0)
            d = self._daily_cache.setdefault(local_day, defaultdict(int))  # type: ignore
            d[delta.app_short] = max(0, d[delta.app_short] + int(delta.seconds))

            # Update current minute bucket (写入保护: clamp to >= 0)
            self._cur_apps[delta.app_short] = max(0, self._cur_apps[delta.app_short] + int(delta.seconds))

    def _invalidate_caches_for_date(self, local_date: str, app_key: str = None) -> None:
        """失效指定日期的缓存（包括 API 缓存和 last_active 缓存）。"""
        # 失效 last_active 缓存中涉及该日期的条目
        with self._lock:
            keys_to_remove = []
            for key in self._last_active_cache:
                key_app, key_start, key_end = key
                if app_key is not None and key_app != app_key:
                    continue
                try:
                    date_obj = _parse_local_date(local_date)
                    start_d = _parse_local_date(key_start)
                    end_d = _parse_local_date(key_end)
                    if start_d <= date_obj <= end_d:
                        keys_to_remove.append(key)
                except (ValueError, TypeError):
                    pass
            for key in keys_to_remove:
                self._last_active_cache.pop(key, None)

    def add_minute(self, rec: MinuteUsageRecord) -> None:
        with self._lock:
            # Used by importer: treat as persisted minute record.
            day = rec.local_date
            payload = {
                "_schema": "minute@1",
                "minute_start_utc": _iso_z(rec.minute_start_utc),
                "local_date": day,
                "apps": dict(rec.apps),
            }
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            self._wal_minutes[day].append(line)

            # Also apply to caches
            self._apply_minute_record_to_cache(payload)
            
            # 失效相关缓存（延迟导入避免循环依赖）
            # 失效该日期的所有 app 的 API 缓存和 last_active 缓存
            self._invalidate_caches_for_date(day)

    def add_event(self, evt: EventRecord) -> None:
        with self._lock:
            payload = {
                "_schema": "event@1",
                "utc_ts": _iso_z(evt.utc_ts),
                "local_date": evt.local_date,
                "kind": evt.kind,
                "payload": evt.payload,
            }
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            self._wal_events[evt.local_date].append(line)
            self._events_cache.setdefault(evt.local_date, []).append(evt)

    # ---------------- reads ----------------
    def _evict_oldest_day(self):
        """联动淘汰：以 _daily_cache 为唯一 day-LRU 顺序源，三套缓存同步删除该天。

        **绝不淘汰"今天"**：今天的 daily 缓存由 add_usage 实时累积，但 _load_day_into_cache
        只从磁盘 minute/WAL 文件重建（漏掉内存里尚未落盘的增量与当前未结算分钟）。一旦今天被淘汰，
        下次读取会触发部分重载 → 应用数突然塌缩（如打开日历逐日加载整月撑爆缓存后，今天只剩 1 个应用）。
        """
        from datetime import datetime as _dtnow, timezone as _tz
        today = _dtnow.now(_tz.utc).astimezone().date().isoformat()
        while len(self._daily_cache) > MAX_CACHE_DAYS:
            # 找最旧且非今天的日子淘汰；今天移到队尾、永不淘汰
            victim = None
            for day in self._daily_cache:            # OrderedDict：从最旧到最新
                if day != today:
                    victim = day
                    break
            if victim is None:                       # 只剩今天 → 停止（即便超过上限也保留今天）
                break
            self._daily_cache.pop(victim, None)
            # 同步淘汰 hourly 和 events
            self._hourly_cache.pop(victim, None)
            self._events_cache.pop(victim, None)

    def get_daily_usage(self, local_date: str) -> Dict[str, int]:
        with self._lock:
            if local_date not in self._daily_cache:
                self._load_day_into_cache(local_date)
            if local_date in self._daily_cache:
                self._daily_cache.move_to_end(local_date)
                self._evict_oldest_day()
            return dict(self._daily_cache.get(local_date, {}))

    def get_hourly_usage(self, local_date: str) -> Dict[int, int]:
        with self._lock:
            # 按各自缓存判断缺失
            if local_date not in self._hourly_cache:
                self._load_day_into_cache(local_date)
            # 统一 touch _daily_cache 作为 LRU 顺序源
            if local_date in self._daily_cache:
                self._daily_cache.move_to_end(local_date)
                self._evict_oldest_day()
            return dict(self._hourly_cache.get(local_date, {}))


    def get_hourly_breakdown(self, local_date: str, dim: str = "app") -> Dict[int, Dict[str, int]]:
        """Return per-hour breakdown for a day.

        - local_date: YYYY-MM-DD (local)
        - dim: "app" | "category"

        Data source: minute_usage jsonl (main + wal). No extra storage.
        """
        with self._lock:
            # Ensure day caches exist for fast reload / map
            if local_date not in self._daily_cache or local_date not in self._hourly_cache:
                self._load_day_into_cache(local_date)
            # 统一 touch _daily_cache 作为 LRU 顺序源
            if local_date in self._daily_cache:
                self._daily_cache.move_to_end(local_date)
                self._evict_oldest_day()

            out: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
            # Read minute records directly to preserve per-key breakdown
            for rec in self._read_jsonl(self._minutes_path(local_date)) + self._read_jsonl(self._wal_minutes_path(local_date)):
                try:
                    apps: Dict[str, int] = rec.get("apps") or {}
                    mu = _parse_iso_z(rec["minute_start_utc"])
                    hour = int(mu.astimezone().hour)
                    if dim == "category":
                        for app, sec in apps.items():
                            out[hour][self._cat_of(str(app))] += int(sec or 0)
                    else:
                        for app, sec in apps.items():
                            out[hour][str(app)] += int(sec or 0)
                except Exception as e:
                    log_exception_summary(log, "DIAG_EXCEPTION", "repo hourly aggregate", "degrade_continue", detail=str(e)[:200], reason_code="E_REPO_BAD_HOURLY_SKIP")
                    continue

            # Convert nested defaultdict -> dict
            return {int(h): dict(v) for h, v in out.items()}


    def get_events(self, local_date: str) -> List[EventRecord]:
        with self._lock:
            # 按各自缓存判断缺失
            if local_date not in self._events_cache:
                self._load_day_into_cache(local_date)
            # 统一 touch _daily_cache 作为 LRU 顺序源
            if local_date in self._daily_cache:
                self._daily_cache.move_to_end(local_date)
                self._evict_oldest_day()
            return list(self._events_cache.get(local_date, []))

    def get_events_range(self, dr: DateRange, kind: Optional[str] = None) -> List[EventRecord]:
        """跨日 events；kind 为 None 时不过滤。"""
        out: List[EventRecord] = []
        start_d = _parse_local_date(dr.start_local_date)
        end_d = _parse_local_date(dr.end_local_date)
        cur = start_d.isoformat()
        end_str = end_d.isoformat()
        while cur <= end_str:
            for evt in self.get_events(cur):
                if kind is None or evt.kind == kind:
                    out.append(evt)
            d = _parse_local_date(cur)
            cur = date.fromordinal(d.toordinal() + 1).isoformat()
        return out

    def get_app_last_active_utc(self, app: str, dr: DateRange) -> Optional[datetime]:
        """该 app 最后一次有使用记录的分钟桶起始 UTC；无则 None。带 LRU 缓存。"""
        app_key = (app or "").strip().lower()
        if not app_key:
            return None
        start_d = _parse_local_date(dr.start_local_date)
        end_d = _parse_local_date(dr.end_local_date)
        
        # 检查缓存
        cache_key = (app_key, dr.start_local_date, dr.end_local_date)
        with self._lock:
            if cache_key in self._last_active_cache:
                # 命中缓存，移到末尾（LRU）
                self._last_active_cache.move_to_end(cache_key)
                return self._last_active_cache[cache_key]
        
        # 未命中缓存，计算
        latest: Optional[datetime] = None
        cur = end_d.isoformat()
        start_str = start_d.isoformat()
        while cur >= start_str:
            recs = self._read_jsonl(self._minutes_path(cur)) + self._read_jsonl(self._wal_minutes_path(cur))
            for rec in recs:
                try:
                    apps = rec.get("apps") or {}
                    if int(apps.get(app_key, 0) or 0) > 0:
                        mu = _parse_iso_z(rec["minute_start_utc"])
                        if latest is None or mu > latest:
                            latest = mu
                except Exception as e:
                    log_exception_summary(log, "DIAG_EXCEPTION", "repo get_app_last_active minute", "degrade_continue", detail=str(e)[:200], reason_code="E_REPO_BAD_MINUTE_SKIP")
                    continue
            d = _parse_local_date(cur)
            cur = date.fromordinal(d.toordinal() - 1).isoformat()
        
        # 写入缓存
        with self._lock:
            self._last_active_cache[cache_key] = latest
            if len(self._last_active_cache) > self._LAST_ACTIVE_CACHE_MAX_SIZE:
                self._last_active_cache.popitem(last=False)  # 移除最旧的条目
        
        return latest

    def get_timeline_segments(self, app: str, dr: DateRange) -> List[TimelineSegment]:
        """连续分钟桶合并为 segment；合并前按 minute_start_utc 排序。cur_start == prev_start+60s 才连续。"""
        app_key = (app or "").strip().lower()
        if not app_key:
            return []
        rows: List[Tuple[datetime, int, str]] = []
        start_d = _parse_local_date(dr.start_local_date)
        end_d = _parse_local_date(dr.end_local_date)
        cur = start_d.isoformat()
        end_str = end_d.isoformat()
        while cur <= end_str:
            for rec in self._read_jsonl(self._minutes_path(cur)) + self._read_jsonl(self._wal_minutes_path(cur)):
                try:
                    apps = rec.get("apps") or {}
                    sec = int(apps.get(app_key, 0) or 0)
                    if sec <= 0:
                        continue
                    mu = _parse_iso_z(rec["minute_start_utc"])
                    local_date = rec.get("local_date") or cur
                    rows.append((mu, sec, local_date))
                except Exception as e:
                    log_exception_summary(log, "DIAG_EXCEPTION", "repo timeline segment", "degrade_continue", detail=str(e)[:200], reason_code="E_REPO_BAD_TIMELINE_SKIP")
                    continue
            d = _parse_local_date(cur)
            cur = date.fromordinal(d.toordinal() + 1).isoformat()
        rows.sort(key=lambda x: x[0])
        segments: List[TimelineSegment] = []
        seg_start: Optional[datetime] = None
        seg_end: Optional[datetime] = None
        seg_sec = 0
        seg_date = ""
        for mu, sec, local_date in rows:
            minute_end = mu + timedelta(seconds=60)
            if seg_end is not None and seg_end == mu:
                seg_end = minute_end
                seg_sec += sec
            else:
                if seg_start is not None:
                    segments.append(
                        TimelineSegment(app=app_key, start_utc=seg_start, end_utc=seg_end, seconds=seg_sec, local_date=seg_date)
                    )
                seg_start = mu
                seg_end = minute_end
                seg_sec = sec
                seg_date = local_date
        if seg_start is not None:
            segments.append(
                TimelineSegment(app=app_key, start_utc=seg_start, end_utc=seg_end, seconds=seg_sec, local_date=seg_date)
            )
        return segments

    def get_usage_range(self, dr: DateRange, dim: str = "app") -> Dict[str, int]:
        out: Dict[str, int] = defaultdict(int)
        start_d = _parse_local_date(dr.start_local_date)
        end_d = _parse_local_date(dr.end_local_date)
        cur = start_d.isoformat()
        end_str = end_d.isoformat()
        while cur <= end_str:
            day_usage = self.get_daily_usage(cur)
            if dim == "category":
                for app, sec in day_usage.items():
                    out[self._cat_of(app)] += int(sec)
            else:
                for k, v in day_usage.items():
                    out[k] += int(v)
            d = _parse_local_date(cur)
            cur = date.fromordinal(d.toordinal() + 1).isoformat()
        return dict(out)

    def get_top(self, dr: DateRange, top_n: int = 10, dim: str = "app") -> List[Tuple[str, int]]:
        usage = self.get_usage_range(dr, dim=dim)
        return sorted(usage.items(), key=lambda x: x[1], reverse=True)[: int(top_n)]

    # ---------------- lifecycle ----------------
    def flush(self) -> None:
        with self._lock:
            # Do NOT finalize current minute here (avoid partial minute duplicates).
            total_bytes = 0
            for day in list(self._wal_minutes.keys()):
                before = len(self._wal_minutes.get(day, []))
                self._flush_minutes_day(day)
                after = len(self._wal_minutes.get(day, []))
                if before != after:
                    total_bytes += 1

            for day in list(self._wal_events.keys()):
                self._flush_events_day(day)

            if total_bytes:
                log.info("repo.flush: minute_wal_pending=%s", sum(len(v) for v in self._wal_minutes.values()))
            self._last_flush_ok_ts = time.time()

    def _merge_one_type(self, wal_glob: str, main_dir: Path, schema_type: str, local_date: str | None = None):
        """通用 WAL 合并逻辑：events 和 minutes 共用（幂等版）"""
        # 按日期过滤 WAL 文件
        if local_date:
            wal_name = wal_glob.replace("*", local_date)
            wp = self.dir_wal / wal_name
            wal_paths = [wp] if wp.exists() else []
        else:
            wal_paths = sorted(self.dir_wal.glob(wal_glob))

        for wal_path in wal_paths:
            if (not wal_path.exists()) or wal_path.stat().st_size == 0:
                continue

            # minutes 文件名映射：minutes-YYYY-MM-DD.jsonl -> minute-YYYY-MM-DD.jsonl
            if schema_type == "minute":
                stem = wal_path.stem.replace("minutes-", "minute-")
                main_path = main_dir / f"{stem}.jsonl"
            else:
                main_path = main_dir / wal_path.name

            try:
                main_path.parent.mkdir(parents=True, exist_ok=True)

                if schema_type == "minute":
                    # 分钟：读主文件 + 读 WAL（均流式），按 (local_date, ts) 聚合，app 秒数取 max
                    # [非阻断边界] 会把单日聚合结果放进内存（约 1440 桶，可接受）
                    merged = {}

                    if main_path.exists():
                        with main_path.open("r", encoding="utf-8") as f:
                            for line in f:
                                s = line.strip()
                                if not s:
                                    continue
                                try:
                                    _merge_minute_row_into(merged, json.loads(s))
                                except Exception as e:
                                    log_exception_summary(log, "DIAG_EXCEPTION", "repo merge minute main", "degrade_continue", detail=str(e)[:200], reason_code="E_REPO_BAD_MINUTE_SKIP")
                                    continue

                    wal_seen = set()
                    with wal_path.open("r", encoding="utf-8") as f:
                        for line in f:
                            s = line.strip()
                            if not s:
                                continue
                            k = _make_dedup_key(s, "minute")
                            if k in wal_seen:
                                continue
                            wal_seen.add(k)
                            try:
                                _merge_minute_row_into(merged, json.loads(s))
                            except Exception as e:
                                log_exception_summary(log, "DIAG_EXCEPTION", "repo merge minute wal", "degrade_continue", detail=str(e)[:200], reason_code="E_REPO_BAD_MINUTE_SKIP")
                                continue

                    tmp = main_path.with_suffix(".jsonl.tmp")
                    with tmp.open("w", encoding="utf-8") as w:
                        for (_, _), rec in sorted(merged.items(), key=lambda x: (x[0][0], x[0][1])):
                            w.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
                    tmp.replace(main_path)
                    wal_path.unlink()
                    continue

                # events：近端去重（主文件尾部窗口 + WAL 批内去重），流式写入
                # [非阻断边界] 仅读取主文件尾部 _MAX_DEDUP_LINES 行做去重，非全历史严格幂等
                existing_keys = set()
                for l in _iter_tail_lines(main_path, _MAX_DEDUP_LINES):
                    s = l.strip()
                    if s:
                        existing_keys.add(_make_dedup_key(s, "event"))

                wal_seen = set()
                with main_path.open("a", encoding="utf-8") as out, wal_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if not s:
                            continue
                        k = _make_dedup_key(s, "event")
                        if (k in wal_seen) or (k in existing_keys):
                            continue
                        wal_seen.add(k)
                        existing_keys.add(k)
                        out.write(s + "\n")

                wal_path.unlink()

            except Exception:
                self._merge_fail_count += 1
                log.exception("repo.merge.%s failed: %s", schema_type, str(wal_path))

    def _merge_one_day(self, local_date: str):
        """按日期合并单天的 WAL 文件"""
        self._merge_one_type("events-*.jsonl", self.dir_events, "event", local_date)
        self._merge_one_type("minutes-*.jsonl", self.dir_minutes, "minute", local_date)

    def merge(self) -> None:
        """Consolidate WAL files into main files with idempotency (dedup)."""
        with self._lock:
            self.flush()
            merged_days = 0
            trunc_bytes = 0

            # 按日期过滤合并（仅处理有 WAL 文件的日期）
            processed_dates = set()
            for wal_path in sorted(self.dir_wal.glob("minutes-*.jsonl")):
                day = wal_path.stem.replace("minutes-", "")
                processed_dates.add(day)
            for wal_path in sorted(self.dir_wal.glob("events-*.jsonl")):
                day = wal_path.stem.replace("events-", "")
                processed_dates.add(day)

            for day in sorted(processed_dates):
                if not day:
                    continue
                try:
                    self._merge_one_day(day)
                    merged_days += 1
                    # 失效相关缓存
                    self._invalidate_caches_for_date(day)
                except Exception:
                    log.exception("repo.merge.day failed: %s", day)

            if merged_days:
                log.info("repo.merge: days=%s", merged_days)

    def close(self) -> None:
        t0 = time.perf_counter()
        with self._lock:
            if self._closed:
                return
            self._closed = True
            # On clean shutdown, finalize current minute to reduce loss (<60s).
            self._finalize_current_minute()
            self.merge()
            dur_ms = (time.perf_counter() - t0) * 1000.0
            self._last_close_ok_ts = time.time()
            self._close_durations_ms.append(dur_ms)
            self._last_close_ms = dur_ms

    def get_metric(self) -> dict:
        """返回 DIAG_METRIC_REPO 用字段（wal_pending, last_flush_ok_ts, last_close_ok_ts, merge_fail_count, repo_close_ms_last, repo_close_ms_p95_5m）。"""
        st = self.stats()
        wal_pending = int(st.get("wal_minutes_pending", 0) or 0) + int(st.get("wal_events_pending", 0) or 0)
        p95 = 0.0
        if self._close_durations_ms:
            sorted_d = sorted(self._close_durations_ms)
            idx = max(0, int(len(sorted_d) * 0.95) - 1)
            p95 = sorted_d[idx]
        return {
            "wal_pending": wal_pending,
            "last_flush_ok_ts": round(self._last_flush_ok_ts, 2),
            "last_close_ok_ts": round(self._last_close_ok_ts, 2),
            "merge_fail_count": self._merge_fail_count,
            "repo_close_ms_last": round(self._last_close_ms, 2),
            "repo_close_ms_p95_5m": round(p95, 2),
        }

    def delete_app_data(self, app_short: str) -> None:
        """M4：删除该 app 全部 usage（main + wal 分钟桶），不删 events。写硬日志。"""
        app_key = (app_short or "").strip().lower()
        if not app_key:
            return
        with self._lock:
            total_removed_sec = 0
            files_touched: List[str] = []
            days_touched: List[str] = []

            def process_path(path: Path, day: str) -> None:
                nonlocal total_removed_sec
                recs = self._read_jsonl(path)
                if not recs:
                    return
                out: List[str] = []
                for rec in recs:
                    apps: Dict[str, Any] = rec.get("apps") or {}
                    if app_key not in apps:
                        out.append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
                        continue
                    total_removed_sec += int(apps.get(app_key, 0) or 0)
                    del apps[app_key]
                    rec["apps"] = apps
                    if apps:
                        out.append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
                if len(out) != len(recs):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
                    files_touched.append(str(path))
                    if day not in days_touched:
                        days_touched.append(day)

            for p in sorted(self.dir_minutes.glob("minute-*.jsonl")):
                day = p.stem.replace("minute-", "")
                process_path(p, day)
            for p in sorted(self.dir_wal.glob("minutes-*.jsonl")):
                day = p.stem.replace("minutes-", "")
                process_path(p, day)

            for d in days_touched:
                # 联动淘汰三套缓存
                self._daily_cache.pop(d, None)
                self._hourly_cache.pop(d, None)
                self._events_cache.pop(d, None)
                # 失效 API 缓存和 last_active 缓存
                self._invalidate_caches_for_date(d, app_key=app_key)

            if files_touched or total_removed_sec:
                log.info(
                    "repo.delete_app_data: app_short=%s files=%s days=%s removed_seconds=%s",
                    app_key,
                    len(files_touched),
                    days_touched,
                    total_removed_sec,
                )

    def reload_days(self, local_dates: List[str]) -> None:
        with self._lock:
            for d in local_dates:
                try:
                    self._load_day_into_cache(d)
                except Exception:
                    log.exception("repo.reload_days failed: day=%s", d)

    # ---------------- misc ----------------
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "days_cached": len(self._daily_cache),
                "wal_minutes_pending": sum(len(v) for v in self._wal_minutes.values()),
                "wal_events_pending": sum(len(v) for v in self._wal_events.values()),
                "cur_minute": _iso_z(self._cur_minute_start_utc) if self._cur_minute_start_utc else None,
                "cur_apps": len(self._cur_apps),
            }

    def exe_sha1(self, exe_path: str) -> str:
        # Keep compatibility with icon cache: upstream has its own helper.
        import hashlib

        h = hashlib.sha1()
        with open(exe_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()


# ---------------------------------------------------------------------------
# Backward-compat alias
#
# Some controller/UI glue still imports `JsonWalRepository`. Keep a stable name
# so refactors don't break startup.
# ---------------------------------------------------------------------------
JsonWalRepository = JsonWalRepo
