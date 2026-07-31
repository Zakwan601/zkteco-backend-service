"""Trigger daily attendance generation through the Supabase Edge Function."""

from datetime import date, datetime, timedelta, timezone
import logging
import threading

import requests

from state import (
    add_pending_attendance_date,
    load_pending_attendance_dates,
    remove_pending_attendance_date,
)

DHAKA_TIMEZONE = timezone(timedelta(hours=6), name="Asia/Dhaka")
REQUEST_TIMEOUT_SECONDS = 30

logger = logging.getLogger(__name__)
_daily_sync_lock = threading.Lock()
_last_daily_sync_date: date | None = None


def dhaka_today() -> date:
    """Return the current calendar day used by the attendance database."""
    return datetime.now(DHAKA_TIMEZONE).date()


def punch_date(timestamp: str) -> date:
    """Convert a ZKBio punch timestamp to its Asia/Dhaka calendar day."""
    normalized = timestamp.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(DHAKA_TIMEZONE)
    return parsed.date()


def sync_attendance_day(url: str, secret: str, selected_date: date) -> None:
    """Recalculate one complete attendance day using the Edge Function."""
    response = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "X-Sync-Secret": secret,
        },
        json={"date": selected_date.isoformat()},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    logger.info(
        "Attendance database sync completed for %s (HTTP %d)",
        selected_date.isoformat(),
        response.status_code,
    )


def queue_attendance_day(selected_date: date) -> None:
    """Persist a newly affected day so an Edge Function failure is retryable."""
    add_pending_attendance_date(selected_date.isoformat())


def sync_pending_attendance_days(url: str, secret: str) -> None:
    """Recalculate all queued days, clearing each only after success."""
    for date_text in sorted(load_pending_attendance_dates()):
        selected_date = date.fromisoformat(date_text)
        logger.info(
            "New punches detected; requesting attendance database sync for %s",
            date_text,
        )
        sync_attendance_day(url, secret, selected_date)
        remove_pending_attendance_date(date_text)


def ensure_current_day_synced(url: str, secret: str) -> None:
    """Call once at process startup and again after the Dhaka date changes."""
    global _last_daily_sync_date

    selected_date = dhaka_today()
    with _daily_sync_lock:
        if _last_daily_sync_date == selected_date:
            return
        logger.info(
            "Requesting startup/date-change attendance sync for %s",
            selected_date.isoformat(),
        )
        sync_attendance_day(url, secret, selected_date)
        _last_daily_sync_date = selected_date
