from __future__ import annotations

"""当前用户会话是否真的可交互。

空闲时长只能回答“多久没有键鼠输入”，不能回答远程桌面是否已经断开、工作站是否
锁定。计时器必须先通过这个门控，避免把不可见桌面上的残留前台窗口算成使用时间。
"""


def is_user_session_interactive() -> bool:
    try:
        import sys

        if sys.platform.startswith("win"):
            from .win_session import is_user_session_interactive_win

            return bool(is_user_session_interactive_win())
    except (ImportError, OSError, AttributeError, TypeError, ValueError):
        # Windows 探针失败时宁可少记一拍，也不能把断开的远程会话当成正在使用。
        return False
    # 其它平台目前没有会话探针；保持原有行为。
    return True
