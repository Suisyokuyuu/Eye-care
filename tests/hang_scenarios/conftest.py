from __future__ import annotations

"""
公共 pytest fixture：

- AppRunner：负责启动/销毁被测应用进程；
- ScenarioDriver：对外提供“运行某个场景”的高层接口（HTTP 调用或内部控制类）；
- HangDetector：读取 debug.log / 诊断日志，对 GUI 线程与队列健康度做判断。

当前实现为最小可用骨架，后续可按需要扩展。
"""

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
    """管理被测 Eye Care 应用的生命周期。"""

    proc: subprocess.Popen | None = None
    data_dir: Path | None = None
    api_port: int = 8765  # 默认调试端口，可按需调整

    def start_app(self, *, extra_args: Iterable[str] | None = None) -> None:
        if self.proc and self.proc.poll() is None:
            return

        # 使用到秒的时间戳在并发 / 快速重跑时可能发生碰撞，这里追加进程 ID 与
        # 单调递增计数，降低目录名复用的概率。
        ts = int(time.time())
        pid = os.getpid()
        uniq = int(time.monotonic_ns() % 10_000_000)
        self.data_dir = PROJECT_ROOT / f"user_data_test_{ts}_{pid}_{uniq}"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.setdefault("EYECARE_DEBUG", "1")
        # 始终以 AppRunner.api_port 作为实际监听端口，避免外部预设的
        # EYECARE_API_PORT 让 wait_for_ready 轮询到错误端口。
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

        self.proc = subprocess.Popen(
            args,
            cwd=str(PROJECT_ROOT),
            env=env,
        )

    def is_running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def wait_for_ready(self, timeout_s: float = 60.0) -> bool:
        """
        基于 HTTP `/api/health` 的就绪检测，避免“未就绪即返回 True”的误判。

        - 仅在应用进程仍存活时继续重试；
        - 要求在超时时间内至少成功返回一次 `{"ok": true}`。
        """
        start = time.time()
        url = f"http://127.0.0.1:{self.api_port}/api/health"

        while time.time() - start < timeout_s:
            if not self.is_running():
                return False

            try:
                with urlrequest.urlopen(url, timeout=2.0) as resp:  # type: ignore[arg-type]
                    if resp.status == 200:
                        raw = resp.read().decode("utf-8") or "{}"
                        payload = json.loads(raw)
                        if payload.get("ok"):
                            return True
            except (urlerror.URLError, TimeoutError, json.JSONDecodeError, ValueError):
                # 连接失败 / 解析失败时简单重试，直到超时
                pass

            time.sleep(0.5)

        return False

    def stop_app(self, timeout_s: float = 10.0) -> None:
        if not self.proc:
            return
        if self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@dataclass
class HangDetector:
    """
    读取 debug.log / 诊断日志，初步判断是否存在疑似卡死。

    当前仅提供最小接口：基于总超时判断是否“疑似卡死”，
    后续可按 DEADLOCK_ANALYSIS 中的方案补充 DIAG_METRIC_DISPATCH 等解析。
    """

    app_runner: "AppRunner"
    hiding_warn_threshold_s: float = 2.0

    def _debug_log_path(self) -> Path:
        """
        始终基于当前 app_runner.data_dir 解析 debug.log，避免绑定到错误会话目录。
        """
        data_dir = self.app_runner.data_dir or (PROJECT_ROOT / "user_data")
        return data_dir / "debug.log"

    def wait_healthy_or_timeout(
        self,
        timeout_s: float,
        mode: Literal["generic", "notify_hide"] = "generic",
        *,
        require_min_hide_pairs: int | None = None,
    ) -> bool:
        """
        在给定时间内等待场景完成，并基于 debug.log 做最小“卡死”判定。

        - 等待 debug.log 出现（最多 timeout_s）；
        - 使用 notify_hang_analyzer 对日志进行一次离线分析；
        - 如存在未闭合的 HIDING（open_hiding），则视为疑似卡死；
        - 否则当前实现视为“未检测到明显卡死”。
        """
        deadline = time.time() + timeout_s
        log_path = self._debug_log_path()

        # 等待日志文件出现或超时
        while time.time() < deadline and not log_path.is_file():
            if not self.app_runner.is_running():
                return False
            time.sleep(0.5)

        if not log_path.is_file():
            # 应用未产生日志，视为异常情况
            return False

        try:
            result = analyze_debug_log_file(log_path)
        except FileNotFoundError:
            return False

        # 先基于关键 ALWAYS_ON 诊断事件做快速失败判断：
        # - DIAG_FLASK_TIMEOUT：后端 Flask 启动超时，可能导致部分 API 永久不可用；
        # - DIAG_NOTIFY_ACK_POST_FAILED：notify ACK/Show 严格投递失败，本次提醒已显式降级。
        # 这些事件在 NORMAL_MODE_LOGGING 中被标记为 ALWAYS_ON，出现在 hang_scenarios 中通常意味着
        # 回归或环境异常，因此一旦命中便视为“检测到疑似异常/卡死”。
        if result.flask_timeout_count > 0:
            return False
        if result.notify_ack_post_failed_count > 0:
            return False

        # 通用规则：若仍存在未闭合 HIDING，会话视为可疑。
        if result.open_hiding:
            return False

        # notify hide 专用逻辑：对 HIDING -> HIDDEN 耗时做简单阈值判断。
        if mode == "notify_hide" and result.max_hide_duration_s > self.hiding_warn_threshold_s:
            return False

        # 对于某些场景（例如 notify ACK/repost_guard 回归），要求至少观察到一定数量的
        # HIDE_REQ/HIDE_DONE 闭环，避免“完全未覆盖 hide 闭环也通过”的情况。
        if require_min_hide_pairs is not None and result.hide_pair_count < require_min_hide_pairs:
            return False

        return True


@dataclass
class ScenarioDriver:
    """封装对被测应用的高层操作（占位骨架）。"""

    app_runner: AppRunner
    _api_token: str | None = None

    @property
    def _base_url(self) -> str:
        return f"http://127.0.0.1:{self.app_runner.api_port}"

    def _fetch_token(self) -> str:
        """
        从 `/api/auth/token` 获取写接口所需的 token。
        """
        if self._api_token:
            return self._api_token

        url = f"{self._base_url}/api/auth/token"
        with urlrequest.urlopen(url, timeout=5.0) as resp:  # type: ignore[arg-type]
            raw = resp.read().decode("utf-8") or "{}"
            payload = json.loads(raw)
        token = payload.get("token")
        if not token:
            raise RuntimeError("failed to obtain API token from /api/auth/token")
        self._api_token = str(token)
        return self._api_token

    def _post_json(self, path: str, body: dict | None = None, require_auth: bool = False) -> None:
        data = json.dumps(body or {}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if require_auth:
            token = self._fetch_token()
            headers["X-EYECare-Token"] = token
        url = f"{self._base_url}{path}"
        req = urlrequest.Request(url, data=data, headers=headers, method="POST")
        with urlrequest.urlopen(req, timeout=5.0):
            pass

    def run_scenario(self, name: str, timeout_s: float) -> bool:
        """
        运行一个命名场景。

        当前实现：
        - 确保应用已启动并通过 `/api/health` 就绪；
        - 通过 `/api/diag/log` 记录场景起始埋点，便于回溯；
        - 针对部分场景（尤其是 notify 相关场景）调用调试 HTTP API 触发真实链路；
        - 其他场景暂以时间窗口占位，后续可逐步细化。
        """
        if not self.app_runner.is_running():
            self.app_runner.start_app()
            assert self.app_runner.wait_for_ready(), "App 未能在超时时间内就绪"

        # 统一记录一条 diag 日志，帮助在 debug.log 中定位具体场景。
        # /api/diag/log 属于写接口，需携带 X-EYECare-Token，否则会被 401 拒绝。
        try:
            self._post_json(
                "/api/diag/log",
                {
                    "src": "pytest.hang_scenarios",
                    "stage": name,
                    "msg": f"start {name}",
                },
                require_auth=True,
            )
        except Exception:
            # 埋点失败不应影响场景本身执行
            pass

        # 针对特定场景做最小可行的 HTTP 级动作，便于触发日志与状态迁移。
        try:
            if name == "scenario_f_notify_hide":
                # 场景 F：显式覆盖“show 一次 + idle 等待 autoHide 完整闭环”链路。
                #
                # - 通过 /api/config 将 notify_auto_hide_seconds 临时下调至 3 秒左右；
                # - 调用一次 /api/debug/notify 触发 show；
                # - 在剩余时间内保持静默，让前端 autoHide 负责触发 HIDE_REQ / HIDE_DONE。
                #
                # 这样可以在 timeout_s=8 秒的窗口内，稳定观测到 HIDING→HIDDEN 的完整闭环
                # （或在存在 bug 时复现“长时间停留在 HIDING”的风险）。
                #
                # 1) 临时降低 auto-hide 时长；配置更新失败应视为场景失败，避免假绿。
                self._post_json(
                    "/api/config",
                    {"notify_auto_hide_seconds": 3},
                    require_auth=True,
                )

                # 2) 触发一次通知 show
                try:
                    self._post_json("/api/debug/notify", {}, require_auth=True)
                except Exception:
                    return False

                # 3) 剩余时间内保持 idle，留给 autoHide 完成 hide 链路
                remaining = max(0.0, timeout_s - 1.5)
                time.sleep(remaining)

            elif name == "scenario_g_notify_storm":
                # 场景 G：高频 show + 间歇 idle，既覆盖“风暴”特性，也确保
                # autoHide 有机会推进 hide 链路。
                #
                # 如仅每 0.2s 连续 show，会不断重置 auto-hide 计时器，导致
                # HIDING/HIDDEN 闭环长期无法完成，从而让 notify_hang_analyzer
                # 在 mode="notify_hide" 下看不到任何 hide 相关信号。
                #
                # 这里采用分段策略：
                # - 前半段：高频 show，模拟 notify 风暴；
                # - 后半段：完全 idle，留给 autoHide 触发 HIDE_REQ / HIDE_DONE，
                #   并让 notify_hang_analyzer 有机会观测到 HIDING → HIDDEN。
                #
                # 同样将 auto-hide 下调至 3 秒左右；如配置失败，则视为场景失败。
                self._post_json(
                    "/api/config",
                    {"notify_auto_hide_seconds": 3},
                    require_auth=True,
                )

                now = time.time()
                end = now + timeout_s
                storm_until = now + timeout_s * 0.4

                # 1) 高频 show 段
                while time.time() < storm_until:
                    self._post_json("/api/debug/notify", {}, require_auth=True)
                    time.sleep(0.2)

                # 2) idle 段：完全不再主动 show，由 autoHide 完成后续 hide 链路。
                remaining = max(0.0, end - time.time())
                if remaining > 0:
                    time.sleep(remaining)

            elif name == "scenario_k_notify_ack_repost_guard":
                # 场景 K：多轮 notify show + ACK + autoHide 回归
                #
                # 目标：
                # - 覆盖「前端 ACK → _schedule_actual_show_from_ack → _do_actual_show」严格投递路径；
                # - 多轮触发 notify show，验证 repost_guard 不会在异常路径上永久卡死后续 show；
                # - 在 autoHide 正常工作的前提下，观察多轮 HIDING→HIDDEN 闭环是否健康。
                #
                # 实现策略：
                # - 将 auto-hide 下调至 3 秒，保证在单次 timeout_s 窗口内能完成多轮 show→hide；
                # - 以约 0.8s 间隔连续触发 /api/debug/notify，交给前端完成 ACK 与 fade；
                # - 不强制模拟 ACK 严格失败场景，仅通过多轮真实链路回归新代码路径。
                self._post_json(
                    "/api/config",
                    {"notify_auto_hide_seconds": 3},
                    require_auth=True,
                )

                # 将窗口拆分为「主动 show 阶段」与「idle 阶段」：
                # - 主动 show 阶段内以 0.8s 间隔多轮触发 /api/debug/notify，并统计成功次数；
                # - idle 阶段完全静默，交给 autoHide 推进 HIDE_REQ/HIDE_DONE 闭环。
                #
                # 这样可以避免“未真正触发任何 notify 仍然通过”的假阳性，
                # 同时为 notify_hang_analyzer 创造至少一对 hide_pairs 的观测机会。
                now = time.time()
                end = now + timeout_s
                # 约 60% 时间用于主动 show，40% 留给 idle + autoHide
                active_until = now + timeout_s * 0.6

                success_count = 0

                # 1) 主动 show 段：尽力多轮触发 notify，统计成功次数
                while time.time() < active_until:
                    try:
                        self._post_json("/api/debug/notify", {}, require_auth=True)
                    except Exception:
                        # 单次触发失败不应中断整场景，继续尝试后续轮次
                        time.sleep(0.5)
                        continue

                    success_count += 1

                    # 0.8 秒间隔：允许 ACK + 最小淡入延迟顺利完成，同时在 auto-hide 计时器尚未
                    # 触发前发起下一轮，制造一定程度的重叠以放大小概率问题的暴露概率。
                    time.sleep(0.8)

                # 若在整个主动 show 段完全没能成功触发任何 notify，则视为场景失败，避免假阳性。
                if success_count == 0:
                    return False

                # 2) idle 段：完全不再 show，由 autoHide 完成后续 hide 链路。
                remaining = max(0.0, end - time.time())
                if remaining > 0:
                    time.sleep(remaining)

            else:
                # 其余场景暂以时间窗口占位，后续可按需要扩展为更精细的 HTTP 操作。
                time.sleep(timeout_s)
        except Exception:
            # 场景执行过程中如遇 HTTP 错误，视为失败，交由上层断言处理。
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

