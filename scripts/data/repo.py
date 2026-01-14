from __future__ import annotations

import json
import uuid
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Tuple


# =============================================================
# Data models
# =============================================================

@dataclass
class MetaInfo:
    device_id: str
    schema_version: int = 1


@dataclass
class Metrics:
    # by_day: { "YYYY-MM-DD": { "app": seconds } }
    by_day: Dict[str, Dict[str, int]]


# =============================================================
# Repository
# =============================================================

class StatsRepository:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

        self.meta_path = self.base_dir / "meta.json"
        self.metrics_path = self.base_dir / "metrics.json"
        self.import_log_path = self.base_dir / "import_log.json"

        self._meta: MetaInfo | None = None
        self._metrics: Metrics | None = None
        self._import_log: set[str] = set()

    # ---------------------------------------------------------
    # Init / Load
    # ---------------------------------------------------------

    def ensure_initialized(self) -> None:
        self.base_dir.mkdir(exist_ok=True)

        # meta
        if self.meta_path.exists():
            raw = self.meta_path.read_text(encoding="utf-8")
            self._meta = self._parse_meta(json.loads(raw))
        else:
            self._meta = MetaInfo(device_id=str(uuid.uuid4()))
            self._save_meta()

        # metrics
        if self.metrics_path.exists():
            raw = self.metrics_path.read_text(encoding="utf-8")
            self._metrics = self._parse_metrics(json.loads(raw))
        else:
            self._metrics = Metrics(by_day={})
            self._save_metrics()

        # import log
        if self.import_log_path.exists():
            raw = self.import_log_path.read_text(encoding="utf-8")
            self._import_log = set(json.loads(raw))
        else:
            self._import_log = set()
            self._save_import_log()

    def _parse_meta(self, obj: dict) -> MetaInfo:
        return MetaInfo(
            device_id=obj.get("device_id", str(uuid.uuid4())),
            schema_version=int(obj.get("schema_version", 1)),
        )

    def _parse_metrics(self, obj: dict) -> Metrics:
        return Metrics(by_day=dict(obj.get("by_day", {})))

    # ---------------------------------------------------------
    # Save helpers
    # ---------------------------------------------------------

    def _save_meta(self) -> None:
        self.meta_path.write_text(
            json.dumps(asdict(self._meta), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_metrics(self) -> None:
        self.metrics_path.write_text(
            json.dumps(asdict(self._metrics), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_import_log(self) -> None:
        self.import_log_path.write_text(
            json.dumps(list(self._import_log), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------

    def add_app_seconds(self, day: str, app: str, sec: int) -> None:
        if not self._metrics:
            return

        day_map = self._metrics.by_day.setdefault(day, {})
        day_map[app] = day_map.get(app, 0) + int(sec)

    def save(self) -> None:
        if self._metrics:
            self._save_metrics()

    def load(self) -> Tuple[MetaInfo, Metrics]:
        return self._meta, self._metrics

    # ---------------------------------------------------------
    # Export / Import
    # ---------------------------------------------------------

    def export_all(self) -> dict:
        return {
            "meta": asdict(self._meta),
            "metrics": asdict(self._metrics),
            "export_id": str(uuid.uuid4()),
        }

    def export_for_ai(self) -> dict:
        """预留给外部助手/接口的导出格式。"""
        return {
            "device_id": self._meta.device_id if self._meta else "",
            "schema_version": self._meta.schema_version if self._meta else 1,
            "metrics": asdict(self._metrics) if self._metrics else {"by_day": {}},
        }

    def import_payload(self, payload: dict) -> Tuple[bool, str | None]:
        export_id = payload.get("export_id")
        if not export_id:
            return False, "无效导入文件"

        if export_id in self._import_log:
            return False, "已导入过该数据"

        meta = payload.get("meta", {})
        if meta.get("device_id") == self._meta.device_id:
            return False, "不能导入同一设备的数据"

        metrics = payload.get("metrics", {}).get("by_day", {})
        for day, apps in metrics.items():
            for app, sec in apps.items():
                self.add_app_seconds(day, app, sec)

        self._import_log.add(export_id)
        self._save_metrics()
        self._save_import_log()
        return True, None
