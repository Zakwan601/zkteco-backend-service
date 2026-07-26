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


def load_settings() -> Settings:
    """Load and validate the ZKBioTime connection settings."""
    load_dotenv()

    values = {
        "ZKBIO_URL": os.getenv("ZKBIO_URL", "").strip(),
        "ZKBIO_USERNAME": os.getenv("ZKBIO_USERNAME", "").strip(),
        "ZKBIO_PASSWORD": os.getenv("ZKBIO_PASSWORD", ""),
        "SUPABASE_URL": os.getenv("SUPABASE_URL", "").strip(),
        "SUPABASE_KEY": os.getenv("SUPABASE_KEY", ""),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        missing_names = ", ".join(missing)
        raise ValueError(f"Missing required environment variables: {missing_names}")

    return Settings(
        zkbio_url=values["ZKBIO_URL"].rstrip("/"),
        zkbio_username=values["ZKBIO_USERNAME"],
        zkbio_password=values["ZKBIO_PASSWORD"],
        supabase_url=values["SUPABASE_URL"].rstrip("/"),
        supabase_key=values["SUPABASE_KEY"],
    )
