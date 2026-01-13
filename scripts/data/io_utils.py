from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict


# -------------------- [Data: low-level IO helpers] --------------------
# 约定：
# - 所有 JSON 读写都在这里做（上层不关心细节）
# - 写入采用“写临时文件 -> 原子替换”避免意外断电/崩溃造成文件半写


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # 文件损坏/编码异常：返回默认值，让上层决定如何处理
        return default


def atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    ensure_dir(path.parent)

    tmp_dir = path.parent
    fd, tmp_path_str = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=str(tmp_dir))
    tmp_path = Path(tmp_path_str)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        # Windows / Linux: replace 是原子操作（同一分区）
        os.replace(str(tmp_path), str(path))
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
