"""URL 取值双路径（文档元素优先 / 地址栏兜底）单测。

覆盖：全屏无地址栏仍能采到、iframe 与后台标签页不被误取、地址栏输入中不算失败、
两路皆硬失败才降频、内部页不降频。纯逻辑，用假 UIA 元素驱动，Linux 可跑（不触碰 COM）。
"""
from __future__ import annotations

import unittest

from eye_care.probes import win_browser_url as mod
from eye_care.probes.win_browser_url import BrowserUrlWatcher

_CONSTS = {
    "bounds_prop": 30001,
    "ctrl_type_prop": 30003,
    "edit_type": 50004,
    "doc_type": 50030,
    "is_value_avail_prop": 30043,
    "value_value_prop": 30045,
    "has_focus_prop": 30008,
    "offscreen_prop": 30022,
    "scope_desc": 4,
}


class _Element:
    """假 UIA 元素：按 property id 返回预设值，未预设的一律抛（模拟不可用）。"""

    def __init__(self, *, value=None, focused=False, offscreen=False, rect=None,
                 raise_on_value=False) -> None:
        self._value = value
        self._focused = focused
        self._offscreen = offscreen
        self._rect = rect
        self._raise_on_value = raise_on_value
        self.value_reads = 0

    @property
    def CurrentBoundingRectangle(self):
        raise OSError("unavailable")  # 强制走 GetCurrentPropertyValue 兜底

    def GetCurrentPropertyValue(self, prop_id):
        if prop_id == _CONSTS["value_value_prop"]:
            self.value_reads += 1
            if self._raise_on_value:
                raise OSError("element not available")
            return self._value
        if prop_id == _CONSTS["has_focus_prop"]:
            return self._focused
        if prop_id == _CONSTS["offscreen_prop"]:
            return self._offscreen
        if prop_id == _CONSTS["bounds_prop"]:
            if self._rect is None:
                raise OSError("no rect")
            return list(self._rect)
        raise AssertionError(f"读取了白名单之外的属性: {prop_id}")


class _Array:
    def __init__(self, items) -> None:
        self._items = items
        self.Length = len(items)

    def GetElement(self, i):
        return self._items[i]


class _Root:
    """按查找条件里的 ControlType 分发候选列表，并统计各类全树扫描次数。"""

    def __init__(self, docs, edits) -> None:
        self._docs = docs
        self._edits = edits
        self.wanted_type = None
        self.doc_scans = 0
        self.edit_scans = 0

    def FindAll(self, scope, cond):
        if self.wanted_type == _CONSTS["doc_type"]:
            self.doc_scans += 1
            return _Array(self._docs)
        self.edit_scans += 1
        return _Array(self._edits)


class _Uia:
    def __init__(self, root) -> None:
        self._root = root

    def ElementFromHandle(self, hwnd):
        return self._root

    def CreatePropertyCondition(self, prop, val):
        # 记录本次查找的 ControlType，供 _Root 分发
        if prop == _CONSTS["ctrl_type_prop"]:
            self._root.wanted_type = val
        return object()

    def CreateAndCondition(self, a, b):
        return object()


class _User32:
    """GetForegroundWindow 返回 self.hwnd（可改，用于模拟切窗口）；GetWindowRect 填 1600x900。"""

    def __init__(self, hwnd: int = 123) -> None:
        self.hwnd = hwnd

    def GetForegroundWindow(self):
        return self.hwnd

    def GetWindowRect(self, hwnd, ptr):
        r = ptr._obj
        r.left, r.top, r.right, r.bottom = 0, 0, 1600, 900
        return 1


def _omnibox(value: str, *, focused: bool = False) -> _Element:
    return _Element(value=value, focused=focused, rect=(160.0, 48.0, 1200.0, 32.0))


def _setup(*, docs=(), edits=()):
    root = _Root(list(docs), list(edits))
    return BrowserUrlWatcher(log=None), _Uia(root), _User32()


class DocumentSourceTests(unittest.TestCase):
    def test_document_is_primary_source(self) -> None:
        doc = _Element(value="https://www.bilibili.com/video/BV1xx?t=42")
        w, uia, user32 = _setup(docs=[doc], edits=[_omnibox("https://example.com")])
        w._sample_once(user32, uia, _CONSTS)

        # 域名来自文档元素，且地址栏根本没被读（主路径命中就不碰兜底）
        self.assertEqual(w.get_domain(), "bilibili.com")
        self.assertEqual(doc.value_reads, 1)

    def test_fullscreen_without_address_bar_still_samples(self) -> None:
        # 全屏：树里没有地址栏 Edit，只有文档 → 仍应采到（这正是 A 方案要解决的场景）
        w, uia, user32 = _setup(docs=[_Element(value="https://youtube.com/watch?v=1")], edits=[])
        w._sample_once(user32, uia, _CONSTS)

        self.assertEqual(w.get_domain(), "youtube.com")
        self.assertEqual(w._hwnd_fail, 0)

    def test_offscreen_background_tab_skipped(self) -> None:
        # 后台标签页的文档标记为 offscreen，应跳过取下一个
        bg = _Element(value="https://background-tab.com", offscreen=True)
        fg = _Element(value="https://active-tab.com")
        w, uia, user32 = _setup(docs=[bg, fg])
        w._sample_once(user32, uia, _CONSTS)

        self.assertEqual(w.get_domain(), "active-tab.com")

    def test_outer_document_wins_over_iframe(self) -> None:
        # 树序 pre-order：外层文档在前，广告 iframe 在后 → 取外层
        w, uia, user32 = _setup(docs=[
            _Element(value="https://news.site.com/a"),
            _Element(value="https://ads.doubleclick.net/x"),
        ])
        w._sample_once(user32, uia, _CONSTS)

        self.assertEqual(w.get_domain(), "news.site.com")

    def test_internal_page_records_nothing_but_is_not_a_failure(self) -> None:
        # chrome:// 内部页：读到了但不可记录 → 不写 domain，也不该计入失败降频
        w, uia, user32 = _setup(docs=[_Element(value="chrome://new-tab-page")], edits=[])
        w._sample_once(user32, uia, _CONSTS)

        self.assertEqual(w.get_domain(), "")
        self.assertEqual(w._hwnd_fail, 0)


class FallbackAndFailureTests(unittest.TestCase):
    def test_falls_back_to_address_bar_when_no_document(self) -> None:
        w, uia, user32 = _setup(docs=[], edits=[_omnibox("bilibili.com/anime")])
        w._sample_once(user32, uia, _CONSTS)

        self.assertEqual(w.get_domain(), "bilibili.com")

    def test_typing_in_address_bar_is_skipped_not_failed(self) -> None:
        # 地址栏有焦点 = 正在输入 → 不读值、不算失败（不触发降频）
        bar = _omnibox("怎么治疗", focused=True)
        w, uia, user32 = _setup(docs=[], edits=[bar])
        w._sample_once(user32, uia, _CONSTS)

        self.assertEqual(w.get_domain(), "")
        self.assertEqual(w._hwnd_fail, 0)
        self.assertEqual(bar.value_reads, 0)  # 输入中的内容一次都没被读

    def test_both_paths_hard_fail_counts_toward_downgrade(self) -> None:
        # 两条路都找不到元素 → 计入失败；连续 _MAX_HWND_FAILS 次后降频
        w, uia, user32 = _setup(docs=[], edits=[])
        for _ in range(mod._MAX_HWND_FAILS):
            w._sample_once(user32, uia, _CONSTS)

        self.assertEqual(w._hwnd_fail, mod._MAX_HWND_FAILS)
        self.assertEqual(w._next_wait_s, mod._DOWNGRADE_INTERVAL_S)

    def test_stale_document_element_is_dropped_and_refound(self) -> None:
        # 导航后旧文档元素失效（读值抛异常）→ 作废缓存，下一拍重找到新文档
        stale = _Element(raise_on_value=True)
        fresh = _Element(value="https://new-site.com")
        root = _Root([stale], [])
        w, uia, user32 = BrowserUrlWatcher(log=None), _Uia(root), _User32()

        w._sample_once(user32, uia, _CONSTS)
        self.assertIsNone(w._cache_doc)
        self.assertEqual(w.get_domain(), "")

        root._docs = [fresh]
        w._sample_once(user32, uia, _CONSTS)
        self.assertEqual(w.get_domain(), "new-site.com")

    def test_missing_document_is_negative_cached(self) -> None:
        # 有地址栏但没有文档元素（渲染进程无障碍未就绪）：地址栏能采成功 → 永不降频，
        # 若没有负缓存就会每拍白扫一遍整棵子树。断言只扫一次。
        root = _Root([], [_omnibox("https://a.com")])
        w, uia, user32 = BrowserUrlWatcher(log=None), _Uia(root), _User32()
        for _ in range(3):
            w._sample_once(user32, uia, _CONSTS)

        self.assertEqual(root.doc_scans, 1)
        self.assertEqual(w.get_domain(), "a.com")     # 兜底路径照常工作
        self.assertEqual(root.edit_scans, 1)          # 地址栏元素也只找一次（之后走缓存）

    def test_document_retried_after_negative_cache_window(self) -> None:
        # 负缓存过期后应重新尝试；此时文档已就绪 → 切回主路径
        root = _Root([], [_omnibox("https://fallback.com")])
        w, uia, user32 = BrowserUrlWatcher(log=None), _Uia(root), _User32()
        w._sample_once(user32, uia, _CONSTS)
        self.assertEqual(w.get_domain(), "fallback.com")

        root._docs = [_Element(value="https://primary.com")]
        w._doc_miss_ts -= mod._DOC_RETRY_AFTER_S + 1  # 模拟负缓存窗口已过
        w._sample_once(user32, uia, _CONSTS)

        self.assertEqual(root.doc_scans, 2)
        self.assertEqual(w.get_domain(), "primary.com")

    def test_hwnd_change_clears_negative_cache(self) -> None:
        # 换窗口应立刻重试文档元素，不继承上个窗口的负缓存
        root = _Root([], [_omnibox("https://a.com")])
        w, uia, user32 = BrowserUrlWatcher(log=None), _Uia(root), _User32()
        w._sample_once(user32, uia, _CONSTS)
        self.assertEqual(root.doc_scans, 1)

        user32.hwnd = 456
        root._docs = [_Element(value="https://other-window.com")]
        w._sample_once(user32, uia, _CONSTS)

        self.assertEqual(root.doc_scans, 2)
        self.assertEqual(w.get_domain(), "other-window.com")

    def test_ttl_expiry_drops_reference_to_old_element(self) -> None:
        # TTL 到期时不只是绕过旧元素，还要真正丢掉对它的引用
        old = _Element(value="https://old.com")
        root = _Root([old], [])
        w, uia, user32 = BrowserUrlWatcher(log=None), _Uia(root), _User32()
        w._sample_once(user32, uia, _CONSTS)
        self.assertIs(w._cache_doc, old)

        root._docs = [_Element(value="https://fresh.com")]
        w._doc_ts -= mod._DOC_CACHE_TTL_S + 1  # 模拟 TTL 已过
        w._sample_once(user32, uia, _CONSTS)

        self.assertIsNot(w._cache_doc, old)
        self.assertEqual(w.get_domain(), "fresh.com")

    def test_stale_address_bar_element_self_heals_after_empty_reads(self) -> None:
        # 缓存的地址栏元素已脱离但只是静默返回空串（不抛异常）：
        # 连续空读到阈值后应作废缓存重找，而不是永久哑掉。
        stale = _omnibox("")
        root = _Root([], [stale])
        w, uia, user32 = BrowserUrlWatcher(log=None), _Uia(root), _User32()
        for _ in range(mod._EDIT_MAX_EMPTY_READS):
            w._sample_once(user32, uia, _CONSTS)

        self.assertIsNone(w._cache_edit)          # 已作废
        self.assertEqual(w.get_domain(), "")

        root._edits = [_omnibox("https://recovered.com")]
        w._sample_once(user32, uia, _CONSTS)
        self.assertEqual(w.get_domain(), "recovered.com")

    def test_page_input_never_read_when_no_omnibox(self) -> None:
        # 全屏且无文档时，树里只剩页内输入框 → 几何校验挡住，绝不读它的值
        page_input = _Element(value="用户在页面里输入的内容", rect=(300.0, 500.0, 600.0, 30.0))
        w, uia, user32 = _setup(docs=[], edits=[page_input])
        w._sample_once(user32, uia, _CONSTS)

        self.assertEqual(w.get_domain(), "")
        self.assertEqual(page_input.value_reads, 0)


if __name__ == "__main__":
    unittest.main()
