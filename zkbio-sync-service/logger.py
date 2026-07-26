"""Console and rotating-file logging for the sync service."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Queue

LOG_DIRECTORY = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIRECTORY / "sync.log"
MAX_LOG_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5
LOG_FORMAT = "[%(levelname)s] %(asctime)s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> None:
    """Configure console and rotating-file handlers once."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if any(getattr(handler, "_zkbio_sync_handler", False) for handler in root_logger.handlers):
        return

    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler._zkbio_sync_handler = True  # type: ignore[attr-defined]

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler._zkbio_sync_handler = True  # type: ignore[attr-defined]

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


class QueueLogHandler(logging.Handler):
    """Forward formatted log messages to a thread-safe GUI queue."""

    def __init__(self, log_queue: Queue[str]) -> None:
        super().__init__()
        self.log_queue = log_queue
        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.log_queue.put_nowait(self.format(record))
        except Exception:
            self.handleError(record)


def flush_logs() -> None:
    """Flush every configured log handler."""
    for handler in logging.getLogger().handlers:
        handler.flush()
