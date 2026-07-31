"""Safety-focused tests for targeted BioTime service recovery."""

import unittest
from unittest.mock import MagicMock, call, patch

import requests

import biotime_recovery as recovery


class BioTimeRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.client.username = "operator"
        self.client.password = "secret"
        self.client.token = None

    @patch("biotime_recovery._api_is_reachable")
    @patch("biotime_recovery.get_service_state")
    def test_healthy_api_does_not_touch_services(
        self,
        get_service_state: MagicMock,
        api_is_reachable: MagicMock,
    ) -> None:
        recovery.ensure_biotime_available(self.client)

        api_is_reachable.assert_called_once_with(self.client)
        get_service_state.assert_not_called()

    @patch("biotime_recovery.time.sleep")
    @patch("biotime_recovery.start_service", return_value=(True, "started"))
    @patch("biotime_recovery.get_service_state")
    @patch("biotime_recovery._api_is_reachable")
    def test_only_stopped_services_are_started(
        self,
        api_is_reachable: MagicMock,
        get_service_state: MagicMock,
        start_service: MagicMock,
        _sleep: MagicMock,
    ) -> None:
        api_is_reachable.side_effect = [requests.ConnectionError(), None]
        get_service_state.side_effect = lambda name: (
            "STOPPED" if name in {"bio-redis", "bio-proxy"} else "RUNNING"
        )

        recovery.ensure_biotime_available(self.client)

        self.assertEqual(
            start_service.call_args_list,
            [call("bio-redis"), call("bio-proxy")],
        )

    @patch("biotime_recovery.time.sleep")
    @patch("biotime_recovery.restart_service", return_value=(True, "started"))
    @patch("biotime_recovery.get_service_state", return_value="RUNNING")
    @patch("biotime_recovery._api_is_reachable")
    def test_only_main_service_restarts_when_everything_is_running(
        self,
        api_is_reachable: MagicMock,
        _get_service_state: MagicMock,
        restart_service: MagicMock,
        _sleep: MagicMock,
    ) -> None:
        api_is_reachable.side_effect = [requests.ConnectionError(), None]

        recovery.ensure_biotime_available(self.client)

        restart_service.assert_called_once_with("bio-server")

    @patch("biotime_recovery.get_service_state")
    @patch("biotime_recovery._api_is_reachable")
    def test_rejected_credentials_do_not_restart_services(
        self,
        api_is_reachable: MagicMock,
        get_service_state: MagicMock,
    ) -> None:
        response = requests.Response()
        response.status_code = 401
        error = requests.HTTPError(response=response)
        api_is_reachable.side_effect = error

        with self.assertRaises(requests.HTTPError):
            recovery.ensure_biotime_available(self.client)

        get_service_state.assert_not_called()

    @patch("biotime_recovery.time.sleep")
    @patch("biotime_recovery.send_discord_alert", return_value="Discord alert sent")
    @patch("biotime_recovery.start_service", return_value=(True, "started"))
    @patch("biotime_recovery.get_service_state", return_value="STOPPED")
    @patch("biotime_recovery._api_is_reachable")
    def test_discord_alert_is_sent_after_failed_retest(
        self,
        api_is_reachable: MagicMock,
        _get_service_state: MagicMock,
        _start_service: MagicMock,
        send_discord_alert: MagicMock,
        _sleep: MagicMock,
    ) -> None:
        api_is_reachable.side_effect = [
            requests.ConnectionError(),
            requests.ConnectionError(),
        ]

        with self.assertRaises(recovery.BioTimeRecoveryError):
            recovery.ensure_biotime_available(
                self.client,
                "https://discord.com/api/webhooks/id/token",
            )

        send_discord_alert.assert_called_once()

    @patch("biotime_recovery.requests.post")
    def test_discord_connection_can_be_tested(self, post: MagicMock) -> None:
        post.return_value.ok = True

        succeeded, message = recovery.send_discord_test(
            "https://discord.com/api/webhooks/id/token"
        )

        self.assertTrue(succeeded)
        self.assertEqual(message, "Test notification sent successfully.")
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
