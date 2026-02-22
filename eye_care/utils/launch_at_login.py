"""
Windows 开机自启动：通过当前用户 Run 注册表项实现。
仅 Windows 有效；其他平台为 no-op。
"""
from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)

# 注册表项名称，与「EyE Care」一致
RUN_KEY_NAME = "EyECare"

# HKCU\Software\Microsoft\Windows\CurrentVersion\Run
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_startup_command() -> str:
    """当前进程的启动命令，用于写入 Run 项。"""
    if getattr(sys, "frozen", False):
        return sys.executable
    return sys.executable + ' "' + os.path.abspath(sys.argv[0]) + '"'


def set_launch_at_login(enabled: bool) -> bool:
    """
    设置是否开机自启动（仅 Windows）。
    enabled=True：写入 HKCU\\...\\Run；enabled=False：删除该项。
    返回是否操作成功。
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg
        cmd = _get_startup_command()
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            if enabled:
                winreg.SetValueEx(key, RUN_KEY_NAME, 0, winreg.REG_SZ, cmd)
                log.info("launch_at_login enabled: Run key set to %s", cmd[:80])
            else:
                try:
                    winreg.DeleteValue(key, RUN_KEY_NAME)
                    log.info("launch_at_login disabled: Run key removed")
                except FileNotFoundError:
                    log.debug("launch_at_login disable skipped: Run key not found")
            return True
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        log.warning("launch_at_login set failed: %s", e)
        return False


def is_launch_at_login_registered() -> bool:
    """当前是否已写入 Run 注册表（仅 Windows）。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(key, RUN_KEY_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False
