from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class AppConfig:
    sample_interval_s: float = 1.0
    idle_threshold_s: int = 60
    reminder_work_minutes: int = 20
    # 休息时长（秒）。用于“马上休息/休息界面”倒计时。
    reminder_rest_seconds: int = 20
    # 休息时长单位，仅用于 UI 展示与输入："sec" | "min"
    reminder_rest_unit: str = "sec"
    theme_name: str = "solid_dark"

    # ---- UI/behavior (persisted) ----
    # 是否启动时默认进入勿扰模式（仅影响下次启动）
    startup_dnd: bool = False
    # 启动时是否显示主界面（否则启动到托盘，仅影响下次启动）
    startup_show_main: bool = True
    # 开机是否自启动（Windows：写入当前用户 Run 注册表或启动文件夹）
    startup_launch_at_login: bool = False

    # 提醒弹窗（RestPrompt）自动渐隐时间（秒）。
    # 0 = 始终显示；>0 = 显示 N 秒后开始渐隐并自动隐藏。
    toast_fade_seconds: int = 0

    # 通知（Notify）自动隐藏时长（秒）。口径：仅在设置页点击【应用】后生效。
    notify_auto_hide_seconds: int = 20

    # 休息倒计时结束时是否播放提示音（仅完成时播放，跳过不播放）
    rest_end_sound_enabled: bool = True

    # 启用休息提醒功能总开关（控制 NotifierService 的启动/停止）
    notify_enabled: bool = True

    # Notify 提示音开关：仅控制“通知气泡显示成功时是否播放提示音”
    # 语义：
    # - notify_enabled == False 时，本开关不生效（不调度 Notify、不播放声音）
    # - notify_enabled == True 且 notify_sound_enabled == True：有气泡时播放提示音
    # - notify_enabled == True 且 notify_sound_enabled == False：仅视觉提醒，不播放提示音
    notify_sound_enabled: bool = True

    # 诊断模式：启用硬日志、截图、watchdog、debug console。默认 False。
    debug_enabled: bool = False

    # ---- M4 应用设置（持久化） ----
    # 单应用分类覆盖（app_short -> category 名）
    app_category_overrides: Dict[str, str] = field(default_factory=dict)
    # 单应用显示名别名（app_short -> 显示名）
    app_display_overrides: Dict[str, str] = field(default_factory=dict)
    # 该 app 为前台时自动勿扰（app_short -> True）
    app_auto_dnd_on_focus: Dict[str, bool] = field(default_factory=dict)
    # 前台应用进入全屏（游戏/全屏视频）时自动进勿扰，退出全屏恢复。默认开启。
    fullscreen_dnd: bool = True
    # 排除计时的黑名单（app_short 列表，不记录、不触发休息）
    blacklist_apps: List[str] = field(default_factory=list)

    # 关闭主窗口时的行为："ask"（询问）| "minimize"（最小化到托盘）| "quit"（退出）
    close_action: str = "ask"

    # 启动引导：True=启动时显示引导；首次完成/跳过后自动置 False
    show_onboarding: bool = True
