"""Run one complete ZKBioTime-to-Supabase synchronization."""

import logging

from attendance import get_attendance
from attendance_sync import (
    ensure_current_day_synced,
    punch_date,
    queue_attendance_day,
    sync_pending_attendance_days,
)
from auth import ZKBioClient
from biotime_recovery import (
    BioTimeRecoveryError,
    DISCORD_ALERT_COOLDOWN_SECONDS,
    ProgressCallback,
    ensure_biotime_available,
    send_discord_event,
)
from config import load_settings
from employees import get_all_employees
from logger import configure_logging
from service_status import (
    publish_safely,
    publish_sync_failed,
    publish_sync_started,
    publish_sync_succeeded,
)
from state import (
    attendance_query_start,
    get_attendance_timestamp,
    load_last_sync_time,
    load_record_fingerprints,
    record_fingerprint,
    save_last_sync_time,
    save_record_fingerprint,
)
from supabase_client import (
    configure_supabase,
    upsert_attendance_with_status,
    upsert_device,
    upsert_employee,
)
from terminals import get_all_terminals

logger = logging.getLogger(__name__)


def main(progress_callback: ProgressCallback | None = None) -> None:
    configure_logging()
    settings = load_settings()
    ensure_current_day_synced(
        settings.sync_attendance_url,
        settings.sync_attendance_secret,
    )
    publish_safely(
        "sync started",
        publish_sync_started,
        settings.supabase_url,
        settings.supabase_key,
    )

    try:
        client = ZKBioClient(
            base_url=settings.zkbio_url,
            username=settings.zkbio_username,
            password=settings.zkbio_password,
        )
        ensure_biotime_available(
            client,
            settings.discord_webhook_url,
            progress_callback,
        )
        configure_supabase(settings.supabase_url, settings.supabase_key)
        logger.info("Logged into ZKBioTime")

        terminals = get_all_terminals(client)
        logger.info("Downloaded %d devices", len(terminals))

        device_fingerprints = load_record_fingerprints("devices")
        uploaded_devices = 0
        for terminal in terminals:
            serial = str(terminal.get("sn") or "").strip()
            fingerprint = record_fingerprint(terminal)
            if serial and device_fingerprints.get(serial) == fingerprint:
                continue
            upsert_device(terminal)
            save_record_fingerprint("devices", serial, fingerprint)
            uploaded_devices += 1
        logger.info("Uploaded %d changed devices", uploaded_devices)

        employees = get_all_employees(client)
        logger.info("Downloaded %d employees", len(employees))

        employee_fingerprints = load_record_fingerprints("employees")
        uploaded_employees = 0
        for employee in employees:
            employee_code = str(employee.get("emp_code") or "").strip()
            fingerprint = record_fingerprint(employee)
            if employee_code and employee_fingerprints.get(employee_code) == fingerprint:
                continue
            upsert_employee(employee)
            save_record_fingerprint("employees", employee_code, fingerprint)
            uploaded_employees += 1
        logger.info("Uploaded %d changed employees", uploaded_employees)

        last_sync_time = load_last_sync_time()
        logger.info("Last sync time: %s", last_sync_time)

        query_start_time = attendance_query_start(last_sync_time)
        attendance_records = get_attendance(client, start_time=query_start_time)
        logger.info(
            "Downloaded %d attendance records from overlap window starting %s",
            len(attendance_records),
            query_start_time,
        )

        uploaded_timestamps: list[str] = []
        inserted_attendance = 0
        for attendance in attendance_records:
            inserted, _response = upsert_attendance_with_status(attendance)
            timestamp = get_attendance_timestamp(attendance)
            uploaded_timestamps.append(timestamp)
            if inserted:
                inserted_attendance += 1
                selected_date = punch_date(timestamp)
                queue_attendance_day(selected_date)
        logger.info("Uploaded %d new attendance records", inserted_attendance)

        sync_pending_attendance_days(
            settings.sync_attendance_url,
            settings.sync_attendance_secret,
        )

        newest_sync_time = max([last_sync_time, *uploaded_timestamps])
        save_last_sync_time(newest_sync_time)
        logger.info("Updated sync state")
    except Exception as error:
        publish_safely(
            "sync failed",
            publish_sync_failed,
            settings.supabase_url,
            settings.supabase_key,
            error,
            settings.zkbio_password,
        )
        if not isinstance(error, BioTimeRecoveryError):
            error_message = f"{type(error).__name__}: {error}"
            for secret in (
                settings.zkbio_password,
                settings.supabase_key,
                settings.sync_attendance_secret,
                settings.discord_webhook_url,
            ):
                if secret:
                    error_message = error_message.replace(secret, "[REDACTED]")
            _sent, notification_result = send_discord_event(
                settings.discord_webhook_url,
                "Attendance synchronization failed",
                error_message,
                color=15548997,
                cooldown_key="sync_failed",
                cooldown_seconds=DISCORD_ALERT_COOLDOWN_SECONDS,
            )
            logger.info(
                "Sync failure Discord notification: %s",
                notification_result,
            )
        raise

    publish_safely(
        "sync succeeded",
        publish_sync_succeeded,
        settings.supabase_url,
        settings.supabase_key,
    )
    logger.info("Synchronization completed successfully")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.getLogger(__name__).exception("ZKBioTime synchronization failed")
        raise SystemExit(1)
