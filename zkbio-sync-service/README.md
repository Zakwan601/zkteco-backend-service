# ZKBio Sync Service

Milestone 1 is a small Python 3.12+ client that proves communication with
ZKBioTime. It authenticates with JWT, downloads all employees, and downloads
attendance transactions. Supabase integration and scheduling are intentionally
not included.

## Setup

Create and activate a virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then replace the example values:

```env
ZKBIO_URL=https://your-zkbiotime-server.example.com
ZKBIO_USERNAME=your_username
ZKBIO_PASSWORD=your_password
```

`ZKBIO_URL` should be the base URL of the ZKBioTime installation. Do not add an
API endpoint path to it.

## Run

```powershell
python main.py
```

On success the program prints:

```text
Logged in successfully
Employees: <number>
Attendance records: <number>
```

## API functions

- `ZKBioClient.get_token()` authenticates at `/jwt-api-token-auth/` and keeps
  the JWT in memory.
- `get_all_employees(client)` downloads `/personnel/api/employees/`.
- `get_attendance(client, start_time=None, end_time=None)` downloads
  `/iclock/api/transactions/` and supports optional time filters.

All authenticated requests include `Authorization: Bearer <token>`. A `401`
invalidates the cached token, obtains a new token, and retries the failed
request once. List endpoints follow `next` links when the server returns a
paginated response.
