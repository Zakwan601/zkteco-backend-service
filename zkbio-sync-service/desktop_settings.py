"""Persistent desktop preferences and editable connection settings."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import dotenv_values, set_key
from PySide6.QtCore import QSettings

from desktop_utils import application_root

DEFAULT_SYNC_INTERVAL = 60


@dataclass(frozen=True)
class ConnectionForm:
    zkbio_url: str
    zkbio_username: str
    zkbio_password: str
    supabase_url: str
    supabase_key: str


class DesktopSettings:
    """Store non-secret preferences in QSettings and credentials in .env."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or application_root()
        self.env_path = self.root / ".env"
        self.settings = QSettings("ZKBioSyncService", "DesktopApp")

    @property
    def sync_interval(self) -> int:
        return max(
            15,
            self.settings.value(
                "sync_interval",
                DEFAULT_SYNC_INTERVAL,
                type=int,
            ),
        )

    @sync_interval.setter
    def sync_interval(self, value: int) -> None:
        self.settings.setValue("sync_interval", max(15, int(value)))

    @property
    def start_with_windows(self) -> bool:
        return self.settings.value("start_with_windows", False, type=bool)

    @start_with_windows.setter
    def start_with_windows(self, value: bool) -> None:
        self.settings.setValue("start_with_windows", bool(value))

    @property
    def start_minimized(self) -> bool:
        return self.settings.value("start_minimized", True, type=bool)

    @start_minimized.setter
    def start_minimized(self, value: bool) -> None:
        self.settings.setValue("start_minimized", bool(value))

    @property
    def notifications_enabled(self) -> bool:
        return self.settings.value("notifications_enabled", True, type=bool)

    @notifications_enabled.setter
    def notifications_enabled(self, value: bool) -> None:
        self.settings.setValue("notifications_enabled", bool(value))

    @property
    def close_notice_shown(self) -> bool:
        return self.settings.value("close_notice_shown", False, type=bool)

    @close_notice_shown.setter
    def close_notice_shown(self, value: bool) -> None:
        self.settings.setValue("close_notice_shown", bool(value))

    @property
    def last_successful_sync(self) -> str:
        return self.settings.value("last_successful_sync", "Never", type=str)

    @last_successful_sync.setter
    def last_successful_sync(self, value: str) -> None:
        self.settings.setValue("last_successful_sync", value)

    def load_connections(self) -> ConnectionForm:
        values = dotenv_values(self.env_path)
        return ConnectionForm(
            zkbio_url=str(values.get("ZKBIO_URL") or ""),
            zkbio_username=str(values.get("ZKBIO_USERNAME") or ""),
            zkbio_password=str(values.get("ZKBIO_PASSWORD") or ""),
            supabase_url=str(values.get("SUPABASE_URL") or ""),
            supabase_key=str(values.get("SUPABASE_KEY") or ""),
        )

    def save_connections(self, form: ConnectionForm) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        values = {
            "ZKBIO_URL": form.zkbio_url.strip().rstrip("/"),
            "ZKBIO_USERNAME": form.zkbio_username.strip(),
            "ZKBIO_PASSWORD": form.zkbio_password,
            "SUPABASE_URL": form.supabase_url.strip().rstrip("/"),
            "SUPABASE_KEY": form.supabase_key,
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError(
                "Complete all connection fields: " + ", ".join(missing)
            )

        for key, value in values.items():
            set_key(
                str(self.env_path),
                key,
                value,
                quote_mode="auto",
            )
            os.environ[key] = value

        self.settings.sync()
