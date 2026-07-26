# ZKBio Sync Service

The same single-worker scheduler can run with a Tkinter monitoring panel or
silently in the Windows background. `main.py` remains available for a one-time
manual synchronization.


## Background schedules

When the worker starts, it loads configuration, authenticates once, performs
one employee sync, and then performs one attendance sync. It continues with:

- Attendance: every 30 seconds.
- Employees: every 6 hours.
- Manual sync commands: handled by the same worker after the active job.

There is only one synchronization worker, and per-job locks provide an
additional guard against overlapping employee or attendance jobs.

## Attendance recovery and duplicate prevention

`data/state.json` records the newest attendance timestamp whose full downloaded
batch was uploaded successfully:

```json
{
    "last_sync_time": "2026-07-26 10:30:00"
}
```

Every attendance request passes this value as `start_time` and follows all API
pagination links. The state file is not advanced if any upload fails.

After a shutdown or PC restart, the previous timestamp is loaded and all missed
transactions are requested. Attendance is stored in `device_logs`; before an
insert, the service checks for the same device, biometric ID, and punch time.
This makes inclusive timestamp queries and failed-batch retries safe.

## Employee synchronization

All ZKBioTime employees are downloaded with pagination and mapped to
`students`. `emp_code` becomes both `admission_number` and `biometric_id`, and
the upsert uses the unique `admission_number` column.

## JWT behavior

One `ZKBioClient` instance and its in-memory JWT are reused for the lifetime of
the worker. A token is not requested on each scheduled run. If an API request
returns HTTP 401, the existing authentication module obtains a new JWT and
retries that failed request once.

Passwords, JWTs, authorization headers, and Supabase keys are never written to
logs.

## Reliability

Network errors, unavailable services, timeouts, temporary API errors, invalid
JSON, and Supabase failures are caught by the scheduler. The failed job is
retried after:

```text
1, 2, 4, 8, 16, 32, 60, 60, ... seconds
```

A successful run resets that job's delay to one second. Failures do not
terminate the background process. Existing API calls use request timeouts, and
all waits are interruptible through `threading.Event`.

## Run with the Tkinter panel

```powershell
.\.venv\Scripts\python.exe app.py
```

The worker starts automatically. The panel displays service, ZKBioTime, and
Supabase status; last employee and attendance times; uploaded attendance
count; last error; and recent logs.

Available controls:

- Start or stop synchronization.
- Request an employee or attendance sync now.
- Open the log file.
- Minimize the window while synchronization continues.
- Exit gracefully after the current synchronization finishes.

No network request runs on Tkinter's main thread. The UI communicates with the
background scheduler using thread-safe queues and polls updates with
`root.after()`.

If `app.py` reports that Tkinter is unavailable, modify or reinstall the
official Windows Python 3.12 distribution and enable the **Tcl/Tk and IDLE**
optional feature. Recreate `.venv` afterward. Tkinter is part of Python and
should not be installed from `pip`.

## Run silently

For a visible console test:

```powershell
.\.venv\Scripts\python.exe service.py
```

Press `Ctrl+C` to request a graceful shutdown. The current sync finishes before
the worker stops and log handlers are flushed.

For normal silent background execution:

```powershell
.\.venv\Scripts\pythonw.exe service.py
```

Logs remain available at `logs/sync.log`.

## Windows Task Scheduler

1. Open **Task Scheduler** and choose **Create Task**.
2. On **General**:
   - Select **Run whether user is logged on or not**.
   - Select **Run with highest privileges**.
3. On **Triggers**, create **At startup**.
4. On **Actions**, choose **Start a program**:
   - Program:
     `C:\Users\USER\Desktop\zkteco backend service\zkbio-sync-service\.venv\Scripts\pythonw.exe`
   - Arguments:
     `"C:\Users\USER\Desktop\zkteco backend service\zkbio-sync-service\service.py"`
   - Start in:
     `C:\Users\USER\Desktop\zkteco backend service\zkbio-sync-service`
5. On **Settings**:
   - Enable **If the task fails, restart every 1 minute**.
   - Choose an appropriate number of restart attempts.
   - Enable **Run task as soon as possible after a scheduled start is missed**.
6. Save the task and provide the Windows account password if requested.

Use Task Scheduler's **End** command to stop a silent scheduled process. An
ended process may not receive a graceful signal, but attendance state is only
committed after a complete upload, so the next startup safely retries any
unfinished range. For a guaranteed graceful stop, run `service.py` with
`python.exe` and press `Ctrl+C`, or use **Exit** in `app.py`.

## Logging

Logs are sent to both the console and:

```text
logs/sync.log
```

`RotatingFileHandler` limits each file to 5 MB and keeps five backups:
`sync.log.1` through `sync.log.5`.

## Duplicate process protection

`app.py` and `service.py` acquire the same global Windows named mutex. If
either mode is already active, a second process logs:

```text
Background sync is already running
```

and exits without starting another worker.

## One-time synchronization

The existing milestone flow is still available:

```powershell
.\.venv\Scripts\python.exe main.py
```

This performs one complete synchronization and exits.
