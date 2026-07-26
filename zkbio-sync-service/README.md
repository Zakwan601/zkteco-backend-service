# ZKBio Sync Service

This Python 3.12+ service performs one complete synchronization from ZKBioTime
to Supabase and then exits. It does not contain a scheduler.

## What each run does

1. Authenticates with ZKBioTime using JWT.
2. Downloads every terminal and upserts each one into Supabase.
3. Downloads every employee and upserts each one into Supabase.
4. Reads the last attendance sync timestamp from `data/state.json`.
5. Downloads attendance starting at that timestamp.
6. Upserts each downloaded attendance record into Supabase.
7. Saves the newest successfully uploaded attendance timestamp.
8. Exits.

## Configuration

Create and activate a virtual environment, then install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and provide the connection details:

```env
ZKBIO_URL=https://your-zkbiotime-server.example.com
ZKBIO_USERNAME=your_username
ZKBIO_PASSWORD=your_password
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_key
```

Use a server-side Supabase `service_role`/secret key. The schema enables RLS,
and an anonymous/publishable key cannot perform this background sync. Never
expose the server-side key in a browser or commit `.env`.

## Employee synchronization

Every run downloads all employees from `/personnel/api/employees/`. Each
ZKBioTime employee is mapped to the existing `students` table:

- `emp_code` becomes both `admission_number` and `biometric_id`.
- `first_name`, `last_name`, active status, birthday, gender, and address are
  mapped when available.
- The upsert uses the unique `students.admission_number` column, so rerunning
  the service updates the same student instead of inserting a duplicate.

`profile_id` and `class_id` remain unchanged for existing students and are
`null` for students first created by the sync.

## Attendance synchronization and state

Attendance is incremental. `data/state.json` stores the last successfully
uploaded attendance timestamp:

```json
{
    "last_sync_time": "2026-07-26 10:30:00"
}
```

On the first run, a missing or `null` timestamp defaults to 24 hours before the
run. The value is sent to `/iclock/api/transactions/` as `start_time`.

Each ZKBioTime transaction is mapped to `device_logs`:

- `emp_code` becomes `student_biometric_id`.
- `punch_time` becomes `punched_at`.
- `terminal_sn` is matched against `devices.device_serial`; the matching
  `devices.id` UUID is stored as `device_id`.
- The complete ZKBioTime object is retained in `raw_data`.
- New logs start with `processed = false`.

If a terminal has no matching `devices` row, the log is still stored with a
`null` device ID and a warning is logged. Because the schema has no unique
constraint for device punches, the service checks for an existing row with the
same device, biometric ID, and punch time before inserting. Existing logs have
only `raw_data` refreshed, so their processing status is preserved.

After all downloaded attendance rows have been uploaded successfully, the
service saves the newest `punch_time`. If no new records are returned, the
existing starting timestamp is retained.

State is not advanced if an upload fails, so the next run can safely retry the
same range. The application-level duplicate check prevents a retry from
creating duplicate `device_logs`.

## Run one synchronization

Activate the virtual environment and run:

```powershell
python main.py
```

Typical console output:

```text
Logged into ZKBioTime
Downloaded 2 devices
Uploaded 2 devices
Downloaded 52 employees
Uploaded 52 employees
Last sync time: 2026-07-26 10:30:00
Downloaded 3 new attendance records
Uploaded 3 attendance records
Updated sync state
Synchronization completed successfully
```

All database operations are isolated in `supabase_client.py`. The program runs
once and exits; it does not use `while True` or scheduling.

## Terminal synchronization helper

Every `main.py` run calls `get_all_terminals(client)` to retrieve all terminals
from `/iclock/api/terminals/`. A terminal is marked online when
`last_activity` is within two minutes of the server clock.

`upsert_device(device)` maps each result to `devices` and upserts on the unique
`device_serial` column. A missing serial creates a new row; an existing serial
updates that row. Fields without a dedicated database column, including the
ZKBioTime numeric ID, terminal timezone, and transfer time, remain available
in `raw_data`. `get_terminal(client, sn)` remains available when only one
serial number is needed.

ZKBioTime device state `1` is stored as `device_state = "active"` with
`is_active = true`. State `0`, state `3`, and all other values are stored as
`device_state = "inactive"` with `is_active = false`. This configured state is
separate from `is_online`, which is calculated from `last_activity`.
