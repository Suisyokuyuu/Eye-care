"""设置页 QML 数据桥（step3）。

把 AppConfig 读出成 QML 设置页可直接绑定的 view-model（`config` map），并接收
设置页【应用】提交的 payload，按 web app.js 的口径做 clamp/校验后落库。

设计要点（与左右栏桥一致）：
  - 唯一一份转换/校验实现，生产与预览共用。差异只在 loader/saver：
      生产 → loader 读真 cfg、saver 落盘(save_config + on_config_updated + 开机自启)。
      预览 → loader 读真 cfg、saver **沙箱**（只 log、不落盘、不动注册表），避免预览改坏正式配置。
  - clamp 口径 1:1 复刻 app.js initSettingsModal.saveAndClose：
      idle 3..300 / work 1..600 分 / rest sec:5..3600 min:60..7200 / notify_hide 0..600。
  - 不在构造期做任何写操作；apply 才写。

QML 侧通过 contextProperty `settingsBridge` 访问：打开页时读 `settingsBridge.config`
填充各控件，点【应用】调 `settingsBridge.apply({...})`。
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import QObject, Property, Signal, Slot

log = logging.getLogger(__name__)

# 设置页涉及的全部 config key（含 close_action，web get_config 漏返，这里补上）
_SETTINGS_KEYS = (
    "startup_launch_at_login",
    "startup_dnd",
    "startup_show_main",
    "idle_threshold_s",
    "close_action",
    "notify_enabled",
    "reminder_work_minutes",
    "reminder_rest_seconds",
    "reminder_rest_unit",
    "notify_auto_hide_seconds",
    "notify_sound_enabled",
    "rest_end_sound_enabled",
    "show_onboarding",
)


def _clamp(v, lo, hi, default):
    try:
        v = int(v)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def sanitize(payload: dict) -> dict:
    """按 app.js 口径 clamp/规整设置 payload，返回只含合法 key 的新 dict。"""
    p = dict(payload or {})
    out: dict = {}
    # 布尔
    for k in ("startup_launch_at_login", "startup_dnd", "startup_show_main",
              "notify_enabled", "notify_sound_enabled", "rest_end_sound_enabled"):
        if k in p:
            out[k] = bool(p[k])
    # 无操作暂停 3..300
    if "idle_threshold_s" in p:
        out["idle_threshold_s"] = _clamp(p["idle_threshold_s"], 3, 300, 60)
    # 关闭行为
    if "close_action" in p:
        ca = str(p["close_action"])
        out["close_action"] = ca if ca in ("ask", "minimize", "quit") else "ask"
    # 休息间隔（分）1..600
    if "reminder_work_minutes" in p:
        out["reminder_work_minutes"] = _clamp(p["reminder_work_minutes"], 1, 600, 20)
    # 休息时长单位
    unit = p.get("reminder_rest_unit")
    unit = unit if unit in ("sec", "min") else "sec"
    out["reminder_rest_unit"] = unit
    # 休息时长：sec → 输入即秒(5..3600)；min → 输入是分，转秒(60..7200)
    if "reminder_rest_seconds" in p:
        raw = _clamp(p["reminder_rest_seconds"], 1, 7200, 5 if unit == "sec" else 60)
        if unit == "min":
            out["reminder_rest_seconds"] = max(60, min(7200, raw))
        else:
            out["reminder_rest_seconds"] = max(5, min(3600, raw))
    # 通知显示时长 0..600
    if "notify_auto_hide_seconds" in p:
        out["notify_auto_hide_seconds"] = _clamp(p["notify_auto_hide_seconds"], 0, 600, 20)
    # 启动引导开关
    if "show_onboarding" in p:
        out["show_onboarding"] = bool(p["show_onboarding"])
    return out


def cfg_to_dict(cfg) -> dict:
    """把 AppConfig 读成设置页 view-model（含默认兜底）。"""
    g = lambda k, d: getattr(cfg, k, d)
    return {
        "startup_launch_at_login": bool(g("startup_launch_at_login", False)),
        "startup_dnd": bool(g("startup_dnd", False)),
        "startup_show_main": bool(g("startup_show_main", True)),
        "idle_threshold_s": int(g("idle_threshold_s", 60) or 60),
        "close_action": str(g("close_action", "ask") or "ask"),
        "notify_enabled": bool(g("notify_enabled", True)),
        "reminder_work_minutes": int(g("reminder_work_minutes", 20) or 20),
        "reminder_rest_seconds": int(g("reminder_rest_seconds", 20) or 20),
        "reminder_rest_unit": str(g("reminder_rest_unit", "sec") or "sec"),
        "notify_auto_hide_seconds": int(g("notify_auto_hide_seconds", 20)),
        "notify_sound_enabled": bool(g("notify_sound_enabled", True)),
        "rest_end_sound_enabled": bool(g("rest_end_sound_enabled", True)),
        "show_onboarding": bool(g("show_onboarding", True)),
    }


def build_settings_io(controller, *, persist: bool, log: Optional[logging.Logger] = None):
    """围绕 controller.cfg 造 (loader, saver)。

    persist=True（生产）：saver 写入 cfg → save_config → on_config_updated →（自启项变化时）set_launch_at_login。
    persist=False（预览）：saver 只 log，不落盘、不动注册表（沙箱）。
    """
    lg = log or logging.getLogger(__name__)

    def loader() -> dict:
        return cfg_to_dict(controller.cfg)

    def saver(clean: dict) -> None:
        if not persist:
            lg.info("[settings 预览沙箱] 不落盘，提交内容=%s", clean)
            return
        cfg = controller.cfg
        launch_changed = ("startup_launch_at_login" in clean
                          and bool(clean["startup_launch_at_login"]) != bool(getattr(cfg, "startup_launch_at_login", False)))
        for k, v in clean.items():
            setattr(cfg, k, v)
        from eye_care.config.store import save_config
        save_config(controller.cfg_path, cfg)
        lg.info("[settings] 已落盘: %s", clean)
        if launch_changed:
            try:
                from eye_care.utils.launch_at_login import set_launch_at_login
                set_launch_at_login(bool(cfg.startup_launch_at_login))
            except Exception as e:  # noqa: BLE001
                lg.warning("set_launch_at_login 失败: %s", e)
        on_updated = getattr(controller, "on_config_updated", None)
        if callable(on_updated):
            try:
                on_updated()
            except Exception as e:  # noqa: BLE001
                lg.warning("on_config_updated 失败: %s", e)

    return loader, saver


class SettingsBridge(QObject):
    """设置页桥：QML 读 `config` 填充、`apply(payload)` 提交。"""

    configChanged = Signal()

    def __init__(self, loader: Callable[[], dict], saver: Callable[[dict], None], *, parent=None):
        super().__init__(parent)
        self._loader = loader
        self._saver = saver
        self._config: dict = {}
        self.reload()

    @Property("QVariantMap", notify=configChanged)
    def config(self) -> dict:
        return self._config

    @Slot()
    def reload(self) -> None:
        try:
            self._config = self._loader() or {}
        except Exception as e:  # noqa: BLE001
            log.warning("settings reload 失败: %s", e)
            self._config = {}
        self.configChanged.emit()

    @Slot("QVariantMap")
    def apply(self, payload) -> None:
        clean = sanitize(dict(payload) if payload else {})
        try:
            self._saver(clean)
        except Exception as e:  # noqa: BLE001
            log.warning("settings apply 落库失败: %s", e)
        self.reload()

    @Slot(bool)
    def setShowOnboarding(self, show: bool) -> None:
        """引导完成/跳过后由 QML 调用，持久化 show_onboarding 设置。"""
        try:
            self._saver({"show_onboarding": bool(show)})
        except Exception as e:  # noqa: BLE001
            log.warning("setShowOnboarding 落库失败: %s", e)
        self.reload()
