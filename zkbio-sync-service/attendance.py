"""ZKBioTime attendance transaction API."""

from typing import Any

from auth import ZKBioClient


def _records_and_next(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(payload, list):
        return payload, None
    if not isinstance(payload, dict):
        raise ValueError("ZKBioTime returned an unexpected response format")

    records = payload.get("data", payload.get("results"))
    if not isinstance(records, list):
        raise ValueError("ZKBioTime response did not contain a record list")

    next_url = payload.get("next")
    return records, next_url if isinstance(next_url, str) and next_url else None


def get_attendance(
    client: ZKBioClient,
    start_time: str | None = None,
    end_time: str | None = None,
) -> list[dict[str, Any]]:
    """Download attendance records, optionally constrained by a time range."""
    params = {
        key: value
        for key, value in {
            "start_time": start_time,
            "end_time": end_time,
        }.items()
        if value is not None
    }
    attendance: list[dict[str, Any]] = []
    next_url: str | None = "/iclock/api/transactions/"
    first_request = True

    while next_url:
        response = client.request(
            "GET",
            next_url,
            params=params if first_request else None,
        )
        first_request = False
        records, next_url = _records_and_next(response.json())
        attendance.extend(records)

    return attendance
