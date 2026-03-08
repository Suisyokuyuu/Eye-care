from __future__ import annotations

"""
notify_hang_analyzer

基于诊断日志(`user_data/debug.log`)对通知状态机健康度做离线分析，主要用于场景 G：
- 关注 notify 状态机的 HIDE_REQ / HIDE_DONE 是否成对出现；
- 统计 HIDING → HIDDEN 的耗时分布，识别是否有“长时间 HIDING”；
- 统计与简化淡出链路相关的 reason_code 频次：
  E_NOTIFY_AFTER_SIMPLE_HIDE / E_NOTIFY_AFTER_SIMPLE_FADE /
  E_NOTIFY_SCHEDULE_AFTER_FADE / E_NOTIFY_TIMEOUT_SIMPLE；
- 简单汇总 DIAG_METRIC_DISPATCH / DIAG_METRIC_NOTIFY 作为 GUI 调度侧背景信息。

本模块不依赖 Flask/pywebview，可在独立 Python 进程中直接导入使用，
也可由 CLI 脚本 `eye_care.tools.notify_hang_detector`（即
`python -m eye_care.tools.notify_hang_detector`）调用。
"""

import dataclasses
import datetime as _dt
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


_TS_FMT = "%Y-%m-%d %H:%M:%S.%f"


@dataclasses.dataclass
class HidePair:
    """单次 HIDE_REQ → HIDE_DONE 配对结果。"""

    session_id: Optional[str]
    prompt_key: Optional[str]
    hide_req_ts: _dt.datetime
    hide_done_ts: _dt.datetime

    @property
    def duration_s(self) -> float:
        return (self.hide_done_ts - self.hide_req_ts).total_seconds()


@dataclasses.dataclass
class NotifyHangAnalysisResult:
    """notify 场景 G 相关的整体分析结果。"""

    hide_pairs: List[HidePair]
    # 仍停留在 HIDING（有 HIDE_REQ 但尚未匹配到 HIDE_DONE）
    open_hiding: Dict[str, _dt.datetime]
    # 与简化淡出链路等相关的 reason_code 计数
    reason_code_counts: Dict[str, int]
    # DIAG_METRIC_* 概览
    metric_dispatch_count: int
    metric_dispatch_last_ts: Optional[_dt.datetime]
    metric_notify_last_ts: Optional[_dt.datetime]
    # 关键 ALWAYS_ON 事件计数（用于 hang_scenarios 中的健康判定）
    critical_event_counts: Dict[str, int]

    @property
    def hide_pair_count(self) -> int:
        """HIDE_REQ/HIDE_DONE 成对出现的次数，便于测试方做最小闭环校验。"""
        return len(self.hide_pairs)

    @property
    def max_hide_duration_s(self) -> float:
        if not self.hide_pairs:
            return 0.0
        return max(p.duration_s for p in self.hide_pairs)

    @property
    def flask_timeout_count(self) -> int:
        """DIAG_FLASK_TIMEOUT 出现次数（后端启动超时告警）。"""
        return self.critical_event_counts.get("DIAG_FLASK_TIMEOUT", 0)

    @property
    def notify_ack_post_failed_count(self) -> int:
        """DIAG_NOTIFY_ACK_POST_FAILED 出现次数（ACK/Show 严格投递失败）。"""
        return self.critical_event_counts.get("DIAG_NOTIFY_ACK_POST_FAILED", 0)


_SM_LINE_RE = re.compile(
    # 2026-02-23 17:53:54.057 INFO ... DIAG_SM_TRANSITION | 状态机迁移(影子) | machine=notify ...
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}).*?"
    r"DIAG_SM_TRANSITION \| .*? \| (?P<kv>.*)$"
)

_EXC_LINE_RE = re.compile(
    # ... DIAG_EXCEPTION | ... | reason_code=E_NOTIFY_...
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}).*?"
    r"DIAG_EXCEPTION \| .*? \| (?P<kv>.*)$"
)

_METRIC_DISPATCH_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}).*?DIAG_METRIC_DISPATCH\b"
)

_METRIC_NOTIFY_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}).*?DIAG_METRIC_NOTIFY\b"
)


_NOTIFY_REASON_CODES = {
    "E_NOTIFY_AFTER_SIMPLE_HIDE",
    "E_NOTIFY_AFTER_SIMPLE_FADE",
    "E_NOTIFY_SCHEDULE_AFTER_FADE",
    "E_NOTIFY_TIMEOUT_SIMPLE",
}


_CRITICAL_ALWAYS_ON_EVENTS = {
    # 后端 / Flask 相关
    "DIAG_FLASK_TIMEOUT",
    # notify ACK / Show 严格投递相关
    "DIAG_NOTIFY_ACK_POST_FAILED",
    "DIAG_NOTIFY_ACK_NO_NATIVE",
    # notify/rest 样式与 overlay 高危降级事件
    "DIAG_NOTIFY_STYLE_APPLY_FAIL",
    "DIAG_REST_OVERLAY_CREATE_FAIL",
}


def _parse_ts(ts_str: str) -> _dt.datetime:
    # debug.log 的毫秒是 3 位，这里用 %f 接收，再裁到毫秒精度
    dt = _dt.datetime.strptime(ts_str, _TS_FMT)
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def _parse_kv_blob(blob: str) -> Dict[str, str]:
    """
    将 "machine=notify from_state=SHOWN to_state=HIDING event=HIDE_REQ ..." 解析为 dict。

    注意：目前 notify 的 prompt_key 由 tuple.__str__ 直接生成，例如
      prompt_key=('2026-02-23', 4)
    其中包含空格，不能简单按空格拆分，否则 value 会被截断。

    这里实现一个对 prompt_key 友好的解析逻辑：
    - 对大部分 k=v 仍按空格拆分；
    - 对 prompt_key，如果 value 以 "(" 开头且当前 token 不以 ")" 结尾，
      则持续向后吞并 token，直到遇到以 ")" 结尾的 token 为止，中间用空格拼接。
    """
    out: Dict[str, str] = {}
    tokens = blob.split()
    i = 0
    n = len(tokens)

    while i < n:
        tok = tokens[i]
        if "=" not in tok:
            i += 1
            continue

        k, v = tok.split("=", 1)

        # 特殊处理 prompt_key，避免 str(tuple) 中的空格导致截断
        if k == "prompt_key" and v.startswith("(") and not v.endswith(")"):
            parts = [v]
            i += 1
            # 吞并直到遇到以 ")" 结尾的 token 或耗尽 tokens
            while i < n and not tokens[i].endswith(")"):
                parts.append(tokens[i])
                i += 1
            if i < n:
                parts.append(tokens[i])
            v = " ".join(parts)

        out[k] = v
        i += 1

    return out


def analyze_debug_log_lines(
    lines: Iterable[str],
) -> NotifyHangAnalysisResult:
    """
    对 debug.log 的行进行离线分析，聚焦 notify 场景 G 相关信号。
    """
    hide_pairs: List[HidePair] = []
    open_hiding: Dict[str, _dt.datetime] = {}
    reason_counts: Dict[str, int] = {}

    metric_dispatch_count = 0
    metric_dispatch_last_ts: Optional[_dt.datetime] = None
    metric_notify_last_ts: Optional[_dt.datetime] = None
    critical_events: Dict[str, int] = {}

    for raw in lines:
        line = raw.rstrip("\n")

        # 1) 状态机迁移（machine=notify）
        m_sm = _SM_LINE_RE.match(line)
        if m_sm:
            ts = _parse_ts(m_sm.group("ts"))
            kv = _parse_kv_blob(m_sm.group("kv"))
            if kv.get("machine") == "notify":
                event = kv.get("event")
                from_state = kv.get("from_state")
                to_state = kv.get("to_state")
                session_id = kv.get("session_id")
                prompt_key = kv.get("prompt_key")

                # 用 session_id 优先作为 key，缺失时退回 prompt_key，再退回全局。
                key = session_id or prompt_key or "<global>"

                if event == "HIDE_REQ" and to_state == "HIDING":
                    open_hiding[key] = ts
                elif event == "HIDE_DONE" and from_state == "HIDING":
                    start_ts = open_hiding.pop(key, None)
                    if start_ts is not None:
                        hide_pairs.append(
                            HidePair(
                                session_id=session_id,
                                prompt_key=prompt_key,
                                hide_req_ts=start_ts,
                                hide_done_ts=ts,
                            )
                        )
            # 即便匹配到 SM，这一行也可能同时是 EXCEPTION/metric，这里不提前 continue

        # 2) DIAG_EXCEPTION + reason_code
        m_exc = _EXC_LINE_RE.match(line)
        if m_exc:
            kv = _parse_kv_blob(m_exc.group("kv"))
            rc = kv.get("reason_code")
            if rc in _NOTIFY_REASON_CODES:
                reason_counts[rc] = reason_counts.get(rc, 0) + 1

        # 3) DIAG_METRIC_DISPATCH / DIAG_METRIC_NOTIFY
        m_md = _METRIC_DISPATCH_RE.match(line)
        if m_md:
            metric_dispatch_count += 1
            metric_dispatch_last_ts = _parse_ts(m_md.group("ts"))

        m_mn = _METRIC_NOTIFY_RE.match(line)
        if m_mn:
            metric_notify_last_ts = _parse_ts(m_mn.group("ts"))

        # 4) 关键 ALWAYS_ON 事件（通过简单子串匹配计数）
        for code in _CRITICAL_ALWAYS_ON_EVENTS:
            if code in line:
                critical_events[code] = critical_events.get(code, 0) + 1

    return NotifyHangAnalysisResult(
        hide_pairs=hide_pairs,
        open_hiding=open_hiding,
        reason_code_counts=reason_counts,
        metric_dispatch_count=metric_dispatch_count,
        metric_dispatch_last_ts=metric_dispatch_last_ts,
        metric_notify_last_ts=metric_notify_last_ts,
        critical_event_counts=critical_events,
    )


def analyze_debug_log_file(path: Path) -> NotifyHangAnalysisResult:
    """
    从指定 debug.log 文件路径读取并做分析。
    """
    path = Path(path)
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        return analyze_debug_log_lines(f)


def format_report(
    result: NotifyHangAnalysisResult,
    *,
    hiding_warn_threshold_s: float = 2.0,
) -> str:
    """
    以人类可读的多行文本形式输出分析结果，适合在 CLI 或日志中直接打印。
    """
    lines: List[str] = []
    hp = result.hide_pairs

    lines.append("== notify 场景 G 状态机健康度 ==")
    lines.append(f"HIDE_REQ/HIDE_DONE 成对次数: {len(hp)}")

    if hp:
        durations = [p.duration_s for p in hp]
        durations_sorted = sorted(durations)
        max_d = max(durations)
        # 简单取中位数（偶数长度时偏右），用于粗略 overview
        p50 = durations_sorted[len(durations_sorted) // 2]
        # p95：采用基于索引的经验分位数，idx ≈ 0.95 * (n - 1)
        if len(durations_sorted) == 1:
            p95 = durations_sorted[0]
        else:
            idx_95 = round(0.95 * (len(durations_sorted) - 1))
            idx_95 = max(0, min(len(durations_sorted) - 1, idx_95))
            p95 = durations_sorted[idx_95]
        lines.append(
            f"HIDING → HIDDEN 耗时(s): min={durations_sorted[0]:.3f} "
            f"p50={p50:.3f} p95={p95:.3f} max={max_d:.3f}"
        )
        slow = [p for p in hp if p.duration_s > hiding_warn_threshold_s]
        if slow:
            lines.append(
                f"[WARN] 检测到 {len(slow)} 次 HIDING 超过阈值 {hiding_warn_threshold_s:.1f}s "
                "(可能存在逻辑卡死或 GUI 阻塞)："
            )
            for p in slow[:10]:
                sid = p.session_id or "?"
                pk = p.prompt_key or "?"
                lines.append(
                    f"  - session_id={sid} prompt_key={pk} "
                    f"hide_req={p.hide_req_ts} hide_done={p.hide_done_ts} "
                    f"duration={p.duration_s:.3f}s"
                )
            if len(slow) > 10:
                lines.append(f"  ... 其余 {len(slow) - 10} 条略")
        else:
            lines.append(
                f"所有 HIDING → HIDDEN 耗时均 <= {hiding_warn_threshold_s:.1f}s，未发现明显长时间 HIDING。"
            )
    else:
        lines.append("未在日志中发现任何 notify HIDE_REQ/HIDE_DONE 迁移。")

    if result.open_hiding:
        lines.append("")
        lines.append("[WARN] 仍处于 HIDING 状态且未观察到 HIDE_DONE 的 session：")
        for key, ts in result.open_hiding.items():
            lines.append(f"  - key={key} since={ts}")
        lines.append("  建议结合 DIAG_METRIC_DISPATCH / hang_dump 进一步确认是否为卡死。")

    lines.append("")
    lines.append("== 简化淡出链路相关 reason_code 统计 (DIAG_EXCEPTION) ==")
    if result.reason_code_counts:
        for rc in sorted(result.reason_code_counts.keys()):
            lines.append(f"{rc}: {result.reason_code_counts[rc]}")
    else:
        lines.append("未发现与 notify 简化淡出链路相关的 E_NOTIFY_* reason_code。")

    lines.append("")
    lines.append("== GUI 调度/notify 指标 (DIAG_METRIC_*) 概览 ==")
    lines.append(f"DIAG_METRIC_DISPATCH: count={result.metric_dispatch_count}")
    lines.append(f"DIAG_METRIC_DISPATCH last_ts={result.metric_dispatch_last_ts}")
    lines.append(f"DIAG_METRIC_NOTIFY   last_ts={result.metric_notify_last_ts}")

    lines.append("")
    lines.append("== 关键 ALWAYS_ON 事件统计 ==")
    if result.critical_event_counts:
        for code in sorted(result.critical_event_counts.keys()):
            lines.append(f"{code}: {result.critical_event_counts[code]}")
    else:
        lines.append("未发现与 hang 诊断相关的关键 ALWAYS_ON 事件（如 DIAG_FLASK_TIMEOUT / DIAG_NOTIFY_ACK_POST_FAILED 等）。")

    return "\n".join(lines)


__all__ = [
    "HidePair",
    "NotifyHangAnalysisResult",
    "analyze_debug_log_lines",
    "analyze_debug_log_file",
    "format_report",
]

