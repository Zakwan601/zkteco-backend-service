"""Application configuration loaded from environment variables."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    zkbio_url: str
    zkbio_username: str
    zkbio_password: str
    supabase_url: str
    supabase_key: str
    sync_attendance_url: str
    sync_attendance_secret: str
    discord_webhook_url: str = ""


def load_settings() -> Settings:
    """Load and validate the ZKBioTime connection settings."""
    load_dotenv()

    values = {
        "ZKBIO_URL": os.getenv("ZKBIO_URL", "").strip(),
        "ZKBIO_USERNAME": os.getenv("ZKBIO_USERNAME", "").strip(),
        "ZKBIO_PASSWORD": os.getenv("ZKBIO_PASSWORD", ""),
        "SUPABASE_URL": os.getenv("SUPABASE_URL", "").strip(),
        "SUPABASE_KEY": os.getenv("SUPABASE_KEY", ""),
        "SYNC_ATTENDANCE_URL": os.getenv("SYNC_ATTENDANCE_URL", "").strip(),
        "SYNC_ATTENDANCE_SECRET": os.getenv("SYNC_ATTENDANCE_SECRET", ""),
        "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_WEBHOOK_URL", "").strip(),
    }
    required_names = (
        "ZKBIO_URL",
        "ZKBIO_USERNAME",
        "ZKBIO_PASSWORD",
        "SUPABASE_URL",
        "SUPABASE_KEY",
        "SYNC_ATTENDANCE_SECRET",
    )
    missing = [name for name in required_names if not values[name]]
    if missing:
        missing_names = ", ".join(missing)
        raise ValueError(f"Missing required environment variables: {missing_names}")

    return Settings(
        zkbio_url=values["ZKBIO_URL"].rstrip("/"),
        zkbio_username=values["ZKBIO_USERNAME"],
        zkbio_password=values["ZKBIO_PASSWORD"],
        supabase_url=values["SUPABASE_URL"].rstrip("/"),
        supabase_key=values["SUPABASE_KEY"],
        sync_attendance_url=(
            values["SYNC_ATTENDANCE_URL"].rstrip("/")
            or values["SUPABASE_URL"].rstrip("/")
            + "/functions/v1/sync-attendance"
        ),
        sync_attendance_secret=values["SYNC_ATTENDANCE_SECRET"],
        discord_webhook_url=values["DISCORD_WEBHOOK_URL"],
    )
