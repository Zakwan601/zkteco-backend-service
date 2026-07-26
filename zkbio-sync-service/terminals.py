"""ZKBioTime terminal API and device status parsing."""

from datetime import datetime, timedelta
from typing import Any

from auth import ZKBioClient

ONLINE_THRESHOLD = timedelta(minutes=2)
TERMINAL_FIELDS = (
    "id",
    "sn",
    "terminal_name",
    "alias",
    "ip_address",
    "fw_ver",
    "push_ver",
    "state",
    "terminal_tz",
    "area_name",
    "last_activity",
    "user_count",
    "fp_count",
    "face_count",
    "palm_count",
    "transaction_count",
    "push_time",
    "transfer_time",
    "transfer_interval",
    "is_attendance",
)


def _parse_server_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        records = payload.get("data", payload.get("results"))
        if isinstance(records, list):
            return records
    raise ValueError("ZKBioTime returned an unexpected terminal response")


def _parse_terminal(
    raw_terminal: dict[str, Any],
    server_now: datetime | None = None,
) -> dict[str, Any]:
    terminal = {field: raw_terminal.get(field) for field in TERMINAL_FIELDS}

    last_activity = terminal.get("last_activity")
    is_online = False
    if isinstance(last_activity, str) and last_activity.strip():
        activity_time = _parse_server_datetime(last_activity)
        now = server_now or datetime.now().astimezone()
        if now.tzinfo is None:
            now = now.replace(tzinfo=activity_time.tzinfo)
        elapsed = now.astimezone(activity_time.tzinfo) - activity_time
        is_online = timedelta(0) <= elapsed <= ONLINE_THRESHOLD

    terminal["is_online"] = is_online
    return terminal


def get_terminal(
    client: ZKBioClient,
    sn: str,
    server_now: datetime | None = None,
) -> dict[str, Any]:
    """Retrieve one terminal by serial number and calculate online status."""
    response = client.request(
        "GET",
        "/iclock/api/terminals/",
        params={"sn": sn},
    )
    records = _records(response.json())
    if not records:
        raise LookupError(f"No ZKBioTime terminal found with serial number {sn}")

    return _parse_terminal(records[0], server_now)


def get_all_terminals(client: ZKBioClient) -> list[dict[str, Any]]:
    """Download every terminal and calculate each device's online status."""
    terminals: list[dict[str, Any]] = []
    next_url: str | None = "/iclock/api/terminals/"
    server_now = datetime.now().astimezone()

    while next_url:
        response = client.request("GET", next_url)
        payload = response.json()
        records = _records(payload)
        terminals.extend(
            _parse_terminal(record, server_now)
            for record in records
        )

        next_value = payload.get("next") if isinstance(payload, dict) else None
        next_url = (
            next_value
            if isinstance(next_value, str) and next_value
            else None
        )

    return terminals
