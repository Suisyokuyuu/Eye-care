"""Native shell regression: deferred tray registration must not strand a window."""
from pathlib import Path
import logging
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


NATIVE = "--native-case" in sys.argv
ROOT = Path(__file__).resolve().parents[1]


class TrayRecoveryTests(unittest.TestCase):
    def test_unavailable_tray_keeps_taskbar_then_recovers(self):
        if not NATIVE:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--native-case"],
                cwd=ROOT, capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return

        from PySide6 import QtWidgets
        from PySide6.QtCore import QMetaObject, QTimer
        from PySide6.QtGui import QGuiApplication, QWindow
        from eye_care.config.models import AppConfig
        from eye_care.config.store import save_config
        from eye_care.qt.runtime_shell import run_qt_shell

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        exit_app = app.exit
        readiness = {"ready": False}
        icons = []
        failures = []
        completed = []

        class ObservedTray(QtWidgets.QSystemTrayIcon):
            def __init__(self, *args):
                super().__init__(*args)
                icons.append(self)

            @staticmethod
            def isSystemTrayAvailable():
                return readiness["ready"]

        def guard(callback):
            def run():
                try:
                    callback()
                except Exception as exc:
                    failures.append(repr(exc))
                    exit_app(1)
            return run

        def check_initial(code=0):
            self.assertEqual(code, 0, "Native startup/sync/settings checks failed")
            self.assertEqual(len(icons), 1)
            self.assertTrue(icons[0].isVisible(), "Register even when the tray is not ready")
            self.assertFalse(icons[0].icon().isNull())
            root = next(w for w in QGuiApplication.allWindows() if w.title() == "EyE Care")
            self.assertFalse(root.property("trayAvailable"))
            self.assertTrue(QMetaObject.invokeMethod(root, "minimizeWithFade"))

            def check_taskbar():
                self.assertEqual(root.visibility(), QWindow.Minimized)
                readiness["ready"] = True
                root.showNormal()
                QTimer.singleShot(650, guard(check_recovery))

            def check_recovery():
                self.assertTrue(root.property("trayAvailable"))
                self.assertTrue(QMetaObject.invokeMethod(root, "minimizeWithFade"))
                QTimer.singleShot(250, guard(check_tray_restore))

            def check_tray_restore():
                self.assertFalse(root.isVisible())
                icons[0].activated.emit(ObservedTray.Trigger)
                self.assertTrue(root.isVisible(), "Tray activation must restore the window")
                completed.append(True)
                exit_app(0)

            QTimer.singleShot(250, guard(check_taskbar))

        app.exit = lambda code=0: guard(lambda: check_initial(code))()
        QTimer.singleShot(14000, guard(lambda: self.fail("Tray recovery timed out")))
        try:
            with tempfile.TemporaryDirectory(prefix="eyecare-tray-") as temporary:
                data = Path(temporary)
                cfg = AppConfig()
                cfg.notify_enabled = False
                cfg.record_browser_enabled = False
                cfg.show_onboarding = False
                save_config(data / "config.json", cfg)
                try:
                    with patch.object(QtWidgets, "QSystemTrayIcon", ObservedTray):
                        run_qt_shell(data, no_single=True, startup_check=True)
                finally:
                    logging.shutdown()
        finally:
            app.exit = exit_app
        self.assertEqual(failures, [])
        self.assertEqual(completed, [True])


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    unittest.main(argv=[sys.argv[0]])
