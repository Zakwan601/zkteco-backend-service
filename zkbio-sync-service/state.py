"""Persistent local state for incremental attendance synchronization."""

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

STATE_FILE = Path(__file__).resolve().parent / "data" / "state.json"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
ATTENDANCE_TIMESTAMP_FIELDS = ("punch_time", "timestamp", "att_time")
RECORD_FINGERPRINTS_KEY = "record_fingerprints"


def _default_last_sync_time() -> str:
    return (datetime.now() - timedelta(hours=24)).strftime(TIME_FORMAT)


def _read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}

    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read sync state from {STATE_FILE}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Sync state must be a JSON object")
    return payload


def _write_state(payload: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = STATE_FILE.with_suffix(".json.tmp")
    temporary_file.write_text(
        json.dumps(payload, indent=4, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_file.replace(STATE_FILE)


def load_last_sync_time() -> str:
    """Read the last sync timestamp, defaulting to 24 hours ago."""
    payload = _read_state()

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

    payload = _read_state()
    payload["last_sync_time"] = last_sync_time
    _write_state(payload)


def record_fingerprint(record: dict[str, Any]) -> str:
    """Create a stable, non-reversible fingerprint for a ZKBioTime record."""
    serialized = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def load_record_fingerprints(collection: str) -> dict[str, str]:
    """Load successful-upload fingerprints for one record collection."""
    fingerprints = _read_state().get(RECORD_FINGERPRINTS_KEY, {})
    if not isinstance(fingerprints, dict):
        return {}

    collection_values = fingerprints.get(collection, {})
    if not isinstance(collection_values, dict):
        return {}
    return {
        str(key): value
        for key, value in collection_values.items()
        if isinstance(value, str)
    }


def save_record_fingerprint(
    collection: str,
    record_key: str,
    fingerprint: str,
) -> None:
    """Remember a fingerprint only after its Supabase upload succeeds."""
    payload = _read_state()
    fingerprints = payload.setdefault(RECORD_FINGERPRINTS_KEY, {})
    if not isinstance(fingerprints, dict):
        fingerprints = {}
        payload[RECORD_FINGERPRINTS_KEY] = fingerprints

    collection_values = fingerprints.setdefault(collection, {})
    if not isinstance(collection_values, dict):
        collection_values = {}
        fingerprints[collection] = collection_values

    collection_values[record_key] = fingerprint
    _write_state(payload)


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
