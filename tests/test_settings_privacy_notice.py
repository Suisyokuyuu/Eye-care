"""设置页「记录浏览器数据」的联网告知护栏。

这是本应用**唯一**会在后台主动联网的功能（为网站卡片抓 favicon）。告知文案是对用户的
承诺，不能在后续重构里被悄悄删掉或改窄，故在此钉死几条不变量。

同 tests/test_bat_encoding.py 的思路：本机（Linux）跑不了 Qt，QML 只能做文件级结构断言，
渲染效果仍需 Windows 实测。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_QML_DIR = Path(__file__).resolve().parent.parent / "eye_care" / "qt_quick" / "qml"
_SETTINGS = _QML_DIR / "SettingsPage.qml"


def _strip(qml: str) -> str:
    """去掉注释与字符串字面量，用于括号配平检查。"""
    out = re.sub(r"//[^\n]*", "", qml)
    return re.sub(r'"(?:[^"\\]|\\.)*"', '""', out)


class SettingsPrivacyNoticeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(_SETTINGS.exists(), f"找不到 {_SETTINGS}")
        self.src = _SETTINGS.read_text(encoding="utf-8")

    def test_browser_toggle_has_a_tip(self) -> None:
        self.assertIn("id: browserCheck", self.src, "浏览器记录开关的 id 没了")
        m = re.search(r"id:\s*browserCheck(.{0,1600}?)onTipDismissed", self.src, re.S)
        self.assertIsNotNone(m, "browserCheck 上的悬停气泡接线没了")
        self.assertIn("tip:", m.group(1), "browserCheck 不再设置 tip 文案")

    def test_tip_discloses_network_access(self) -> None:
        """文案必须说清：会联网、只抓图标、满 1 分钟才抓、不经第三方。"""
        m = re.search(r"tip:\s*(.+?)onTipRequested", self.src, re.S)
        self.assertIsNotNone(m, "取不到 tip 文案")
        tip = m.group(1)
        for must in ("联网", "图标", "1 分钟", "第三方"):
            self.assertIn(must, tip, f"联网告知文案里缺少关键信息：{must}")

    def test_check_component_supports_tip(self) -> None:
        """Check 组件的气泡能力（property + 两个信号）必须还在。"""
        for token in ("property string tip:", "signal tipRequested", "signal tipDismissed"):
            self.assertIn(token, self.src, f"Check 组件缺少 {token}")

    def test_tip_bubble_is_not_clipped_and_not_clickable(self) -> None:
        """气泡必须在 page 顶层（卡片/Flickable 都 clip）且不吃鼠标事件。"""
        m = re.search(r"id:\s*hoverTip(.{0,400}?)property string tipText", self.src, re.S)
        self.assertIsNotNone(m, "hoverTip 容器没了")
        block = m.group(1)
        self.assertIn("z: 999", block, "气泡层级被改低，可能被其它元素盖住")
        self.assertIn("enabled: false", block, "气泡会吃鼠标事件，将挡住底下的复选框")
        self.assertIn("function showTip", self.src)
        self.assertIn("function hideTip", self.src)

    def test_touched_qml_files_are_balanced(self) -> None:
        """本轮改动的 QML 括号配平（Linux 无 Qt，只能做这一层静态检查）。"""
        for name in ("SettingsPage.qml", "SiteDetailPage.qml"):
            with self.subTest(qml=name):
                body = _strip((_QML_DIR / name).read_text(encoding="utf-8"))
                for op, cl in (("{", "}"), ("(", ")"), ("[", "]")):
                    self.assertEqual(body.count(op), body.count(cl),
                                     f"{name} 的 {op}{cl} 不配平")

    def test_no_duplicate_ids_in_touched_qml(self) -> None:
        for name in ("SettingsPage.qml", "SiteDetailPage.qml"):
            with self.subTest(qml=name):
                ids = re.findall(r"\bid:\s*(\w+)", (_QML_DIR / name).read_text(encoding="utf-8"))
                dups = sorted({i for i in ids if ids.count(i) > 1})
                self.assertEqual(dups, [], f"{name} 有重复 id: {dups}")


if __name__ == "__main__":
    unittest.main()
