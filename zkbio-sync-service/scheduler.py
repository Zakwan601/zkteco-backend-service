"""Single-worker background scheduler for continuous synchronization."""

from dataclasses import asdict, dataclass
from datetime import datetime
import ctypes
import logging
import os
from queue import Empty, Queue
import threading
import time
from typing import Any

from attendance import get_attendance
from auth import ZKBioClient
from config import Settings, load_settings
from employees import get_all_employees
from state import get_attendance_timestamp, load_last_sync_time, save_last_sync_time
from service_status import publish_heartbeat, publish_safely, publish_stopped
from supabase_client import configure_supabase, upsert_attendance, upsert_employee

ATTENDANCE_INTERVAL_SECONDS = 30
EMPLOYEE_INTERVAL_SECONDS = 6 * 60 * 60
MAX_BACKOFF_SECONDS = 60
HEARTBEAT_INTERVAL_SECONDS = 5 * 60
MUTEX_NAME = r"Global\ZKBioTimeSupabaseSyncService"
ERROR_ALREADY_EXISTS = 183
ERROR_ACCESS_DENIED = 5

logger = logging.getLogger(__name__)


@dataclass
class SchedulerStatus:
    service_status: str = "Stopped"
    zkbio_status: str = "Not connected"
    supabase_status: str = "Not connected"
    last_employee_sync: str = "Never"
    last_attendance_sync: str = "Never"
    attendance_uploaded: int = 0
    last_error: str = "None"


class SingleInstanceLock:
    """Windows named mutex that prevents duplicate sync processes."""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self.name = name
        self._handle: int | None = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        create_mutex.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_bool

        handle = create_mutex(None, False, self.name)
        error = ctypes.get_last_error()
        if not handle:
            if error == ERROR_ACCESS_DENIED:
                return False
            raise ctypes.WinError(error)

        if error == ERROR_ALREADY_EXISTS:
            close_handle(handle)
            return False

        self._handle = int(handle)
        return True

    def release(self) -> None:
        if self._handle is None or os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_bool
        close_handle(self._handle)
        self._handle = None

    def __enter__(self) -> "SingleInstanceLock":
        if not self.acquire():
            raise RuntimeError("Background sync is already running")
        return self

    def __exit__(self, *_args: Any) -> None:
        self.release()


class BackgroundScheduler:
    """Run all scheduled and manual synchronization on one worker thread."""

    def __init__(
        self,
        attendance_interval: float = ATTENDANCE_INTERVAL_SECONDS,
        employee_interval: float = EMPLOYEE_INTERVAL_SECONDS,
    ) -> None:
        self.attendance_interval = attendance_interval
        self.employee_interval = employee_interval
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._commands: Queue[str] = Queue()
        self._thread: threading.Thread | None = None
        self._status = SchedulerStatus()
        self._status_lock = threading.Lock()
        self._employee_lock = threading.Lock()
        self._attendance_lock = threading.Lock()
        self._settings: Settings | None = None
        self._client: ZKBioClient | None = None
        self._backoff = {"employee": 1, "attendance": 1}

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_status(self) -> dict[str, Any]:
        with self._status_lock:
            return asdict(self._status)

    def _set_status(self, **changes: Any) -> None:
        with self._status_lock:
            for key, value in changes.items():
                setattr(self._status, key, value)

    def start(self) -> bool:
        """Start the worker. Return False when it was already running."""
        if self.is_running:
            return False

        self._stop_event.clear()
        self._wake_event.clear()
        self._backoff = {"employee": 1, "attendance": 1}
        self._set_status(service_status="Starting")
        self._thread = threading.Thread(
            target=self._worker_entry,
            name="zkbio-sync-worker",
            daemon=False,
        )
        self._thread.start()
        return True

    def stop(self, wait: bool = True) -> None:
        """Request shutdown; the active synchronization is allowed to finish."""
        if not self.is_running:
            self._set_status(service_status="Stopped")
            return

        self._set_status(service_status="Stopping")
        self._stop_event.set()
        self._wake_event.set()
        if wait and self._thread is not threading.current_thread():
            self._thread.join()

    def sync_employees_now(self) -> None:
        if not self.start():
            self._commands.put("employee")
            self._wake_event.set()

    def sync_attendance_now(self) -> None:
        if not self.start():
            self._commands.put("attendance")
            self._wake_event.set()

    def _safe_error(self, error: Exception) -> str:
        message = f"{type(error).__name__}: {error}"
        if self._settings is not None:
            secrets = (
                self._settings.zkbio_password,
                self._settings.supabase_key,
            )
            for secret in secrets:
                if secret:
                    message = message.replace(secret, "[REDACTED]")
        return message

    def _record_error(self, context: str, error: Exception) -> None:
        safe_error = self._safe_error(error)
        self._set_status(last_error=safe_error)
        logger.error("%s: %s", context, safe_error)

    def _wait(self, seconds: float) -> bool:
        """Return True when shutdown was requested during the wait."""
        deadline = time.monotonic() + max(0, seconds)
        while not self._stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._wake_event.wait(remaining)
            self._wake_event.clear()
            if not self._commands.empty():
                return False
        return True

    def _initialize(self) -> bool:
        delay = 1
        while not self._stop_event.is_set():
            try:
                self._settings = load_settings()
                self._client = ZKBioClient(
                    base_url=self._settings.zkbio_url,
                    username=self._settings.zkbio_username,
                    password=self._settings.zkbio_password,
                )
                configure_supabase(
                    self._settings.supabase_url,
                    self._settings.supabase_key,
                )
                self._set_status(supabase_status="Configured")
                self._client.get_token()
                self._set_status(
                    zkbio_status="Connected",
                    service_status="Running",
                    last_error="None",
                )
                logger.info("Logged into ZKBioTime")
                return True
            except Exception as error:
                self._set_status(
                    zkbio_status="Connection failed",
                    service_status="Retrying",
                )
                self._record_error("Initialization failed", error)
                logger.info("Retrying initialization in %d seconds", delay)
                if self._wait(delay):
                    return False
                delay = min(delay * 2, MAX_BACKOFF_SECONDS)
        return False

    def _sync_employees(self) -> None:
        if self._client is None:
            raise RuntimeError("ZKBioTime client is not initialized")

        try:
            employees = get_all_employees(self._client)
            self._set_status(zkbio_status="Connected")
        except Exception:
            self._set_status(zkbio_status="Connection failed")
            raise

        try:
            for employee in employees:
                upsert_employee(employee)
            self._set_status(supabase_status="Connected")
        except Exception:
            self._set_status(supabase_status="Upload failed")
            raise

        completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self._set_status(
            last_employee_sync=completed_at,
            last_error="None",
        )
        logger.info("Employee sync completed (%d employees)", len(employees))

    def _sync_attendance(self) -> None:
        if self._client is None:
            raise RuntimeError("ZKBioTime client is not initialized")

        last_sync_time = load_last_sync_time()
        try:
            records = get_attendance(
                self._client,
                start_time=last_sync_time,
            )
            self._set_status(zkbio_status="Connected")
        except Exception:
            self._set_status(zkbio_status="Connection failed")
            raise

        if not records:
            completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
            self._set_status(
                last_attendance_sync=completed_at,
                last_error="None",
            )
            logger.info("No new attendance")
            return

        uploaded_timestamps: list[str] = []
        try:
            for record in records:
                upsert_attendance(record)
                uploaded_timestamps.append(get_attendance_timestamp(record))
            self._set_status(supabase_status="Connected")
        except Exception:
            self._set_status(supabase_status="Upload failed")
            raise

        save_last_sync_time(max(uploaded_timestamps))
        completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._status_lock:
            self._status.last_attendance_sync = completed_at
            self._status.attendance_uploaded += len(records)
            self._status.last_error = "None"
        logger.info("Uploaded %d attendance records", len(records))

    def _run_job(self, name: str) -> float:
        lock = self._employee_lock if name == "employee" else self._attendance_lock
        job = self._sync_employees if name == "employee" else self._sync_attendance
        interval = (
            self.employee_interval
            if name == "employee"
            else self.attendance_interval
        )

        if not lock.acquire(blocking=False):
            logger.info("%s sync is already running", name.capitalize())
            return time.monotonic() + interval

        try:
            job()
        except Exception as error:
            self._record_error(f"{name.capitalize()} sync failed", error)
            delay = self._backoff[name]
            self._backoff[name] = min(delay * 2, MAX_BACKOFF_SECONDS)
            logger.info("Retrying %s sync in %d seconds", name, delay)
            return time.monotonic() + delay
        finally:
            lock.release()

        self._backoff[name] = 1
        return time.monotonic() + interval

    def _worker_run(self) -> None:
        if not self._initialize():
            return

        if self._settings is not None:
            publish_safely(
                "executable heartbeat",
                publish_heartbeat,
                self._settings.supabase_url,
                self._settings.supabase_key,
            )
        heartbeat_due = time.monotonic() + HEARTBEAT_INTERVAL_SECONDS

        employee_due = self._run_job("employee")
        if self._stop_event.is_set():
            return
        attendance_due = self._run_job("attendance")

        while not self._stop_event.is_set():
            try:
                command = self._commands.get_nowait()
            except Empty:
                command = None

            if command == "employee":
                employee_due = self._run_job("employee")
                continue
            if command == "attendance":
                attendance_due = self._run_job("attendance")
                continue

            now = time.monotonic()
            if now >= heartbeat_due:
                if self._settings is not None:
                    publish_safely(
                        "executable heartbeat",
                        publish_heartbeat,
                        self._settings.supabase_url,
                        self._settings.supabase_key,
                    )
                heartbeat_due = now + HEARTBEAT_INTERVAL_SECONDS
                continue
            if now >= attendance_due:
                attendance_due = self._run_job("attendance")
                continue
            if now >= employee_due:
                employee_due = self._run_job("employee")
                continue

            self._wait(min(attendance_due, employee_due, heartbeat_due) - now)

    def _worker_entry(self) -> None:
        logger.info("Background service started")
        restart_delay = 1
        try:
            while not self._stop_event.is_set():
                try:
                    self._worker_run()
                    break
                except Exception as error:
                    self._record_error("Unexpected scheduler error", error)
                    logger.info(
                        "Restarting background worker in %d seconds",
                        restart_delay,
                    )
                    if self._wait(restart_delay):
                        break
                    restart_delay = min(restart_delay * 2, MAX_BACKOFF_SECONDS)
        finally:
            if self._settings is not None:
                publish_safely(
                    "executable shutdown",
                    publish_stopped,
                    self._settings.supabase_url,
                    self._settings.supabase_key,
                )
            self._set_status(service_status="Stopped")
            logger.info("Background service stopped")
