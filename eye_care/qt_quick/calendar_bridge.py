"""日期选择器 QML 数据桥（step3）。

复刻 web `#calendarModal` 的核心：月历网格 + 有数据的日子高亮 + 选一天。
（web 是双月范围选择；这里按我们仪表盘的「锚定日期 + 日/周/月 tab」模型简化为**单日选择**，
选中的日期交由外壳调 left/right bridge.setDate 定位，周/月由 period tab 决定。）

后端复用 StatsService.get_calendar_month（返回该月有数据的日期列表）。纯读，无写，预览生产同路径。

QML 侧 contextProperty `calendarBridge`：绑 `monthTitle`/`cells`/`selectedDate`，
`prev()`/`next()` 翻月、`select(iso)` 选日；外壳读 `selectedDate` 做 setDate。
"""
from __future__ import annotations

import calendar as _cal
import datetime as _dt
import logging
from typing import Callable, Optional

from PySide6.QtCore import QObject, Property, Signal, Slot

log = logging.getLogger(__name__)

WEEK_HEADERS = ["一", "二", "三", "四", "五", "六", "日"]   # 周一开头


def build_calendar_io(controller, log: Optional[logging.Logger] = None):
    """造 month_loader(year, month) -> set[iso]（该月有数据的日期）。"""
    lg = log or logging.getLogger(__name__)
    from eye_care.services.context import ServiceContext
    from eye_care.services.stats_service import StatsService

    ctx = ServiceContext(controller=controller, log=lg)
    stats = StatsService(ctx)

    def month_loader(year: int, month: int) -> set:
        try:
            res = stats.get_calendar_month(year=year, month=month) or {}
            return set(res.get("days_with_data") or [])
        except Exception as e:  # noqa: BLE001
            lg.warning("calendar month 读取失败 %s-%s: %s", year, month, e)
            return set()

    return month_loader


class CalendarBridge(QObject):
    gridChanged = Signal()
    selectionChanged = Signal()

    def __init__(self, month_loader: Callable[[int, int], set], *, today: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._loader = month_loader
        today_d = _dt.date.today()
        if today:
            try:
                today_d = _dt.date.fromisoformat(today)
            except ValueError:
                pass
        self._today = today_d.isoformat()
        self._year = today_d.year
        self._month = today_d.month
        # 范围选择（复刻 web）：先点开始→再点结束（同天即单日）。_start/_end 为 iso 或 None。
        self._start: Optional[str] = self._today
        self._end: Optional[str] = self._today
        self._cells: list = []
        self._rebuild()

    # ── 属性 ──
    @Property(str, notify=gridChanged)
    def monthTitle(self) -> str:
        return "%d 年 %d 月" % (self._year, self._month)

    @Property("QVariantList", constant=True)
    def weekHeaders(self) -> list:
        return WEEK_HEADERS

    @Property("QVariantList", notify=gridChanged)
    def cells(self) -> list:
        return self._cells

    @Property(str, notify=selectionChanged)
    def selectedDate(self) -> str:        # 向后兼容：= 范围起点
        return self._start or self._today

    @Property(str, notify=selectionChanged)
    def rangeStart(self) -> str:
        return self._start or ""

    @Property(str, notify=selectionChanged)
    def rangeEnd(self) -> str:
        return self._end or self._start or ""

    @Property(str, notify=selectionChanged)
    def rangeLabel(self) -> str:
        s, e = self._start, (self._end or self._start)
        if not s:
            return "请选择日期"
        if not self._end or self._end == s:
            return s
        return f"{s} → {e}"

    # ── 操作 ──
    @Slot()
    def prev(self) -> None:
        y, m = (self._year - 1, 12) if self._month == 1 else (self._year, self._month - 1)
        self._year, self._month = y, m
        self._rebuild()

    @Slot()
    def next(self) -> None:
        y, m = (self._year + 1, 1) if self._month == 12 else (self._year, self._month + 1)
        self._year, self._month = y, m
        self._rebuild()

    @Slot(str)
    def select(self, iso: str) -> None:
        """范围选择：无起点/已成对 → 设新起点(清结束)；已有起点未配对 → 设结束(早于起点则交换)。"""
        iso = str(iso or "").strip()
        if not iso:
            return
        if not self._start or (self._start and self._end):
            self._start, self._end = iso, None
        else:
            if iso < self._start:
                self._start, self._end = iso, self._start
            else:
                self._end = iso
        self._mark()
        self.selectionChanged.emit()
        self.gridChanged.emit()

    @Slot()
    def reset(self) -> None:
        """清空选择（重新选起点）。"""
        self._start = self._end = None
        self._mark()
        self.selectionChanged.emit()
        self.gridChanged.emit()

    @Slot()
    def reload(self) -> None:
        # 每次打开日历：把上次遗留的"半个选择"(start 有、end 无)补全成单日，
        # 让新一次点选从完整态开始——否则"上次选了 X→这次点今天"会被当成 X→今天 的范围，
        # 导致"切回今天"实际触发跨天 setRange 而非 setDate(今天)。
        if self._start and not self._end:
            self._end = self._start
            self._mark()
            self.selectionChanged.emit()
        self._rebuild()

    def _mark(self) -> None:
        """按当前 start/end 刷新每格的 selected/inRange/rangeStart/rangeEnd 标记。"""
        s = self._start
        e = self._end or self._start
        lo, hi = (s, e) if (s and e and s <= e) else (e, s)
        for c in self._cells:
            iso = c["iso"]
            c["rangeStart"] = (iso == self._start)
            c["rangeEnd"] = (iso == (self._end or self._start))
            c["selected"] = (iso == self._start or iso == self._end)
            c["inRange"] = bool(lo and hi and lo < iso < hi)

    def _rebuild(self) -> None:
        have = self._loader(self._year, self._month)
        first = _dt.date(self._year, self._month, 1)
        # 周一开头：first.weekday() 周一=0
        lead = first.weekday()
        start = first - _dt.timedelta(days=lead)
        cells = []
        for i in range(42):  # 6 行 x 7 列
            d = start + _dt.timedelta(days=i)
            iso = d.isoformat()
            cells.append({
                "day": d.day,
                "iso": iso,
                "inMonth": (d.month == self._month),
                "hasData": iso in have,
                "isToday": (iso == self._today),
                "selected": False,
                "inRange": False,
                "rangeStart": False,
                "rangeEnd": False,
            })
        self._cells = cells
        self._mark()
        self.gridChanged.emit()
