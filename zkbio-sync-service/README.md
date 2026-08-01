# ZKBioTime Attendance Sync

A Windows desktop and system-tray application that runs the
ZKBioTime-to-Supabase synchronization in a background worker.

```text
ZKBioTime → existing main.main() sync → Supabase
```

The desktop interface is intended for non-technical school administrators. It
starts in the Windows notification area, runs synchronization on a background
Qt thread, displays connection and log information, and can launch
automatically with Windows.

## Project structure

```text
app.py                    PySide6 desktop entry point
qt_app.py                 Qt application bootstrap and single-instance guard
desktop_gui.py            Dashboard, settings, tray icon, and controller
desktop_settings.py       QSettings and .env persistence
desktop_utils.py          Windows startup, icons, logs, and runtime paths
sync_worker.py             QThread wrapper around existing main.main()
main.py                   Existing one-time synchronization (unchanged)
service.py                Existing silent scheduler mode
scheduler.py              Existing background scheduler
auth.py                   ZKBioTime JWT client
employees.py              Employee API and pagination
attendance.py             Attendance API and pagination
terminals.py              Terminal API
supabase_client.py         Supabase mappings and upserts
state.py                  Incremental attendance state
logger.py                 Console and rotating-file logging
logs/sync.log             Runtime log
ZKBioSyncService.spec     PyInstaller one-file build
build_exe.bat             Windows build command
```

## Install

Use Python 3.12 or newer. In Command Prompt:

```bat
cd /d "C:\Users\USER\Desktop\zkteco backend service\zkbio-sync-service"
set PYTHONHOME=

py -3.12 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install --no-cache-dir -r requirements.txt
```

`PYTHONHOME` is cleared because the ZKBioTime installation may set it to its
embedded Python 3.11 runtime, which is incompatible with this Python 3.12
virtual environment.

## Configuration

The application reads `.env` beside the source files or packaged executable:

```env
ZKBIO_URL=http://127.0.0.1:78
ZKBIO_USERNAME=your_username
ZKBIO_PASSWORD=your_password
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_server_side_key
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/webhook_id/webhook_token
```

These values can also be edited from the desktop Settings page. Secrets remain
in `.env`, which is excluded by `.gitignore`.

## Run the desktop application

```bat
set PYTHONHOME=
.venv\Scripts\activate.bat
python app.py
```

The application starts minimized to the system tray by default and performs an
initial synchronization. It then synchronizes every 60 seconds. The interval
is configurable from 15 seconds to 24 hours.

The tray icon indicates:

- Green: connected/idle
- Yellow: synchronization in progress
- Red: the latest synchronization failed

Right-click the tray icon for:

- Sync Now
- Dashboard
- Settings
- View Logs
- About
- Exit

Closing the window hides it in the tray instead of terminating it. A notice is
shown the first time. Use **Exit** from the tray or application to stop it.
When a sync is active, Exit waits for `main.main()` to finish.

## Dashboard

The dashboard displays:

- ZKBioTime status
- Supabase status
- Last successful desktop synchronization
- Current synchronization interval
- Recent messages from `logs/sync.log`

The interface never performs API work on the Qt main thread.
`SyncWorker(QThread)` imports and calls the existing `main.main()` function.
If a scheduled run is still active, an overlapping run is skipped.

## BioTime API recovery

Before each synchronization, the application calls the BioTime JWT login
endpoint. If the endpoint is unavailable, it checks these BioTime services in
dependency order:

```text
bio-pgsql
bio-redis
bio-cache
bio-server
bio-monitor
bio-proxy
bio-apache0
```

Only stopped BioTime services are started. If every service is already running
but the API is unavailable, only `bio-server` is restarted. The application
waits 15 seconds, tests the API again, and sends a Discord alert if it is still
unavailable. Every check, service action, wait, retry, and notification result
appears immediately in the dashboard banner, status bar, and log.

The executable requests Administrator permission because Windows service
control requires elevation. TCP/IP NetBIOS Helper and Windows Biometric Service
are not automatically changed because they are Windows components rather than
BioTime application services.

## Discord alerts

This integration uses a Discord incoming webhook, so it does not require a bot
or a continuously connected Discord client.

1. Open the destination channel in Discord.
2. Open **Edit Channel**, then **Integrations** and **Webhooks**.
3. Select **New Webhook**, choose its name/channel, and copy its webhook URL.
4. Open this application's **Settings** page and paste the URL into
   **Discord webhook**. Save the settings.
5. Select **Test Discord** and confirm that the test message appears in the
   selected channel.

Treat the webhook URL like a password. Anyone who has it can post into that
channel. Failed-recovery alerts are limited to one message every 30 minutes to
prevent repeated notifications.

Discord receives these important events:

- Application started
- Application closed normally
- Synchronization failed
- BioTime recovery succeeded after service intervention
- BioTime recovery failed after the API retest

Routine successful synchronization runs are not posted. Repeated sync failures
and recovery-success messages use a 30-minute cooldown to avoid channel spam.

## Frontend service status

Run `supabase_service_status.sql` once in the Supabase SQL editor. The desktop
executable then publishes a heartbeat every five minutes and records the start,
success, or failure of each complete synchronization.
Startup sets the service online immediately, and a normal application or
service shutdown sets it offline immediately.

Read the computed view from the frontend:

```javascript
const { data, error } = await supabase
  .from('sync_service_health')
  .select('*')
  .eq('service_key', 'zkbio-sync-service')
  .single()
```

Use `data.is_running` for the executable state and `data.last_sync_at` for the
last successful sync. `is_running` automatically becomes false when no
heartbeat has arrived for 10 minutes, including after a crash or PC shutdown.
The timeout is a fallback for forced termination and power loss, when the
executable has no opportunity to send its immediate offline update.

## Settings

The Settings page supports:

- ZKBioTime URL, username, and password
- Supabase URL and key
- Synchronization interval
- Launch after Windows login
- Start minimized
- Windows notifications

The Windows startup option writes a per-user entry under:

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
```

It can be disabled again from the same Settings page.

## Attendance recovery and duplicate prevention

The existing `data/state.json` logic remains active. Attendance requests use a
24-hour overlap before the last successfully uploaded punch timestamp. This
catches transactions that BioTime uploads late or records with a back-dated
device clock. Existing Supabase duplicate checks make the overlap safe, and the
state cursor never moves backward.

The same state file stores non-reversible fingerprints for successfully
uploaded devices and employees. A record is sent to Supabase only when it is
new or its ZKBioTime data changed. If devices, employees, and attendance are
all unchanged, the sync performs no Supabase HTTP requests. A fingerprint is
saved only after its corresponding Supabase upload succeeds.

After a shutdown or PC restart, the next synchronization requests everything
newer than the saved timestamp. Existing Supabase logic checks for the same
device, biometric ID, and punch time before inserting, preventing duplicates
after retries.

## Daily attendance generation

After one or more new punch rows are inserted, the service calls the Supabase
`sync-attendance` Edge Function once for every affected `Asia/Dhaka` date. It
also calls the function for the current Dhaka date at application startup and
when the local date changes. Successful duplicate checks do not trigger extra
calls.

Set the shared function secret in `.env`:

```text
SYNC_ATTENDANCE_SECRET=your_sync_attendance_edge_function_secret
```

The endpoint defaults to
`SUPABASE_URL/functions/v1/sync-attendance`. It can be overridden with
`SYNC_ATTENDANCE_URL`. Dates awaiting recalculation are saved in
`data/state.json`, so a failed function request is logged and retried on the
next synchronization interval without losing the newly inserted punches.

## JWT behavior

The existing ZKBioTime client handles JWT authentication and one retry after
HTTP 401. Because each `main.main()` call creates its own one-time sync client,
the desktop wrapper does not inspect, display, or log JWTs.

## Logging

Logs are written to:

```text
logs\sync.log
```

The log rotates at 5 MB and retains five backup files. The packaged executable
creates its `logs` and `data` folders beside the executable so state and logs
remain persistent.

Passwords, JWTs, authorization headers, and Supabase keys must never be added
to log messages.

## Build a single Windows executable

After installing requirements:

```bat
cd /d "C:\Users\USER\Desktop\zkteco backend service\zkbio-sync-service"
set PYTHONHOME=
build_exe.bat
```

Or invoke PyInstaller directly:

```bat
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean ZKBioSyncService.spec
```

The output is:

```text
dist\ZKBioSyncService.exe
```

The build is a single windowed executable. Place `.env` beside it, or open the
tray Settings page and save the connection values. The application creates
`data\state.json` and `logs\sync.log` beside the executable as needed.

## Existing run modes

The original one-time synchronization remains available:

```bat
python main.py
```

The existing non-GUI scheduler remains available:

```bat
python service.py
```
