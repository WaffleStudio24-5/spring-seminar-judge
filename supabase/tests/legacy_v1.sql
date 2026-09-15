-- Run against a local test database with the first two migrations applied:
-- psql <local-test-db-url> -X -v ON_ERROR_STOP=1 -f supabase/tests/legacy_v1.sql
begin;

insert into public.results (
    repository, assignment, assignment_sha, commit_sha, status,
    workflow_run_id, run_number, run_attempt, graded_at
) values
    ('test/legacy-v1-copy', 'main', repeat('a', 40), repeat('b', 40), 'PASSED', 1, 1, 1, '2026-09-01Z'),
    ('test/legacy-v1-keep', 'main', repeat('a', 40), repeat('b', 40), 'PASSED', 2, 1, 1, '2026-09-01Z'),
    ('test/legacy-v1-keep', 'v1', repeat('c', 40), repeat('d', 40), 'FAILED', 3, 2, 1, '2026-09-02Z'),
    ('test/legacy-v1-copy', 'v2', repeat('e', 40), repeat('f', 40), 'FAILED', 4, 3, 1, '2026-09-03Z');

\ir ../migrations/20260916000000_copy_legacy_results_to_v1.sql
\ir ../migrations/20260916000000_copy_legacy_results_to_v1.sql

do $$
begin
    if not exists (
        select 1 from public.results
        where repository = 'test/legacy-v1-copy' and assignment = 'v1'
          and status = 'PASSED' and assignment_sha = repeat('a', 40)
          and commit_sha = repeat('b', 40) and workflow_run_id = 1
          and run_number = 1 and run_attempt = 1 and graded_at = '2026-09-01Z'
    ) then
        raise exception 'legacy result or provenance was not copied';
    end if;
    if not exists (
        select 1 from public.results
        where repository = 'test/legacy-v1-keep' and assignment = 'v1'
          and status = 'FAILED' and assignment_sha = repeat('c', 40)
          and workflow_run_id = 3 and graded_at = '2026-09-02Z'
    ) then
        raise exception 'existing v1 result was overwritten';
    end if;
    if (select count(*) from public.results
        where repository in ('test/legacy-v1-copy', 'test/legacy-v1-keep')) <> 5
    or not exists (
        select 1 from public.results
        where repository = 'test/legacy-v1-copy' and assignment = 'v2'
          and status = 'FAILED' and workflow_run_id = 4
    ) then
        raise exception 'original results changed or migration is not repeatable';
    end if;
end $$;

rollback;
