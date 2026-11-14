"""Statistics-link behavior must work before syncing and report desktop failures."""
import unittest
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

_native = "--native-case" in sys.argv


class NotionLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if _native:
            from PySide6.QtCore import QCoreApplication
            from eye_care.qt_quick.notion_bridge import NotionBridge
            cls.app = QCoreApplication.instance() or QCoreApplication([])
            cls.bridge_type = NotionBridge

    def isolated(self):
        # Older portable tests install Qt stubs globally. Keep native Qt out of
        # that process rather than modifying their shared module state.
        if _native:
            return False
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--native-case",
                                 "NotionLinkTests." + self._testMethodName],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return True

    def bridge(self, opener, parent="https://app.notion.com/p/12345678123442348234123456789abc"):
        service = SimpleNamespace(persist=True,
            settings=lambda: {"parent_page": parent},
            status=lambda: {"last_page_url": "https://www.notion.so/aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa"})
        return self.bridge_type(service, url_opener=opener)

    def test_open_uses_configured_statistics_home_instead_of_legacy_day_link(self):
        if self.isolated(): return
        opened = []
        bridge = self.bridge(lambda url: opened.append(url) or True)
        self.assertTrue(bridge.openPage())
        self.assertEqual(opened, ["https://www.notion.so/12345678123442348234123456789abc"])

    def test_failed_desktop_request_is_visible_to_user(self):
        if self.isolated(): return
        bridge = self.bridge(lambda url: False)
        self.assertFalse(bridge.openPage())
        self.assertTrue(bridge.error)
        self.assertIn("默认浏览器", bridge.message)

    def test_invalid_link_never_launches_external_handler(self):
        if self.isolated(): return
        opened = []
        bridge = self.bridge(lambda url: opened.append(url), parent="not-a-notion-id")
        self.assertFalse(bridge.openPage())
        self.assertEqual(opened, [])

    def test_open_uses_current_unsaved_link_and_is_available_during_sync(self):
        if self.isolated(): return
        opened=[]
        bridge=self.bridge(lambda url: opened.append(url) or True)
        bridge._busy=True
        self.assertTrue(bridge.openPage('bbbbbbbbbbbb4bbb8bbbbbbbbbbbbbbb'))
        self.assertEqual(opened,['https://www.notion.so/bbbbbbbbbbbb4bbb8bbbbbbbbbbbbbbb'])


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    unittest.main(argv=[sys.argv[0], sys.argv[2]] if _native else [sys.argv[0]])
