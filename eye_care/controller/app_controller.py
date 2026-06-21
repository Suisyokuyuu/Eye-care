from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..config.display_utils import get_display_name as _get_display_name, is_blacklisted as _is_blacklisted
from ..config.models import AppConfig
from ..config.store import load_config, save_config
from ..data.json_wal_repo import JsonWalRepository
from ..data.repository import UsageDelta, EventRecord
from ..diagnostics import diag
from ..diagnostics.diag_events import log_exception_summary
from ..probes.foreground import get_foreground
from ..probes.idle import get_idle_seconds
from ..ui.state_machines import RestEntryGuardMachine
from ..ui.state_machines.types import RestEntryGuardState
from ..utils.time_utils import utcnow, local_date_today
from .viewmodel_service import ViewModelService

log = logging.getLogger(__name__)

REST_ENTRY_GUARD_COOLDOWN_S = 2.0

# WAL: flush to disk every 60s.
# Consolidation/truncation is deferred to next startup replay for stability.
FLUSH_INTERVAL_S = 60
# Checkpoint (persist daily + truncate WAL) every 1 hour. 
CHECKPOINT_INTERVAL_S = 60 * 60
# NOTE: checkpoint runs in background thread to avoid blocking tick loop.

# 提醒冷却最小值：避免用户频繁 ESC/“稍后”导致提醒连发。
# 口径：无论工作阈值多小，提醒之间至少相隔 60 秒。
MIN_REMIND_COOLDOWN_S = 60


@dataclass
class ControllerState:
    # DEPRECATED: is_paused 已废弃，永远为 False，保留字段兼容旧版 API
    is_paused: bool = False  # type: ignore[assignment]
    is_dnd: bool = False
    # 暂停（手动，原“离开”）：不记录 usage、不增长 cont_work、不触发 rest/notify；不持久化。
    force_idle: bool = False
    # 自动 idle：一段时间无操作时由正常模式自动进入，托盘/模式显示 idle；恢复操作后回到正常。勿扰时不自动进入。
    auto_idle: bool = False
    # M4 自动勿扰：manual=用户点的勿扰；auto_app=某 app 前台触发的勿扰，离开该 app 后恢复
    dnd_reason: Optional[str] = None  # "manual" | "auto_app" | None
    auto_dnd_trigger_app: Optional[str] = None
    prev_mode_before_auto_dnd: str = "normal"


class AppController:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.cfg_path = self.data_dir / "config.json"
        self.cfg: AppConfig = load_config(self.cfg_path)

        self.repo = JsonWalRepository(self.data_dir)
        if hasattr(self.repo, "set_category_overrides"):
            self.repo.set_category_overrides(getattr(self.cfg, "app_category_overrides", None) or {})
        self._apply_exit_state_need_merge()
        self.vm = ViewModelService(self.repo)
        self.state = ControllerState()

        self._stop = threading.Event()
        self._thr: Optional[threading.Thread] = None
        self._last_flush = time.time()
        self._last_checkpoint = time.time()
        self._checkpoint_inflight = False
        self._checkpoint_lock = threading.Lock()

        # runtime lock：保护 _app_paths / rest 状态等运行期字段
        self._lock = threading.RLock()

        # transient runtime states (not persisted)
        self._last_idle_s: int = 0
        self._prev_idle_s: int = 0
        self._last_fg_short: str = ""
        self._last_count_app: str = ""  # last app we actually counted seconds for (for idle rollback)
        self._app_paths: dict[str, str] = {}  # app_short -> exe_path (persisted to app_paths.json for icon API)
        self._last_app_paths_persist: float = 0.0

        # auto_idle 防闪烁：记录进入 auto_idle 的时间，退出前需保持最小持续时间
        self._auto_idle_entered_at: float = 0.0
        self._auto_idle_min_duration: float = 1.0  # 最小保持 1 秒
        # app_paths 后台加载：异步加载，避免阻塞启动
        self._app_paths_loaded = threading.Event()
        self._app_paths_loading = False
        # 在后台线程异步加载 app_paths
        threading.Thread(target=self._load_app_paths, daemon=True, name="app_paths_loader").start()

        # minute_usage 口径：不再维护 timeline_segments；每秒 add_usage，Repo 负责按分钟聚合落盘。

        # ---- rest reminder runtime (transient) ----
        # 口径：
        # - 不对用户暴露“提醒冷却”设置；但 UI 的“稍后”需要一个内部 snooze。
        # - 到点只弹一次，直到发生：休息开始/用户离开(Idle)/“跳过本轮”(下次阈值再弹)
        self._cont_work_s: int = 0
        self._rest_ack_work_s: int = 0  # 'skip this cycle' anchor
        # 休息轮次：每次连续用眼被清零（rest_complete）即 +1。通知去重键带上它，避免计时重置后
        # work_s 重新爬过同一个"桶"被去重逻辑当成重复而吞掉（用户主诉：通知第一次弹、后面不弹）。
        self._rest_cycle: int = 0
        self._rest_due: bool = False
        self._rest_notified: bool = False
        self._rest_snooze_until: float = 0.0
        self._rest_next_prompt_work_s: int = 0  # next prompt work_s threshold
        self._last_prompt_toast_shown: bool = False  # 本轮 due 是否已弹过系统通知，避免刷屏

        # 是否处于“休息中”（由 UI 的休息遮罩触发）。
        # 口径：用户点了“马上休息/开始休息”后，直到 rest_complete（休息结束）
        # 或 rest_snooze（用户按 ESC 跳过）才解除。
        # 休息中：不计时、不触发提醒。
        self._is_resting: bool = False

        # debug flags (runtime, non-persisted)
        self._debug_notify: bool = False
        self._debug_last_log_ts: float = 0.0
        self._debug_last_tick_log_ts: float = 0.0
        self._debug_post_notify_show_cb: Optional[Callable[[], None]] = None

        # rest blocked 日志降噪：仅状态变化时输出
        self._rest_blocked_last: bool = False
        self._rest_block_reason_last: str = ""

        # Rest 进入守卫（5.5）：立即休息按钮与 /api/rest/start 共用
        self._rest_entry_guard = RestEntryGuardMachine(log)
        self._rest_guard_cooldown_timer: Optional[threading.Timer] = None

        # tick timing (use monotonic to avoid drift when loop is slower than interval)
        self._tick_mono_last: float = 0.0
        self._tick_accum: float = 0.0


    def _apply_exit_state_need_merge(self) -> None:
        """If previous run left exit_state.json with need_merge=true, run merge and clear the marker."""
        p = self.data_dir / "exit_state.json"
        try:
            if not p.exists():
                return
            raw = json.loads(p.read_text(encoding="utf-8") or "{}")
            if not isinstance(raw, dict) or not raw.get("need_merge"):
                return
            self.repo.merge()
            p.unlink()
            log.info("exit_state: need_merge applied, merged WAL and removed marker")
        except Exception:
            log.exception("exit_state: apply need_merge failed")

    def _load_app_paths(self) -> None:
        """从 data_dir/app_paths.json 加载 app_short -> exe_path，供图标 API 使用。
        
        可在后台线程异步调用，也可同步调用（通过 _ensure_app_paths_loaded）。
        """
        with self._lock:
            if self._app_paths_loading:
                return  # 已在加载中，避免重复
            self._app_paths_loading = True
        
        try:
            p = self.data_dir / "app_paths.json"
            if p.exists():
                raw = json.loads(p.read_text(encoding="utf-8") or "{}")
                if isinstance(raw, dict):
                    stale: list[str] = []
                    with self._lock:
                        for k, v in raw.items():
                            if not k or not v:
                                continue
                            app_short = str(k)
                            exe_path = str(v)
                            exe = Path(exe_path)
                            if exe.exists():
                                self._app_paths[app_short] = exe_path
                            else:
                                stale.append(app_short)
                    if stale:
                        log.info("app_paths: removed %d stale entries on load", len(stale))
                        # 冷启动 GC 后立即持久化，确保磁盘上的 app_paths.json 收敛
                        self._persist_app_paths()
        except Exception:
            log.exception("load app_paths failed")
        finally:
            with self._lock:
                self._app_paths_loading = False
                self._app_paths_loaded.set()
    
    def _ensure_app_paths_loaded(self, timeout: float = 2.0) -> None:
        """确保 app_paths 已加载，如果未加载则等待（最多 timeout 秒）。
        
        如果超时仍未加载完成，则降级返回空字典（调用方需处理空字典情况）。
        """
        if self._app_paths_loaded.is_set():
            return  # 已加载完成
        
        # 注意：不要在持锁状态下执行 _load_app_paths()，否则文件 IO 会被"外层锁"包住。
        # 这里锁内只做状态判断；需要同步加载时，锁外执行。
        should_sync_load = False
        with self._lock:
            if (not self._app_paths_loading) and (not self._app_paths_loaded.is_set()):
                should_sync_load = True
        if should_sync_load:
            # 立即同步加载（例如后台线程还没跑起来/加载失败未 set event）
            # 注意：即使 _load_app_paths() 因后台线程已开始加载而立即返回，
            # 我们仍需要统一走 wait(timeout) 确保加载完成，避免竞态。
            self._load_app_paths()
        
        # 等待加载完成（最多 timeout 秒），统一处理同步加载和后台加载两种情况
        if not self._app_paths_loaded.wait(timeout=timeout):
            log.warning("app_paths 加载超时（%s秒），返回空字典降级", timeout)

    def _persist_app_paths(self) -> None:
        """将 _app_paths 写入 app_paths.json（供下次启动与图标 API）。"""
        p = self.data_dir / "app_paths.json"
        try:
            with self._lock:
                copy = dict(self._app_paths)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(copy, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            log.exception("persist app_paths failed")

    def _cleanup_app_paths_runtime(self) -> int:
        """运行期 GC：移除已不存在的 exe 路径，避免图标 API 长期命中无效路径。"""
        with self._lock:
            items = list(self._app_paths.items())
        stale: list[str] = []
        for app_short, exe_path in items:
            try:
                if exe_path and not Path(exe_path).exists():
                    stale.append(app_short)
            except Exception:
                # exists() 异常视为非致命，不中断整体 GC
                continue
        if not stale:
            return 0
        with self._lock:
            for app_short in stale:
                self._app_paths.pop(app_short, None)
        try:
            self._persist_app_paths()
        except Exception:
            log.exception("cleanup app_paths runtime persist failed")
        log.info("app_paths: removed %d stale entries at runtime", len(stale))
        return len(stale)

    # ----- lifecycle -----
    def start(self) -> None:
        if self._thr and self._thr.is_alive():
            return
        self._stop.clear()
        # reset tick clock so usage seconds follows real elapsed time
        self._tick_mono_last = time.monotonic()
        self._tick_accum = 0.0
        self._thr = threading.Thread(target=self._tick_loop, daemon=True, name="tick_loop")
        self._thr.start()

    def stop(self) -> None:
        """Stable shutdown:

        - Stop tick loop
        - Flush WAL (after tick exited), then merge WAL into main files (when tick stopped).
        - In finally: always attempt repo.close() in a sub-thread with timeout (finalize last minute + merge).
        - Save config
        """
        diag.emit("DIAG_STOP_BEGIN", log, "进入 stop")
        self._stop.set()
        tick_joined = True
        if self._thr:
            self._thr.join(timeout=2.0)
            tick_joined = not self._thr.is_alive()
            if not tick_joined:
                log.warning("controller.stop: tick thread did not exit within timeout; skipping repo.flush to avoid race")
            diag.emit("DIAG_STOP_TICK_JOIN", log, "tick join 结果", result="ok" if tick_joined else "timeout")

        try:
            # Flush + merge only when tick has stopped (unchanged behavior).
            if tick_joined and self._thr and not self._thr.is_alive():
                try:
                    self.repo.flush()
                except Exception as e:
                    log_exception_summary(log, "DIAG_EXCEPTION", "controller.stop repo.flush", "可能影响数据落盘", detail=str(e)[:200], reason_code="E_REPO_FLUSH")
                try:
                    self.repo.merge()
                except Exception as e:
                    log_exception_summary(log, "DIAG_EXCEPTION", "controller.stop repo.merge", "可能影响数据合并", detail=str(e)[:200], reason_code="E_REPO_MERGE")
        finally:
            # Unconditionally attempt repo.close() (finalize current minute + merge); avoid deadlock via timeout.
            close_result = {"done": False, "exc": None}

            def _run_close() -> None:
                try:
                    diag.emit("DIAG_REPO_CLOSE_BEGIN", log, "开始执行 repo.close")
                    self.repo.close()
                    close_result["done"] = True
                except Exception as e:
                    close_result["exc"] = e

            close_thr = threading.Thread(target=_run_close, daemon=True, name="repo_close")
            close_thr.start()
            close_thr.join(timeout=3.0)
            close_ok = close_result["done"] and not close_thr.is_alive()
            need_merge = not tick_joined or not close_ok
            st = diag.safe_call(
                self.repo.stats,
                "E_REPO_STATS",
                "repo",
                None,
                log=log,
                phase_cn="controller.stop repo.stats",
                impact_cn="wal_pending 记为 -1",
            )
            if st is not None:
                wal_pending = int(st.get("wal_minutes_pending", 0) or 0) + int(st.get("wal_events_pending", 0) or 0)
            else:
                wal_pending = -1
            if close_thr.is_alive():
                diag.emit(
                    "DIAG_REPO_CLOSE_FAIL", log, "repo.close 超时",
                    finalized=False, wal_pending=wal_pending, need_merge=need_merge, reason_code="timeout",
                )
            elif close_result["done"]:
                diag.emit(
                    "DIAG_REPO_CLOSE_OK", log, "repo.close 成功",
                    finalized=True, wal_pending=wal_pending, need_merge=need_merge,
                )
            else:
                exc = close_result["exc"]
                reason = str(exc)[:200] if exc else "unknown"
                diag.emit(
                    "DIAG_REPO_CLOSE_FAIL", log, "repo.close 异常",
                    finalized=False, wal_pending=wal_pending, need_merge=need_merge, reason_code="exception", reason=reason,
                )
                if exc:
                    log.exception("controller.stop: repo.close failed")

            if need_merge:
                try:
                    state_path = self.data_dir / "exit_state.json"
                    self.data_dir.mkdir(parents=True, exist_ok=True)
                    state_path.write_text(
                        json.dumps(
                            {"exit_clean": False, "need_merge": True, "ts": utcnow().isoformat()},
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    diag.emit("DIAG_EXIT_STATE_WRITE", log, "写入 exit_state", need_merge=True)
                except Exception as e:
                    log_exception_summary(log, "DIAG_EXCEPTION", "controller.stop write exit_state", "恢复依赖下次启动", detail=str(e)[:200], reason_code="E_EXIT_STATE_WRITE")

            try:
                save_config(self.cfg_path, self.cfg)
            except Exception as e:
                log_exception_summary(log, "DIAG_EXCEPTION", "controller.stop save_config", "配置未保存", detail=str(e)[:200], reason_code="E_SAVE_CONFIG")

    # ----- commands -----
    def set_dnd(self, on: bool) -> None:
        # 计算"模式签名"：dnd + force_idle
        before_mode = "dnd" if self.state.is_dnd else ("leave" if self.state.force_idle else "normal")
        self.state.force_idle = False  # 切换到勿扰/正常即退出离开
        self.state.is_dnd = bool(on)
        after_mode = "dnd" if self.state.is_dnd else ("leave" if self.state.force_idle else "normal")
        # 用模式签名判断是否发事件
        if before_mode != after_mode:
            self._emit_event(
                name="mode_set",
                payload={"mode": after_mode},
            )

    def set_force_idle(self, on: bool) -> None:
        """离开（手动）：仅支持开启；关闭只能通过切换到正常/勿扰/离开。"""
        before = bool(self.state.force_idle)
        self.state.force_idle = bool(on)
        after = bool(self.state.force_idle)
        if before != after:
            self._emit_event(
                name="mode_force_idle_set",
                payload={"force_idle": after},
            )

    def set_run_mode(self, mode: str) -> None:
        """设置运行模式（互斥）：normal / dnd / leave。idle 仅由自动检测进入。"""
        mode = (mode or "").strip().lower()
        if mode not in ("normal", "dnd", "leave"):
            return
        before = self._current_mode()
        self.state.auto_idle = False  # 任意手动切模式都清除自动 idle
        self.state.is_paused = False  # 兼容透传，默认始终 False
        self.state.is_dnd = mode == "dnd"
        self.state.force_idle = mode == "leave"
        if mode == "dnd":
            self.state.dnd_reason = "manual"
            self.state.auto_dnd_trigger_app = None
        else:
            self.state.dnd_reason = None
            self.state.auto_dnd_trigger_app = None
        after = self._current_mode()
        if before != after:
            self._emit_event(
                name="mode_set",
                payload={"mode": after},
            )

    def get_display_name(self, app_short: str) -> str:
        """M4：显示名（去 .exe + 别名），仅展示层。"""
        return _get_display_name(self.cfg, app_short or "")

    def is_blacklisted(self, app_short: str) -> bool:
        """M4：是否排除计时黑名单。"""
        return _is_blacklisted(self.cfg, app_short or "")

    # --- rest reminder API (UI -> controller) ---
    def rest_start(self) -> None:
        """User decided to start resting *now*.

        口径：
        - 不立刻清零连续用眼；真正清零发生在 rest_complete。
        - 不把 due 状态清掉：用户若立刻取消休息，仍然视为“需要休息”，但会按冷却策略再提示。
        - 进入休息遮罩期间不再触发 rest prompt（由 _is_resting 控制）。
        """
        with self._lock:
            self._is_resting = True
            # clear any pending snooze so overlay can complete normally
            self._rest_snooze_until = 0.0
            self._rest_next_prompt_work_s = 0
        self._emit_event(name="rest_begin", payload={"ack_work_s": int(self._cont_work_s)})

    def rest_complete(self) -> None:
        """Rest finished. Reset continuous work & clear reminder state."""
        should_emit = False
        with self._lock:
            # Idempotent guard:
            # rest_complete can be triggered by both tick auto-complete and API /api/rest/complete
            # around the same moment. If state is already fully completed, skip duplicate event emit.
            already_completed = (
                (not bool(self._is_resting))
                and int(self._cont_work_s) == 0
                and int(self._rest_ack_work_s) == 0
                and (not bool(self._rest_due))
                and (not bool(self._rest_notified))
                and float(self._rest_snooze_until) <= 0.0
            )
            if not already_completed:
                self._is_resting = False
                self._cont_work_s = 0
                self._rest_ack_work_s = 0
                self._rest_due = False
                self._rest_notified = False
                self._rest_snooze_until = 0.0
                self._rest_cycle += 1  # 新一轮连续用眼，去重键随之翻新，使下一轮提醒能再次弹出
                should_emit = True
        if should_emit:
            self._emit_event(name="rest_complete", payload={})
        # [FIX] 补偿进入：rest 结束后若用户仍 idle，补偿进入 auto_idle（但不 rollback）
        self._compensate_auto_idle_on_exit_rest()

    def rest_snooze(self) -> None:
        """User clicked '跳过/取消本轮休息'.

        口径（按用户验收口径修复）：
        - 跳过不算完成：不清零连续用眼。
        - 跳过后仍然保持"需要休息"状态（due=True），只是进入冷却，冷却后再次弹提醒。
        """
        now = time.time()
        with self._lock:
            # if pressing ESC during overlay, exit resting state
            self._is_resting = False
            # keep _rest_due as-is (usually True when prompt fired)
            # 标记为已提醒：避免冷却后每分钟连发；下一次提醒在"下一轮阈值"后再触发
            self._rest_notified = True
            self._rest_snooze_until = float(now + MIN_REMIND_COOLDOWN_S)
            # [FIX] 修复计算逻辑：点击"稍后"后，需要再工作一个完整的提醒间隔才再次提醒
            # 旧逻辑：((int(self._cont_work_s) // 60) + 1) * 60 会导致只等1分钟就再次提醒
            # 新逻辑：当前工作时间 + 提醒阈值，确保等待完整间隔
            thr_s = int(getattr(self.cfg, "reminder_work_minutes", 20) or 20) * 60
            self._rest_next_prompt_work_s = int(self._cont_work_s) + int(max(60, thr_s))

        self._emit_event(name="rest_snooze", payload={"skip_cycle": True, "ack_work_s": int(self._cont_work_s)})
        # [FIX] 补偿进入：rest 结束后若用户仍 idle，补偿进入 auto_idle（但不 rollback）
        self._compensate_auto_idle_on_exit_rest()

    def notify_rest_entered(self) -> None:
        """Rest 已进入（rest_start 成功后调用），守卫锁住「立即休息」。
        
        按下按钮后立即锁定，等待 2 秒后自动释放（防连点）。
        不等遮罩关闭——遮罩关闭时也会调 notify_rest_closed 做安全兜底。
        """
        with self._lock:
            self._rest_entry_guard.record_rest_entered()
        # 2 秒后自动解锁（即使遮罩没关）
        cooldown_end_at = time.time() + REST_ENTRY_GUARD_COOLDOWN_S
        with self._lock:
            if self._rest_entry_guard.state != RestEntryGuardState.LOCKED_ACTIVE:
                return
            self._rest_entry_guard._cooldown_end_at = cooldown_end_at
        timer = threading.Timer(
            REST_ENTRY_GUARD_COOLDOWN_S,
            self._on_rest_guard_cooldown_expire,
        )
        timer.daemon = True
        timer.start()

    def notify_rest_closed(self) -> None:
        """Rest 遮罩已关闭（CLOSED），进入 2 秒冷却；冷却从本调用时刻起算。幂等：仅 LOCKED_ACTIVE 时执行。"""
        with self._lock:
            if self._rest_entry_guard.state != RestEntryGuardState.LOCKED_ACTIVE:
                try:
                    from ..diagnostics.debug_switch import is_debug_enabled
                    if is_debug_enabled():
                        log.debug("notify_rest_closed skip: guard.state=%s (expect LOCKED_ACTIVE)", self._rest_entry_guard.state.value)
                except Exception as e:
                    log_exception_summary(log, "DIAG_EXCEPTION", "controller fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_CONTROLLER_FALLBACK")
                return
            cooldown_end_at = time.time() + REST_ENTRY_GUARD_COOLDOWN_S
            if self._rest_entry_guard.record_rest_closed(cooldown_end_at):
                if self._rest_guard_cooldown_timer is not None:
                    try:
                        self._rest_guard_cooldown_timer.cancel()
                    except Exception as e:
                        log_exception_summary(log, "DIAG_EXCEPTION", "controller fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_CONTROLLER_FALLBACK")
                self._rest_guard_cooldown_timer = threading.Timer(
                    REST_ENTRY_GUARD_COOLDOWN_S,
                    self._on_rest_guard_cooldown_expire,
                )
                self._rest_guard_cooldown_timer.daemon = True
                self._rest_guard_cooldown_timer.start()

    def _on_rest_guard_cooldown_expire(self) -> None:
        """2 秒冷却到期，解锁「立即休息」。
        
        处理两种状态：
        - LOCKED_ACTIVE：notify_rest_entered 自动解锁路径 → 直接解锁
        - LOCKED_COOLDOWN：notify_rest_closed 正常冷却路径 → record_cooldown_expire
        """
        with self._lock:
            self._rest_guard_cooldown_timer = None
            if self._rest_entry_guard.state == RestEntryGuardState.LOCKED_ACTIVE:
                # 直接解锁（不走 LOCKED_COOLDOWN）
                self._rest_entry_guard.record(
                    RestEntryGuardState.UNLOCKED, "COOLDOWN_EXPIRE",
                )
            else:
                self._rest_entry_guard.record_cooldown_expire()

    def get_rest_start_guard_status(self) -> dict:
        """返回 rest 进入守卫状态，供 snapshot 与 /api/rest/start 共用。键：start_enabled, start_unlock_in_ms, start_block_reason。"""
        with self._lock:
            g = self._rest_entry_guard
            return {
                "start_enabled": g.is_start_allowed(),
                "start_unlock_in_ms": g.unlock_in_ms(time.time()),
                "start_block_reason": g.get_block_reason(),
            }

    def debug_force_rest_due(self) -> None:
        """Dev helper: force prompt conditions (for console testing)."""
        thr = int(getattr(self.cfg, "reminder_work_minutes", 20) or 20) * 60
        with self._lock:
            self._cont_work_s = max(0, thr)
            self._rest_due = True
            self._rest_notified = False
            self._rest_snooze_until = 0.0

    def debug_set_work_s_to_threshold_minus_one(self) -> None:
        """调试：将连续用眼时间设为【休息阈值-1秒】，约 1 秒后会触发休息提醒。"""
        thr_s = int(getattr(self.cfg, "reminder_work_minutes", 20) or 20) * 60
        with self._lock:
            self._cont_work_s = max(0, thr_s - 1)
            self._rest_due = False
            self._rest_notified = False
            self._rest_snooze_until = 0.0
            self._rest_next_prompt_work_s = 0

    def on_config_updated(self) -> None:
        """Called after cfg is changed at runtime.

        Reconcile rest reminder state so increasing the threshold does not keep an old 'due' state.
        This avoids the situation where user changed reminder_work_minutes but still gets frequent prompts
        until restart.
        """
        try:
            thr = int(getattr(self.cfg, "reminder_work_minutes", 20) or 20) * 60
        except Exception:
            thr = 20 * 60

        with self._lock:
            # If new threshold is larger than current continuous work, clear due/notified/snooze.
            if thr > 0 and int(self._cont_work_s) < int(thr):
                self._rest_due = False
                self._rest_notified = False
                self._rest_snooze_until = 0.0
                self._rest_next_prompt_work_s = 0

        # 调用通知配置变更回调（如果已注册）
        if hasattr(self, "_notify_config_callback") and callable(self._notify_config_callback):
            try:
                self._notify_config_callback()
            except Exception:
                log.exception("notify config callback failed")

    # ----- debug -----
    def set_debug_notify(self, on: bool) -> None:
        with self._lock:
            self._debug_notify = bool(on)

    def is_debug_notify(self) -> bool:
        with self._lock:
            return bool(self._debug_notify)

    def set_debug_post_notify_show(self, cb: Optional[Callable[[], None]]) -> None:
        """由 main 在 GUI/dispatcher 就绪后注入，用于「立刻弹窗」从渐入接入弹窗链路。"""
        self._debug_post_notify_show_cb = cb

    def debug_trigger_notify_show(self) -> None:
        """调试：直接投递一次 notify show（走完整 show→渐入 链路），不依赖 rest_due 轮询。"""
        cb = getattr(self, "_debug_post_notify_show_cb", None)
        if callable(cb):
            try:
                cb()
            except Exception as e:
                log_exception_summary(log, "DIAG_EXCEPTION", "controller fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_CONTROLLER_FALLBACK")

    # ----- timeline / events helpers -----
    def _current_mode(self) -> str:
        if self.state.auto_idle:
            return "idle"
        if self.state.force_idle:
            return "leave"
        if self.state.is_dnd:
            return "dnd"
        return "normal"

    def _current_state(self, idle_s: int) -> str:
        try:
            thr = int(self.cfg.idle_threshold_s)
        except Exception:
            thr = 60
        return "idle" if idle_s >= thr else "active"

    def _emit_event(self, name: str, payload: dict) -> None:
        """Non-blocking best-effort: events are buffered and flushed by repo.flush timer."""
        try:
            rec = EventRecord(
                utc_ts=utcnow(),
                local_date=local_date_today(),
                kind=str(name),
                payload=payload,
            )
            self.repo.add_event(rec)
        except Exception:
            log.exception("emit_event failed: %s", name)

    def _get_runtime_extra(self, mark_prompted: bool = False):
        """构建当前运行时的 extra 字典（app_paths, rest, state 等），供 snapshot_today / snapshot_for_date 共用。

        mark_prompted=True 时，会在 should_prompt 出现时立刻标记为已提醒，避免被 UI 拉取提前"消费"。
        """
        # 确保 app_paths 已加载（超时降级为空字典）
        self._ensure_app_paths_loaded(timeout=2.0)
        now = time.time()
        with self._lock:
            app_paths = dict(self._app_paths)
            debug_notify = bool(self._debug_notify)
            last_idle = int(self._last_idle_s)
            last_fg = str(self._last_fg_short)
            work_s = int(self._cont_work_s)
            ack_work_s = int(self._rest_ack_work_s)
            due = bool(self._rest_due)
            notified = bool(self._rest_notified)
            snooze_until = float(self._rest_snooze_until)
            next_prompt_work_s = int(getattr(self, '_rest_next_prompt_work_s', 0) or 0)
            rest_cycle = int(getattr(self, '_rest_cycle', 0) or 0)
            is_resting = bool(self._is_resting)
            thr_s = int(getattr(self.cfg, "reminder_work_minutes", 20) or 20) * 60
            elapsed = max(0, int(work_s) - int(ack_work_s))

            # 兜底：若因时序导致 _rest_due 未置位，按阈值重新推导
            if (not due) and (thr_s > 0) and (elapsed >= thr_s) and (not is_resting):
                due = True
                self._rest_due = True

            if due and notified and ((next_prompt_work_s > 0) and (work_s >= next_prompt_work_s)):
                self._rest_notified = False
                notified = False
                self._rest_snooze_until = 0.0

            should_prompt = False
            prompt_reason = ""
            if due and (not notified) and ((next_prompt_work_s <= 0) or (work_s >= next_prompt_work_s)) and (now >= snooze_until) and (not self.state.is_dnd) and (not self.state.is_paused) and (not self.state.force_idle) and (not is_resting) and (not self.is_blacklisted(last_fg or "")):
                should_prompt = True
                try:
                    from ..diagnostics.debug_switch import is_debug_enabled
                    if is_debug_enabled():
                        log.info("rest: prompt show work_s=%s thr_s=%s", work_s, thr_s)
                except Exception as e:
                    log_exception_summary(log, "DIAG_EXCEPTION", "controller fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_CONTROLLER_FALLBACK")
                if mark_prompted:
                    self._rest_notified = True
                    notified = True
                    self._rest_next_prompt_work_s = int(work_s) + int(max(60, thr_s))
                prompt_reason = "连续使用时间已达到提醒阈值，建议休息。"
                if debug_notify:
                    log.info(
                        "debug: rest prompt extra due=%s notified=%s snooze_until=%.0f next_prompt=%s idle_s=%s resting=%s",
                        due,
                        notified,
                        snooze_until,
                        next_prompt_work_s,
                        last_idle,
                        is_resting,
                    )

            # rest blocked 日志：仅状态变化时输出（blocked↔unblocked 或 blocked 原因变化）
            blocked = bool(due and (not should_prompt))
            if blocked:
                reason = "paused=%s|dnd=%s|resting=%s|snooze=%s|idle=%s" % (
                    self.state.is_paused,
                    self.state.is_dnd,
                    is_resting,
                    "1" if (float(snooze_until or 0) > now) else "0",
                    self.state.force_idle or self.state.auto_idle,
                )
                if (blocked != self._rest_blocked_last) or (reason != self._rest_block_reason_last):
                    log.info(
                        "debug: rest blocked | reason=%s work_s=%s thr_s=%s paused=%s dnd=%s force_idle=%s auto_idle=%s resting=%s snooze_until=%s",
                        reason,
                        work_s,
                        thr_s,
                        self.state.is_paused,
                        self.state.is_dnd,
                        self.state.force_idle,
                        self.state.auto_idle,
                        is_resting,
                        snooze_until,
                    )
                self._rest_blocked_last = True
                self._rest_block_reason_last = reason
            else:
                if self._rest_blocked_last:
                    log.info("debug: rest unblocked | work_s=%s thr_s=%s", work_s, thr_s)
                self._rest_blocked_last = False
                self._rest_block_reason_last = ""

        guard = self.get_rest_start_guard_status()
        rest = {
            "work_s": work_s,
            "ack_work_s": ack_work_s,
            "elapsed_since_ack_s": elapsed,
            "threshold_s": thr_s,
            "cycle": rest_cycle,
            "due": due,
            "notified": notified,
            "snooze_until": snooze_until,
            "should_prompt": should_prompt,
            "prompt_reason": prompt_reason,
            "start_enabled": bool(guard.get("start_enabled", True)),
            "start_unlock_in_ms": int(guard.get("start_unlock_in_ms", 0)),
            "start_block_reason": str(guard.get("start_block_reason", "") or ""),
        }
        if debug_notify:
            now_ts = time.time()
            if now_ts - float(self._debug_last_log_ts or 0.0) >= 5.0:
                self._debug_last_log_ts = now_ts
                log.info(
                    "debug: rest state work_s=%s due=%s notified=%s snooze_until=%.0f next_prompt=%s idle_s=%s paused=%s dnd=%s force_idle=%s resting=%s should_prompt=%s",
                    work_s,
                    due,
                    notified,
                    snooze_until,
                    next_prompt_work_s,
                    last_idle,
                    bool(self.state.is_paused),
                    bool(self.state.is_dnd),
                    bool(self.state.force_idle),
                    is_resting,
                    should_prompt,
                )
        return {
            "app_paths": app_paths,
            "idle_s": last_idle,
            "fg": last_fg,
            "state": self.state,
            "rest": rest,
            "debug": {"notify": self.is_debug_notify()},
        }

    def snapshot_today(self, mark_prompted: bool = False):
        vm = self.vm.get_today(local_date_today())
        return vm, self._get_runtime_extra(mark_prompted=mark_prompted)

    def snapshot_for_date(self, local_date: str, mark_prompted: bool = False):
        """与 snapshot_today 相同结构，但 vm 为指定日期的使用数据；rest/state 仍为当前运行时状态。"""
        from ..utils.time_utils import normalize_local_date
        local_date = normalize_local_date(local_date)
        vm = self.vm.get_today(local_date)
        return vm, self._get_runtime_extra(mark_prompted=mark_prompted)

    def mark_rest_notified(self) -> None:
        with self._lock:
            self._rest_notified = True
            try:
                thr_s = int(getattr(self.cfg, "reminder_work_minutes", 20) or 20) * 60
            except Exception:
                thr_s = 20 * 60
            self._rest_next_prompt_work_s = int(self._cont_work_s) + int(max(60, thr_s))

    def get_app_paths(self) -> dict[str, str]:
        """获取 app_paths 字典。如果尚未加载完成，会等待最多2秒。
        
        超时后返回空字典（降级处理）。
        """
        self._ensure_app_paths_loaded(timeout=2.0)
        with self._lock:
            return dict(self._app_paths)

    def remove_app_path(self, app_short: str, exe_path: str) -> bool:
        """从 app_paths 中移除指定 app_short 条目（需路径一致），并持久化到磁盘。

        用于 /api/icon 在检测到 exe 已被删除时做就地自清理。
        """
        app_short = str(app_short or "")
        exe_path = str(exe_path or "")
        if not app_short or not exe_path:
            return False
        with self._lock:
            current = self._app_paths.get(app_short)
            if not current or str(current) != exe_path:
                return False
            self._app_paths.pop(app_short, None)
        try:
            self._persist_app_paths()
        except Exception:
            log.exception("remove_app_path persist failed")
        log.info("app_paths: removed stale entry app=%s", app_short)
        return True

    def force_flush(self) -> None:
        self.repo.flush()
        self._last_flush = time.time()

    def force_checkpoint(self) -> None:
        """Trigger an immediate checkpoint (persist + truncate WAL) in background."""
        self._start_checkpoint(reason="manual")
    def repo_stats(self) -> dict:
        try:
            return self.repo.stats()
        except Exception:
            log.exception("repo_stats failed")
            return {}

    # ----- internal -----
    def _start_checkpoint(self, reason: str) -> None:
        # avoid concurrent checkpoints
        with self._checkpoint_lock:
            if self._checkpoint_inflight:
                return
            self._checkpoint_inflight = True

        def _run():
            t0 = time.time()
            try:
                self.repo.merge()
                log.info("checkpoint ok: reason=%s dur_ms=%s", reason, int((time.time()-t0)*1000))
            except Exception:
                log.exception("checkpoint failed: reason=%s", reason)
            finally:
                with self._checkpoint_lock:
                    self._checkpoint_inflight = False
                self._last_checkpoint = time.time()

        threading.Thread(target=_run, daemon=True, name="checkpoint").start()

    def _compensate_auto_idle_on_exit_rest(self) -> None:
        """补偿进入：rest 结束后若用户仍 idle，补偿进入 auto_idle（但不 rollback）。

        触发条件：
        - idle_s >= idle_threshold_s
        - 且当前不在 dnd/leave/auto_idle/resting

        动作：
        - auto_idle=True
        - 设置进入 idle 的时间戳（防闪烁）
        - 明确不走 rollback
        """
        try:
            idle_th = int(getattr(self.cfg, "idle_threshold_s", 60) or 60)
            idle = int(get_idle_seconds())
            # 触发条件：idle 满足阈值 且 当前在 normal 模式（非 dnd/leave/auto_idle/resting）
            if idle >= idle_th:
                if not self.state.is_dnd and not self.state.force_idle and not self.state.auto_idle and not self._is_resting:
                    self.state.auto_idle = True
                    self._auto_idle_entered_at = time.time()
                    self._auto_idle_entry_idle = idle
        except Exception:
            log.exception("_compensate_auto_idle_on_exit_rest failed")

    def _tick_loop(self) -> None:
        interval = float(self.cfg.sample_interval_s or 1.0)
        while not self._stop.is_set():
            t0 = time.time()
            try:
                # --- tick elapsed seconds (monotonic) ---
                now_mono = time.monotonic()
                last_mono = float(self._tick_mono_last or 0.0)
                if last_mono <= 0.0:
                    last_mono = now_mono
                delta = max(0.0, now_mono - last_mono)
                self._tick_mono_last = now_mono
                self._tick_accum = float(self._tick_accum or 0.0) + delta
                sec_add = int(self._tick_accum)
                # keep fractional remainder
                if sec_add > 0:
                    self._tick_accum -= float(sec_add)
                # cap to avoid huge jumps after long stalls (debugger / sleep)  # not quota-related
                if sec_add > 5:
                    sec_add = 5
                # fallback: ensure progress when loop is near 1s but rounding produced 0
                if sec_add <= 0 and delta >= 0.9:
                    sec_add = 1

                now_utc = utcnow()
                idle = int(get_idle_seconds())
                # keep previous idle for edge-detection (enter-idle rollback, rest-complete trigger)
                prev_idle = int(self._prev_idle_s)
                with self._lock:
                    self._last_idle_s = idle
                    self._prev_idle_s = idle

                fg_short = ""
                fg_exe = ""

                idle_th = int(getattr(self.cfg, "idle_threshold_s", 60) or 60)
                if idle < idle_th:
                    fg = get_foreground()
                    fg_short = str(fg.app_short or "")
                    fg_exe = str(fg.exe_path or "")
                    with self._lock:
                        self._last_fg_short = fg_short
                        if fg_short and fg_exe:
                            self._app_paths[fg_short] = fg_exe

                # 退出自动 idle：用户恢复操作，回到原模式（仅当是自动进入的，且已保持最小持续时间）
                # 防闪烁：只有当 auto_idle 保持了 _auto_idle_min_duration 秒后才允许退出
                can_exit_auto_idle = (
                    self.state.auto_idle and
                    time.time() - self._auto_idle_entered_at >= self._auto_idle_min_duration
                )
                # 记录进入 auto_idle 时的 idle 值，用于检测退出边缘
                if self.state.auto_idle and not hasattr(self, '_auto_idle_entry_idle'):
                    self._auto_idle_entry_idle = prev_idle if prev_idle >= idle_th else idle
                # 退出条件：当前不 idle，且进入时的 idle 值 >= idle_th（说明确实是从 idle 恢复的）
                if self.state.auto_idle and can_exit_auto_idle:
                    entry_idle = getattr(self, '_auto_idle_entry_idle', -1)
                    if idle < idle_th and entry_idle >= idle_th:
                        self.state.auto_idle = False
                        self._auto_idle_entered_at = 0.0
                        self._auto_idle_entry_idle = -1

                # M4 自动勿扰（前台为该 app 时进勿扰，离开时恢复；手动勿扰优先）
                auto_dnd_apps = getattr(self.cfg, "app_auto_dnd_on_focus", None) or {}
                if fg_short and auto_dnd_apps.get(fg_short):
                    if not self.state.is_dnd:
                        self.state.prev_mode_before_auto_dnd = self._current_mode()
                        self.state.is_dnd = True
                        self.state.dnd_reason = "auto_app"
                        self.state.auto_dnd_trigger_app = fg_short
                        self._emit_event(name="mode_set", payload={"mode": "dnd", "reason": "auto_app"})
                elif getattr(self.state, "dnd_reason", None) == "auto_app" and getattr(self.state, "auto_dnd_trigger_app", None) and fg_short != self.state.auto_dnd_trigger_app:
                    prev = getattr(self.state, "prev_mode_before_auto_dnd", "normal") or "normal"
                    self.state.dnd_reason = None
                    self.state.auto_dnd_trigger_app = None
                    self.state.is_dnd = False
                    # DEPRECATED: is_paused 已废弃，删除恢复分支
                    # self.state.is_paused = prev == "paused"  # 已删除
                    self.state.force_idle = prev == "leave"
                    # 自动勿扰结束：若休息提醒已到，清除"已通知/下次提醒工作量"，允许立即重新提醒。
                    # 不清除 _rest_snooze_until，以尊重用户在休息遮罩中点"稍后"的明确选择。
                    with self._lock:
                        if self._rest_due:
                            self._rest_notified = False
                            self._rest_next_prompt_work_s = 0
                    self._emit_event(name="mode_set", payload={"mode": prev, "reason": "auto_app_leave"})

                if not self.state.is_paused and not self.state.force_idle and not self.state.auto_idle:

                    # continuous work / rest reminder state machine
                    rest_s = int(getattr(self.cfg, "reminder_rest_seconds", 20) or 20)

                    # 1) 进入 idle 状态时：设置 auto_idle 标志（但不立即重置连续用眼时间）
                    # 重置连续用眼时间应该在 idle >= rest_s 时通过 rest_complete() 执行
                    if idle >= idle_th and prev_idle < idle_th:
                        # [FIX] 禁止 rest 期间进入 auto-idle，避免状态混乱
                        if self._is_resting:
                            pass  # skip auto_idle entry during rest
                        elif not self.state.is_dnd:
                            self.state.auto_idle = True  # 同步托盘/模式为 idle，恢复操作后在上方清除
                            self._auto_idle_entered_at = time.time()  # 记录进入时间，防闪烁
                            self._auto_idle_entry_idle = idle  # 记录进入时的 idle 值
                        # [FIX] 不再在进入 idle 时立即重置连续用眼时间
                        # 重置应该在 idle >= rest_s 时通过 rest_complete() 执行（见下方第913行）

                    if idle < idle_th:
                        # 休息遮罩期间：冻结连续用眼/不记录 usage，避免“休息中还在计时、甚至再次触发提醒”。
                        with self._lock:
                            is_resting = bool(self._is_resting)

                        if self.is_debug_notify():
                            now_ts = time.time()
                            if now_ts - float(self._debug_last_tick_log_ts or 0.0) >= 5.0:
                                self._debug_last_tick_log_ts = now_ts
                                log.info(
                                    "debug: tick idle_s=%s idle_th=%s fg=%s resting=%s paused=%s dnd=%s cont_work_s=%s",
                                    idle,
                                    idle_th,
                                    fg_short,
                                    is_resting,
                                    bool(self.state.is_paused),
                                    bool(self.state.is_dnd),
                                    int(self._cont_work_s),
                                )

                        if (not is_resting) and fg_short and not self.is_blacklisted(fg_short):
                            if int(sec_add) > 0:
                                self.repo.add_usage(UsageDelta(app_short=fg_short, seconds=int(sec_add), utc_ts=now_utc))
                                self._last_count_app = fg_short

                                # only count when there is a real foreground app
                                with self._lock:
                                    self._cont_work_s += int(sec_add)

                                    thr = int(getattr(self.cfg, "reminder_work_minutes", 20) or 20) * 60
                                    elapsed = int(self._cont_work_s) - int(self._rest_ack_work_s)
                                    if thr > 0 and elapsed >= thr:
                                        if not self._rest_due:
                                            log.info(
                                                "rest: due reached cont_work_s=%s ack=%s thr_s=%s work_min=%s",
                                                self._cont_work_s,
                                                self._rest_ack_work_s,
                                                thr,
                                                getattr(self.cfg, "reminder_work_minutes", None),
                                            )
                                            # 进入需要休息：只在首次 due 触发时重置状态
                                            self._rest_notified = False
                                            self._rest_snooze_until = 0.0
                                            self._rest_next_prompt_work_s = 0
                                            self._rest_due = True
                        elif self.is_debug_notify() and (not fg_short):
                            log.info("debug: tick skip usage (no fg app)")

                # 2) 自动完成休息：用户离开足够久 = 已休息，重置连续用眼。
                # 注意：放在 if not auto_idle: 块之外，确保 idle 状态下也能触发。
                # 但 paused/force_idle/dnd 下不跨越用户显式模式，禁止自动 complete。
                #
                # [FIX] 判定"已休息"的 idle 阈值改用 idle_threshold_s（用户设的"无操作暂停"时间），
                # 不再用 reminder_rest_seconds（休息时长，默认仅 20s）。旧逻辑把 20s 短暂离开就当成
                # 休息、把连续用眼清零——即使用户把 idle 阈值调到 999s 也照清不误（用户主诉）。
                # 仍保证不小于一次休息时长，避免 idle 阈值被设得过小（如 3s）时一停就清零。
                rest_s = int(getattr(self.cfg, "reminder_rest_seconds", 20) or 20)
                rested_idle_th = max(int(idle_th), rest_s)
                if rested_idle_th > 0 and prev_idle < rested_idle_th and idle >= rested_idle_th:
                    if (not self.state.is_paused) and (not self.state.force_idle) and (not self.state.is_dnd):
                        self.rest_complete()

                now = time.time()

                if now - self._last_flush >= FLUSH_INTERVAL_S:
                    self.repo.flush()
                    self._last_flush = now

                if now - self._last_app_paths_persist >= FLUSH_INTERVAL_S:
                    self._last_app_paths_persist = now
                    removed = 0
                    try:
                        removed = self._cleanup_app_paths_runtime()
                    except Exception:
                        log.exception("cleanup app_paths runtime failed")
                    if removed == 0:
                        self._persist_app_paths()

                # periodic checkpoint (low-frequency)
                if CHECKPOINT_INTERVAL_S and (now - self._last_checkpoint >= CHECKPOINT_INTERVAL_S):
                    self._start_checkpoint(reason="timer")
                    self._last_checkpoint = now

            except Exception:
                log.exception("tick error")

            dt = time.time() - t0
            time.sleep(max(0.0, interval - dt))
