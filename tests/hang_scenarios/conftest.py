from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal
from urllib import error as urlerror
from urllib import request as urlrequest

import pytest

from eye_care.diagnostics.notify_hang_analyzer import analyze_debug_log_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = PROJECT_ROOT / "main.py"


@dataclass
class AppRunner:
    """Start and stop an isolated EyE Care process for integration tests."""

    proc: subprocess.Popen | None = None
    data_dir: Path | None = None
    api_port: int = 8765

    def start_app(self, *, extra_args: Iterable[str] | None = None) -> None:
        if self.proc and self.proc.poll() is None:
            return

        ts = int(time.time())
        pid = os.getpid()
        uniq = int(time.monotonic_ns() % 10_000_000)
        self.data_dir = PROJECT_ROOT / f"user_data_test_{ts}_{pid}_{uniq}"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.setdefault("EYECARE_DEBUG", "1")
        env["EYECARE_API_PORT"] = str(self.api_port)

        args = [
            sys.executable,
            str(MAIN_PY),
            "--data-dir",
            str(self.data_dir),
            "--no-single",
        ]
        if extra_args:
            args.extend(extra_args)

        self.proc = subprocess.Popen(args, cwd=str(PROJECT_ROOT), env=env)

    def is_running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def wait_for_ready(self, timeout_s: float = 60.0) -> bool:
        url = f"http://127.0.0.1:{self.api_port}/api/health"
        start = time.time()

        while time.time() - start < timeout_s:
            if not self.is_running():
                return False
            try:
                with urlrequest.urlopen(url, timeout=2.0) as resp:  # type: ignore[arg-type]
                    if resp.status == 200:
                        payload = json.loads(resp.read().decode("utf-8") or "{}")
                        if payload.get("ok"):
                            return True
            except (urlerror.URLError, TimeoutError, json.JSONDecodeError, ValueError):
                pass
            time.sleep(0.5)

        return False

    def stop_app(self, timeout_s: float = 10.0) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@dataclass
class HangDetector:
    """Analyze debug.log for notify hang signatures."""

    app_runner: AppRunner
    hiding_warn_threshold_s: float = 2.0

    def _debug_log_path(self) -> Path:
        data_dir = self.app_runner.data_dir or (PROJECT_ROOT / "user_data")
        return data_dir / "debug.log"

    def wait_healthy_or_timeout(
        self,
        timeout_s: float,
        mode: Literal["generic", "notify_hide"] = "generic",
        *,
        require_min_hide_pairs: int | None = None,
    ) -> bool:
        deadline = time.time() + timeout_s
        log_path = self._debug_log_path()

        while time.time() < deadline and not log_path.is_file():
            if not self.app_runner.is_running():
                return False
            time.sleep(0.5)

        if not log_path.is_file():
            return False

        try:
            result = analyze_debug_log_file(log_path)
        except FileNotFoundError:
            return False

        if result.flask_timeout_count > 0:
            return False
        if result.notify_ack_post_failed_count > 0:
            return False
        if result.open_hiding:
            return False
        if mode == "notify_hide" and result.max_hide_duration_s > self.hiding_warn_threshold_s:
            return False
        if require_min_hide_pairs is not None and result.hide_pair_count < require_min_hide_pairs:
            return False

        return True


@dataclass
class ScenarioDriver:
    """Drive high-value scenarios through the local HTTP API."""

    app_runner: AppRunner
    _api_token: str | None = None

    @property
    def _base_url(self) -> str:
        return f"http://127.0.0.1:{self.app_runner.api_port}"

    def _fetch_token(self) -> str:
        if self._api_token:
            return self._api_token

        with urlrequest.urlopen(f"{self._base_url}/api/auth/token", timeout=5.0) as resp:  # type: ignore[arg-type]
            payload = json.loads(resp.read().decode("utf-8") or "{}")
        token = payload.get("token")
        if not token:
            raise RuntimeError("failed to obtain API token from /api/auth/token")
        self._api_token = str(token)
        return self._api_token

    def _post_json(self, path: str, body: dict | None = None, require_auth: bool = False) -> None:
        data = json.dumps(body or {}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if require_auth:
            headers["X-EYECare-Token"] = self._fetch_token()
        req = urlrequest.Request(f"{self._base_url}{path}", data=data, headers=headers, method="POST")
        with urlrequest.urlopen(req, timeout=5.0):
            pass

    def run_scenario(self, name: str, timeout_s: float) -> bool:
        if not self.app_runner.is_running():
            self.app_runner.start_app()
            assert self.app_runner.wait_for_ready(), "App did not become ready before timeout"

        try:
            self._post_json(
                "/api/diag/log",
                {"src": "pytest.hang_scenarios", "stage": name, "msg": f"start {name}"},
                require_auth=True,
            )
        except Exception:
            pass

        try:
            if name == "scenario_f_notify_hide":
                self._post_json("/api/config", {"notify_auto_hide_seconds": 3}, require_auth=True)
                self._post_json("/api/debug/notify", {}, require_auth=True)
                time.sleep(max(0.0, timeout_s - 1.5))

            elif name == "scenario_g_notify_storm":
                self._post_json("/api/config", {"notify_auto_hide_seconds": 3}, require_auth=True)
                end = time.time() + timeout_s
                storm_until = time.time() + timeout_s * 0.4
                while time.time() < storm_until:
                    self._post_json("/api/debug/notify", {}, require_auth=True)
                    time.sleep(0.2)
                time.sleep(max(0.0, end - time.time()))

            elif name == "scenario_k_notify_ack_repost_guard":
                self._post_json("/api/config", {"notify_auto_hide_seconds": 3}, require_auth=True)
                end = time.time() + timeout_s
                active_until = time.time() + timeout_s * 0.6
                success_count = 0

                while time.time() < active_until:
                    try:
                        self._post_json("/api/debug/notify", {}, require_auth=True)
                    except Exception:
                        time.sleep(0.5)
                        continue
                    success_count += 1
                    time.sleep(0.8)

                if success_count == 0:
                    return False
                time.sleep(max(0.0, end - time.time()))

            else:
                return False
        except Exception:
            return False

        return True


@pytest.fixture(scope="function")
def app_runner() -> Iterable[AppRunner]:
    runner = AppRunner()
    try:
        yield runner
    finally:
        runner.stop_app()


@pytest.fixture(scope="function")
def hang_detector(app_runner: AppRunner) -> HangDetector:
    return HangDetector(app_runner=app_runner)


@pytest.fixture(scope="function")
def scenario_driver(app_runner: AppRunner) -> ScenarioDriver:
    return ScenarioDriver(app_runner=app_runner)

