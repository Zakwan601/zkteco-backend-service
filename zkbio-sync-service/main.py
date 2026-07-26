"""Run one complete ZKBioTime-to-Supabase synchronization."""

import logging

from attendance import get_attendance
from auth import ZKBioClient
from config import load_settings
from employees import get_all_employees
from logger import configure_logging
from state import get_attendance_timestamp, load_last_sync_time, save_last_sync_time
from supabase_client import (
    configure_supabase,
    upsert_attendance,
    upsert_device,
    upsert_employee,
)
from terminals import get_all_terminals

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    settings = load_settings()
    client = ZKBioClient(
        base_url=settings.zkbio_url,
        username=settings.zkbio_username,
        password=settings.zkbio_password,
    )
    configure_supabase(settings.supabase_url, settings.supabase_key)

    client.get_token()
    logger.info("Logged into ZKBioTime")

    terminals = get_all_terminals(client)
    logger.info("Downloaded %d devices", len(terminals))

    for terminal in terminals:
        upsert_device(terminal)
    logger.info("Uploaded %d devices", len(terminals))

    employees = get_all_employees(client)
    logger.info("Downloaded %d employees", len(employees))

    for employee in employees:
        upsert_employee(employee)
    logger.info("Uploaded %d employees", len(employees))

    last_sync_time = load_last_sync_time()
    logger.info("Last sync time: %s", last_sync_time)

    attendance_records = get_attendance(client, start_time=last_sync_time)
    logger.info(
        "Downloaded %d new attendance records",
        len(attendance_records),
    )

    uploaded_timestamps: list[str] = []
    for attendance in attendance_records:
        upsert_attendance(attendance)
        uploaded_timestamps.append(get_attendance_timestamp(attendance))
    logger.info("Uploaded %d attendance records", len(attendance_records))

    newest_sync_time = max(uploaded_timestamps, default=last_sync_time)
    save_last_sync_time(newest_sync_time)
    logger.info("Updated sync state")
    logger.info("Synchronization completed successfully")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.getLogger(__name__).exception("ZKBioTime synchronization failed")
        raise SystemExit(1)
