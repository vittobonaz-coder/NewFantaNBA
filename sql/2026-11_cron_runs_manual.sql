-- cron_runs: modalità ammesse (novembre 2026).
-- Da eseguire una volta nello SQL Editor di Supabase, PRIMA di pubblicare il nuovo codice.
--
-- - injuries: il cron degli infortuni registra già i suoi run, ma il vincolo ammetteva solo daily e rollover,
--             quindi la scrittura falliva in silenzio (record_cron_run intercetta l'errore)
-- - manual:   modifiche fatte a mano fuori dal cron (swap_players.py, SupabaseSync.mark_data_changed):
--             le app vedono un "run" più recente dei loro dati locali e riscaricano le formazioni

-- Toglie i vincoli CHECK esistenti su cron_runs, qualunque nome abbiano (di solito cron_runs_mode_check)
do $$
declare c record;
begin
    for c in select conname from pg_constraint
             where conrelid = 'public.cron_runs'::regclass and contype = 'c'
    loop
        execute format('alter table public.cron_runs drop constraint %I', c.conname);
    end loop;
end $$;

alter table public.cron_runs
    add constraint cron_runs_mode_check check (mode in ('daily', 'rollover', 'injuries', 'manual'));
