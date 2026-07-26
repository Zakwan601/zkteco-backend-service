"""Persistent local state for incremental attendance synchronization."""

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

STATE_FILE = Path(__file__).resolve().parent / "data" / "state.json"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
ATTENDANCE_TIMESTAMP_FIELDS = ("punch_time", "timestamp", "att_time")


def _default_last_sync_time() -> str:
    return (datetime.now() - timedelta(hours=24)).strftime(TIME_FORMAT)


def load_last_sync_time() -> str:
    """Read the last sync timestamp, defaulting to 24 hours ago."""
    if not STATE_FILE.exists():
        return _default_last_sync_time()

    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read sync state from {STATE_FILE}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Sync state must be a JSON object")

    last_sync_time = payload.get("last_sync_time")
    if last_sync_time is None:
        return _default_last_sync_time()
    if not isinstance(last_sync_time, str) or not last_sync_time.strip():
        raise ValueError("last_sync_time must be a non-empty string")

    return last_sync_time


def save_last_sync_time(last_sync_time: str) -> None:
    """Atomically persist the newest successfully uploaded timestamp."""
    if not last_sync_time:
        raise ValueError("last_sync_time cannot be empty")

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = STATE_FILE.with_suffix(".json.tmp")
    payload = {"last_sync_time": last_sync_time}
    temporary_file.write_text(
        json.dumps(payload, indent=4) + "\n",
        encoding="utf-8",
    )
    temporary_file.replace(STATE_FILE)


def get_attendance_timestamp(attendance: dict[str, Any]) -> str:
    """Return the timestamp used to advance incremental sync state."""
    for field in ATTENDANCE_TIMESTAMP_FIELDS:
        value = attendance.get(field)
        if isinstance(value, str) and value.strip():
            return value

    supported = ", ".join(ATTENDANCE_TIMESTAMP_FIELDS)
    raise ValueError(
        f"Attendance record has no timestamp; expected one of: {supported}"
    )
