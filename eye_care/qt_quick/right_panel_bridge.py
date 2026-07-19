"""主仪表盘「右栏」QML 数据桥。

把 /api/snapshot 的 timebar_* / stats_* / rest 转成右栏 QML 可直接绑定的 view-model：
  - 时段堆叠柱状图：barLabels（x 桶）、barSeries（每 app 一组堆叠，带颜色 + values 对齐 labels）、
    yMax/yTicks（Y 轴刻度，分钟或小时单位）
  - Top4 分布（与饼图同色）
  - KPI 卡片文案：今日屏幕时间/最长连续专注/休息完成率/已连续用眼/今日休息·跳过/提醒频率·休息时长

与左栏同构：唯一一份转换实现，生产/预览共用，差异只在 snapshot_provider 数据源。颜色/时长复用
left_panel_bridge 的 web 移植工具（可传入共享 color_cache，让左右栏跨面板同 app 同色）。

数据契约（对照 api/common.py _timebars_for_day/_range + app.js updateRightPanelFromSnapshot）：
  timebar_labels: day=["0".."23"]、week=["周一".."周日"]、month=["1日"..]；
  timebar_keys:   top5 app key + "其他"；
  timebar_values: rows=labels 长度，每行=[各 key 的秒]，即 values[行下标][key下标]。
"""
from __future__ import annotations

import logging
import math
from typing import Callable, Optional

from PySide6.QtCore import QObject, Property, Signal, Slot

from .left_panel_bridge import (
    BASE_PALETTE, _hash32, _hue_distance, _HUE_DISTANCE_MIN,
    _pick_color_avoiding_near, _rgb_to_hsl,
    _step_anchor, format_work_time, resolve_app_name,
)

log = logging.getLogger(__name__)


def format_work_time_compact(seconds) -> str:
    """KPI 卡片紧凑时长：X时X分 / X时 / X分 / X秒。
    卡片格窄，full『X小时X分钟』会溢出（用户反馈）→ 统一用『时/分』紧凑写法，任意时长/窗口都不超。"""
    if seconds is None or seconds < 0:
        return "0分"
    s = int(seconds)
    h, m = s // 3600, (s % 3600) // 60
    if h > 0 and m > 0:
        return f"{h}时{m}分"
    if h > 0:
        return f"{h}时"
    if m > 0:
        return f"{m}分"
    return f"{s}秒"


def format_continuous_work_time(seconds) -> str:
    """已连续用眼：<60s=0分；否则同紧凑写法（与其余三格统一）。"""
    if seconds is None or seconds < 0 or int(seconds) < 60:
        return "0分"
    return format_work_time_compact(seconds)


class RightPanelBridge(QObject):
    """右栏 QML 数据桥（见模块 docstring）。"""

    dataChanged = Signal()       # 数据更新（含 10s 轮询）→ QML 重绑，不重播动画
    resetAnim = Signal()         # 仅切周期 → QML 重播柱状图入场动画

    def __init__(
        self,
        snapshot_provider: Callable[[str], dict],
        *,
        today_str: Optional[str] = None,
        color_cache: Optional[dict] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._provider = snapshot_provider
        self._today_str = today_str
        self._date: Optional[str] = None   # 锚定日期（日历选择）
        self._range: Optional[tuple] = None  # 自定义范围 (start,end)；日历选范围 → setRange
        self._period = "day"
        self._dim = "app"                   # 时段柱状图 + Top4 维度：app | category | browser（跟随左栏视图）
        self._snap: dict = {}
        self._key_color_cache: dict = color_cache if color_cache is not None else {}
        # 计算结果
        self._bar_labels: list = []
        self._bar_series: list = []
        self._bar_series_sig: list = []   # 柱图按分钟粒度的可见签名，避免每拍重建
        self._y_max = 0
        self._y_ticks: list = []
        self._use_hours = False
        self._top4: list = []
        self._top4_sig: list = []   # Top4 可见签名（并入 dim），避免同内容/空↔空切维度不换对象
        self._total_text = "—"
        self._focus_text = "—"
        self._rate_text = "—"
        self._range_label = "—"
        self._continuous_text = "0 分钟"
        self._reminder_text = "每 20 分钟"
        self._duration_text = "20 秒"
        self._done_text = "0次"
        self._skip_text = "0次"
        self._recompute()

    # ── QML 入口 ──
    @Slot(str)
    def setPeriod(self, period: str) -> None:
        period = str(period).lower()
        if period not in ("day", "week", "month"):
            period = "day"
        if period != self._period or self._range is not None:
            self._period = period
            self._range = None
            self._recompute()
            self.resetAnim.emit()  # 切周期 → 重播柱状图入场

    @Slot(str)
    def setDim(self, dim: str) -> None:
        """柱状图/Top4 维度切换（跟随左栏视图：应用/分类/浏览器）。仿 setPeriod。"""
        d = str(dim or "").lower()
        if d.startswith("bro"):
            d = "browser"
        elif d.startswith("cat"):
            d = "category"
        else:
            d = "app"
        if d != self._dim:
            self._dim = d
            self._recompute()
            self.resetAnim.emit()  # 切维度 → 重播柱状图入场

    @Slot(str)
    def setDate(self, date: str) -> None:
        date = str(date or "").strip() or None
        if date != self._date or self._range is not None:
            self._date = date
            self._range = None
            self._recompute()
            self.resetAnim.emit()

    @Slot(str, str)
    def setRange(self, start: str, end: str) -> None:
        """自定义日期范围（日历范围选择）。覆盖 period/date。"""
        start = str(start or "").strip()
        end = str(end or "").strip()
        if not start or not end:
            return
        if start > end:
            start, end = end, start
        self._range = (start, end)
        self._recompute()
        self.resetAnim.emit()

    @Slot(int)
    def stepDay(self, delta: int) -> None:
        """日期导航 ◀▶：按当前周期翻页（日±1天/周±7天/月±1月），与左栏同步。"""
        new_date = _step_anchor(self._date or self._today_str, self._period, delta)
        if new_date is None:
            return
        self._date = new_date
        self._range = None
        self._recompute()
        self.resetAnim.emit()

    @Slot()
    def refresh(self) -> None:
        self._recompute()

    # ── 取数 + 渲染 ──
    def _recompute(self) -> None:
        try:
            if self._range:
                self._snap = self._provider("custom", None, self._range[0], self._range[1], dim=self._dim) or {}
            else:
                self._snap = (self._provider(self._period, self._date, dim=self._dim) if self._date
                              else self._provider(self._period, dim=self._dim)) or {}
        except TypeError:
            # provider 为旧签名（不接受 dim keyword，异常降级路径）→ 退回不带 dim 的调用
            self._snap = self._provider(self._period) or {}
        except Exception:
            log.exception("right panel snapshot provider failed")
            self._snap = {}
        self._render()

    def _color_for_key(self, key: str, used_solids: list) -> tuple:
        """与 left_panel_bridge 相同策略：cache 只存基色，每次渲染做上下文避让。"""
        if key not in self._key_color_cache:
            self._key_color_cache[key] = tuple(BASE_PALETTE[_hash32(key) % len(BASE_PALETTE)])
        base = self._key_color_cache[key]
        if not used_solids:
            return base
        used_hues = [_rgb_to_hsl(*c)[0] for c in used_solids]
        bh = _rgb_to_hsl(*base)[0]
        if any(_hue_distance(bh, u) < _HUE_DISTANCE_MIN for u in used_hues):
            return _pick_color_avoiding_near(used_hues, base)
        return base

    def _date_label(self, snap: dict) -> str:
        rk = snap.get("range_key", "day")
        local_date = ((snap.get("vm") or {}).get("local_date")) or ""
        rs = snap.get("range_start") or local_date
        re_ = snap.get("range_end") or rs
        if rk == "day":
            today = self._today_str
            return "今日" if (today and local_date == today) else (local_date or "—")

        def md(d):
            p = (d or "").split("-")
            return f"{p[1]}-{p[2]}" if len(p) >= 3 else d
        return f"{md(rs)} ~ {md(re_)}" if (rs and re_) else (local_date or "—")

    @staticmethod
    def _compute_y(max_stack: int):
        """返回 (use_hours, y_max_sec, ticks=[{sec,label}])，复刻 app.js 的分钟/小时刻度逻辑。"""
        if max_stack <= 0:
            return False, 300, [{"sec": 0, "label": "0"}, {"sec": 300, "label": "5"}]
        if max_stack >= 3 * 3600:
            # 小时单位：选步长使刻度数 ~<=6
            max_h = max_stack / 3600.0
            step_h = next((s for s in (1, 2, 3, 5, 10) if max_h / s <= 6), 10)
            y_max = math.ceil(max_h / step_h) * step_h * 3600
            ticks = []
            v = 0
            while v <= y_max + 1:
                h = v / 3600.0
                ticks.append({"sec": v, "label": (str(int(h)) if h % 1 == 0 else f"{h:.1f}")})
                v += step_h * 3600
            return True, y_max, ticks
        # 分钟单位
        max_min = math.ceil(max_stack / 60)
        step_min = 5 if max_min <= 50 else 10
        y_max = math.ceil(max_min / step_min) * step_min * 60
        ticks = []
        v = 0
        while v <= y_max + 1:
            ticks.append({"sec": v, "label": str(round(v / 60))})
            v += step_min * 60
        return False, y_max, ticks

    def _render(self) -> None:
        snap = self._snap or {}
        rk = snap.get("range_key", self._period)
        is_range = rk in ("week", "month", "custom")
        names = snap.get("display_names") or {}
        paths = snap.get("app_paths") or {}
        # 实际维度以 snapshot 回写的 timebar_dim 为准（browser 开关关时后端已回退 app，
        # 用回退后的值让柱状图与 Top4 维度一致）。
        eff_dim = str(snap.get("timebar_dim") or self._dim or "app").lower()
        # 站点显示名别名（key=site_key）：仅在最终打标签处套用，颜色键仍用 site_key。
        site_overrides = snap.get("site_display_overrides") or {}

        def short_name(k):
            # browser 维度：site_key 套显示名（无则原域名），不走 app 名解析（避免 strip .exe 等副作用/误配）。
            if eff_dim == "browser":
                return site_overrides.get(k) or k
            # 与左栏完全一致的解析（统一联动 key，修复 tabby 等大小写不匹配导致的联动失效）
            return resolve_app_name(k, names, paths)

        # ── 柱状图：labels + 每 key 一组堆叠 series ──
        labels = list(snap.get("timebar_labels") or [])
        keys = list(snap.get("timebar_keys") or [])
        values = list(snap.get("timebar_values") or [])   # values[行][key下标]
        # day 且全为纯数字标签 → 加"时"
        disp_labels = labels
        if rk == "day" and labels and all(str(l).strip().isdigit() for l in labels):
            disp_labels = [f"{str(l).strip()}时" for l in labels]

        max_stack = 0
        for row in values:
            if row:
                max_stack = max(max_stack, sum(int(v or 0) for v in row))
        use_hours, y_max, y_ticks = self._compute_y(max_stack)
        self._use_hours = use_hours
        self._y_max = y_max
        if y_ticks != self._y_ticks:   # 刻度模型不变则保持同一对象，避免 Y 轴 Repeater 无谓重建
            self._y_ticks = y_ticks

        used: list = []
        series = []
        for i, key in enumerate(keys):
            r, g, b = self._color_for_key(key, used)
            used.append((r, g, b))
            col = [int((values[row][i] if (row < len(values) and i < len(values[row])) else 0) or 0)
                   for row in range(len(labels))]
            series.append({"name": short_name(key) if key != "其他" else "其他",
                           "key": key,   # 保留原始 key（app_short）供点击导航用
                           "r": r, "g": g, "b": b, "values": col})
        # 仅在**可见内容**真变时才换对象：图表/Y 轴/Top 模型不变 → 保持同一对象，即使本拍因 KPI
        # 文本触发 dataChanged，TimeBarChart 的 Repeater 也不会拆毁重建（消除偶发"重绘只剩一条"）。
        # 柱高按**分钟粒度**比较——几秒的累加不改变观感却会逼着每拍重建，故按分钟判定是否真变。
        if disp_labels != self._bar_labels:
            self._bar_labels = disp_labels
        # 签名并入 eff_dim：两维度数据恰好相同（尤其空↔空）时切维度也强制换对象，QML 才会重绘。
        series_sig = [eff_dim] + [(s["name"], s["key"], s["r"], s["g"], s["b"], tuple(int(v) // 60 for v in s["values"])) for s in series]
        if series_sig != self._bar_series_sig:
            self._bar_series_sig = series_sig
            self._bar_series = series

        # ── Top4 分布（跟随维度：app=应用用量 / category=分类用量 / browser=domain 用量，与饼图同色）──
        if eff_dim == "browser":
            usage = (snap.get("range_browser_domains") if is_range else None) \
                or snap.get("browser_domains") or {}
        elif eff_dim == "category":
            usage = (snap.get("range_usage_by_category") if is_range else None) \
                or snap.get("usage_by_category") or {}
        else:
            usage = (snap.get("range_daily_usage") if is_range else None) \
                or ((snap.get("vm") or {}).get("daily_usage")) or {}
        top_items = sorted(((k, int(v or 0)) for k, v in usage.items()),
                           key=lambda kv: kv[1], reverse=True)[:4]
        used4: list = []
        top4 = []
        for k, sec in top_items:
            r, g, b = self._color_for_key(k, used4)
            used4.append((r, g, b))
            top4.append({"name": short_name(k), "val": format_work_time(sec),
                         "r": r, "g": g, "b": b})
        top4_sig = [eff_dim] + [(t["name"], t["val"], t["r"], t["g"], t["b"]) for t in top4]
        if top4_sig != self._top4_sig:
            self._top4_sig = top4_sig
            self._top4 = top4

        # ── KPI ──
        self._total_text = format_work_time_compact(int(snap.get("stats_total_seconds") or 0))
        self._focus_text = format_work_time_compact(int(snap.get("stats_longest_focus_seconds") or 0))
        rate = snap.get("stats_rest_rate_percent")
        self._rate_text = f"{rate}%" if rate is not None else "—"
        self._done_text = f"{int(snap.get('stats_rest_complete_count') or 0)}次"
        self._skip_text = f"{int(snap.get('stats_rest_snooze_count') or 0)}次"
        self._range_label = self._date_label(snap)
        rest = snap.get("rest") or {}
        self._continuous_text = format_continuous_work_time(rest.get("work_s"))
        # 提醒频率/休息时长：优先 rest.threshold_s / snap.rest_duration_s，否则默认 20/20
        interval_min = int(round((rest.get("threshold_s") or 1200) / 60))
        self._reminder_text = f"每 {interval_min} 分钟"
        self._duration_text = f"{int(snap.get('rest_duration_s') or 20)} 秒"
        self.dataChanged.emit()

    # ── QML 属性 ──
    @Property("QVariantList", notify=dataChanged)
    def barLabels(self):
        return self._bar_labels

    @Property("QVariantList", notify=dataChanged)
    def barSeries(self):
        return self._bar_series

    @Property(int, notify=dataChanged)
    def yMax(self):
        return self._y_max

    @Property("QVariantList", notify=dataChanged)
    def yTicks(self):
        return self._y_ticks

    @Property(bool, notify=dataChanged)
    def useHours(self):
        return self._use_hours

    @Property("QVariantList", notify=dataChanged)
    def top4(self):
        return self._top4

    @Property(str, notify=dataChanged)
    def totalText(self):
        return self._total_text

    @Property(str, notify=dataChanged)
    def focusText(self):
        return self._focus_text

    @Property(str, notify=dataChanged)
    def rateText(self):
        return self._rate_text

    @Property(str, notify=dataChanged)
    def rangeLabel(self):
        return self._range_label

    @Property(str, notify=dataChanged)
    def continuousText(self):
        return self._continuous_text

    @Property(str, notify=dataChanged)
    def reminderText(self):
        return self._reminder_text

    @Property(str, notify=dataChanged)
    def durationText(self):
        return self._duration_text

    @Property(str, notify=dataChanged)
    def doneText(self):
        return self._done_text

    @Property(str, notify=dataChanged)
    def skipText(self):
        return self._skip_text
