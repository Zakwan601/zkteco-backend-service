"""Publish executable health and synchronization status to Supabase."""

from datetime import datetime
import logging
from collections.abc import Callable

import httpx

SERVICE_STATUS_TABLE = "sync_service_status"
SERVICE_KEY = "zkbio-sync-service"
PROCESS_STARTED_AT = datetime.now().astimezone().isoformat()
STATUS_REQUEST_TIMEOUT_SECONDS = 15

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _publish(supabase_url: str, supabase_key: str, **changes: object) -> None:
    """Upsert a partial status record through Supabase PostgREST."""
    timestamp = _now()
    payload = {
        "service_key": SERVICE_KEY,
        "process_started_at": PROCESS_STARTED_AT,
        "reported_running": True,
        "last_heartbeat_at": timestamp,
        "updated_at": timestamp,
        **changes,
    }
    response = httpx.post(
        f"{supabase_url.rstrip('/')}/rest/v1/{SERVICE_STATUS_TABLE}",
        params={"on_conflict": "service_key"},
        headers={
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        json=payload,
        timeout=STATUS_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def publish_heartbeat(supabase_url: str, supabase_key: str) -> None:
    """Record that the executable process is still alive."""
    _publish(supabase_url, supabase_key)


def publish_stopped(supabase_url: str, supabase_key: str) -> None:
    """Immediately record a graceful executable shutdown."""
    _publish(supabase_url, supabase_key, reported_running=False)


def publish_sync_started(supabase_url: str, supabase_key: str) -> None:
    """Record the beginning of a complete synchronization attempt."""
    _publish(
        supabase_url,
        supabase_key,
        last_sync_started_at=_now(),
        last_sync_status="running",
        last_error=None,
    )


def publish_sync_succeeded(supabase_url: str, supabase_key: str) -> None:
    """Record the completion time of a successful synchronization."""
    completed_at = _now()
    _publish(
        supabase_url,
        supabase_key,
        last_sync_at=completed_at,
        last_sync_status="success",
        last_error=None,
    )


def publish_sync_failed(
    supabase_url: str,
    supabase_key: str,
    error: Exception,
    *sensitive_values: str,
) -> None:
    """Record a failed synchronization without exposing credentials."""
    message = f"{type(error).__name__}: {error}"
    for sensitive_value in (supabase_key, *sensitive_values):
        if sensitive_value:
            message = message.replace(sensitive_value, "[REDACTED]")
    _publish(
        supabase_url,
        supabase_key,
        last_sync_status="failed",
        last_error=message,
    )


def publish_safely(
    action: str,
    publisher: Callable[..., None],
    *args: object,
) -> None:
    """Publish telemetry without making the main data sync depend on it."""
    try:
        publisher(*args)
    except Exception as error:
        logger.warning("Could not publish %s status: %s", action, error)
