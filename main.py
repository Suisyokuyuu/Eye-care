from __future__ import annotations

import argparse
import logging
import json
import os
import time
from pathlib import Path

from eye_care.bootstrap import dpi_console
from eye_care.diagnostics import log_exception_summary


dpi_console.enable_high_dpi_awareness()
dpi_console.hide_console_if_needed()


def parse_args():
    ap = argparse.ArgumentParser(description="EyE Care host launcher")
    ap.add_argument("--data-dir", default=None, help="Data directory, defaults to ./user_data")
    ap.add_argument("--no-ui", action="store_true", help="Run API/headless mode without desktop UI")
    ap.add_argument("--no-single", action="store_true", help="Disable single-instance guard")
    ap.add_argument("--debug", action="store_true", help="Enable debug logging and extra diagnostics")
    ap.add_argument("--startup-check", action="store_true", help="Verify desktop startup with an isolated --data-dir")
    ap.add_argument("--host", choices=("qt",), default=os.environ.get("EYECARE_HOST", "qt"), help="Desktop host to use (Qt only)")
    return ap.parse_args()


def main():
    args = parse_args()
    if args.startup_check and (not args.data_dir or args.no_ui):
        raise SystemExit("--startup-check requires an isolated --data-dir")
    from eye_care.bootstrap.constants import PROJECT_ROOT

    app_root = PROJECT_ROOT
    data_dir = Path(args.data_dir).resolve() if args.data_dir else (app_root / "user_data")
    data_dir.mkdir(parents=True, exist_ok=True)
    from eye_care.diagnostics.logging_setup import setup_logging
    setup_logging(data_dir / "debug.log")

    if args.no_ui:
        from eye_care.controller.app_controller import AppController
        from eye_care.diagnostics.logging_setup import setup_logging

        setup_logging(data_dir / "debug.log")
        log = logging.getLogger(__name__)
        controller = AppController(data_dir=data_dir)
        controller.start()
        log.info("no-ui: headless. Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return
        finally:
            controller.stop()
        return

    try:
        from eye_care.qt import run_qt_shell

        run_qt_shell(data_dir=data_dir, no_single=args.no_single or args.startup_check,
                     debug_console=args.debug, startup_check=args.startup_check)
    except Exception as exc:
        logging.getLogger(__name__).exception("Desktop startup failed")
        if args.startup_check:
            report_path = data_dir / "startup_check.json"
            if not report_path.exists():
                report_path.write_text(json.dumps({
                    "ok": False, "error": str(exc), "cause": str(exc.__cause__) if exc.__cause__ else "",
                }, ensure_ascii=False, indent=2), encoding="utf-8")
            raise SystemExit(1)
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
            user32.MessageBoxW.restype = wintypes.INT
            detail = f"{exc}\n{exc.__cause__}" if exc.__cause__ else str(exc)
            user32.MessageBoxW(None, f"启动失败：{detail}\n\n详细原因已记录到数据目录的 debug.log。", "EyE Care", 0x00000010 | 0x00040000)
        except Exception as fallback_exc:
            log_exception_summary(
                logging.getLogger(__name__),
                "DIAG_EXCEPTION",
                "main fallback",
                "degrade_continue",
                detail=str(fallback_exc)[:200],
                reason_code="E_MAIN_FALLBACK",
            )
        raise


if __name__ == "__main__":
    main()
