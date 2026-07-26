"""Milestone 1 command-line entry point."""

import logging

from attendance import get_attendance
from auth import ZKBioClient
from config import load_settings
from employees import get_all_employees
from logger import configure_logging


def main() -> None:
    configure_logging()
    settings = load_settings()
    client = ZKBioClient(
        base_url=settings.zkbio_url,
        username=settings.zkbio_username,
        password=settings.zkbio_password,
    )

    client.get_token()
    print("Logged in successfully")

    employees = get_all_employees(client)
    print(f"Employees: {len(employees)}")

    attendance = get_attendance(client)
    print(f"Attendance records: {len(attendance)}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.getLogger(__name__).exception("ZKBioTime synchronization failed")
        raise SystemExit(1)
