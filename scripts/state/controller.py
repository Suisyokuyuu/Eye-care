from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Optional, List

from scripts.core.engine import CoreEngine
from scripts.core.models import CoreSnapshot, RunMode
from scripts.data.repo import StatsRepository

from .win_probe import get_foreground_app_info, extract_app_icon_png
from .input_watch import InputWatcher
from .utils import aggregate_range, seconds_to_hhmmss


@dataclass
class UiStatus:
    run_mode: str = "ACTIVE"
    front_app: str = ""
    front_app_icon: str = ""

    dnd: bool = False
    watching: bool = False

    continuous_work_s: int = 0
    idle_elapsed_s: int = 0
    rest_remaining_s: int = 0
    rest_done_in_idle: bool = False

    need_break: bool = False
    remind_seq: int = 0

    status_text: str = ""
    work_text: str = ""
    idle_text: str = ""
    rest_text: str = ""


class AppController:
    def __init__(self, data_dir: Path, engine: CoreEngine, repo: StatsRepository):
        self.data_dir = Path(data_dir)
        self.engine = engine
        self.repo = repo
        self.icon_dir = self.data_dir / "app_icons"
        self.icon_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._latest: CoreSnapshot = CoreSnapshot()
        self._latest_ui: UiStatus = UiStatus()
        self._latest_icon_path: str = ""
        self._icon_cache: Dict[str, str] = {}
        self._app_icon_by_name: Dict[str, str] = {}

        self._running = False
        self._tick_thread: Optional[threading.Thread] = None
        self._input_watcher: Optional[InputWatcher] = None

        self.save_interval_s = 10
        self._last_save_ts = 0.0

        self._ui_listeners: List[Callable[[], None]] = []

    def register_ui_listener(self, fn: Callable[[], None]) -> None:
        with self._lock:
            self._ui_listeners.append(fn)

    def _notify_ui(self) -> None:
        with self._lock:
            listeners = list(self._ui_listeners)
        for fn in listeners:
            try:
                fn()
            except Exception:
                pass

    # ---------------- lifecycle ----------------

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True

        self._input_watcher = InputWatcher(on_any_input=self._on_user_input)
        self._input_watcher.start()

        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

    # ---------------- actions (立刻刷新) ----------------

    def _refresh_now(self) -> None:
        now = time.time()
        try:
            app, exe_path = get_foreground_app_info()
            icon_path = self._ensure_app_icon(exe_path)
        except Exception:
            app, exe_path, icon_path = "", "", ""

        if not app:
            app = "未知应用"
        snap = self.engine.tick(now, app)
        self._publish_snapshot(snap, icon_path)
        self._notify_ui()

    def toggle_dnd(self) -> None:
        with self._lock:
            self.engine.toggle_dnd()
        self._refresh_now()

    def toggle_watching(self) -> None:
        with self._lock:
            self.engine.toggle_watching()
        self._refresh_now()

    def complete_rest(self) -> None:
        with self._lock:
            self.engine.mark_rest_completed()
        self._refresh_now()

    # ---------------- queries ----------------

    def get_ui_status(self) -> UiStatus:
        with self._lock:
            return UiStatus(**self._latest_ui.__dict__)

    def get_metrics_for_range(self, start: date, end: date) -> Dict[str, int]:
        _, metrics = self.repo.load()
        by_day = metrics.by_day if metrics else {}
        return aggregate_range(by_day, start, end)

    def get_ai_payload(self) -> dict:
        return self.repo.export_for_ai()

    def get_app_icon_map(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._app_icon_by_name)

    # ---------------- internal ----------------

    def _on_user_input(self) -> None:
        try:
            self.engine.notify_user_input(time.time())
        except Exception:
            pass

    def _tick_loop(self) -> None:
        while True:
            with self._lock:
                if not self._running:
                    break

            now = time.time()
            try:
                front_app, exe_path = get_foreground_app_info()
                icon_path = self._ensure_app_icon(exe_path)
            except Exception:
                front_app, exe_path, icon_path = "", "", ""

            if not front_app:
                front_app = "未知应用"

            snap = self.engine.tick(now, front_app)

            # 统计常开：ACTIVE 且有 app 累加
            if snap.run_mode == RunMode.ACTIVE and snap.front_app:
                try:
                    self.repo.add_app_seconds(date.today().isoformat(), snap.front_app, 1)
                except Exception:
                    pass

            if now - self._last_save_ts >= float(self.save_interval_s):
                try:
                    self.repo.save()
                    self._last_save_ts = now
                except Exception:
                    pass

            self._publish_snapshot(snap, icon_path)
            self._notify_ui()

            time.sleep(1)

    def _publish_snapshot(self, snap: CoreSnapshot, icon_path: str = "") -> None:
        with self._lock:
            if icon_path:
                self._latest_icon_path = icon_path
            ui = UiStatus()
            ui.front_app = snap.front_app
            ui.front_app_icon = self._latest_icon_path
            ui.run_mode = snap.run_mode.value

            ui.dnd = bool(getattr(snap, "dnd", False))
            ui.watching = bool(getattr(snap, "watching", False))

            ui.continuous_work_s = int(getattr(snap, "continuous_work_s", 0))
            ui.idle_elapsed_s = int(getattr(snap, "idle_elapsed_s", 0))
            ui.rest_remaining_s = int(getattr(snap, "rest_remaining_s", 0))
            ui.rest_done_in_idle = bool(getattr(snap, "rest_done_in_idle", False))

            ui.need_break = bool(getattr(snap, "need_break", False))
            ui.remind_seq = int(getattr(snap, "remind_seq", 0))

            if ui.run_mode == "IDLE":
                ui.status_text = "状态：空闲中"
            elif ui.watching:
                ui.status_text = "状态：观影模式"
            elif ui.dnd:
                ui.status_text = "状态：勿扰模式"
            else:
                ui.status_text = "状态：统计中"

            ui.work_text = f"连续工作：{seconds_to_hhmmss(ui.continuous_work_s)}"

            if ui.run_mode == "IDLE":
                ui.idle_text = f"已空闲：{seconds_to_hhmmss(ui.idle_elapsed_s)}"
                if ui.rest_done_in_idle:
                    ui.rest_text = "本轮休息：已完成（等待返回）"
                else:
                    ui.rest_text = f"距离完成休息：{seconds_to_hhmmss(max(ui.rest_remaining_s, 0))}"
            else:
                ui.idle_text = ""
                ui.rest_text = ""

            if ui.front_app and ui.front_app_icon:
                self._app_icon_by_name[ui.front_app] = ui.front_app_icon

            self._latest = snap
            self._latest_ui = ui

    def _ensure_app_icon(self, exe_path: str) -> str:
        if not exe_path:
            self._latest_icon_path = ""
            return ""

        cached = self._icon_cache.get(exe_path)
        if cached and Path(cached).exists():
            self._latest_icon_path = cached
            return cached

        digest = hashlib.sha1(exe_path.encode("utf-8", errors="ignore")).hexdigest()
        out_path = self.icon_dir / f"{digest}.png"
        if out_path.exists():
            self._icon_cache[exe_path] = str(out_path)
            self._latest_icon_path = str(out_path)
            return str(out_path)

        try:
            ok = extract_app_icon_png(exe_path, out_path, size=32)
        except Exception:
            ok = False

        if ok:
            self._icon_cache[exe_path] = str(out_path)
            self._latest_icon_path = str(out_path)
            return str(out_path)

        self._latest_icon_path = ""
        return ""
