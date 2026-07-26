"""Windows integration and reusable desktop helpers."""

from collections.abc import Iterable
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

STARTUP_VALUE_NAME = "ZKBioTime Attendance Sync"
STARTUP_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def application_root() -> Path:
    """Return the writable folder beside the executable or source files."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def prepare_runtime_environment() -> None:
    """Load the external .env and point state storage at the writable root."""
    root = application_root()
    load_dotenv(root / ".env", override=True)

    import state

    state.STATE_FILE = root / "data" / "state.json"


def log_file_path() -> Path:
    return application_root() / "logs" / "sync.log"


def read_recent_logs(max_lines: int = 120) -> str:
    path = log_file_path()
    if not path.exists():
        return "No log messages yet."
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return f"Could not read log file: {error}"
    return "\n".join(lines[-max_lines:])


def open_log_file() -> None:
    path = log_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    raise OSError("Opening files is supported only on Windows")


def create_status_icon(color: str, size: int = 64) -> QIcon:
    """Create a crisp colored status indicator without external assets."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#FFFFFF"))
    painter.setBrush(QColor(color))
    margin = max(4, size // 10)
    painter.drawEllipse(margin, margin, size - margin * 2, size - margin * 2)
    painter.end()
    return QIcon(pixmap)


def _startup_command() -> str:
    root = application_root()
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --background'

    pythonw = Path(sys.executable).resolve().with_name("pythonw.exe")
    launcher = pythonw if pythonw.exists() else Path(sys.executable).resolve()
    return f'"{launcher}" "{root / "app.py"}" --background'


def configure_windows_startup(enabled: bool) -> None:
    if os.name != "nt":
        raise OSError("Windows startup integration is available only on Windows")

    import winreg

    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER,
        STARTUP_REGISTRY_PATH,
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key,
                STARTUP_VALUE_NAME,
                0,
                winreg.REG_SZ,
                _startup_command(),
            )
        else:
            try:
                winreg.DeleteValue(key, STARTUP_VALUE_NAME)
            except FileNotFoundError:
                pass


def nonempty(values: Iterable[str]) -> bool:
    return all(value.strip() for value in values)
