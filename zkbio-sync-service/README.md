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

The existing `data/state.json` logic remains active. Attendance is requested
using the last successfully uploaded punch timestamp. The state file advances
only after a full downloaded batch uploads successfully.

The same state file stores non-reversible fingerprints for successfully
uploaded devices and employees. A record is sent to Supabase only when it is
new or its ZKBioTime data changed. If devices, employees, and attendance are
all unchanged, the sync performs no Supabase HTTP requests. A fingerprint is
saved only after its corresponding Supabase upload succeeds.

After a shutdown or PC restart, the next synchronization requests everything
newer than the saved timestamp. Existing Supabase logic checks for the same
device, biometric ID, and punch time before inserting, preventing duplicates
after retries.

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
