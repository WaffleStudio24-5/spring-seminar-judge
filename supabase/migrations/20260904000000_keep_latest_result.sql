begin;

with ranked_results as (
    select
        ctid,
        row_number() over (
            partition by repository, assignment
            order by graded_at desc, workflow_run_id desc, run_attempt desc
        ) as position
    from public.results
)
delete from public.results as stored
using ranked_results
where stored.ctid = ranked_results.ctid
  and ranked_results.position > 1;

alter table public.results drop constraint results_pkey;
alter table public.results add primary key (repository, assignment);
grant update on table public.results to service_role;

commit;
