"""BioTime API health checks, targeted Windows-service recovery, and alerts."""

from collections.abc import Callable
from datetime import datetime, timezone
import logging
import os
import platform
import re
import subprocess
import time

import requests

from auth import ZKBioClient

ProgressCallback = Callable[[str, str, str], None]

BIOTIME_SERVICES = (
    "bio-pgsql",
    "bio-redis",
    "bio-cache",
    "bio-server",
    "bio-monitor",
    "bio-proxy",
    "bio-apache0",
)
MAIN_BIOTIME_SERVICE = "bio-server"
API_PROBE_TIMEOUT_SECONDS = 10
RECOVERY_WAIT_SECONDS = 15
SERVICE_COMMAND_TIMEOUT_SECONDS = 15
SERVICE_STATE_WAIT_SECONDS = 12
DISCORD_TIMEOUT_SECONDS = 10
DISCORD_ALERT_COOLDOWN_SECONDS = 30 * 60

logger = logging.getLogger(__name__)
_last_discord_alert_at = 0.0


class BioTimeRecoveryError(RuntimeError):
    """Raised when the API remains unavailable after targeted recovery."""


def _progress(
    callback: ProgressCallback | None,
    title: str,
    detail: str,
    level: str = "working",
) -> None:
    logger.info("BioTime recovery: %s - %s", title, detail)
    if callback is not None:
        callback(title, detail, level)


def _api_is_reachable(client: ZKBioClient) -> None:
    client.token = None
    client.get_token(timeout=API_PROBE_TIMEOUT_SECONDS)


def _is_client_error(error: Exception) -> bool:
    if not isinstance(error, requests.HTTPError) or error.response is None:
        return False
    return 400 <= error.response.status_code < 500


def _run_service_command(*arguments: str) -> subprocess.CompletedProcess[str]:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        ["sc.exe", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=SERVICE_COMMAND_TIMEOUT_SECONDS,
        creationflags=creation_flags,
        check=False,
    )


def get_service_state(service_name: str) -> str:
    """Return a Windows service state such as RUNNING or STOPPED."""
    if os.name != "nt":
        return "UNSUPPORTED"
    result = _run_service_command("query", service_name)
    combined_output = f"{result.stdout}\n{result.stderr}"
    match = re.search(r"STATE\s*:\s*\d+\s+(\w+)", combined_output)
    if match:
        return match.group(1).upper()
    if result.returncode == 1060 or "1060" in combined_output:
        return "NOT_FOUND"
    return f"QUERY_FAILED_{result.returncode}"


def _wait_for_service(service_name: str, wanted_state: str) -> bool:
    deadline = time.monotonic() + SERVICE_STATE_WAIT_SECONDS
    while time.monotonic() < deadline:
        if get_service_state(service_name) == wanted_state:
            return True
        time.sleep(1)
    return get_service_state(service_name) == wanted_state


def start_service(service_name: str) -> tuple[bool, str]:
    """Start one stopped service and confirm that it reaches RUNNING."""
    result = _run_service_command("start", service_name)
    if result.returncode not in (0, 1056):
        return False, f"start failed (Windows error {result.returncode})"
    if _wait_for_service(service_name, "RUNNING"):
        return True, "started"
    return False, f"did not reach RUNNING (state: {get_service_state(service_name)})"


def restart_service(service_name: str) -> tuple[bool, str]:
    """Restart one running service and confirm recovery."""
    stop_result = _run_service_command("stop", service_name)
    if stop_result.returncode not in (0, 1062):
        return False, f"stop failed (Windows error {stop_result.returncode})"
    if stop_result.returncode == 0 and not _wait_for_service(
        service_name,
        "STOPPED",
    ):
        return False, "did not stop in time"
    return start_service(service_name)


def _safe_error(error: Exception, client: ZKBioClient) -> str:
    message = f"{type(error).__name__}: {error}"
    for secret in (client.username, client.password, client.token or ""):
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message[:1000]


def send_discord_alert(
    webhook_url: str,
    error_detail: str,
    service_states: dict[str, str],
    recovery_actions: list[str],
) -> str:
    """Send a confirmed one-way Discord webhook alert with rate limiting."""
    global _last_discord_alert_at

    if not webhook_url:
        return "Discord webhook is not configured"
    if not webhook_url.startswith("https://discord.com/api/webhooks/"):
        return "Discord webhook URL is invalid"

    now = time.monotonic()
    remaining = DISCORD_ALERT_COOLDOWN_SECONDS - (now - _last_discord_alert_at)
    if _last_discord_alert_at and remaining > 0:
        return f"Discord alert suppressed by cooldown ({int(remaining)}s remaining)"

    state_lines = "\n".join(
        f"{name}: {state}" for name, state in service_states.items()
    ) or "Service state unavailable"
    action_lines = "\n".join(recovery_actions) or "No recovery action completed"
    payload = {
        "username": "BioTime Service Monitor",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "BioTime API recovery failed",
                "description": (
                    "The attendance sync application could not restore the "
                    "BioTime API after checking its Windows services."
                ),
                "color": 15548997,
                "fields": [
                    {"name": "Computer", "value": platform.node() or "Unknown"},
                    {"name": "Error", "value": error_detail or "Unknown"},
                    {"name": "Service states", "value": state_lines[:1024]},
                    {"name": "Recovery actions", "value": action_lines[:1024]},
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }
    try:
        response = requests.post(
            webhook_url,
            params={"wait": "true"},
            json=payload,
            timeout=DISCORD_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        return f"Discord request failed ({type(error).__name__})"
    if not response.ok:
        return f"Discord rejected the alert (HTTP {response.status_code})"

    _last_discord_alert_at = now
    return "Discord alert sent"


def send_discord_test(webhook_url: str) -> tuple[bool, str]:
    """Send a user-requested test message without affecting alert cooldown."""
    if not webhook_url:
        return False, "Enter a Discord webhook URL first."
    if not webhook_url.startswith("https://discord.com/api/webhooks/"):
        return False, "The Discord webhook URL is invalid."

    payload = {
        "username": "BioTime Service Monitor",
        "content": (
            "BioTime monitoring is connected successfully. Future recovery "
            "failures will be reported in this channel."
        ),
        "allowed_mentions": {"parse": []},
    }
    try:
        response = requests.post(
            webhook_url,
            params={"wait": "true"},
            json=payload,
            timeout=DISCORD_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        return False, f"Discord request failed ({type(error).__name__})."
    if not response.ok:
        return False, f"Discord rejected the test (HTTP {response.status_code})."
    return True, "Test notification sent successfully."


def ensure_biotime_available(
    client: ZKBioClient,
    discord_webhook_url: str = "",
    progress: ProgressCallback | None = None,
) -> None:
    """Probe BioTime and perform a minimal recovery when it is unavailable."""
    _progress(
        progress,
        "Checking BioTime API",
        "Testing the authentication endpoint before synchronization.",
    )
    try:
        _api_is_reachable(client)
    except Exception as initial_error:
        if _is_client_error(initial_error):
            _progress(
                progress,
                "BioTime rejected the login",
                "The API is online, but the configured credentials were rejected.",
                "error",
            )
            raise
    else:
        _progress(
            progress,
            "BioTime API is healthy",
            "The login endpoint responded successfully.",
            "success",
        )
        return

    _progress(
        progress,
        "BioTime API is unavailable",
        "Checking the BioTime Windows services now.",
        "error",
    )
    service_states = {
        service_name: get_service_state(service_name)
        for service_name in BIOTIME_SERVICES
    }
    recovery_actions: list[str] = []
    stopped_services = [
        name for name in BIOTIME_SERVICES if service_states[name] == "STOPPED"
    ]

    if stopped_services:
        for service_name in stopped_services:
            _progress(
                progress,
                f"Starting {service_name}",
                f"Current state: {service_states[service_name]}",
            )
            succeeded, result = start_service(service_name)
            recovery_actions.append(f"{service_name}: {result}")
            service_states[service_name] = get_service_state(service_name)
            _progress(
                progress,
                f"{service_name}: {result}",
                f"New state: {service_states[service_name]}",
                "success" if succeeded else "error",
            )
    elif all(state == "RUNNING" for state in service_states.values()):
        _progress(
            progress,
            f"Restarting {MAIN_BIOTIME_SERVICE}",
            "All dependencies are running, so only the main service will restart.",
        )
        succeeded, result = restart_service(MAIN_BIOTIME_SERVICE)
        recovery_actions.append(f"{MAIN_BIOTIME_SERVICE}: {result}")
        service_states[MAIN_BIOTIME_SERVICE] = get_service_state(
            MAIN_BIOTIME_SERVICE
        )
        _progress(
            progress,
            f"{MAIN_BIOTIME_SERVICE}: {result}",
            f"New state: {service_states[MAIN_BIOTIME_SERVICE]}",
            "success" if succeeded else "error",
        )
    else:
        unavailable = ", ".join(
            f"{name}={state}"
            for name, state in service_states.items()
            if state != "RUNNING"
        )
        recovery_actions.append(f"No safe automatic action: {unavailable}")

    _progress(
        progress,
        "Waiting for BioTime",
        f"Allowing services {RECOVERY_WAIT_SECONDS} seconds to initialize.",
    )
    time.sleep(RECOVERY_WAIT_SECONDS)
    _progress(
        progress,
        "Retesting BioTime API",
        "Checking whether the recovery restored the login endpoint.",
    )
    try:
        _api_is_reachable(client)
    except Exception as final_error:
        error_detail = _safe_error(final_error, client)
        alert_result = send_discord_alert(
            discord_webhook_url,
            error_detail,
            service_states,
            recovery_actions,
        )
        _progress(
            progress,
            "BioTime recovery failed",
            f"API is still unavailable. {alert_result}.",
            "error",
        )
        raise BioTimeRecoveryError(
            f"BioTime API is unavailable after service recovery. {alert_result}."
        ) from final_error

    _progress(
        progress,
        "BioTime recovery succeeded",
        "The API is responding and synchronization will continue.",
        "success",
    )
