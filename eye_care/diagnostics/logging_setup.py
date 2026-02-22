"""
日志设置。当 debug 关闭时，仅输出到 stderr（若 EYECARE_CONSOLE_LOG=1），不写固定路径文件。
当 debug 开启时，写入 data_dir/debug.log。
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading

from . import diag


def _is_debug() -> bool:
    try:
        from .debug_switch import is_debug_enabled
        return is_debug_enabled()
    except Exception:
        return bool(os.environ.get("EYECARE_DEBUG", "").strip() in ("1", "true", "yes"))


def _install_excepthooks(logger: logging.Logger) -> None:
    # 捕获主线程未处理异常：先打中文概述，再打英文堆栈
    def _sys_hook(exctype, value, tb):
        diag.emit("DIAG_UNCAUGHT", logger, "主线程未捕获异常，进程可能即将退出", level=logging.ERROR)
        logger.exception("UNCAUGHT exception", exc_info=(exctype, value, tb))
    sys.excepthook = _sys_hook

    # 捕获子线程未处理异常（Py>=3.8）；6.1 必带 thread_name, thread_ident, last_known_phase
    def _thread_hook(args):
        thread = getattr(args, "thread", None)
        thread_name = getattr(thread, "name", None) or ""
        thread_ident = getattr(thread, "ident", None)
        diag.emit(
            "DIAG_UNCAUGHT_THREAD", logger, "子线程未捕获异常，该线程逻辑异常",
            level=logging.ERROR,
            thread_name=thread_name,
            thread_ident=thread_ident,
            last_known_phase="thread_excepthook",
        )
        logger.exception("UNCAUGHT thread exception", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_hook

def setup_logging(log_path: Path) -> None:
    """log_path 来自 data_dir，非固定路径。仅在 debug 开启时输出详细诊断到文件。"""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers[:] = []

    # 始终写 data_dir/debug.log（路径由 data_dir 决定，非固定）
    fh = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    # NOTE: console logging can freeze the whole app if the console is in a blocked state
    # (e.g., Windows console selection / QuickEdit). Default to file-only.
    if os.environ.get("EYECARE_CONSOLE_LOG", "0") == "1":
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    _install_excepthooks(root)

    logging.getLogger(__name__).info("logging enabled -> %s", log_path)
