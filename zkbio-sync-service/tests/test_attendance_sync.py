"""Tests for daily attendance Edge Function triggering."""

from datetime import date
import unittest
from unittest.mock import MagicMock, call, patch

import requests

import attendance_sync


class AttendanceSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        attendance_sync._last_daily_sync_date = None

    @patch("attendance_sync.requests.post")
    def test_posts_selected_date_and_secret(self, post: MagicMock) -> None:
        response = post.return_value
        response.status_code = 200

        attendance_sync.sync_attendance_day(
            "https://example.supabase.co/functions/v1/sync-attendance",
            "shared-secret",
            date(2026, 7, 31),
        )

        post.assert_called_once_with(
            "https://example.supabase.co/functions/v1/sync-attendance",
            headers={
                "Content-Type": "application/json",
                "X-Sync-Secret": "shared-secret",
            },
            json={"date": "2026-07-31"},
            timeout=attendance_sync.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status.assert_called_once_with()

    @patch("attendance_sync.sync_attendance_day")
    @patch("attendance_sync.dhaka_today")
    def test_current_day_runs_once_then_on_date_change(
        self,
        today: MagicMock,
        sync_day: MagicMock,
    ) -> None:
        today.side_effect = [
            date(2026, 7, 31),
            date(2026, 7, 31),
            date(2026, 8, 1),
        ]

        for _ in range(3):
            attendance_sync.ensure_current_day_synced("url", "secret")

        self.assertEqual(
            sync_day.call_args_list,
            [
                call("url", "secret", date(2026, 7, 31)),
                call("url", "secret", date(2026, 8, 1)),
            ],
        )

    @patch("attendance_sync.remove_pending_attendance_date")
    @patch("attendance_sync.sync_attendance_day")
    @patch(
        "attendance_sync.load_pending_attendance_dates",
        return_value={"2026-07-31", "2026-08-01"},
    )
    def test_pending_dates_clear_only_after_success(
        self,
        _load: MagicMock,
        sync_day: MagicMock,
        remove: MagicMock,
    ) -> None:
        sync_day.side_effect = [None, requests.ConnectionError("offline")]

        with self.assertRaises(requests.ConnectionError):
            attendance_sync.sync_pending_attendance_days("url", "secret")

        remove.assert_called_once_with("2026-07-31")

    def test_utc_punch_is_converted_to_dhaka_date(self) -> None:
        self.assertEqual(
            attendance_sync.punch_date("2026-07-31T20:30:00Z"),
            date(2026, 8, 1),
        )


if __name__ == "__main__":
    unittest.main()
