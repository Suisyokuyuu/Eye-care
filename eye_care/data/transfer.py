import json
import logging
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .repository import Repository

log = logging.getLogger(__name__)

# days 路径穿越防护：仅允许 YYYY-MM-DD 格式
_DAY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_day(day: str) -> bool:
    """校验 day 格式，防止路径穿越。"""
    return bool(day and isinstance(day, str) and _DAY_PATTERN.match(day.strip()))


def _path_under_data_dir(data_dir: Path, target: Path) -> bool:
    """校验目标路径 resolve 后位于 data_dir 下。"""
    try:
        resolved_target = Path(target).resolve()
        resolved_data = Path(data_dir).resolve()
        resolved_target.relative_to(resolved_data)
        return True
    except (ValueError, OSError):
        return False


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8").strip()


def _write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def get_or_create_device_id(data_dir: Path) -> str:
    p = data_dir / "device_id.txt"
    if p.exists():
        v = _read_text(p)
        if v:
            return v
    v = str(uuid.uuid4())
    _write_text(p, v)
    return v


def _load_export_seq(data_dir: Path) -> int:
    p = data_dir / "export_seq.txt"
    if not p.exists():
        return 0
    try:
        return int(_read_text(p) or "0")
    except Exception:
        return 0


def _next_export_seq(data_dir: Path) -> int:
    seq = _load_export_seq(data_dir) + 1
    _write_text(data_dir / "export_seq.txt", str(seq))
    return seq


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            # ignore bad lines (but keep import/export robust)
            continue
    return out


def _write_jsonl(p: Path, rows: List[Dict[str, Any]]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows)
    if text:
        text += "\n"
    p.write_text(text, encoding="utf-8")


def _to_nonneg_int(v: Any) -> int:
    try:
        return max(0, int(v))
    except Exception:
        return 0


def _normalize_minute_row(rec: Dict[str, Any], fallback_day: str) -> Optional[Dict[str, Any]]:
    if not isinstance(rec, dict):
        return None
    minute_start = str(rec.get("minute_start_utc", "") or "").strip()
    if not minute_start:
        return None
    local_date = str(rec.get("local_date", "") or fallback_day).strip() or fallback_day
    raw_apps = rec.get("apps") if isinstance(rec.get("apps"), dict) else {}
    apps: Dict[str, int] = {}
    for k, v in raw_apps.items():
        app = str(k or "").strip()
        if not app:
            continue
        apps[app] = _to_nonneg_int(v)
    return {
        "_schema": "minute@1",
        "minute_start_utc": minute_start,
        "local_date": local_date,
        "apps": apps,
    }


def _merge_minute_rows(local_rows: List[Dict[str, Any]], in_rows: List[Dict[str, Any]], day: str) -> List[Dict[str, Any]]:
    local_cnt: Dict[Tuple[str, str, str], int] = {}
    in_cnt: Dict[Tuple[str, str, str], int] = {}
    sample: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for rec in local_rows:
        n = _normalize_minute_row(rec, day)
        if n is None:
            continue
        apps_sig = json.dumps(n.get("apps") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        key = (str(n["local_date"]), str(n["minute_start_utc"]), apps_sig)
        local_cnt[key] = int(local_cnt.get(key, 0)) + 1
        sample[key] = n

    for rec in in_rows:
        n = _normalize_minute_row(rec, day)
        if n is None:
            continue
        apps_sig = json.dumps(n.get("apps") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        key = (str(n["local_date"]), str(n["minute_start_utc"]), apps_sig)
        in_cnt[key] = int(in_cnt.get(key, 0)) + 1
        sample[key] = n

    out: List[Dict[str, Any]] = []
    for key in sorted(set(local_cnt.keys()) | set(in_cnt.keys()), key=lambda x: (x[0], x[1], x[2])):
        keep_n = max(int(local_cnt.get(key, 0)), int(in_cnt.get(key, 0)))
        row = sample[key]
        for _ in range(keep_n):
            out.append(row)
    return out


def _normalize_event_row(rec: Dict[str, Any], fallback_day: str) -> Optional[Dict[str, Any]]:
    if not isinstance(rec, dict):
        return None
    utc_ts = str(rec.get("utc_ts", "") or "").strip()
    kind = str(rec.get("kind", "") or "").strip()
    if not utc_ts or not kind:
        return None
    local_date = str(rec.get("local_date", "") or fallback_day).strip() or fallback_day
    payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
    return {
        "_schema": "event@1",
        "utc_ts": utc_ts,
        "local_date": local_date,
        "kind": kind,
        "payload": payload,
    }


def _merge_event_rows(local_rows: List[Dict[str, Any]], in_rows: List[Dict[str, Any]], day: str) -> List[Dict[str, Any]]:
    local_cnt: Dict[Tuple[str, str, str, str], int] = {}
    in_cnt: Dict[Tuple[str, str, str, str], int] = {}
    sample: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

    for rec in local_rows:
        n = _normalize_event_row(rec, day)
        if n is None:
            continue
        payload_sig = json.dumps(n.get("payload") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        key = (str(n["local_date"]), str(n["utc_ts"]), str(n["kind"]), payload_sig)
        local_cnt[key] = int(local_cnt.get(key, 0)) + 1
        sample[key] = n

    for rec in in_rows:
        n = _normalize_event_row(rec, day)
        if n is None:
            continue
        payload_sig = json.dumps(n.get("payload") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        key = (str(n["local_date"]), str(n["utc_ts"]), str(n["kind"]), payload_sig)
        in_cnt[key] = int(in_cnt.get(key, 0)) + 1
        sample[key] = n

    out: List[Dict[str, Any]] = []
    for key in sorted(set(local_cnt.keys()) | set(in_cnt.keys()), key=lambda x: (x[0], x[1], x[2], x[3])):
        keep_n = max(int(local_cnt.get(key, 0)), int(in_cnt.get(key, 0)))
        row = sample[key]
        for _ in range(keep_n):
            out.append(row)
    return out


def _write_report(data_dir: Path, *, kind: str, title: str, summary: str, table_rows: List[Dict[str, Any]]) -> Path:
    """Write a human-readable transfer report under user_data/transfer_reports.

    Keep it simple (TXT) so users can read it with any editor.
    """
    data_dir = Path(data_dir)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    p = data_dir / "transfer_reports" / f"{kind}-{ts}.txt"
    csv_p = data_dir / "transfer_reports" / f"{kind}-{ts}.csv"
    lines: List[str] = []
    lines.append(title)
    lines.append(f"time_local: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("Summary")
    lines.append("------")
    lines.append(summary.strip())
    lines.append("")

    if table_rows:
        # Make a tiny fixed table.
        cols = list(table_rows[0].keys())
        # widths
        widths = {c: len(str(c)) for c in cols}
        for r in table_rows:
            for c in cols:
                widths[c] = max(widths[c], len(str(r.get(c, ""))))

        def _fmt_row(r: Dict[str, Any]) -> str:
            return " | ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols)

        lines.append("Details")
        lines.append("-------")
        lines.append(_fmt_row({c: c for c in cols}))
        lines.append("-+-".join("-" * widths[c] for c in cols))
        for r in table_rows:
            lines.append(_fmt_row(r))
        lines.append("")

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Optional CSV for spreadsheet viewing.
    try:
        if table_rows:
            import csv

            cols = list(table_rows[0].keys())
            with csv_p.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                for r in table_rows:
                    w.writerow({c: r.get(c, "") for c in cols})
    except Exception as e:
        log.warning("transfer report csv write failed: %s", e)

    # Also write a stable pointer for convenience.
    try:
        (data_dir / "transfer_reports" / f"last_{kind}_report.txt").write_text(str(p), encoding="utf-8")
        (data_dir / "transfer_reports" / f"last_{kind}_report.csv").write_text(str(csv_p), encoding="utf-8")
    except Exception as e:
        log.warning("transfer report pointer write failed: %s", e)
    return p


def _minute_file(data_dir: Path, day: str) -> Path:
    return data_dir / "minute_usage" / f"minute-{day}.jsonl"


def _events_file(data_dir: Path, day: str) -> Path:
    return data_dir / "events" / f"events-{day}.jsonl"


def _read_jsonl_from_bytes(data: bytes) -> List[Dict[str, Any]]:
    """Parse jsonl from raw bytes (e.g. zip entry)."""
    out: List[Dict[str, Any]] = []
    for line in data.decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _local_days(data_dir: Path) -> List[str]:
    days = set()
    for p in (data_dir / "minute_usage").glob("minute-*.jsonl"):
        day = p.stem.replace("minute-", "")
        if len(day) == 10:
            days.add(day)
    return sorted(days)


def _load_import_log(data_dir: Path) -> Dict[str, Any]:
    p = data_dir / "import_log.json"
    if not p.exists():
        return {"imported_export_ids": [], "last_imported_seq": {}}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return {"imported_export_ids": [], "last_imported_seq": {}}
        obj.setdefault("imported_export_ids", [])
        obj.setdefault("last_imported_seq", {})
        return obj
    except Exception:
        return {"imported_export_ids": [], "last_imported_seq": {}}


def _save_import_log(data_dir: Path, obj: Dict[str, Any]) -> None:
    p = data_dir / "import_log.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def export_all(data_dir: Path, out_path: Path) -> Dict[str, Any]:
    """Export local main data as ZIP: minute_usage/*.jsonl + events/*.jsonl（与本地存储格式一致，不展开成大 JSON）."""
    data_dir = Path(data_dir)
    out_path = Path(out_path)
    device_id = get_or_create_device_id(data_dir)
    export_id = str(uuid.uuid4())
    export_seq = _next_export_seq(data_dir)
    export_time = _utc_iso_now()

    days = _local_days(data_dir)
    day_stats: List[Dict[str, Any]] = []
    total_minutes = 0
    total_events = 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        meta = {
            "schema": "eye_care_export@4",
            "export_id": export_id,
            "device_id": device_id,
            "export_seq": export_seq,
            "export_time": export_time,
            "days": days,
        }
        zf.writestr("_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))

        for day in days:
            m_path = _minute_file(data_dir, day)
            e_path = _events_file(data_dir, day)
            m_raw = m_path.read_bytes() if m_path.exists() else b""
            e_raw = e_path.read_bytes() if e_path.exists() else b""

            # 导出保护: 逐行 clamp minute apps 值，容错处理（无效行原样保留）
            def _clamp_minute_line(line: bytes) -> bytes:
                try:
                    # utf-8-sig 兼容 BOM
                    rec = json.loads(line.decode("utf-8-sig"))
                    if "apps" in rec and isinstance(rec["apps"], dict):
                        rec["apps"] = {k: max(0, int(v)) for k, v in rec["apps"].items()}
                    return (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
                except Exception:
                    # 容错: 无效行原样保留，确保换行符不丢失避免行粘连
                    return line if line.endswith(b"\n") else line + b"\n"

            # 导出保护: 逐行 clamp event seconds 值
            def _clamp_event_line(line: bytes) -> bytes:
                try:
                    rec = json.loads(line.decode("utf-8-sig"))
                    if "seconds" in rec and isinstance(rec["seconds"], (int, float)):
                        rec["seconds"] = max(0, int(rec["seconds"]))
                    return (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
                except Exception:
                    # 容错: 无效行原样保留，确保换行符不丢失避免行粘连
                    return line if line.endswith(b"\n") else line + b"\n"

            # 处理 minute 文件
            m_lines = []
            for line in m_raw.splitlines():
                if line.strip():
                    m_lines.append(_clamp_minute_line(line))
            m_clamped = b"".join(m_lines)
            zf.writestr(f"minute_usage/minute-{day}.jsonl", m_clamped)

            # 处理 events 文件
            e_lines = []
            for line in e_raw.splitlines():
                if line.strip():
                    e_lines.append(_clamp_event_line(line))
            e_clamped = b"".join(e_lines)
            zf.writestr(f"events/events-{day}.jsonl", e_clamped)

            m_lines_count = len(m_lines)
            e_lines_count = len(e_lines)
            total_minutes += m_lines_count
            total_events += e_lines_count
            day_stats.append({"day": day, "minutes": m_lines_count, "events": e_lines_count})

    log.info("export ok: export_id=%s seq=%s days=%s", export_id, export_seq, len(days))
    return {
        "status": "ok",
        "meta": meta,
        "total_minutes": total_minutes,
        "total_events": total_events,
        "days": len(day_stats),
        "day_stats": day_stats,
    }


def _zip_read(zf: zipfile.ZipFile, name: str) -> bytes:
    """从 ZIP 读一项，兼容正反斜杠（Windows 下部分 zip 可能存成反斜杠）。"""
    try:
        return zf.read(name)
    except KeyError:
        alt = name.replace("/", "\\")
        if alt != name:
            return zf.read(alt)
        raise


def _load_payload_from_zip(zip_path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """从 ZIP 导出包读出 _meta 与 minute_usage/events（与本地格式一致）。返回 (payload, meta)。"""
    payload: Dict[str, Any] = {"_meta": {}, "minute_usage": {}, "events": {}}
    with zipfile.ZipFile(zip_path, "r") as zf:
        try:
            meta = json.loads(_zip_read(zf, "_meta.json").decode("utf-8"))
        except (KeyError, json.JSONDecodeError) as e:
            raise ValueError(f"ZIP 中缺少或无效的 _meta.json: {e}") from e
        payload["_meta"] = meta
        raw_days = meta.get("days") or []
        if not raw_days:
            for name in zf.namelist():
                n = name.replace("\\", "/")
                if "minute_usage/minute-" in n and n.endswith(".jsonl"):
                    stem = n.split("/")[-1].replace("minute-", "").replace(".jsonl", "")
                    if len(stem) == 10 and stem.replace("-", "").isdigit():
                        raw_days.append(stem)
            raw_days = sorted(set(raw_days))
        # 路径穿越防护：仅保留合法 YYYY-MM-DD，拒绝并审计非法条目
        days: List[str] = []
        for d in raw_days:
            if _validate_day(str(d)):
                days.append(str(d).strip())
            else:
                log.warning("AUDIT transfer.import.rejected_day: day=%r invalid format, skipped", d)
        if len(days) < len(raw_days):
            log.info("AUDIT transfer.import.days_filtered: rejected=%s valid=%s", len(raw_days) - len(days), len(days))
        for day in days:
            try:
                payload["minute_usage"][day] = _read_jsonl_from_bytes(
                    _zip_read(zf, f"minute_usage/minute-{day}.jsonl")
                )
            except KeyError:
                payload["minute_usage"][day] = []
            try:
                payload["events"][day] = _read_jsonl_from_bytes(
                    _zip_read(zf, f"events/events-{day}.jsonl")
                )
            except KeyError:
                payload["events"][day] = []
    return payload, meta


def import_all(
    data_dir: Path,
    in_path: Path,
    repo: Repository,
    conflict_policy: str = "merge_conflicts",
) -> Dict[str, Any]:
    """Import export file (.zip or legacy .json).

    conflict_policy:
      - skip_conflicts: keep local day if local minute/events file exists.
      - overwrite_conflicts: overwrite local day with imported rows.
      - merge_conflicts: merge local+import rows at record level with dedup.
    """
    data_dir = Path(data_dir)
    in_path = Path(in_path)

    if in_path.suffix.lower() == ".zip":
        payload, meta = _load_payload_from_zip(in_path)
    else:
        payload = json.loads(in_path.read_text(encoding="utf-8"))
        meta = (payload or {}).get("_meta") or {}
    export_id = str(meta.get("export_id", ""))
    src_device = str(meta.get("device_id", ""))
    src_seq = int(meta.get("export_seq", 0) or 0)

    if not export_id:
        raise ValueError("import file missing _meta.export_id")

    log_obj = _load_import_log(data_dir)
    imported_ids = set(log_obj.get("imported_export_ids") or [])

    already_imported = export_id in imported_ids
    if already_imported and conflict_policy != "merge_conflicts":
        log.info("import skip: export_id already imported: %s", export_id)
        return {"status": "skipped", "reason": "export_id_dedup", "export_id": export_id}
    if already_imported and conflict_policy == "merge_conflicts":
        log.info("import reapply: export_id already imported but policy=merge_conflicts: %s", export_id)

    local_device = get_or_create_device_id(data_dir)
    last_seq_map = log_obj.get("last_imported_seq") or {}
    last_seq = int((last_seq_map.get(src_device) or 0))

    if src_device == local_device and src_seq <= last_seq:
        if conflict_policy != "merge_conflicts":
            imported_ids.add(export_id)
            log_obj["imported_export_ids"] = sorted(imported_ids)
            last_seq_map[src_device] = max(last_seq, src_seq)
            log_obj["last_imported_seq"] = last_seq_map
            _save_import_log(data_dir, log_obj)
            return {"status": "skipped", "reason": "same_device_seq", "export_id": export_id}
        log.info(
            "import reapply: same_device_seq but policy=merge_conflicts export_id=%s src_seq=%s last_seq=%s",
            export_id,
            src_seq,
            last_seq,
        )

    minute_usage = (payload or {}).get("minute_usage") or {}
    events = (payload or {}).get("events") or {}

    applied_days: List[str] = []
    skipped_days: List[str] = []
    conflicted_days: List[str] = []
    minute_items = 0
    event_items = 0
    day_stats: List[Dict[str, Any]] = []

    all_days_raw = sorted(set(minute_usage.keys()) | set(events.keys()))
    for day in all_days_raw:
        # 路径穿越防护：正则校验 + resolve 边界校验
        if not _validate_day(str(day)):
            log.warning("AUDIT transfer.import.rejected_day: day=%r invalid format, skipped", day)
            skipped_days.append(str(day))
            continue

        day = str(day).strip()
        rows = minute_usage.get(day) if isinstance(minute_usage, dict) else None
        ev_rows = events.get(day) if isinstance(events, dict) else None
        rows = rows if isinstance(rows, list) else []
        ev_rows = ev_rows if isinstance(ev_rows, list) else []

        local_m_path = _minute_file(data_dir, day)
        local_e_path = _events_file(data_dir, day)
        if not _path_under_data_dir(data_dir, local_m_path) or not _path_under_data_dir(data_dir, local_e_path):
            log.warning("AUDIT transfer.import.rejected_path: day=%s path escapes data_dir, skipped", day)
            skipped_days.append(day)
            continue

        local_exists = local_m_path.exists() or local_e_path.exists()

        action = "applied"
        final_rows = rows
        final_ev_rows = ev_rows

        if local_exists:
            if conflict_policy == "overwrite_conflicts":
                conflicted_days.append(day)
                action = "overwritten"
            elif conflict_policy == "merge_conflicts":
                conflicted_days.append(day)
                local_rows = _read_jsonl(local_m_path)
                local_ev_rows = _read_jsonl(local_e_path)
                final_rows = _merge_minute_rows(local_rows, rows, day)
                final_ev_rows = _merge_event_rows(local_ev_rows, ev_rows, day)
                action = "merged"
            else:
                skipped_days.append(day)
                day_stats.append({"day": day, "action": "skipped", "minutes": len(rows), "events": len(ev_rows)})
                continue

        _write_jsonl(local_m_path, final_rows)
        m_cnt = len(final_rows)
        minute_items += m_cnt

        _write_jsonl(local_e_path, final_ev_rows)
        e_cnt = len(final_ev_rows)
        event_items += e_cnt

        applied_days.append(day)
        day_stats.append({"day": day, "action": action, "minutes": m_cnt, "events": e_cnt})

    imported_ids.add(export_id)
    log_obj["imported_export_ids"] = sorted(imported_ids)
    if src_device:
        last_seq_map[src_device] = max(last_seq, src_seq)
        log_obj["last_imported_seq"] = last_seq_map
    _save_import_log(data_dir, log_obj)

    try:
        if applied_days:
            repo.reload_days(applied_days)
    except Exception:
        log.exception("repo.reload_days failed")

    log.info("import ok: export_id=%s device=%s seq=%s", export_id, src_device, src_seq)
    return {
        "status": "ok",
        "export_id": export_id,
        "device_id": src_device,
        "export_seq": src_seq,
        "applied_days": sorted(applied_days),
        "skipped_days": sorted(skipped_days),
        "conflicted_days": sorted(conflicted_days),
        "minute_items": minute_items,
        "events": event_items,
        "day_stats": day_stats,
    }


def make_import_report(data_dir: Path, *, in_path: Path, result: Dict[str, Any], conflict_policy: str) -> Path:
    """Create a readable report for users after import."""
    status = (result or {}).get("status")
    export_id = result.get("export_id", "")
    src_dev = str(result.get("device_id", "") or "")
    src_seq = int(result.get("export_seq", 0) or 0)
    applied = result.get("applied_days") or []
    skipped = result.get("skipped_days") or []
    conflicted = result.get("conflicted_days") or []
    minute_items = int(result.get("minute_items", 0) or 0)
    event_items = int(result.get("events", 0) or 0)

    summary = (
        f"file: {in_path}\n"
        f"status: {status}\n"
        f"source_device: {src_dev[:8]}...  export_seq: {src_seq}\n"
        f"export_id: {export_id}\n"
        f"applied_days: {len(applied)}  skipped_days: {len(skipped)}  conflicted_days: {len(conflicted)}\n"
        f"imported_minutes: {minute_items}  imported_events: {event_items}\n"
        f"conflict_policy: {conflict_policy}"
    )

    rows = []
    for r in (result.get("day_stats") or []):
        rows.append({
            "day": r.get("day", ""),
            "action": r.get("action", ""),
            "minutes": r.get("minutes", 0),
            "events": r.get("events", 0),
        })

    return _write_report(
        data_dir,
        kind="import",
        title="EyE Care - Import Report",
        summary=summary,
        table_rows=rows,
    )


def make_export_report(data_dir: Path, *, out_path: Path, result: Dict[str, Any]) -> Path:
    meta = (result or {}).get("meta") or {}
    export_id = str(meta.get("export_id", ""))
    dev = str(meta.get("device_id", ""))
    seq = int(meta.get("export_seq", 0) or 0)
    export_time = str(meta.get("export_time", ""))
    total_minutes = int(result.get("total_minutes", 0) or 0)
    total_events = int(result.get("total_events", 0) or 0)
    days = int(result.get("days", 0) or 0)

    summary = (
        f"file: {out_path}\n"
        f"export_id: {export_id}\n"
        f"device_id: {dev[:8]}...  export_seq: {seq}\n"
        f"export_time: {export_time}\n"
        f"days: {days}  minutes: {total_minutes}  events: {total_events}"
    )

    rows = []
    for r in (result.get("day_stats") or []):
        rows.append({
            "day": r.get("day", ""),
            "minutes": r.get("minutes", 0),
            "events": r.get("events", 0),
        })

    return _write_report(
        data_dir,
        kind="export",
        title="EyE Care - Export Report",
        summary=summary,
        table_rows=rows,
    )

