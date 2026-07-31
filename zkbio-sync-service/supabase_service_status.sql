-- Run this once in the Supabase SQL editor.

create table if not exists public.sync_service_status (
    service_key text primary key,
    process_started_at timestamptz not null default now(),
    reported_running boolean not null default false,
    last_heartbeat_at timestamptz not null default now(),
    last_sync_started_at timestamptz,
    last_sync_at timestamptz,
    last_sync_status text not null default 'never'
        check (last_sync_status in ('never', 'running', 'success', 'failed')),
    last_error text,
    updated_at timestamptz not null default now()
);

-- Makes this script safe to rerun if the table was created by an older version.
alter table public.sync_service_status
    add column if not exists reported_running boolean not null default false;

comment on table public.sync_service_status is
    'Heartbeat and latest synchronization result for backend executables.';

alter table public.sync_service_status enable row level security;

drop policy if exists "Frontend can read sync status"
    on public.sync_service_status;
create policy "Frontend can read sync status"
    on public.sync_service_status
    for select
    to anon, authenticated
    using (true);

-- The executable must use the server-side key already configured in .env.
-- Browser clients are deliberately not allowed to change service status.
revoke insert, update, delete on public.sync_service_status
    from anon, authenticated;
grant select on public.sync_service_status to anon, authenticated;
grant select, insert, update on public.sync_service_status to service_role;

-- Query this view from the frontend. `is_running` becomes false automatically
-- if two expected five-minute heartbeats are missed.
create or replace view public.sync_service_health
with (security_invoker = true)
as
select
    service_key,
    process_started_at,
    reported_running,
    last_heartbeat_at,
    last_sync_started_at,
    last_sync_at,
    last_sync_status,
    last_error,
    updated_at,
    reported_running
        and last_heartbeat_at >= now() - interval '10 minutes' as is_running
from public.sync_service_status;

grant select on public.sync_service_health to anon, authenticated;
