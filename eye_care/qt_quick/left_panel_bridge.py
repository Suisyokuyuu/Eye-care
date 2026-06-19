"""主仪表盘「左栏」QML 数据桥。

把 /api/snapshot 的原始 payload 转成左栏 QML 直接可绑定的 view-model：
饼图 model、应用/分类列表、Top5 汇总行、总时长文案、汇总标题、日期文案。

设计要点：
  - 这是 *唯一* 一份转换实现，生产与预览共用。差异只在数据源：
      生产  → snapshot_provider = lambda rk: SnapshotService(...).get_snapshot(query={...})
      生产  → snapshot_provider = make_provider(controller)（见 dashboard_data.py）
    因此 Windows 上跑预览验证的就是真实接线 + 真实转换代码路径。
  - 颜色/时长格式 1:1 移植 web（charts.js 的 BASE_PALETTE + _hash32 + 色相避让 +
    全局 key→color 缓存；app.js 的 formatWorkTime），保证饼图与列表同 key 同色、
    与 web 观感一致。
  - 不碰任何业务写操作；只读 snapshot → 组装展示数据。日期导航（上一天/下一天/选日期）
    后续再接，当前固定取 provider 给的当日/范围。

QML 侧通过 contextProperty `leftPanelBridge` 访问；切「应用/分类」「日/周/月」调
setView/setPeriod，10s 轮询或数据更新调 refresh，本类 emit dataChanged 触发重绑。
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from PySide6.QtCore import QObject, Property, Signal, Slot

log = logging.getLogger(__name__)

# ── web charts.js 移植：调色板 + hash + 色相避让 ──────────────────────────────
BASE_PALETTE = [
    (59, 130, 246),   # 蓝
    (249, 115, 22),   # 橙
    (20, 184, 166),   # 青
    (239, 68, 68),    # 红
    (34, 197, 94),    # 绿
    (139, 92, 246),   # 紫
    (234, 179, 8),    # 黄（备用）
    (236, 72, 153),   # 粉（备用；原灰色饱和度过低导致色相避让失效，换成粉红确保明显区分）
]
_HUE_DISTANCE_MIN = 18
_PICK_AVOID_MAX_RETRIES = 8
_ICON_MAX_RETRIES = 5   # 失败超过此次数（≈50s）后停止重试，防止无图标应用每拍都做磁盘 IO


def _hash32(s: str) -> int:
    """FNV-1a 32-bit，与 charts.js _hash32 完全一致（含 |0 截断语义）。"""
    s = "" if s is None else str(s)
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF        # JS `(h*16777619)|0` → 取低 32 位
    return h & 0xFFFFFFFF


def _rgb_to_hsl(r: int, g: int, b: int):
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2.0
    s = h = 0.0
    if mx != mn:
        d = mx - mn
        s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == r:
            h = ((g - b) / d + (6 if g < b else 0)) / 6.0
        elif mx == g:
            h = ((b - r) / d + 2) / 6.0
        else:
            h = ((r - g) / d + 4) / 6.0
    return round(h * 360), round(s * 100), round(l * 100)


def _hsl_to_rgb(h: float, s: float, l: float):
    s, l = s / 100.0, l / 100.0

    def k(n):
        return (n + h / 30.0) % 12

    a = s * min(l, 1 - l)

    def f(n):
        return l - a * max(-1, min(k(n) - 3, min(9 - k(n), 1)))

    return [round(255 * f(0)), round(255 * f(8)), round(255 * f(4))]


def _hue_distance(h1: float, h2: float) -> float:
    d = abs(h1 - h2) % 360
    return 360 - d if d > 180 else d


def _pick_color_avoiding_near(used_hues, base_rgb):
    """与 charts.js pickColorAvoidingNear 同义：base 与已用色相过近则按 18° 步进偏移。
    used_hues 为已用颜色的色相列表。返回 (r,g,b)。"""
    bh, bs, bl = _rgb_to_hsl(*base_rgb)

    def too_close(hue):
        return any(_hue_distance(hue, u) < _HUE_DISTANCE_MIN for u in used_hues)

    if not too_close(bh):
        return tuple(base_rgb)
    for retry in range(_PICK_AVOID_MAX_RETRIES):
        cand = (bh + _HUE_DISTANCE_MIN * (retry + 1)) % 360
        if cand < 0:
            cand += 360
        if not too_close(cand):
            return tuple(_hsl_to_rgb(cand, bs, bl))
    return tuple(base_rgb)


def format_work_time(seconds) -> str:
    """与 app.js formatWorkTime 一致：满时显示 X小时X分钟 / X小时 / X分钟 / X秒。"""
    if seconds is None or seconds < 0:
        return "0分钟"
    s = int(seconds)
    h, m = s // 3600, (s % 3600) // 60
    if h > 0 and m > 0:
        return f"{h}小时{m}分钟"
    if h > 0:
        return f"{h}小时"
    if m > 0:
        return f"{m}分钟"
    return f"{s}秒"


def _strip_exe(name: str) -> str:
    return name[:-4] if name and name.lower().endswith(".exe") else name


def _step_anchor(base: str | None, period: str, delta: int):
    """按周期翻页：返回新的锚定日期 ISO 串（失败返回 None）。左右栏共用，保证同步。

    日=±delta 天、周=±delta*7 天、月=±delta 个自然月（落到目标月 1 号，避免月末溢出）。
    """
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(str(base))
    except Exception:
        return None
    delta = int(delta)
    p = (period or "day").lower()
    if p == "week":
        d = d + _dt.timedelta(days=7 * delta)
    elif p == "month":
        m = d.month - 1 + delta
        y = d.year + m // 12
        d = _dt.date(y, m % 12 + 1, 1)
    else:
        d = d + _dt.timedelta(days=delta)
    return d.isoformat()


def resolve_app_name(key: str, names: dict | None, paths: dict | None) -> str:
    """统一的 app key → 显示名解析（左右栏共用）。

    联动高亮按显示名匹配，故饼图/柱状图/卡片必须对同一 key 解析出**完全相同**的名字。
    历史 bug：app_short 是小写、去扩展名的 exe 主干名（如 "tabby"），左栏用 exe 路径真实
    文件名（"Tabby"，保留大小写），右栏柱图直接用小写 key（"tabby"）→ 大小写不一致 →
    联动失配。这里收敛为同一套优先级：
      1) 显式别名 / display_name（与 key 不同时）
      2) exe 路径文件名（保留原始大小写，如 Tabby）
      3) 去 .exe 的 key 兜底
    """
    key = key or ""
    dn = (names or {}).get(key)
    if dn and dn != key:
        return _strip_exe(dn)
    p = (paths or {}).get(key)
    if p:
        base = os.path.basename(str(p).replace("\\", "/"))
        if base:
            return _strip_exe(base)
    return _strip_exe(dn or key)


class LeftPanelBridge(QObject):
    """左栏 QML 数据桥（见模块 docstring）。"""

    dataChanged = Signal()       # 数据更新（含 10s 轮询）→ QML 重绑，不重播动画
    resetAnim = Signal()         # 仅切视图/周期 → QML 重播饼图入场动画（复刻 web chartViewEnter）

    def __init__(
        self,
        snapshot_provider: Callable[[str], dict],
        *,
        today_str: Optional[str] = None,
        color_cache: Optional[dict] = None,
        icon_resolver: Optional[Callable[[str], str]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._provider = snapshot_provider
        self._today_str = today_str
        self._icon_resolver = icon_resolver   # app_short → data_url（""=无图标）；生产注入，预览/mock 可 None
        self._icon_cache: dict = {}           # app_short → data_url（非空才缓存）
        self._icon_miss_count: dict = {}      # app_short → 连续失败次数；超上限后停止重试
        self._date: Optional[str] = None   # 锚定日期（None=今天）；日历选择 → setDate
        self._range: Optional[tuple] = None  # 自定义范围 (start,end)；日历选范围 → setRange（覆盖 period/date）
        self._view = "app"        # app | category
        self._period = "day"      # day | week | month
        self._snap: dict = {}
        # key→(r,g,b)，跨视图/周期保持同 key 同色；传入共享 dict 可让左右栏跨面板同色（生产用）。
        self._key_color_cache: dict = color_cache if color_cache is not None else {}
        # 计算结果（QML 直接绑定）
        self._pie_model: list = []
        self._app_list: list = []
        self._top_lines: list = []
        self._total_text = "0分钟"
        self._summary_title = "屏幕使用时间"
        self._date_text = ""
        self._render_sig = None    # 上次渲染的可见签名，用于跳过无可见变化的刷新
        self._recompute()

    # ── QML 调用入口 ──────────────────────────────────────────────────────
    @Slot(str)
    def setView(self, view: str) -> None:
        view = "category" if str(view).lower().startswith("cat") else "app"
        if view != self._view:
            self._view = view
            self._render()        # 同一 snapshot 换视图，无需重新取数
            self.resetAnim.emit()  # 切视图=复刻 web chartViewEnter，重播入场动画

    @Slot(str)
    def setPeriod(self, period: str) -> None:
        period = str(period).lower()
        if period not in ("day", "week", "month"):
            period = "day"
        if period != self._period or self._range is not None:
            self._period = period
            self._range = None         # 切回 日/周/月 → 取消自定义范围
            self._recompute()     # 周期变 → 范围变 → 重新取 snapshot
            self.resetAnim.emit()  # 切周期=重播入场动画

    @Slot(str)
    def setDate(self, date: str) -> None:
        """锚定日期（日历选择）。空串=回今天。周/月由 period tab 决定，date 为锚点。"""
        date = str(date or "").strip() or None
        if date != self._date or self._range is not None:
            self._date = date
            self._range = None         # 选单日 → 取消自定义范围
            self._recompute()
            self.resetAnim.emit()

    @Slot(str, str)
    def setRange(self, start: str, end: str) -> None:
        """自定义日期范围（日历范围选择，复刻 web）。覆盖 period/date，取 custom snapshot。"""
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
        """日期导航 ◀▶：按**当前周期**翻页（取消自定义范围）。

        日=±1 天、周=±7 天、月=±1 个自然月。原先恒 ±1 天，导致周/月视图里翻 1 天
        范围常不变（同一周/月内）→ 用户感觉"翻不动/不稳定"。
        """
        new_date = _step_anchor(self._date or self._today_str, self._period, delta)
        if new_date is None:
            return
        self._date = new_date
        self._range = None
        self._recompute()
        self.resetAnim.emit()

    @Slot()
    def refresh(self) -> None:
        """重新取 snapshot 并重算（10s 轮询 / 数据更新时调）。"""
        self._recompute()

    # ── 取数 + 渲染 ───────────────────────────────────────────────────────
    def _recompute(self) -> None:
        try:
            if self._range:
                # 自定义范围（custom）：provider 需支持 range_start/range_end（生产 provider 支持；mock 不支持→降级）。
                self._snap = self._provider("custom", None, self._range[0], self._range[1]) or {}
            else:
                # provider 可能只接受 range_key（mock）或同时接受 date（真实）；按需降级。
                self._snap = (self._provider(self._period, self._date) if self._date
                              else self._provider(self._period)) or {}
        except TypeError:
            self._snap = self._provider(self._period) or {}
        except Exception:
            log.exception("left panel snapshot provider failed")
            self._snap = {}
        self._render()

    def _color_for_key(self, key: str, used_solids: list) -> tuple:
        """key→(r,g,b)，缓存只存自然基色（hash→调色板），每次渲染都在上下文中做相邻避让。

        旧实现把避让后的颜色缓存：后续调用直接返回缓存值，完全跳过避让检查——相邻 key
        若恰好撞色（均来自缓存），无法修正。新实现：
          - cache 只存「自然基色」（由 hash 确定，跨 session/视图稳定）
          - 每次调用都用当前 used_solids 做避让，缓存命中时若与相邻色冲突则临时偏转
            （不更新 cache，保留基色稳定性）
        """
        # 确保基色已缓存（首次：hash → 调色板）
        if key not in self._key_color_cache:
            self._key_color_cache[key] = tuple(BASE_PALETTE[_hash32(key) % len(BASE_PALETTE)])
        base = self._key_color_cache[key]
        if not used_solids:
            return base
        used_hues = [_rgb_to_hsl(*c)[0] for c in used_solids]
        bh = _rgb_to_hsl(*base)[0]
        if any(_hue_distance(bh, u) < _HUE_DISTANCE_MIN for u in used_hues):
            # 基色与相邻色冲突 → 临时偏转（不写回 cache）
            return _pick_color_avoiding_near(used_hues, base)
        return base

    def _date_label(self, snap: dict) -> str:
        """复刻 app.js 的 dateLabel：日=今日/日期；周/月=MM-DD ~ MM-DD。"""
        rk = snap.get("range_key", "day")
        local_date = ((snap.get("vm") or {}).get("local_date")) or ""
        rs = snap.get("range_start") or ""
        re_ = snap.get("range_end") or rs
        if rk == "day":
            today = self._today_str
            return "今日" if (today and local_date == today) else local_date
        # 周/月/自定义统一 MM-DD ~ MM-DD
        def md(d):
            p = (d or "").split("-")
            return f"{p[1]}-{p[2]}" if len(p) >= 3 else d
        return f"{md(rs)} ~ {md(re_)}" if (rs and re_) else local_date

    def _render(self) -> None:
        snap = self._snap or {}
        rk = snap.get("range_key", self._period)
        is_range = rk in ("week", "month", "custom")

        if self._view == "category":
            usage = (snap.get("range_usage_by_category") if is_range else None) \
                or snap.get("usage_by_category") or {}
            names = None         # 分类名即 key
            paths = {}
        else:
            usage = (snap.get("range_daily_usage") if is_range else None) \
                or ((snap.get("vm") or {}).get("daily_usage")) or {}
            names = snap.get("display_names") or {}
            paths = snap.get("app_paths") or {}

        total_sec = sum(int(v or 0) for v in usage.values())
        if self._view == "app" and rk == "day" and snap.get("today_total_seconds") is not None:
            total_sec = int(snap.get("today_total_seconds") or 0)

        # 组装 + 降序
        items = []
        for key, raw in usage.items():
            sec = int(raw or 0)
            if self._view == "category":
                name = key
            else:
                name = resolve_app_name(key, names, paths)  # 与右栏柱图统一，保证联动 key 一致
            pct = (100.0 * sec / total_sec) if total_sec > 0 else 0.0
            items.append({"key": key, "name": name, "sec": sec, "pct": pct,
                          "dur": format_work_time(sec)})
        items.sort(key=lambda it: it["sec"], reverse=True)

        # 逐项分配颜色（同一顺序累积 used，做相邻避让；缓存保证跨视图稳定）
        used: list = []
        for it in items:
            r, g, b = self._color_for_key(it["key"], used)
            it["r"], it["g"], it["b"] = r, g, b
            used.append((r, g, b))

        # ── 饼图 top10/5% 阈值合并「其他」──────────────────────────────────────
        # 最多显示 10 个切片；占比 < 5% 的项目及其后所有项合并为「其他」。
        # 列表（appList）仍显示全部，不受阈值影响。
        _PIE_TOP_N = 10
        _PIE_PCT_MIN = 3.0
        is_cat = (self._view == "category")
        pie_displayed: list = []
        other_sec = 0
        for it in items:
            if it["sec"] <= 0:
                other_sec += 0
                continue
            if len(pie_displayed) < _PIE_TOP_N and it["pct"] >= _PIE_PCT_MIN:
                pie_displayed.append(it)
            else:
                other_sec += it["sec"]

        pie_model = [
            {"name": it["name"], "key": it["key"], "isCategory": is_cat,
             "value": it["sec"], "r": it["r"], "g": it["g"], "b": it["b"]}
            for it in pie_displayed
        ]
        if other_sec > 0:
            # 「其他」也做相邻避让（饼图中它与最后项和首项相邻；传入所有显示项的颜色）
            other_used = [(it["r"], it["g"], it["b"]) for it in pie_displayed]
            r_o, g_o, b_o = self._color_for_key("其他", other_used)
            pie_model.append({"name": "其他", "key": "__other__", "isCategory": False,
                               "value": other_sec, "r": r_o, "g": g_o, "b": b_o})

        app_list = [
            {"name": it["name"], "key": it["key"], "isCategory": is_cat,
             "dur": it["dur"], "pct": round(it["pct"]),
             "sec": it["sec"], "r": it["r"], "g": it["g"], "b": it["b"],
             "icon": ("" if is_cat else self._icon_for(it["key"]))}
            for it in items
        ]
        top_lines = [
            {"name": it["name"], "dur": it["dur"], "pct": round(it["pct"]),
             "r": it["r"], "g": it["g"], "b": it["b"]}
            for it in items[:5]
        ]
        total_text = format_work_time(total_sec)
        date_label = self._date_label(snap)
        summary_title = (f"{date_label} " if date_label else "") + "屏幕使用时间"
        date_text = date_label or "今日"

        # 仅当**可见内容**变化才重赋值+发信号；否则跳过，避免每 10s 整模型替换、QML 拆建 delegate
        # （偶发"重绘只剩一条"的根因）。可见签名故意**不含原始秒数**（modelData.sec 在左栏列表未被使用，
        # 饼图角度按 1% 粒度即够）——只看 名称/时长文案/取整百分比/图标/顺序/总时长，几秒累加不触发刷新。
        sig = (
            tuple((it["name"], it["dur"], round(it["pct"]), it.get("icon", "")) for it in app_list),
            total_text, summary_title, date_text,
        )
        if sig == self._render_sig:
            return
        self._render_sig = sig
        self._pie_model, self._app_list, self._top_lines = pie_model, app_list, top_lines
        self._total_text, self._summary_title, self._date_text = total_text, summary_title, date_text
        log.debug("left.render view=%s period=%s range=%s date=%s items=%d",
                  self._view, self._period, self._range, self._date, len(app_list))
        self.dataChanged.emit()

    def _icon_for(self, key: str) -> str:
        """app_short → 图标 data_url（带缓存；无 resolver / 取不到 → ""）。

        成功结果永久缓存；失败允许重试，但超过 _ICON_MAX_RETRIES 次后本 session 放弃，
        避免对无图标应用每次轮询都做磁盘 IO（约 50s 内解决导入/启动的瞬态失败窗口）。
        """
        if not self._icon_resolver:
            return ""
        if key in self._icon_cache:
            return self._icon_cache[key]
        if self._icon_miss_count.get(key, 0) >= _ICON_MAX_RETRIES:
            return ""
        try:
            url = self._icon_resolver(key) or ""
        except Exception:
            url = ""
        if url:
            self._icon_cache[key] = url
            self._icon_miss_count.pop(key, None)
        else:
            self._icon_miss_count[key] = self._icon_miss_count.get(key, 0) + 1
        return url

    # ── QML 可绑定属性 ────────────────────────────────────────────────────
    @Property("QVariantList", notify=dataChanged)
    def pieModel(self):
        return self._pie_model

    @Property("QVariantList", notify=dataChanged)
    def appList(self):
        return self._app_list

    @Property(int, notify=dataChanged)
    def appCount(self):
        """列表项数——ListView 用它做 model（数量不变时不重置、行原地更新，避免重绘闪烁）。"""
        return len(self._app_list)

    @Property("QVariantList", notify=dataChanged)
    def topLines(self):
        return self._top_lines

    @Property(str, notify=dataChanged)
    def totalText(self):
        return self._total_text

    @Property(str, notify=dataChanged)
    def summaryTitle(self):
        return self._summary_title

    @Property(str, notify=dataChanged)
    def dateText(self):
        return self._date_text
