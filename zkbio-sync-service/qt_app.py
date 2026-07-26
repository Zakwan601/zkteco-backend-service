"""Application bootstrap for the PySide6 tray interface."""

import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from desktop_gui import MainWindow
from desktop_settings import DesktopSettings
from desktop_utils import prepare_runtime_environment
from logger import configure_logging, flush_logs
from scheduler import SingleInstanceLock

logger = logging.getLogger(__name__)


def main() -> int:
    prepare_runtime_environment()
    configure_logging()

    application = QApplication(sys.argv)
    application.setApplicationName("Attendance Sync")
    application.setOrganizationName("ZKBioSyncService")
    application.setQuitOnLastWindowClosed(False)
    application.setStyle("Fusion")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            "System tray unavailable",
            "Windows system tray support is required to run Attendance Sync.",
        )
        return 1

    instance_lock = SingleInstanceLock()
    if not instance_lock.acquire():
        logger.info("Background sync is already running")
        QMessageBox.information(
            None,
            "Attendance Sync",
            "Attendance Sync is already running.",
        )
        return 0

    settings = DesktopSettings()
    window = MainWindow(settings)
    force_background = "--background" in sys.argv
    if force_background or settings.start_minimized:
        window.hide()
    else:
        window.show()

    def cleanup() -> None:
        instance_lock.release()
        flush_logs()

    application.aboutToQuit.connect(cleanup)
    exit_code = application.exec()
    logging.shutdown()
    return exit_code
