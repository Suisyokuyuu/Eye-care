"""
事件路由器/策略引擎：读取 event_codes.yml，按 policy/module/block 决定是否放行，并做节流。
业务层只调用 diagnostics 门面 emit()，不在此模块外做策略判断。
"""
from __future__ import annotations

import fnmatch
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger(__name__)

# 回滚：设为 1 时跳过路由，始终放行（与旧行为一致）
# 退役里程碑：v1.1 默认禁用；计划 v1.2 移除。启用时告警。
LEGACY_ENV = "EYECARE_DIAG_LEGACY"
_LEGACY_WARNED = False


def _warn_legacy_if_enabled() -> None:
    """启用 legacy 时仅告警一次。"""
    global _LEGACY_WARNED
    if _LEGACY_WARNED:
        return
    if os.environ.get(LEGACY_ENV, "").strip() in ("1", "true", "yes"):
        _LEGACY_WARNED = True
        log.warning(
            "EYECARE_DIAG_LEGACY=1 已启用，将在 v1.2 移除；建议迁移至 event_codes.yml 策略",
        )

_CACHE: Optional[Dict[str, Any]] = None
_THROTTLE: Dict[str, float] = {}  # throttle_key -> last_emit_ts
_THROTTLE_WINDOW_S = 30
_UNKNOWN_COUNTS: Dict[str, int] = {}  # event_code -> count
_UNKNOWN_LAST_LOG: Dict[str, float] = {}  # event_code -> last log ts
_UNKNOWN_LOG_WINDOW_S = 60


def _find_event_codes_path() -> Path:
    """定位 event_codes.yml。

    现作为后端的一环随包发布：文件位于本模块同目录
    （eye_care/diagnostics/event_codes.yml），打包时由 spec 的 datas 一并带上。
    保留旧 docs/ 路径作为向后兼容兜底（旧布局 / 开发期）。
    """
    here = Path(__file__).resolve().parent
    p = here / "event_codes.yml"
    if p.exists():
        return p
    # 向后兼容：旧 docs 布局
    base = here.parent.parent
    legacy = base / "docs" / "diagnostics" / "event_codes.yml"
    if legacy.exists():
        return legacy
    legacy_cwd = Path.cwd() / "docs" / "diagnostics" / "event_codes.yml"
    if legacy_cwd.exists():
        return legacy_cwd
    return p


def _load_config() -> Dict[str, Any]:
    """加载 event_codes.yml 并解析为运行时结构。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = _find_event_codes_path()
    try:
        import yaml
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.error("diagnostics: failed to load event_codes.yml from %s: %s", path, e)
        _CACHE = {
            "canonical": {},
            "aliases": {},
            "deprecated": [],
            "allow_policies": ["ALWAYS_ON"],
            "block_patterns": [],
            "default_modules": ["notify", "repo"],
            "available_modules": ["notify", "rest", "repo", "dispatch", "api", "style"],
            "exception_throttle_window_s": 30,
        }
        return _CACHE

    canonical: Dict[str, Dict[str, Any]] = {}
    for ent in raw.get("canonical_entries") or []:
        code = ent.get("event_code")
        if code:
            canonical[code] = ent
    aliases = dict(raw.get("aliases") or {})
    deprecated = list(raw.get("deprecated_placeholders") or [])
    rc = raw.get("runtime_controls") or {}
    nm = rc.get("normal_mode") or {}
    dm = rc.get("debug_mode") or {}
    et = rc.get("exception_throttle") or {}
    _CACHE = {
        "canonical": canonical,
        "aliases": aliases,
        "deprecated": deprecated,
        "allow_policies": nm.get("allow_policies") or ["ALWAYS_ON"],
        "block_patterns": nm.get("block_event_patterns") or [],
        "default_modules": dm.get("default_modules") or ["notify", "repo"],
        "available_modules": dm.get("available_modules") or ["notify", "rest", "repo", "dispatch", "api", "style"],
        "exception_throttle_window_s": et.get("reason_code_window_s") or 30,
    }
    return _CACHE


def _owner_to_module(owner: str) -> str:
    """DEBUG_ONLY 条目的 owner 映射到 debug 模块名。"""
    if owner == "rest_overlay":
        return "rest"
    return owner


def _should_throttle(throttle_key: str, window_s: float) -> bool:
    """同一 throttle_key 在 window_s 内已出现过则节流（返回 True = 应跳过）。"""
    now = time.monotonic()
    last = _THROTTLE.get(throttle_key)
    if last is not None and (now - last) < window_s:
        return True
    _THROTTLE[throttle_key] = now
    return False


def reset_cache() -> None:
    """测试用：清空配置与节流状态。"""
    global _CACHE, _THROTTLE, _UNKNOWN_COUNTS, _UNKNOWN_LAST_LOG, _LEGACY_WARNED
    _CACHE = None
    _THROTTLE.clear()
    _UNKNOWN_COUNTS.clear()
    _UNKNOWN_LAST_LOG.clear()
    _LEGACY_WARNED = False


def _record_unknown_event(event_code: str, logger: logging.Logger) -> None:
    """未登记事件：节流内只计数，窗口到期时输出一条 DIAG_UNKNOWN_EVENT，禁止静默丢弃。"""
    now = time.monotonic()
    _UNKNOWN_COUNTS[event_code] = _UNKNOWN_COUNTS.get(event_code, 0) + 1
    last = _UNKNOWN_LAST_LOG.get(event_code, 0)
    if now - last >= _UNKNOWN_LOG_WINDOW_S:
        count = _UNKNOWN_COUNTS[event_code]
        _UNKNOWN_LAST_LOG[event_code] = now
        logger.warning(
            "DIAG_UNKNOWN_EVENT | 未登记事件(节流) | event_code=%s count=%s",
            event_code,
            count,
        )


def emit(
    event_code: str,
    logger: logging.Logger,
    msg_cn: str,
    level: int = logging.INFO,
    **kwargs: Any,
) -> bool:
    """
    策略引擎入口：是否允许输出该条诊断。
    - 若返回 True，调用方（diagnostics 层）写 log；若 False，不写。
    - 业务层只传 event_code + 内容，不在此处做 policy/模块判断。
    """
    if os.environ.get(LEGACY_ENV, "").strip() in ("1", "true", "yes"):
        _warn_legacy_if_enabled()
        return True

    cfg = _load_config()
    if event_code in cfg["deprecated"]:
        return False

    canonical = cfg["aliases"].get(event_code, event_code)
    entry = cfg["canonical"].get(canonical)
    if not entry:
        _record_unknown_event(event_code, logger)
        return False

    policy = entry.get("policy") or "DEBUG_ONLY"
    throttle_key = entry.get("throttle_key") or canonical
    throttle_window_s = float(entry.get("throttle_window_s") or cfg.get("exception_throttle_window_s", _THROTTLE_WINDOW_S))
    module: Optional[str] = None
    if policy == "DEBUG_ONLY":
        module = entry.get("module") or _owner_to_module(entry.get("owner") or "")

    # DIAG_SM_TRANSITION：按 kwargs["machine"] 归属到 notify/rest/style，且不按固定 key 节流（避免大量迁移被吞）
    if canonical == "DIAG_SM_TRANSITION":
        module = kwargs.get("machine") or "runtime"
        throttle_key = "DIAG_SM_TRANSITION:%s:%s:%s" % (
            str(kwargs.get("machine", "")),
            str(kwargs.get("event", "")),
            str(kwargs.get("session_id", ""))[:32],
        )
        throttle_window_s = 0  # 不节流：window_s=0 表示每次不同 key 都放行（key 已含 event/session 区分）

    if policy == "DEPRECATED":
        return False

    try:
        from .debug_switch import is_debug_enabled, is_debug_module
    except ImportError:
        is_debug_enabled = lambda: False  # type: ignore[assignment]
        is_debug_module = lambda m: False  # type: ignore[assignment]

    if is_debug_enabled():
        if policy == "ALWAYS_ON":
            return True
        if policy == "DEBUG_ONLY" and module and is_debug_module(module):
            if throttle_window_s > 0 and _should_throttle(throttle_key, throttle_window_s):
                return False
            return True
        return False

    # normal mode: only ALWAYS_ON, no throttle for ALWAYS_ON
    if policy not in cfg["allow_policies"]:
        return False
    # 某些关键 ALWAYS_ON 事件需要绕过 block_patterns（例如 ACK 严格投递失败）
    _block_exempt = {
        "DIAG_NOTIFY_ACK_POST_FAILED",
    }
    if canonical in _block_exempt or event_code in _block_exempt:
        return True
    for pat in cfg["block_patterns"]:
        if fnmatch.fnmatch(event_code, pat) or fnmatch.fnmatch(canonical, pat):
            return False
    return True
