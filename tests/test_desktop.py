import ctypes
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from eye_care.utils.desktop import system_launch_environment


class DesktopEnvironmentTests(unittest.TestCase):
    def run_launch(self, fail):
        bundle = Path('bundled-runtime').resolve()
        previous_dir = str(bundle)
        get = Mock()
        def query(size, buffer):
            if buffer is not None: buffer.value = previous_dir
            return len(previous_dir)
        get.side_effect = query
        setter = Mock(return_value=1)
        kernel = Mock(GetDllDirectoryW=get, SetDllDirectoryW=setter)
        initial = os.pathsep.join([str(bundle / 'PySide6'), str(Path('system-tools').resolve())])
        with patch.object(sys, 'platform', 'win32'), patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, '_MEIPASS', str(bundle), create=True), \
             patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), patch.dict(os.environ, {'PATH': initial}):
            try:
                with system_launch_environment():
                    self.assertEqual(setter.call_args.args, (None,))
                    self.assertNotIn(str(bundle), os.environ['PATH'])
                    if fail: raise RuntimeError('handler failed')
            except RuntimeError:
                if not fail: raise
            self.assertEqual(os.environ['PATH'], initial)
            self.assertEqual(setter.call_args.args, (previous_dir,))

    def test_frozen_launch_removes_bundle_paths_and_restores_them(self):
        self.run_launch(False)

    def test_handler_failure_still_restores_application_environment(self):
        self.run_launch(True)
