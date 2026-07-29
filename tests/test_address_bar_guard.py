"""地址栏几何校验（隐私护栏）单测。

`Edit + 有 Value 模式` 会同时命中页内搜索框/登录框，读它们的值 = 读用户正在输入的内容。
`_is_address_bar` 用几何形状把地址栏和页内输入框区分开，本文件锁死这条护栏的行为。
纯逻辑，用假元素驱动，Linux 可跑（不触碰 COM）。
"""
from __future__ import annotations

import unittest

from eye_care.probes.win_browser_url import BrowserUrlWatcher

# 1600x900 窗口，左上角在 (0, 0)
_WIN = (0.0, 0.0, 1600.0, 900.0)
_CONSTS = {"bounds_prop": 30001}


class _FakeElement:
    """假 UIA 元素：只实现取包围盒用得上的两条路径。

    rect=None 模拟取不到位置；raise_struct=True 模拟 CurrentBoundingRectangle 不可用
    （走 GetCurrentPropertyValue 的 [left, top, width, height] 兜底）。
    """

    def __init__(self, rect, *, raise_struct: bool = True) -> None:
        self._rect = rect
        self._raise_struct = raise_struct

    @property
    def CurrentBoundingRectangle(self):
        if self._raise_struct or self._rect is None:
            raise OSError("unavailable")
        left, top, width, height = self._rect

        class _R:
            pass

        r = _R()
        r.left, r.top = left, top
        r.right, r.bottom = left + width, top + height
        return r

    def GetCurrentPropertyValue(self, prop_id):
        if self._rect is None:
            raise OSError("no rect")
        left, top, width, height = self._rect
        return [left, top, width, height]


def _watcher() -> BrowserUrlWatcher:
    return BrowserUrlWatcher(log=None)


class AddressBarGuardTests(unittest.TestCase):
    def test_omnibox_shape_accepted(self) -> None:
        # 典型地址栏：距窗口顶部 48px、宽 1200、高 32
        el = _FakeElement((160.0, 48.0, 1200.0, 32.0))
        self.assertTrue(_watcher()._is_address_bar(el, _CONSTS, _WIN))

    def test_rect_from_struct_path_accepted(self) -> None:
        # CurrentBoundingRectangle 可用时走结构体路径，结论应一致
        el = _FakeElement((160.0, 48.0, 1200.0, 32.0), raise_struct=False)
        self.assertTrue(_watcher()._is_address_bar(el, _CONSTS, _WIN))

    def test_in_page_input_rejected(self) -> None:
        # 页内搜索框：形状像地址栏，但位于文档区（距顶 400px）→ 必须拒
        el = _FakeElement((160.0, 400.0, 1200.0, 32.0))
        self.assertFalse(_watcher()._is_address_bar(el, _CONSTS, _WIN))

    def test_narrow_box_at_top_rejected(self) -> None:
        # 顶部的小输入框（如页内工具条）→ 宽度不够，拒
        el = _FakeElement((160.0, 48.0, 60.0, 32.0))
        self.assertFalse(_watcher()._is_address_bar(el, _CONSTS, _WIN))

    def test_tall_textarea_at_top_rejected(self) -> None:
        # 顶部的多行文本域 → 高度超限，拒
        el = _FakeElement((160.0, 48.0, 1200.0, 300.0))
        self.assertFalse(_watcher()._is_address_bar(el, _CONSTS, _WIN))

    def test_missing_rect_rejected(self) -> None:
        # 取不到位置 = 无法证明它是地址栏 → 拒（宁可不采）
        el = _FakeElement(None)
        self.assertFalse(_watcher()._is_address_bar(el, _CONSTS, _WIN))

    def test_dpi_scaled_offset_still_accepted(self) -> None:
        # 150% 缩放下地址栏顶边偏移放大（48→120），仍应在阈值内
        el = _FakeElement((240.0, 120.0, 1800.0, 48.0))
        self.assertTrue(_watcher()._is_address_bar(el, _CONSTS, (0.0, 0.0, 2400.0, 1350.0)))

    def test_hidpi_300_percent_still_accepted(self) -> None:
        # 300% 缩放：地址栏高 96、顶边偏移 144（都超了 100% 下的固定阈值），
        # 靠「偏移 ≤ 5 倍控件高度」这条 DPI 无关的规则接住
        el = _FakeElement((480.0, 144.0, 3600.0, 96.0))
        self.assertTrue(_watcher()._is_address_bar(el, _CONSTS, (0.0, 0.0, 4800.0, 2700.0)))

    def test_hidpi_page_input_still_rejected(self) -> None:
        # 同样 300% 缩放，但控件在文档区（顶边偏移 1200 = 12.5 倍行高）→ 仍须拒
        el = _FakeElement((480.0, 1200.0, 3600.0, 96.0))
        self.assertFalse(_watcher()._is_address_bar(el, _CONSTS, (0.0, 0.0, 4800.0, 2700.0)))

    def test_offscreen_window_uses_relative_offset(self) -> None:
        # 窗口在副屏（top=-900）：校验用的是相对偏移，不是绝对坐标
        el = _FakeElement((160.0, -852.0, 1200.0, 32.0))
        self.assertTrue(_watcher()._is_address_bar(el, _CONSTS, (0.0, -900.0, 1600.0, 0.0)))


class FindEditPicksAddressBarTests(unittest.TestCase):
    """_find_edit：页内输入框排在前面时，应跳过它继续找到地址栏。"""

    class _FakeArray:
        def __init__(self, items) -> None:
            self._items = items
            self.Length = len(items)

        def GetElement(self, i):
            return self._items[i]

    class _FakeRoot:
        def __init__(self, items) -> None:
            self._items = items

        def FindAll(self, scope, cond):
            return FindEditPicksAddressBarTests._FakeArray(self._items)

    class _FakeUia:
        def __init__(self, root) -> None:
            self._root = root

        def ElementFromHandle(self, hwnd):
            return self._root

        def CreatePropertyCondition(self, prop, val):
            return object()

        def CreateAndCondition(self, a, b):
            return object()

    class _FakeUser32:
        """GetWindowRect 往 byref 传进来的结构体里填 1600x900。"""

        def GetWindowRect(self, hwnd, ptr):
            r = ptr._obj
            r.left, r.top, r.right, r.bottom = 0, 0, 1600, 900
            return 1

    def _consts(self):
        return {
            "bounds_prop": 30001,
            "ctrl_type_prop": 30003,
            "edit_type": 50004,
            "is_value_avail_prop": 30043,
            "scope_desc": 4,
        }

    def test_skips_page_input_and_returns_omnibox(self) -> None:
        page_input = _FakeElement((300.0, 500.0, 600.0, 30.0))   # 文档区输入框
        omnibox = _FakeElement((160.0, 48.0, 1200.0, 32.0))      # 地址栏
        root = self._FakeRoot([page_input, omnibox])
        got = _watcher()._find_edit(self._FakeUia(root), self._consts(), 123, self._FakeUser32())
        self.assertIs(got, omnibox)

    def test_returns_none_when_no_candidate_passes(self) -> None:
        # 全屏 / 无地址栏窗口：只有页内输入框 → 一个都不采
        root = self._FakeRoot([_FakeElement((300.0, 500.0, 600.0, 30.0))])
        got = _watcher()._find_edit(self._FakeUia(root), self._consts(), 123, self._FakeUser32())
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()
