create table public.results (
    repository text not null,
    assignment text not null,
    assignment_sha text not null,
    commit_sha text not null,
    status text not null check (status in ('PASSED', 'FAILED', 'ERROR')),
    workflow_run_id bigint not null,
    run_number bigint not null,
    run_attempt bigint not null,
    graded_at timestamptz not null default now(),
    primary key (repository, assignment, workflow_run_id, run_attempt)
);

alter table public.results enable row level security;
revoke all on table public.results from anon, authenticated;
grant select, insert on table public.results to service_role;
