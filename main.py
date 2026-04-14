from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from eye_care.bootstrap import dpi_console
from eye_care.bootstrap.constants import DEFAULT_API_PORT
from eye_care.diagnostics import log_exception_summary


dpi_console.enable_high_dpi_awareness()
dpi_console.hide_console_if_needed()


def parse_args():
    ap = argparse.ArgumentParser(description="EyE Care host launcher")
    ap.add_argument("--data-dir", default=None, help="Data directory, defaults to ./user_data")
    ap.add_argument("--no-ui", action="store_true", help="Run API/headless mode without desktop UI")
    ap.add_argument("--no-single", action="store_true", help="Disable single-instance guard")
    ap.add_argument("--debug", action="store_true", help="Enable debug console and extra diagnostics")
    ap.add_argument("--api-port", type=int, default=None, metavar="PORT", help="Explicit local API port")
    ap.add_argument("--host", choices=("legacy", "qt"), default=os.environ.get("EYECARE_HOST", "legacy"), help="Desktop host to use")
    return ap.parse_args()


def main():
    args = parse_args()
    from eye_care.bootstrap.constants import PROJECT_ROOT

    app_root = PROJECT_ROOT
    data_dir = Path(args.data_dir).resolve() if args.data_dir else (app_root / "user_data")
    data_dir.mkdir(parents=True, exist_ok=True)

    api_port = args.api_port
    if api_port is None:
        try:
            api_port = int(os.environ.get("EYECARE_API_PORT", "0"))
        except (TypeError, ValueError):
            api_port = 0

    if args.no_ui and api_port > 0:
        from eye_care.api.server import run_server
        from eye_care.controller.app_controller import AppController
        from eye_care.diagnostics.logging_setup import setup_logging

        setup_logging(data_dir / "debug.log")
        log = logging.getLogger(__name__)
        controller = AppController(data_dir=data_dir)
        controller.start()
        log.info("API mode: server on port %s", api_port)
        try:
            run_server(controller, host="127.0.0.1", port=api_port)
        except KeyboardInterrupt:
            return
        finally:
            controller.stop()
        return

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

    port = int(os.environ.get("EYECARE_API_PORT", str(DEFAULT_API_PORT)))
    try:
        if args.host == "qt":
            from eye_care.qt import run_qt_shell

            run_qt_shell(data_dir=data_dir, no_single=args.no_single, api_port=port, debug_console=args.debug)
        else:
            from eye_care.bootstrap.runtime_shell import run_pywebview_shell

            run_pywebview_shell(data_dir=data_dir, no_single=args.no_single, api_port=port, debug_console=args.debug)
    except Exception as exc:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
            user32.MessageBoxW.restype = wintypes.INT
            user32.MessageBoxW(None, f"?????{exc}", "EyE Care", 0x00000010 | 0x00040000)
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
