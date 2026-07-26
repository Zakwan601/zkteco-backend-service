"""Tkinter monitoring and control panel for the background scheduler."""

from __future__ import annotations

import logging
import os
from queue import Empty, Queue
import threading

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError as error:
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    TKINTER_IMPORT_ERROR: ImportError | None = error
else:
    TKINTER_IMPORT_ERROR = None

from logger import LOG_FILE, QueueLogHandler, configure_logging, flush_logs
from scheduler import BackgroundScheduler, SingleInstanceLock

logger = logging.getLogger(__name__)


class SyncControlPanel:
    """Small responsive UI that controls, but never performs, synchronization."""

    def __init__(self, root: tk.Tk, scheduler: BackgroundScheduler) -> None:
        self.root = root
        self.scheduler = scheduler
        self.log_queue: Queue[str] = Queue()
        self.queue_handler = QueueLogHandler(self.log_queue)
        logging.getLogger().addHandler(self.queue_handler)
        self.exiting = False
        self.shutdown_complete = threading.Event()

        self.root.title("ZKBioTime Sync Service")
        self.root.geometry("820x620")
        self.root.minsize(700, 520)
        self.root.protocol("WM_DELETE_WINDOW", self.exit_application)

        self.status_variables = {
            "service_status": tk.StringVar(value="Stopped"),
            "zkbio_status": tk.StringVar(value="Not connected"),
            "supabase_status": tk.StringVar(value="Not connected"),
            "last_employee_sync": tk.StringVar(value="Never"),
            "last_attendance_sync": tk.StringVar(value="Never"),
            "attendance_uploaded": tk.StringVar(value="0"),
            "last_error": tk.StringVar(value="None"),
        }

        self._build_ui()
        self.root.after(250, self._poll_updates)
        self.scheduler.start()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=14)
        container.pack(fill=tk.BOTH, expand=True)

        status_frame = ttk.LabelFrame(container, text="Synchronization Status", padding=10)
        status_frame.pack(fill=tk.X)

        labels = (
            ("Service Status", "service_status"),
            ("ZKBioTime Status", "zkbio_status"),
            ("Supabase Status", "supabase_status"),
            ("Last Employee Sync", "last_employee_sync"),
            ("Last Attendance Sync", "last_attendance_sync"),
            ("Attendance Uploaded", "attendance_uploaded"),
            ("Last Error", "last_error"),
        )
        for row, (label, key) in enumerate(labels):
            ttk.Label(status_frame, text=f"{label}:").grid(
                row=row,
                column=0,
                sticky=tk.W,
                padx=(0, 12),
                pady=3,
            )
            ttk.Label(
                status_frame,
                textvariable=self.status_variables[key],
                wraplength=590,
            ).grid(row=row, column=1, sticky=tk.W, pady=3)
        status_frame.columnconfigure(1, weight=1)

        button_frame = ttk.Frame(container)
        button_frame.pack(fill=tk.X, pady=12)
        buttons = (
            ("Start Sync", self.scheduler.start),
            ("Stop Sync", self.stop_sync),
            ("Sync Employees Now", self.scheduler.sync_employees_now),
            ("Sync Attendance Now", self.scheduler.sync_attendance_now),
            ("Open Log File", self.open_log_file),
            ("Hide Window", self.root.iconify),
            ("Exit", self.exit_application),
        )
        for index, (text, command) in enumerate(buttons):
            ttk.Button(button_frame, text=text, command=command).grid(
                row=index // 4,
                column=index % 4,
                sticky=tk.EW,
                padx=4,
                pady=4,
            )
        for column in range(4):
            button_frame.columnconfigure(column, weight=1)

        log_frame = ttk.LabelFrame(container, text="Recent Logs", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_frame,
            height=16,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        scrollbar = ttk.Scrollbar(
            log_frame,
            orient=tk.VERTICAL,
            command=self.log_text.yview,
        )
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _poll_updates(self) -> None:
        status = self.scheduler.get_status()
        for key, variable in self.status_variables.items():
            variable.set(str(status[key]))

        messages: list[str] = []
        while True:
            try:
                messages.append(self.log_queue.get_nowait())
            except Empty:
                break

        if messages:
            self.log_text.configure(state=tk.NORMAL)
            for message in messages:
                self.log_text.insert(tk.END, message + "\n")
            line_count = int(self.log_text.index("end-1c").split(".")[0])
            if line_count > 500:
                self.log_text.delete("1.0", f"{line_count - 500}.0")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

        if not self.shutdown_complete.is_set():
            self.root.after(250, self._poll_updates)

    def stop_sync(self) -> None:
        threading.Thread(
            target=self.scheduler.stop,
            kwargs={"wait": True},
            name="scheduler-stop-request",
            daemon=True,
        ).start()

    def open_log_file(self) -> None:
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            LOG_FILE.touch(exist_ok=True)
            os.startfile(LOG_FILE)  # type: ignore[attr-defined]
        except Exception as error:
            logger.error("Could not open log file: %s", error)

    def exit_application(self) -> None:
        if self.exiting:
            return
        self.exiting = True
        self.status_variables["service_status"].set("Stopping")
        threading.Thread(
            target=self._finish_exit,
            name="application-shutdown",
            daemon=True,
        ).start()
        self.root.after(100, self._poll_shutdown)

    def _finish_exit(self) -> None:
        self.scheduler.stop(wait=True)
        flush_logs()
        self.shutdown_complete.set()

    def _poll_shutdown(self) -> None:
        if self.shutdown_complete.is_set():
            self.root.destroy()
            return
        self.root.after(100, self._poll_shutdown)

    def close(self) -> None:
        logging.getLogger().removeHandler(self.queue_handler)
        self.queue_handler.close()


def main() -> int:
    configure_logging()
    if TKINTER_IMPORT_ERROR is not None:
        logger.error(
            "Tkinter is unavailable. Install Python 3.12 with the Tcl/Tk "
            "optional feature, then recreate the virtual environment."
        )
        return 1

    instance_lock = SingleInstanceLock()
    if not instance_lock.acquire():
        logger.info("Background sync is already running")
        return 0

    scheduler = BackgroundScheduler()
    root: tk.Tk | None = None
    panel: SyncControlPanel | None = None
    try:
        root = tk.Tk()
        panel = SyncControlPanel(root, scheduler)
        root.mainloop()
    finally:
        scheduler.stop(wait=True)
        if panel is not None:
            panel.close()
        instance_lock.release()
        flush_logs()
        logging.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
