from datetime import timedelta
import unittest

from state import ATTENDANCE_LOOKBACK, attendance_query_start


class AttendanceQueryStartTests(unittest.TestCase):
    def test_rewinds_cursor_to_include_back_dated_punches(self) -> None:
        self.assertEqual(ATTENDANCE_LOOKBACK, timedelta(hours=24))
        self.assertEqual(
            attendance_query_start("2026-08-01 18:12:16"),
            "2026-07-31 18:12:16",
        )

    def test_rejects_an_invalid_cursor(self) -> None:
        with self.assertRaisesRegex(ValueError, "last_sync_time must use"):
            attendance_query_start("not-a-timestamp")


if __name__ == "__main__":
    unittest.main()
