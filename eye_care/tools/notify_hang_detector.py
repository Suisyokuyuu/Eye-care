from __future__ import annotations

"""
CLI: notify_hang_detector

用法示例（在项目根目录下）：

    python -m eye_care.tools.notify_hang_detector --debug-log user_data\\debug.log

功能：
- 读取 `user_data/debug.log`；
- 调用 `eye_care.diagnostics.notify_hang_analyzer` 对 notify 场景 G 相关信号做离线分析；
- 在标准输出打印一份简要报告。
"""

import argparse
import sys
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    """
    确保项目根目录在 sys.path 中，使得直接运行脚本
    `python eye_care/tools/notify_hang_detector.py` 时也能导入 `eye_care` 包。
    """
    here = Path(__file__).resolve()
    # 结构：.../Eye care V1.0.00/eye_care/tools/notify_hang_detector.py
    # - parents[0] -> tools
    # - parents[1] -> eye_care
    # - parents[2] -> 项目根目录（Eye care V1.0.00）
    root = here.parents[2]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


_ensure_project_root_on_path()

from eye_care.diagnostics.notify_hang_analyzer import (  # noqa: E402
    analyze_debug_log_file,
    format_report,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="EyE Care notify HangDetector（基于 debug.log 的离线分析）"
    )
    ap.add_argument(
        "--debug-log",
        type=str,
        default="user_data/debug.log",
        help="要分析的 debug.log 路径（默认：user_data/debug.log）",
    )
    ap.add_argument(
        "--hiding-threshold",
        type=float,
        default=2.0,
        help="HIDING → HIDDEN 耗时告警阈值（秒，默认 2.0）",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv or sys.argv[1:])
    log_path = Path(ns.debug_log)
    if not log_path.is_file():
        print(f"[notify_hang_detector] 找不到 debug.log 文件: {log_path}", file=sys.stderr)
        return 1

    result = analyze_debug_log_file(log_path)
    report = format_report(result, hiding_warn_threshold_s=ns.hiding_threshold)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

