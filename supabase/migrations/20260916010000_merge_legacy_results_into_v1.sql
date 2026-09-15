-- main was the same assignment as v1. Keep one canonical row per repository.
delete from public.results as legacy
using public.results as current
where legacy.assignment = 'main'
  and current.assignment = 'v1'
  and current.repository = legacy.repository;

update public.results
set assignment = 'v1'
where assignment = 'main';
