"""
API 鉴权：写接口 token 校验。
启动时生成 UUID 存内存，通过 GET /api/auth/token 下发；前端首屏加载时请求并缓存。
"""
from __future__ import annotations

import uuid
from typing import Optional

_TOKEN: Optional[str] = None


def generate_token() -> str:
    """启动时调用，生成并存储 token，仅存内存不持久化。"""
    global _TOKEN
    _TOKEN = str(uuid.uuid4())
    return _TOKEN


def get_token() -> Optional[str]:
    """返回当前 token，进程重启后为 None。"""
    return _TOKEN


def validate_token(header_value: Optional[str]) -> bool:
    """校验 X-EYECare-Token header 是否与当前 token 一致。"""
    t = get_token()
    if not t:
        return False
    return bool(header_value and header_value.strip() == t)
