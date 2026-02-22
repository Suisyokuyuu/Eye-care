"""
诊断开关：统一控制所有诊断能力（硬日志、截图、watchdog、debug console 等）。

默认关闭。启用方式：
- 环境变量 EYECARE_DEBUG=1
- 或配置 debug.enabled=true（需在 config 加载后传入）

Debug 模式必须模块化：禁止一键全开。默认仅 notify+repo。
环境变量 EYECARE_DEBUG_MODULES=notify,repo 或配置 debug.modules 指定模块列表。
"""
from __future__ import annotations

import os
from typing import Optional, Set

_cached: Optional[bool] = None
_debug_modules: Optional[Set[str]] = None
_available: Set[str] = {"notify", "rest", "repo", "dispatch", "api", "style", "runtime", "tray"}


def _parse_modules(s: str) -> Set[str]:
    out: Set[str] = set()
    for x in s.split(","):
        x = x.strip().lower()
        if x and x in _available:
            out.add(x)
    return out


def _get_debug_modules() -> Set[str]:
    global _debug_modules
    if _debug_modules is not None:
        return _debug_modules
    env_val = os.environ.get("EYECARE_DEBUG_MODULES", "").strip()
    if env_val:
        _debug_modules = _parse_modules(env_val)
        return _debug_modules
    _debug_modules = {"notify", "repo"}
    return _debug_modules


def is_debug_enabled(config_enabled: Optional[bool] = None) -> bool:
    """检查诊断开关。config_enabled 来自 load_config 后的 cfg.debug_enabled。"""
    global _cached
    if _cached is not None:
        return _cached
    env_val = os.environ.get("EYECARE_DEBUG", "").strip()
    if env_val in ("1", "true", "yes", "on"):
        _cached = True
        return True
    if config_enabled is True:
        _cached = True
        return True
    _cached = False
    return False


def is_debug_module(module: str) -> bool:
    """Debug 模式下该模块是否开启。仅当 is_debug_enabled() 为 True 时有效；否则恒为 False。"""
    if not is_debug_enabled():
        return False
    return (module or "").strip().lower() in _get_debug_modules()


def set_debug_modules(modules: Optional[Set[str]] = None) -> None:
    """设置 Debug 开启的模块（测试或配置注入）。None 表示恢复默认 notify,repo。"""
    global _debug_modules
    _debug_modules = modules if modules is not None else {"notify", "repo"}


def set_debug_enabled(enabled: bool) -> None:
    """测试用：强制设置开关。"""
    global _cached
    _cached = bool(enabled)


def reset_cache() -> None:
    """测试用：重置缓存。"""
    global _cached, _debug_modules
    _cached = None
    _debug_modules = None
