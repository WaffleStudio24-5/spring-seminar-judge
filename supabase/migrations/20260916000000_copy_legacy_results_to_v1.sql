-- Legacy main tests are equivalent to v1, as confirmed by the assignment maintainer.
-- Preserve the original SHA and timestamp; an existing v1 result takes precedence.
insert into public.results (
    repository, assignment, assignment_sha, commit_sha, status,
    workflow_run_id, run_number, run_attempt, graded_at
)
select
    repository, 'v1', assignment_sha, commit_sha, status,
    workflow_run_id, run_number, run_attempt, graded_at
from public.results
where assignment = 'main'
on conflict (repository, assignment) do nothing;
