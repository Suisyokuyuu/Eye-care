from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, Optional, List, Tuple

from scripts.core.engine import CoreEngine
from scripts.core.models import CoreSnapshot, RunMode
from scripts.data.repo import StatsRepository
from scripts.state.utils import seconds_to_hhmmss  # 你后面会统一成“XX小时XX分钟”，这里保持调用

from .win_probe import get_foreground_app_info, extract_app_icon_png
from .input_watch import InputWatcher


@dataclass
class UiStatus:
    run_mode: str = "ACTIVE"
    front_app: str = ""
    front_app_icon: str = ""

    # NORMAL / DND / WATCHING
    manual_mode: str = "NORMAL"

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
    """
    目标：功能归功能，UI 只读 UiStatus / 调 action。
    修复：
    - Top10 图标“必须保存一次/刷新一次才出现”：原因是 icon 缓存只在“当过前台”才填充
      -> 引入 icon_index.json（app_short -> icon_path）启动加载 + 运行时增量写入
    """

    def __init__(self, data_dir: Path, engine: CoreEngine, repo: StatsRepository):
        self.data_dir = Path(data_dir)
        self.engine = engine
        self.repo = repo

        # 图标输出目录（exe_path -> png）
        self.icon_dir = self.data_dir / "app_icons"
        self.icon_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()

        self._latest: CoreSnapshot = CoreSnapshot()
        self._latest_ui: UiStatus = UiStatus()
        self._latest_icon_path: str = ""

        # exe_path -> png path（落盘缓存：同 exe 永久复用）
        self._icon_cache: Dict[str, str] = {}

        # app_short(lower) -> png path（Top10/主界面直接用）
        self._icon_by_app: Dict[str, str] = {}

        # app_short->icon 的持久化索引（解决重启后 Top10 空图标）
        self._icon_index_path = self.data_dir / "icon_index.json"
        self._icon_index_dirty = False
        self._icon_index_last_save = 0.0

        self._running = False
        self._tick_thread: Optional[threading.Thread] = None
        self._input_watcher: Optional[InputWatcher] = None

        self.save_interval_s = 10
        self._last_save_ts = 0.0

        self._ui_listeners: List[Callable[[], None]] = []

        # ✅ 启动即加载历史 icon 索引（这一步就是你想要的“启动载入本地图标”）
        self._load_icon_index()

    # ---------------- UI listeners ----------------

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

        # ✅ 启动立刻刷新一次：主窗第一次显示 front_app/icon 更容易就绪
        try:
            self._refresh_now()
        except Exception:
            pass

        self._input_watcher = InputWatcher(on_any_input=self._on_user_input)
        self._input_watcher.start()

        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

    def stop(self) -> None:
        """可选：给退出流程用（不要求你现在一定调用）"""
        with self._lock:
            self._running = False
        try:
            if self._input_watcher:
                self._input_watcher.stop()
        except Exception:
            pass
        try:
            self._flush_icon_index(force=True)
        except Exception:
            pass

    # ---------------- public API ----------------

    def refresh_now(self) -> None:
        """给 main/主界面显示时调用：强制刷新前台 app + icon + ui_status"""
        self._refresh_now()

    def get_ui_status(self) -> UiStatus:
        with self._lock:
            return self._latest_ui

        def get_metrics_for_range(self, d1: date, d2: date) -> Dict[str, int]:
            try:
                _meta, metrics = self.repo.load()
                by_day = getattr(metrics, "by_day", {}) if metrics else {}
                if not isinstance(by_day, dict):
                    return {}

                if d2 < d1:
                    d1, d2 = d2, d1

                out: Dict[str, int] = {}
                cur = d1
                while cur <= d2:
                    day_key = cur.isoformat()
                    day_map = by_day.get(day_key, {}) or {}
                    if isinstance(day_map, dict):
                        for app, sec in day_map.items():
                            try:
                                out[app] = out.get(app, 0) + int(sec)
                            except Exception:
                                pass
                    cur += timedelta(days=1)
                return out
            except Exception:
                return {}

    def skip_break(self) -> None:
        """UI: 跳过本轮提醒（不再弹），下一轮再提醒。"""
        try:
            if hasattr(self.engine, "skip_break"):
                self.engine.skip_break()
        finally:
            # 立刻刷新，让 UI/notify 状态同步
            try:
                self.refresh_now()
            except Exception:
                pass

    def complete_rest(self) -> None:
        """UI: 手动标记已完成休息（开始新一轮）。"""
        try:
            # 你的 engine 里叫 mark_rest_completed
            if hasattr(self.engine, "mark_rest_completed"):
                self.engine.mark_rest_completed()
        finally:
            try:
                self.refresh_now()
            except Exception:
                pass

    def get_metrics_for_range(self, d1: date, d2: date) -> Dict[str, int]:
        """
        聚合 [d1, d2]（含端点）的使用秒数：{app: seconds}
        兼容当前 StatsRepository 只有 load()/metrics.by_day 的实现。
        """
        try:
            _meta, metrics = self.repo.load()
            by_day = getattr(metrics, "by_day", {}) if metrics else {}
            if not isinstance(by_day, dict):
                return {}

            if d2 < d1:
                d1, d2 = d2, d1

            out: Dict[str, int] = {}
            cur = d1
            while cur <= d2:
                day_key = cur.isoformat()
                day_map = by_day.get(day_key, {}) or {}
                if isinstance(day_map, dict):
                    for app, sec in day_map.items():
                        try:
                            out[app] = out.get(app, 0) + int(sec)
                        except Exception:
                            pass
                cur += timedelta(days=1)
            return out
        except Exception:
            return {}

    def get_icon_map_for_apps(self, apps: List[str]) -> Dict[str, str]:
        """
        输入 apps: ["chrome","python","Feishu"...]
        输出: {"chrome": "...png", "python": "...png", ...}
        """
        res: Dict[str, str] = {}
        with self._lock:
            cache = dict(self._icon_by_app)

        for name in (apps or []):
            k = (name or "").strip().lower()
            if not k:
                continue
            p = cache.get(k)
            if p and Path(p).exists():
                # 输出 key 保持原 app 名（UI 用）
                res[name] = p
        return res

    # 模式 API（UI/托盘统一用这些）
    def set_normal(self) -> None:
        with self._lock:
            if hasattr(self.engine, "set_normal"):
                self.engine.set_normal()
            elif hasattr(self.engine, "set_manual_mode"):
                try:
                    from scripts.core.models import ManualMode
                    self.engine.set_manual_mode(ManualMode.NORMAL)
                except Exception:
                    pass
            else:
                # 兜底：旧版 toggle
                st = self.get_ui_status()
                if getattr(st, "dnd", False) and hasattr(self.engine, "toggle_dnd"):
                    self.engine.toggle_dnd()
                if getattr(st, "watching", False) and hasattr(self.engine, "toggle_watching"):
                    self.engine.toggle_watching()
        self._refresh_now()

    def set_dnd(self) -> None:
        with self._lock:
            if hasattr(self.engine, "set_dnd"):
                self.engine.set_dnd()
            elif hasattr(self.engine, "set_manual_mode"):
                try:
                    from scripts.core.models import ManualMode
                    self.engine.set_manual_mode(ManualMode.DND)
                except Exception:
                    pass
            elif hasattr(self.engine, "toggle_dnd"):
                # 旧版 toggle：确保打开 dnd
                st = self.get_ui_status()
                if not getattr(st, "dnd", False):
                    self.engine.toggle_dnd()
        self._refresh_now()

    def set_watching(self) -> None:
        with self._lock:
            if hasattr(self.engine, "set_watching"):
                self.engine.set_watching()
            elif hasattr(self.engine, "set_manual_mode"):
                try:
                    from scripts.core.models import ManualMode
                    self.engine.set_manual_mode(ManualMode.WATCHING)
                except Exception:
                    pass
            elif hasattr(self.engine, "toggle_watching"):
                st = self.get_ui_status()
                if not getattr(st, "watching", False):
                    self.engine.toggle_watching()
        self._refresh_now()

    # 兼容旧 toggle（如果你别处还在用）
    def toggle_dnd(self) -> None:
        with self._lock:
            if hasattr(self.engine, "toggle_dnd"):
                self.engine.toggle_dnd()
        self._refresh_now()

    def toggle_watching(self) -> None:
        with self._lock:
            if hasattr(self.engine, "toggle_watching"):
                self.engine.toggle_watching()
        self._refresh_now()

    # ---------------- internal ----------------

    def _on_user_input(self) -> None:
        try:
            self.engine.notify_user_input(time.time())
        except Exception:
            pass

    def _refresh_now(self) -> None:
        now = time.time()
        app, exe_path = get_foreground_app_info()
        icon_path = self._ensure_app_icon(exe_path)

        # ✅ 写入 app->icon（并持久化索引）
        k = (app or "").strip().lower()
        if k and icon_path:
            with self._lock:
                # 内存缓存
                self._icon_by_app[k] = icon_path
            self._mark_icon_index_dirty()
            self._flush_icon_index()

        snap = self.engine.tick(now, app)
        self._publish_snapshot(snap, icon_path)
        self._notify_ui()

    def _tick_loop(self) -> None:
        while True:
            with self._lock:
                if not self._running:
                    break

            now = time.time()
            front_app, exe_path = get_foreground_app_info()
            icon_path = self._ensure_app_icon(exe_path)

            snap = self.engine.tick(now, front_app)

            # ✅ 记住这个 app 的图标（供 Top10/列表直接命中）
            try:
                k = (front_app or "").strip().lower()
                if k and icon_path:
                    with self._lock:
                        self._icon_by_app[k] = icon_path
                    self._mark_icon_index_dirty()
                    self._flush_icon_index()
            except Exception:
                pass

            # 统计：ACTIVE 且有 app 就累加（每秒）
            if getattr(snap, "run_mode", None) == RunMode.ACTIVE and getattr(snap, "front_app", ""):
                try:
                    self.repo.add_app_seconds(date.today().isoformat(), snap.front_app, 1)
                except Exception:
                    pass

            # 按间隔保存统计
            if now - self._last_save_ts >= float(self.save_interval_s):
                try:
                    self.repo.save()
                    self._last_save_ts = now
                except Exception:
                    pass

            self._publish_snapshot(snap, icon_path)
            self._notify_ui()

            time.sleep(1)

    def _publish_snapshot(self, snap: CoreSnapshot, icon_path: str) -> None:
        ui = UiStatus()
        try:
            ui.run_mode = getattr(snap, "run_mode", RunMode.ACTIVE).value if hasattr(getattr(snap, "run_mode", None), "value") else str(getattr(snap, "run_mode", "ACTIVE"))
        except Exception:
            ui.run_mode = "ACTIVE"

        ui.front_app = getattr(snap, "front_app", "") or ""
        ui.front_app_icon = icon_path or ""

        # dnd/watching
        ui.dnd = bool(getattr(snap, "dnd", False))
        ui.watching = bool(getattr(snap, "watching", False))

        # manual_mode（新版字段优先，否则用 dnd/watching 推）
        mm = getattr(snap, "manual_mode", None)
        if mm is not None:
            try:
                ui.manual_mode = mm.value
            except Exception:
                ui.manual_mode = str(mm)
        else:
            ui.manual_mode = "WATCHING" if ui.watching else ("DND" if ui.dnd else "NORMAL")

        ui.continuous_work_s = int(getattr(snap, "continuous_work_s", 0) or 0)
        ui.idle_elapsed_s = int(getattr(snap, "idle_elapsed_s", 0) or 0)
        ui.rest_remaining_s = int(getattr(snap, "rest_remaining_s", 0) or 0)
        ui.rest_done_in_idle = bool(getattr(snap, "rest_done_in_idle", False))
        ui.need_break = bool(getattr(snap, "need_break", False))
        ui.remind_seq = int(getattr(snap, "remind_seq", 0) or 0)

        # 文案（UI 直接用）
        if ui.run_mode == "IDLE":
            ui.status_text = "状态：空闲中"
        else:
            if ui.manual_mode == "WATCHING":
                ui.status_text = "状态：视频模式"
            elif ui.manual_mode == "DND":
                ui.status_text = "状态：勿扰模式"
            else:
                ui.status_text = "状态：统计中"

        ui.work_text = f"已连续看屏幕：{seconds_to_hhmmss(ui.continuous_work_s)}"

        if ui.run_mode == "IDLE":
            ui.idle_text = f"已空闲：{seconds_to_hhmmss(ui.idle_elapsed_s)}"
            if ui.rest_done_in_idle:
                ui.rest_text = "本轮休息：已完成（等待返回）"
            else:
                ui.rest_text = f"距离完成休息：{seconds_to_hhmmss(max(ui.rest_remaining_s, 0))}"
        else:
            ui.idle_text = ""
            ui.rest_text = ""

        with self._lock:
            self._latest = snap
            self._latest_ui = ui

    # ---------------- icon handling ----------------

    def _ensure_app_icon(self, exe_path: str) -> str:
        """
        exe_path -> 本地 png 路径
        - 同 exe_path 会复用缓存文件（icon_dir 下 sha1 命名）
        """
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
            if extract_app_icon_png(exe_path, out_path, size=32):
                self._icon_cache[exe_path] = str(out_path)
                self._latest_icon_path = str(out_path)
                return str(out_path)
        except Exception:
            pass

        self._latest_icon_path = ""
        return ""

    # ---------------- icon index persistence ----------------

    def _load_icon_index(self) -> None:
        """启动加载：把历史 app_short->icon_path 回填到内存，让 Top10 直接命中。"""
        try:
            p = self._icon_index_path
            if not p.exists():
                return
            obj = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(obj, dict):
                return

            cleaned: Dict[str, str] = {}
            for k, v in obj.items():
                if not isinstance(k, str) or not k.strip():
                    continue
                if not isinstance(v, str) or not v.strip():
                    continue
                if os.path.exists(v):
                    cleaned[k.strip().lower()] = v

            with self._lock:
                for k, v in cleaned.items():
                    self._icon_by_app.setdefault(k, v)
        except Exception:
            pass

    def _mark_icon_index_dirty(self) -> None:
        self._icon_index_dirty = True

    def _flush_icon_index(self, force: bool = False) -> None:
        """节流写盘，避免每秒写文件。"""
        try:
            if not self._icon_index_dirty and not force:
                return
            now = time.time()
            if (not force) and (now - self._icon_index_last_save < 2.0):
                return

            with self._lock:
                payload = dict(self._icon_by_app)

            self._icon_index_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._icon_index_dirty = False
            self._icon_index_last_save = now
        except Exception:
            pass
