"""Run the shared scheduler silently without a graphical interface."""

import logging
import signal
import threading

from logger import configure_logging, flush_logs
from scheduler import BackgroundScheduler, SingleInstanceLock

logger = logging.getLogger(__name__)


def main() -> int:
    configure_logging()
    instance_lock = SingleInstanceLock()
    if not instance_lock.acquire():
        logger.info("Background sync is already running")
        flush_logs()
        return 0

    shutdown_event = threading.Event()
    scheduler = BackgroundScheduler()

    def request_shutdown(_signum: int, _frame: object) -> None:
        logger.info("Shutdown requested")
        shutdown_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, request_shutdown)

    try:
        scheduler.start()
        while not shutdown_event.wait(1):
            pass
    except KeyboardInterrupt:
        shutdown_event.set()
    finally:
        scheduler.stop(wait=True)
        instance_lock.release()
        flush_logs()
        logging.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
