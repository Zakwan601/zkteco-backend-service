"""ZKBioTime employee API."""

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


def get_all_employees(client: ZKBioClient) -> list[dict[str, Any]]:
    """Download and return every employee as a Python dictionary."""
    employees: list[dict[str, Any]] = []
    next_url: str | None = "/personnel/api/employees/"

    while next_url:
        response = client.request("GET", next_url)
        records, next_url = _records_and_next(response.json())
        employees.extend(records)

    return employees
