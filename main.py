"""
EyE Care 主入口(推荐入口)。

目标：
- 直接用 main.py 启动 pywebview 壳(WebView2)，UI 页面统一放在 eye_care/ui/web/ 下。
- 仍支持 --no-ui / --api-port 以便调试或只跑后端。

说明：
- UI 页面由同一个 Flask 进程提供(/ + /api/*)，因此前端 fetch 同源，无需额外端口/跨域。
- 前端业务调用统一走 HTTP /api/*（fetch）。
- pywebview.api 仅负责窗口能力（创建/显示/隐藏/置顶/透明度/位置/多窗口管理）。

本文件为 facade，启动逻辑已拆分至 eye_care/bootstrap/ 目录。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from eye_care.diagnostics import diag, log_exception_summary
from eye_care.bootstrap import dpi_console
from eye_care.bootstrap.constants import DEFAULT_API_PORT


# ----------------------------
# DPI / Console 初始化（模块级别执行）
# ----------------------------
dpi_console.enable_high_dpi_awareness()
dpi_console.hide_console_if_needed()


def parse_args():
    ap = argparse.ArgumentParser(description="EyE Care(pywebview/WebView2)")
    ap.add_argument("--data-dir", default=None, help="数据目录，默认 ./user_data")
    ap.add_argument("--no-ui", action="store_true", help="无界面(API 或 headless)")
    ap.add_argument("--no-single", action="store_true", help="不启用单实例锁")
    ap.add_argument("--debug", action="store_true", help="启用调试：控制台窗口与调试能力")
    ap.add_argument("--api-port", type=int, default=None, metavar="PORT",
                    help="仅启动 HTTP API(隐含 --no-ui)。端口默认来自 EYECARE_API_PORT 或 17992")
    return ap.parse_args()


def main():
    args = parse_args()
    from eye_care.bootstrap.constants import PROJECT_ROOT
    app_root = PROJECT_ROOT
    data_dir = Path(args.data_dir).resolve() if args.data_dir else (app_root / "user_data")
    data_dir.mkdir(parents=True, exist_ok=True)

    # API 模式：--no-ui 且指定端口
    api_port = args.api_port
    if api_port is None:
        try:
            api_port = int(os.environ.get("EYECARE_API_PORT", "0"))
        except (TypeError, ValueError):
            api_port = 0

    if args.no_ui and api_port > 0:
        from eye_care.diagnostics.logging_setup import setup_logging
        from eye_care.controller.app_controller import AppController
        from eye_care.api.server import run_server
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

    # Headless：--no-ui 且未指定端口
    if args.no_ui:
        from eye_care.diagnostics.logging_setup import setup_logging
        from eye_care.controller.app_controller import AppController
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

    # 默认：UI 壳(main 完全接管 run_pywebview)；仅 --debug 时启用控制台
    port = int(os.environ.get("EYECARE_API_PORT", str(DEFAULT_API_PORT)))
    try:
        from eye_care.bootstrap.runtime_shell import run_pywebview_shell
        run_pywebview_shell(data_dir=data_dir, no_single=args.no_single, api_port=port, debug_console=args.debug)
    except Exception as e:
        # 尽量把错误展示出来(双击运行时也能看到)
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
            user32.MessageBoxW.restype = wintypes.INT
            user32.MessageBoxW(None, f"启动失败：{e}", "EyE Care", 0x00000010 | 0x00040000)  # MB_ICONERROR|TOPMOST
        except Exception as e:
            log_exception_summary(logging.getLogger(__name__), "DIAG_EXCEPTION", "main fallback", "degrade_continue", detail=str(e)[:200], reason_code="E_MAIN_FALLBACK")
        raise


if __name__ == "__main__":
    main()
