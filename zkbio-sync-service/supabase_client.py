"""All Supabase database access for the synchronization service."""

from datetime import datetime
import logging
from typing import Any

from supabase import Client, create_client

STUDENTS_TABLE = "students"
DEVICES_TABLE = "devices"
DEVICE_LOGS_TABLE = "device_logs"
EMPLOYEE_CONFLICT_COLUMN = "admission_number"

_client: Client | None = None
_device_id_cache: dict[str, str | None] = {}
logger = logging.getLogger(__name__)


def configure_supabase(url: str, key: str) -> None:
    """Create the shared Supabase client used by database helpers."""
    global _client
    _client = create_client(url, key)
    _device_id_cache.clear()


def _get_client() -> Client:
    if _client is None:
        raise RuntimeError("Supabase client has not been configured")
    return _client


def _required_text(record: dict[str, Any], field: str, label: str) -> str:
    value = record.get(field)
    if value is None:
        raise ValueError(f"{label} is missing {field}")

    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} has an empty {field}")
    return text


def _as_active(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "inactive", "disabled"}
    return bool(value)


def _employee_payload(employee: dict[str, Any]) -> dict[str, Any]:
    employee_code = _required_text(employee, "emp_code", "Employee record")
    first_name = str(employee.get("first_name") or employee.get("name") or employee_code)
    last_name = str(employee.get("last_name") or "")

    payload: dict[str, Any] = {
        "admission_number": employee_code,
        "biometric_id": employee_code,
        "first_name": first_name,
        "last_name": last_name,
        "is_active": _as_active(
            employee.get("enable_att", employee.get("is_active", True))
        ),
    }

    optional_fields = {
        "birthday": "date_of_birth",
        "gender": "gender",
        "address": "address",
    }
    for source, destination in optional_fields.items():
        value = employee.get(source)
        if value not in (None, ""):
            payload[destination] = value

    return payload


def upsert_employee(employee: dict[str, Any]) -> Any:
    """Map a ZKBioTime employee to students and upsert by Employee Code."""
    payload = _employee_payload(employee)
    return (
        _get_client()
        .table(STUDENTS_TABLE)
        .upsert(payload, on_conflict=EMPLOYEE_CONFLICT_COLUMN)
        .execute()
    )


def _local_timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None

    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.isoformat()


def upsert_device(device: dict[str, Any]) -> Any:
    """Map parsed ZKBioTime terminal information to the devices table."""
    serial = _required_text(device, "sn", "Terminal record")
    terminal_name = str(device.get("terminal_name") or serial)
    area_name = device.get("area_name")
    is_active = str(device.get("state")).strip() == "1"
    synced_at = datetime.now().astimezone().isoformat()

    payload = {
        "device_serial": serial,
        "name": terminal_name,
        "model": terminal_name,
        "is_active": is_active,
        "sn": serial,
        "alias": device.get("alias"),
        "ip_address": device.get("ip_address"),
        "firmware_version": device.get("fw_ver"),
        "push_version": device.get("push_ver"),
        "area": area_name,
        "location": area_name,
        "user_count": int(device.get("user_count") or 0),
        "fingerprint_count": int(device.get("fp_count") or 0),
        "face_count": int(device.get("face_count") or 0),
        "palm_count": int(device.get("palm_count") or 0),
        "transaction_count": int(device.get("transaction_count") or 0),
        "last_activity": _local_timestamp(device.get("last_activity")),
        "push_time": (
            str(device["push_time"]) if device.get("push_time") is not None else None
        ),
        "transfer_interval": (
            str(device["transfer_interval"])
            if device.get("transfer_interval") is not None
            else None
        ),
        "attendance_status": (
            str(device["is_attendance"])
            if device.get("is_attendance") is not None
            else None
        ),
        "device_state": "active" if is_active else "inactive",
        "is_online": bool(device.get("is_online")),
        "raw_data": device,
        "synced_at": synced_at,
        "last_sync_at": synced_at,
    }
    return (
        _get_client()
        .table(DEVICES_TABLE)
        .upsert(payload, on_conflict="device_serial")
        .execute()
    )


def _resolve_device_id(attendance: dict[str, Any]) -> str | None:
    serial_value = attendance.get("terminal_sn")
    if serial_value is None or not str(serial_value).strip():
        return None

    serial = str(serial_value).strip()
    if serial in _device_id_cache:
        return _device_id_cache[serial]

    response = (
        _get_client()
        .table(DEVICES_TABLE)
        .select("id")
        .eq("device_serial", serial)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    device_id = rows[0].get("id") if rows else None
    if not isinstance(device_id, str):
        device_id = None
        logger.warning(
            "No Supabase device found for ZKBioTime terminal serial %s",
            serial,
        )

    _device_id_cache[serial] = device_id
    return device_id


def _find_existing_log(
    device_id: str | None,
    student_biometric_id: str,
    punched_at: str,
) -> str | None:
    query = (
        _get_client()
        .table(DEVICE_LOGS_TABLE)
        .select("id")
        .eq("student_biometric_id", student_biometric_id)
        .eq("punched_at", punched_at)
    )
    if device_id is None:
        query = query.is_("device_id", "null")
    else:
        query = query.eq("device_id", device_id)

    response = query.limit(1).execute()
    rows = response.data or []
    log_id = rows[0].get("id") if rows else None
    return log_id if isinstance(log_id, str) else None


def upsert_attendance(attendance: dict[str, Any]) -> Any:
    """Map a ZKBioTime punch to device_logs without creating duplicates."""
    student_biometric_id = _required_text(
        attendance,
        "emp_code",
        "Attendance record",
    )
    punched_at = _required_text(attendance, "punch_time", "Attendance record")
    device_id = _resolve_device_id(attendance)
    existing_log_id = _find_existing_log(
        device_id,
        student_biometric_id,
        punched_at,
    )

    if existing_log_id is not None:
        return (
            _get_client()
            .table(DEVICE_LOGS_TABLE)
            .update({"raw_data": attendance})
            .eq("id", existing_log_id)
            .execute()
        )

    payload = {
        "device_id": device_id,
        "student_biometric_id": student_biometric_id,
        "punched_at": punched_at,
        "processed": False,
        "raw_data": attendance,
    }
    return _get_client().table(DEVICE_LOGS_TABLE).insert(payload).execute()
