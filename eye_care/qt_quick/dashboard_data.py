"""主仪表盘「生产数据源」——把 AppController + SnapshotService 包成 bridge 用的 provider。

两条用法：
  - 接外壳/接生产：`make_provider(controller, log)` —— 复用外壳里**已经在跑**的 controller，
    不另开 repo（外壳整合时用这个）。
  - 独立预览跑真实数据：`build_readonly_source(data_dir, log)` —— 新建一个 *只读* controller
    （`_ReadOnlyController`：no-op 掉 WAL merge 与 app_paths 落盘两处写副作用），可安全地与正在
    运行的正式 app 共存读同一个 user_data。返回 (provider, controller)。

provider(range_key) -> dict：返回一份完整 snapshot（同时含左栏 usage/category 与右栏 timebar/stats），
左右两个 bridge 共用同一个 provider + 同一个 color_cache 即可。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional, Tuple


def make_provider(controller, log: Optional[logging.Logger] = None) -> Callable[..., dict]:
    """用一个已存在的 controller 造 provider（外壳整合用——不另开 repo）。
    provider(range_key, date=None)：date 缺省=今天（生产用今天；预览可传历史日期定位有数据的那天）。"""
    from eye_care.services import ServiceContext, SnapshotService

    svc = SnapshotService(ServiceContext(controller=controller, log=log or logging.getLogger(__name__)))

    def provider(range_key: str, date: Optional[str] = None,
                 range_start: Optional[str] = None, range_end: Optional[str] = None,
                 *, dim: str = "app") -> dict:
        # dim 为 keyword-only：保持向后兼容——不带 dim 的旧调用（如 left_panel_bridge）不受影响。
        query = {"range": range_key, "dim": dim}
        if date:
            query["date"] = date
        if range_key == "custom":
            # 日历自定义范围（复刻 web 范围选择）：SnapshotService 支持 range="custom" + range_start/range_end。
            query["range_start"] = range_start
            query["range_end"] = range_end
        return svc.get_snapshot(query=query)

    return provider


def latest_data_date(data_dir) -> Optional[str]:
    """扫 data_dir/minute_usage/minute-YYYY-MM-DD.jsonl，返回最近有数据的日期（无则 None）。预览用。"""
    import re
    d = Path(data_dir) / "minute_usage"
    if not d.exists():
        return None
    dates = []
    for p in d.glob("minute-*.jsonl"):
        m = re.search(r"minute-(\d{4}-\d{2}-\d{2})\.jsonl$", p.name)
        if m and p.stat().st_size > 0:
            dates.append(m.group(1))
    return max(dates) if dates else None


def build_readonly_source(
    data_dir, log: Optional[logging.Logger] = None
) -> Tuple[Callable[[str], dict], object]:
    """新建只读 controller + provider（独立预览用，可与运行中的 app 共存）。返回 (provider, controller)。"""
    from eye_care.controller.app_controller import AppController

    log = log or logging.getLogger(__name__)

    class _ReadOnlyController(AppController):
        """预览只读：去掉构造期仅有的写副作用（WAL merge、app_paths 落盘），其余只读路径不变。"""

        def _apply_exit_state_need_merge(self) -> None:  # 不触发 WAL merge / 不动 exit_state 标记
            pass

        def _load_app_paths(self) -> None:
            # 跳过 app_paths 加载（图标用，QML 仪表盘暂不需要），但**必须置位 loaded 事件**，
            # 否则 get_app_paths 每次会等 2s 超时。名称解析走 display_names/key 兜底即可。
            self._app_paths_loaded.set()

        def _persist_app_paths(self) -> None:  # 双保险：任何路径都不写 app_paths.json
            pass

    ctrl = _ReadOnlyController(data_dir=Path(data_dir))
    return make_provider(ctrl, log), ctrl
