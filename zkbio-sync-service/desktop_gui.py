"""Modern Qt dashboard, settings view, and system tray controller."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from desktop_settings import ConnectionForm, DesktopSettings
from desktop_utils import (
    configure_windows_startup,
    create_status_icon,
    open_log_file,
    read_recent_logs,
)
from sync_worker import SyncWorker

HEARTBEAT_INTERVAL_MILLISECONDS = 5 * 60 * 1000

logger = logging.getLogger(__name__)

GREEN = "#15803D"
YELLOW = "#B45309"
RED = "#DC2626"
SLATE = "#475569"

STYLESHEET = """
QWidget {
    color: #172033;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QMainWindow {
    background: #F4F7FC;
}
QFrame#sidebar {
    background: #10203A;
    border: none;
}
QFrame#sidebar QLabel {
    background: transparent;
}
QLabel#brand {
    color: white;
    font-size: 16pt;
    font-weight: 700;
}
QLabel#brandSub {
    color: #C3CEE0;
}
QLabel#sidebarCredit {
    color: #B5C2D8;
    font-size: 8.5pt;
    line-height: 1.4;
}
QPushButton#navButton {
    color: #F1F5F9;
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 11px 14px;
    text-align: left;
    font-weight: 600;
}
QPushButton#navButton:hover {
    background: #203455;
    color: white;
}
QPushButton#primaryButton {
    color: white;
    background: #1D4ED8;
    border: none;
    border-radius: 8px;
    padding: 10px 18px;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    background: #1E40AF;
}
QPushButton#secondaryButton {
    color: #1E3A5F;
    background: white;
    border: 1px solid #D6DEEA;
    border-radius: 8px;
    padding: 9px 16px;
    font-weight: 600;
}
QPushButton#secondaryButton:hover {
    background: #EDF3FA;
}
QFrame#card {
    background: white;
    border: 1px solid #DFE7F2;
    border-radius: 14px;
}
QFrame#card:hover {
    border: 1px solid #C8D6EA;
}
QFrame#hero {
    background: #EAF2FF;
    border: 1px solid #CFE0FF;
    border-radius: 14px;
}
QLabel#heroTitle {
    color: #173B72;
    font-size: 13pt;
    font-weight: 700;
}
QLabel#heroDetail {
    color: #52709D;
}
QLabel#eyebrow {
    color: #1D4ED8;
    font-size: 8.5pt;
    font-weight: 700;
}
QLabel#pageTitle {
    color: #13213C;
    font-size: 20pt;
    font-weight: 700;
}
QLabel#sectionTitle {
    color: #13213C;
    font-size: 12pt;
    font-weight: 700;
}
QLabel#statusValue {
    font-size: 14pt;
    font-weight: 700;
}
QLineEdit, QSpinBox {
    background: white;
    border: 1px solid #CBD5E1;
    border-radius: 7px;
    padding: 8px;
    min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus {
    border: 1px solid #2563EB;
}
QPlainTextEdit {
    background: #0F172A;
    color: #D7E1F2;
    border: none;
    border-radius: 8px;
    padding: 8px;
    font-family: "Cascadia Mono", "Consolas";
    font-size: 9pt;
}
QLabel {
    background: transparent;
}
QStatusBar {
    background: white;
    color: #52627A;
    border-top: 1px solid #E2E8F0;
}
"""


class StatusCard(QFrame):
    def __init__(self, title: str, value: str, color: str = SLATE) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setMinimumHeight(96)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(17, 14, 17, 15)
        layout.setSpacing(7)
        self.accent = QFrame()
        self.accent.setFixedHeight(3)
        self.accent.setStyleSheet(
            f"background: {color}; border: none; border-radius: 1px;"
        )
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #64748B; font-weight: 600;")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("statusValue")
        self.value_label.setStyleSheet(f"color: {color};")
        layout.addWidget(self.accent)
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str, color: str = SLATE) -> None:
        self.value_label.setText(value)
        self.value_label.setStyleSheet(f"color: {color};")
        self.accent.setStyleSheet(
            f"background: {color}; border: none; border-radius: 1px;"
        )


class MainWindow(QMainWindow):
    """Main dashboard and controller for the tray-first desktop app."""

    discord_test_finished = Signal(bool, str)

    def __init__(self, settings: DesktopSettings) -> None:
        super().__init__()
        self.settings = settings
        self.worker = SyncWorker(self)
        self.allow_exit = False
        self.pending_exit = False
        self._stopped_reported = False
        self._heartbeat_lock = threading.Lock()
        self._discord_notification_lock = threading.Lock()

        self.setWindowTitle("School Attendance Sync")
        self.setMinimumSize(940, 650)
        self.resize(1080, 720)
        self.setStyleSheet(STYLESHEET)

        self.icons = {
            "idle": create_status_icon(GREEN),
            "syncing": create_status_icon(YELLOW),
            "error": create_status_icon(RED),
        }
        self.setWindowIcon(self.icons["idle"])

        self.pages = QStackedWidget()
        self.dashboard_page = self._build_dashboard()
        self.settings_page = self._build_settings()
        self.about_page = self._build_about()
        self.pages.addWidget(self.dashboard_page)
        self.pages.addWidget(self.settings_page)
        self.pages.addWidget(self.about_page)
        self.setCentralWidget(self._build_shell())

        self.tray = self._build_tray()
        self.tray.show()

        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.request_sync)
        self.apply_sync_interval()
        self.sync_timer.start()

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.refresh_logs)
        self.log_timer.start(2000)

        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self.request_heartbeat)
        self.heartbeat_timer.start(HEARTBEAT_INTERVAL_MILLISECONDS)

        self.worker.sync_started.connect(self.on_sync_started)
        self.worker.sync_progress.connect(self.on_sync_progress)
        self.worker.sync_succeeded.connect(self.on_sync_succeeded)
        self.worker.sync_failed.connect(self.on_sync_failed)
        self.worker.finished.connect(self.on_worker_finished)
        self.discord_test_finished.connect(self.on_discord_test_finished)

        self.refresh_settings_form()
        self.refresh_logs()
        QTimer.singleShot(100, self.request_heartbeat)
        QTimer.singleShot(300, self.notify_app_started)
        QTimer.singleShot(700, self.request_sync)

    def _build_shell(self) -> QWidget:
        shell = QWidget()
        layout = QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(18, 24, 18, 18)

        brand = QLabel("Attendance Sync")
        brand.setObjectName("brand")
        brand_sub = QLabel("School integration service")
        brand_sub.setObjectName("brandSub")
        side_layout.addWidget(brand)
        side_layout.addWidget(brand_sub)
        side_layout.addSpacing(28)

        for title, index in (
            ("Dashboard", 0),
            ("Settings", 1),
            ("About", 2),
        ):
            button = QPushButton(title)
            button.setObjectName("navButton")
            button.clicked.connect(
                lambda _checked=False, page_index=index: self.show_page(page_index)
            )
            side_layout.addWidget(button)

        side_layout.addStretch()
        credit = QLabel("Made by Zakwan\nFor issues: 01795111957")
        credit.setObjectName("sidebarCredit")
        side_layout.addWidget(credit)
        side_layout.addSpacing(12)
        version = QLabel("Desktop Service - v1.1")
        version.setObjectName("brandSub")
        side_layout.addWidget(version)

        content = QFrame()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 24, 28, 24)
        content_layout.addWidget(self.pages)
        footer = QLabel("Made by Zakwan  |  For issues, contact: 01795111957")
        footer.setStyleSheet("color: #8290A5; font-size: 8.5pt;")
        footer.setAlignment(Qt.AlignmentFlag.AlignRight)
        content_layout.addWidget(footer)

        layout.addWidget(sidebar)
        layout.addWidget(content, 1)
        return shell

    def _build_dashboard(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("Synchronization Dashboard")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Live status for ZKBioTime and Supabase")
        subtitle.setStyleSheet("color: #64748B;")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        sync_button = QPushButton("Sync Now")
        sync_button.setObjectName("primaryButton")
        sync_button.clicked.connect(self.request_sync)
        header.addLayout(title_block)
        header.addStretch()
        header.addWidget(sync_button)
        layout.addLayout(header)

        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(18, 15, 18, 15)
        hero_text = QVBoxLayout()
        hero_text.setSpacing(3)
        eyebrow = QLabel("BACKGROUND SERVICE")
        eyebrow.setObjectName("eyebrow")
        self.service_state_label = QLabel("Starting service")
        self.service_state_label.setObjectName("heroTitle")
        self.service_detail_label = QLabel(
            "Preparing the first synchronization and Supabase heartbeat."
        )
        self.service_detail_label.setObjectName("heroDetail")
        hero_text.addWidget(eyebrow)
        hero_text.addWidget(self.service_state_label)
        hero_text.addWidget(self.service_detail_label)
        hero_layout.addLayout(hero_text)
        hero_layout.addStretch()
        layout.addWidget(hero)

        cards = QGridLayout()
        cards.setSpacing(12)
        self.zkbio_card = StatusCard("ZKBioTime", "Waiting")
        self.supabase_card = StatusCard("Supabase", "Waiting")
        self.last_sync_card = StatusCard(
            "Last successful sync",
            self.settings.last_successful_sync,
        )
        self.interval_card = StatusCard(
            "Sync interval",
            f"{self.settings.sync_interval} seconds",
            "#1D4ED8",
        )
        cards.addWidget(self.zkbio_card, 0, 0)
        cards.addWidget(self.supabase_card, 0, 1)
        cards.addWidget(self.last_sync_card, 1, 0)
        cards.addWidget(self.interval_card, 1, 1)
        layout.addLayout(cards)

        logs_header = QHBoxLayout()
        logs_title = QLabel("Recent Logs")
        logs_title.setObjectName("sectionTitle")
        view_button = QPushButton("Open log file")
        view_button.setObjectName("secondaryButton")
        view_button.clicked.connect(self.view_logs)
        logs_header.addWidget(logs_title)
        logs_header.addStretch()
        logs_header.addWidget(view_button)
        layout.addLayout(logs_header)

        self.logs_view = QPlainTextEdit()
        self.logs_view.setReadOnly(True)
        layout.addWidget(self.logs_view, 1)
        return page

    def _build_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Connection details and desktop preferences")
        subtitle.setStyleSheet("color: #64748B;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("card")
        form = QFormLayout(card)
        form.setContentsMargins(22, 20, 22, 20)
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(12)

        self.zkbio_url_input = QLineEdit()
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.supabase_url_input = QLineEdit()
        self.supabase_key_input = QLineEdit()
        self.supabase_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.discord_webhook_input = QLineEdit()
        self.discord_webhook_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.discord_webhook_input.setPlaceholderText(
            "Optional Discord incoming webhook URL"
        )
        self.interval_input = QSpinBox()
        self.interval_input.setRange(15, 86400)
        self.interval_input.setSuffix(" seconds")
        self.startup_checkbox = QCheckBox("Launch automatically after Windows login")
        self.minimized_checkbox = QCheckBox("Start minimized to the system tray")
        self.notifications_checkbox = QCheckBox("Show Windows notifications")

        form.addRow("ZKBioTime URL", self.zkbio_url_input)
        form.addRow("Username", self.username_input)
        form.addRow("Password", self.password_input)
        form.addRow("Supabase URL", self.supabase_url_input)
        form.addRow("Supabase key", self.supabase_key_input)
        form.addRow("Discord webhook", self.discord_webhook_input)
        form.addRow("Sync interval", self.interval_input)
        form.addRow("", self.startup_checkbox)
        form.addRow("", self.minimized_checkbox)
        form.addRow("", self.notifications_checkbox)
        layout.addWidget(card)

        actions = QHBoxLayout()
        save_button = QPushButton("Save Settings")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self.save_settings)
        reload_button = QPushButton("Reload")
        reload_button.setObjectName("secondaryButton")
        reload_button.clicked.connect(self.refresh_settings_form)
        self.test_discord_button = QPushButton("Test Discord")
        self.test_discord_button.setObjectName("secondaryButton")
        self.test_discord_button.clicked.connect(self.test_discord_webhook)
        actions.addStretch()
        actions.addWidget(self.test_discord_button)
        actions.addWidget(reload_button)
        actions.addWidget(save_button)
        layout.addLayout(actions)
        layout.addStretch()
        return page

    def _build_about(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("About")
        title.setObjectName("pageTitle")
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        heading = QLabel("School Attendance Synchronization")
        heading.setObjectName("sectionTitle")
        description = QLabel(
            "A lightweight Windows tray application that synchronizes "
            "ZKBioTime devices, students, and attendance records with Supabase."
        )
        description.setWordWrap(True)
        detail = QLabel(
            "The desktop interface calls the existing synchronization flow "
            "without changing its business logic."
        )
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #64748B;")
        card_layout.addWidget(heading)
        card_layout.addSpacing(8)
        card_layout.addWidget(description)
        card_layout.addWidget(detail)

        developer_card = QFrame()
        developer_card.setObjectName("card")
        developer_layout = QVBoxLayout(developer_card)
        developer_layout.setContentsMargins(24, 22, 24, 22)
        developer_layout.setSpacing(7)
        developer_eyebrow = QLabel("DEVELOPER & SUPPORT")
        developer_eyebrow.setObjectName("eyebrow")
        developer_name = QLabel("Made by Zakwan")
        developer_name.setObjectName("sectionTitle")
        developer_contact = QLabel("For issues, contact: 01795111957")
        developer_contact.setStyleSheet("color: #52627A; font-size: 11pt;")
        developer_contact.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        developer_layout.addWidget(developer_eyebrow)
        developer_layout.addWidget(developer_name)
        developer_layout.addWidget(developer_contact)

        layout.addWidget(title)
        layout.addSpacing(16)
        layout.addWidget(card)
        layout.addSpacing(12)
        layout.addWidget(developer_card)
        layout.addStretch()
        return page

    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(self.icons["idle"], self)
        tray.setToolTip("Attendance Sync • Connected/Idle")

        menu = QMenu()
        sync_action = QAction("Sync Now", self)
        sync_action.triggered.connect(self.request_sync)
        dashboard_action = QAction("Dashboard", self)
        dashboard_action.triggered.connect(lambda: self.show_page(0, reveal=True))
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(lambda: self.show_page(1, reveal=True))
        logs_action = QAction("View Logs", self)
        logs_action.triggered.connect(self.view_logs)
        about_action = QAction("About", self)
        about_action.triggered.connect(lambda: self.show_page(2, reveal=True))
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.exit_application)

        menu.addAction(sync_action)
        menu.addSeparator()
        menu.addAction(dashboard_action)
        menu.addAction(settings_action)
        menu.addAction(logs_action)
        menu.addAction(about_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(self.on_tray_activated)
        return tray

    def show_page(self, index: int, reveal: bool = False) -> None:
        self.pages.setCurrentIndex(index)
        if reveal:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def on_tray_activated(
        self,
        reason: QSystemTrayIcon.ActivationReason,
    ) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_page(0, reveal=True)

    def apply_sync_interval(self) -> None:
        interval = self.settings.sync_interval
        self.sync_timer.setInterval(interval * 1000)
        if hasattr(self, "interval_card"):
            self.interval_card.set_value(f"{interval} seconds", "#1D4ED8")

    def request_sync(self) -> None:
        if self.worker.isRunning():
            self.statusBar().showMessage(
                "A synchronization is already running.",
                4000,
            )
            return
        self.worker.start()

    def request_heartbeat(self) -> None:
        """Publish a heartbeat without blocking the Qt interface."""
        if self._stopped_reported:
            return
        if not self._heartbeat_lock.acquire(blocking=False):
            return
        threading.Thread(
            target=self._publish_heartbeat,
            name="supabase-heartbeat",
            daemon=True,
        ).start()

    def _publish_heartbeat(self) -> None:
        connections = None
        try:
            from config import load_settings
            from service_status import publish_heartbeat

            connections = load_settings()
            publish_heartbeat(
                connections.supabase_url,
                connections.supabase_key,
            )
        except Exception as error:
            logger.warning("Could not publish executable heartbeat: %s", error)
            if connections is not None:
                from biotime_recovery import (
                    DISCORD_ALERT_COOLDOWN_SECONDS,
                    send_discord_event,
                )

                safe_error = f"{type(error).__name__}: {error}"
                for secret in (
                    connections.supabase_key,
                    connections.discord_webhook_url,
                ):
                    if secret:
                        safe_error = safe_error.replace(secret, "[REDACTED]")
                send_discord_event(
                    connections.discord_webhook_url,
                    "Supabase heartbeat failed",
                    safe_error,
                    color=15548997,
                    cooldown_key="heartbeat_failed",
                    cooldown_seconds=DISCORD_ALERT_COOLDOWN_SECONDS,
                )
        finally:
            self._heartbeat_lock.release()

    def report_stopped(self) -> None:
        """Tell Supabase immediately when the application exits normally."""
        if self._stopped_reported:
            return
        self._stopped_reported = True
        # Wait for any in-flight heartbeat so it cannot overwrite the offline
        # state after this final request completes.
        with self._heartbeat_lock, self._discord_notification_lock:
            try:
                from config import load_settings

                connections = load_settings()
            except Exception as error:
                logger.warning("Could not load shutdown settings: %s", error)
                return

            try:
                from service_status import publish_stopped

                publish_stopped(
                    connections.supabase_url,
                    connections.supabase_key,
                )
            except Exception as error:
                logger.warning("Could not publish executable shutdown: %s", error)

            try:
                from biotime_recovery import send_discord_event

                _sent, result = send_discord_event(
                    connections.discord_webhook_url,
                    "Attendance Sync application stopped",
                    "The application closed normally and is now offline.",
                    color=9807270,
                )
                logger.info(
                    "Application shutdown Discord notification: %s",
                    result,
                )
            except Exception as error:
                logger.warning("Could not send shutdown notification: %s", error)

    def notify_app_started(self) -> None:
        """Send one non-blocking application startup notification."""
        threading.Thread(
            target=self._notify_app_started,
            name="discord-startup-notification",
            daemon=True,
        ).start()

    def _notify_app_started(self) -> None:
        with self._discord_notification_lock:
            try:
                from biotime_recovery import send_discord_event
                from config import load_settings

                connections = load_settings()
                _sent, result = send_discord_event(
                    connections.discord_webhook_url,
                    "Attendance Sync application started",
                    (
                        "The application is online and will begin monitoring "
                        "BioTime and synchronizing attendance."
                    ),
                    color=3447003,
                )
                logger.info(
                    "Application startup Discord notification: %s",
                    result,
                )
            except Exception as error:
                logger.warning(
                    "Could not send application startup notification: %s",
                    error,
                )

    def on_sync_started(self) -> None:
        self.set_status_icon("syncing")
        self.service_state_label.setText("Synchronization in progress")
        self.service_detail_label.setText(
            "Downloading the latest device, student, and attendance data."
        )
        self.zkbio_card.set_value("Synchronizing", YELLOW)
        self.supabase_card.set_value("Synchronizing", YELLOW)
        self.statusBar().showMessage("Synchronization in progress…")
        logger.info("Desktop synchronization started")

    def on_sync_progress(self, title: str, detail: str, level: str) -> None:
        """Show live API checks and service-recovery actions."""
        colors = {
            "working": YELLOW,
            "success": GREEN,
            "error": RED,
        }
        color = colors.get(level, YELLOW)
        self.service_state_label.setText(title)
        self.service_detail_label.setText(detail)
        self.zkbio_card.set_value(title, color)
        self.statusBar().showMessage(f"{title}: {detail}")
        self.refresh_logs()

    def on_sync_succeeded(self, completed_at: str) -> None:
        self.settings.last_successful_sync = completed_at
        self.last_sync_card.set_value(completed_at, GREEN)
        self.zkbio_card.set_value("Connected", GREEN)
        self.supabase_card.set_value("Connected", GREEN)
        self.set_status_icon("idle")
        self.service_state_label.setText("Service is running normally")
        self.service_detail_label.setText(
            f"Last successful synchronization: {completed_at}"
        )
        self.statusBar().showMessage("Synchronization completed successfully.", 5000)
        self.refresh_logs()
        if self.settings.notifications_enabled:
            self.tray.showMessage(
                "Attendance Sync",
                "Synchronization completed successfully.",
                self.icons["idle"],
                5000,
            )

    def on_sync_failed(self, message: str) -> None:
        self.zkbio_card.set_value("Error", RED)
        self.supabase_card.set_value("Error", RED)
        self.set_status_icon("error")
        self.service_state_label.setText("Synchronization needs attention")
        self.service_detail_label.setText(
            "The service is still running and will retry automatically."
        )
        self.statusBar().showMessage(f"Synchronization failed: {message}", 8000)
        self.refresh_logs()
        if self.settings.notifications_enabled:
            self.tray.showMessage(
                "Attendance Sync Error",
                message,
                self.icons["error"],
                8000,
            )

    def on_worker_finished(self) -> None:
        if self.pending_exit:
            self.allow_exit = True
            self.tray.hide()
            QApplication.instance().quit()

    def set_status_icon(self, state: str) -> None:
        icon = self.icons[state]
        self.tray.setIcon(icon)
        self.setWindowIcon(icon)
        tooltip = {
            "idle": "Attendance Sync • Connected/Idle",
            "syncing": "Attendance Sync • Synchronizing",
            "error": "Attendance Sync • Error",
        }[state]
        self.tray.setToolTip(tooltip)

    def refresh_logs(self) -> None:
        text = read_recent_logs()
        if text != self.logs_view.toPlainText():
            self.logs_view.setPlainText(text)
            scrollbar = self.logs_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def refresh_settings_form(self) -> None:
        connections = self.settings.load_connections()
        self.zkbio_url_input.setText(connections.zkbio_url)
        self.username_input.setText(connections.zkbio_username)
        self.password_input.setText(connections.zkbio_password)
        self.supabase_url_input.setText(connections.supabase_url)
        self.supabase_key_input.setText(connections.supabase_key)
        self.discord_webhook_input.setText(connections.discord_webhook_url)
        self.interval_input.setValue(self.settings.sync_interval)
        self.startup_checkbox.setChecked(self.settings.start_with_windows)
        self.minimized_checkbox.setChecked(self.settings.start_minimized)
        self.notifications_checkbox.setChecked(
            self.settings.notifications_enabled
        )

    def save_settings(self) -> None:
        form = ConnectionForm(
            zkbio_url=self.zkbio_url_input.text(),
            zkbio_username=self.username_input.text(),
            zkbio_password=self.password_input.text(),
            supabase_url=self.supabase_url_input.text(),
            supabase_key=self.supabase_key_input.text(),
            discord_webhook_url=self.discord_webhook_input.text(),
        )
        try:
            self.settings.save_connections(form)
            self.settings.sync_interval = self.interval_input.value()
            self.settings.start_minimized = self.minimized_checkbox.isChecked()
            self.settings.notifications_enabled = (
                self.notifications_checkbox.isChecked()
            )
            configure_windows_startup(self.startup_checkbox.isChecked())
            self.settings.start_with_windows = self.startup_checkbox.isChecked()
            self.settings.settings.sync()
        except Exception as error:
            logger.error("Could not save desktop settings: %s", error)
            QMessageBox.critical(
                self,
                "Could not save settings",
                str(error),
            )
            return

        self.apply_sync_interval()
        QMessageBox.information(
            self,
            "Settings saved",
            "Your settings were saved successfully.",
        )

    def test_discord_webhook(self) -> None:
        """Send a test webhook without blocking the Qt interface."""
        webhook_url = self.discord_webhook_input.text().strip()
        if not webhook_url:
            QMessageBox.warning(
                self,
                "Discord webhook",
                "Enter a Discord webhook URL first.",
            )
            return

        self.test_discord_button.setEnabled(False)
        self.statusBar().showMessage("Sending Discord test notification…")

        def send_test() -> None:
            from biotime_recovery import send_discord_test

            succeeded, message = send_discord_test(webhook_url)
            self.discord_test_finished.emit(succeeded, message)

        threading.Thread(
            target=send_test,
            name="discord-webhook-test",
            daemon=True,
        ).start()

    def on_discord_test_finished(self, succeeded: bool, message: str) -> None:
        self.test_discord_button.setEnabled(True)
        self.statusBar().showMessage(message, 6000)
        if succeeded:
            QMessageBox.information(self, "Discord webhook", message)
        else:
            QMessageBox.warning(self, "Discord webhook", message)

    def view_logs(self) -> None:
        try:
            open_log_file()
        except Exception as error:
            logger.error("Could not open log file: %s", error)
            QMessageBox.warning(self, "Log file", str(error))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.allow_exit:
            event.accept()
            return

        if not self.settings.close_notice_shown:
            result = QMessageBox.question(
                self,
                "Keep synchronization running?",
                "Closing this window will minimize Attendance Sync to the "
                "system tray. Synchronization will continue in the background.",
                QMessageBox.StandardButton.Ok
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Ok,
            )
            if result != QMessageBox.StandardButton.Ok:
                event.ignore()
                return
            self.settings.close_notice_shown = True

        event.ignore()
        self.hide()
        if self.settings.notifications_enabled:
            self.tray.showMessage(
                "Attendance Sync is still running",
                "Use the tray icon to reopen the dashboard or exit.",
                self.icons["idle"],
                5000,
            )

    def exit_application(self) -> None:
        self.sync_timer.stop()
        self.log_timer.stop()
        self.heartbeat_timer.stop()
        if self.worker.isRunning():
            self.pending_exit = True
            self.hide()
            self.tray.showMessage(
                "Attendance Sync",
                "Waiting for the current synchronization to finish before exiting.",
                self.icons["syncing"],
                5000,
            )
            return

        self.allow_exit = True
        self.tray.hide()
        QApplication.instance().quit()
