"""Qt worker thread that invokes the existing one-time synchronization."""

from datetime import datetime
import logging

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class SyncWorker(QThread):
    """Call main.main() away from the GUI thread."""

    sync_started = Signal()
    sync_succeeded = Signal(str)
    sync_failed = Signal(str)

    def run(self) -> None:
        self.sync_started.emit()
        try:
            from main import main as run_existing_sync

            run_existing_sync()
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            logger.exception("Desktop synchronization failed")
            self.sync_failed.emit(message)
            return

        completed_at = datetime.now().astimezone().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        self.sync_succeeded.emit(completed_at)
