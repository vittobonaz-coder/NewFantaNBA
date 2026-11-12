-- Fase 1, migrazione B: RLS su tutte le tabelle e revoca dei privilegi della chiave pubblicabile (novembre 2026).
-- Da eseguire nello SQL Editor di Supabase SOLO DOPO che:
--   1. la migrazione A (sql/2026-11_fase1a_password_rpc.sql) è stata eseguita;
--   2. il nuovo codice della Fase 1 è su main e Render l'ha pubblicato (login e salvataggi passano dalle RPC);
--   3. il segreto SUPABASE_SECRET_KEY è su GitHub e un run manuale del cron con il nuovo codice è riuscito.
-- Se eseguita prima, il login e i salvataggi della versione web si rompono e il cron smette di scrivere.
--
-- Dopo questa migrazione, con la chiave pubblicabile (ruoli anon e authenticated):
--   - si leggono solo i dati di lega: matchups, lineup_players, nba_games, nba_players, player_injuries,
--     cron_runs, rosters, v_standings e di fanta_teams solo id e name;
--   - profiles, login_tokens, player_stats e standings_adjustments non si leggono;
--   - nessuna scrittura diretta: l'app scrive solo con le RPC della migrazione A;
--   - la chiave segreta (service_role), usata da cron e script, non cambia: scavalca RLS e permessi.
--
-- PROVA A SECCO (consigliata): esegui il file sostituendo il "commit;" in fondo con il blocco
-- PROVA A SECCO riportato dopo, che controlla i permessi e annulla tutto con rollback.

begin;

-- 1. Tutte le tabelle di public: RLS attiva e nessun privilegio per anon e authenticated --------------------
--    (ciclo su tutte le tabelle, così non ne resta fuori nessuna)
do $$
declare
    r record;
begin
    for r in select c.relname
             from pg_class c join pg_namespace n on n.oid = c.relnamespace
             where n.nspname = 'public' and c.relkind in ('r', 'p')
    loop
        execute format('alter table public.%I enable row level security', r.relname);
        execute format('revoke all on table public.%I from anon, authenticated', r.relname);
    end loop;
end $$;

revoke all on table public.v_standings from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;

-- La vecchia policy di scrittura degli infortuni (sql/2026-11_sostituzioni_infortuni.sql) non serve più:
-- il cron scrive con la chiave segreta
drop policy if exists "player_injuries scrittura" on public.player_injuries;
drop policy if exists "player_injuries lettura" on public.player_injuries;


-- 2. Lettura dei dati di lega -------------------------------------------------------------------------------

grant select on table
    public.matchups,
    public.lineup_players,
    public.nba_games,
    public.nba_players,
    public.player_injuries,
    public.cron_runs,
    public.rosters,
    public.v_standings
to anon, authenticated;

-- fanta_teams: solo id e name (user_id collega la squadra al profilo e non serve all'app).
-- Attenzione: con i permessi per colonna, select=* su fanta_teams dalla chiave pubblicabile fallisce.
grant select (id, name) on table public.fanta_teams to anon, authenticated;

-- Policy di sola lettura (le righe sono tutte visibili; le scritture non hanno policy e sono negate)
do $$
declare
    t text;
begin
    foreach t in array array['matchups', 'lineup_players', 'nba_games', 'nba_players', 'player_injuries',
                             'cron_runs', 'rosters', 'fanta_teams']
    loop
        execute format('drop policy if exists "lettura dati di lega" on public.%I', t);
        execute format('create policy "lettura dati di lega" on public.%I for select to anon, authenticated using (true)', t);
    end loop;
end $$;

-- v_standings è una vista con i permessi del proprietario (postgres, proprietario anche delle tabelle):
-- continua a leggere matchups, fanta_teams e standings_adjustments senza essere bloccata dalle RLS.


-- 3. Oggetti creati in futuro in public: di default nessun permesso per anon e authenticated ------------------
--    (Supabase di solito li dà tutti: una tabella nuova nascerebbe di nuovo aperta).
--    Ogni tabella nuova che l'app deve leggere va quindi abilitata esplicitamente nella sua migrazione.

alter default privileges for role postgres in schema public revoke all on tables    from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on functions from anon, authenticated, public;

-- PROVA A SECCO: sostituisci la riga qui sotto con il blocco PROVA A SECCO
commit;

notify pgrst, 'reload schema';


-- =====================================================================================================
-- PROVA A SECCO (al posto del "commit;" qui sopra: controlla e poi annulla tutto)
-- =====================================================================================================
--
-- select c.relname as tabella, c.relrowsecurity as rls,
--        has_table_privilege('anon', c.oid, 'select') as anon_legge,
--        has_any_column_privilege('anon', c.oid, 'select') as anon_legge_colonne,
--        has_table_privilege('anon', c.oid, 'insert,update,delete,truncate') as anon_scrive
-- from pg_class c join pg_namespace n on n.oid = c.relnamespace
-- where n.nspname = 'public' and c.relkind in ('r', 'p', 'v')
-- order by c.relname;
-- set local role anon;
-- select (select count(*) from public.matchups) as matchups,
--        (select count(*) from public.v_standings) as classifica,
--        (select count(*) from public.fanta_teams) as squadre;
-- rollback;
--
-- Attesi: rls = true su tutte le tabelle; anon_scrive = false ovunque; anon_legge = false su profiles,
-- login_tokens, player_stats, standings_adjustments, fanta_teams (che ha anon_legge_colonne = true);
-- i conteggi dell'ultima query uguali a quelli di oggi (squadre e righe di classifica = numero di squadre).


-- =====================================================================================================
-- VERIFICA DOPO L'ESECUZIONE
-- =====================================================================================================
-- 1. La stessa query dei permessi della prova a secco (senza set role e rollback).
-- 2. Da PC: python tools/verifica_permessi.py (solo la chiave pubblicabile, non modifica nessuna riga).
-- 3. Versione web su Render: login, cambio formazione e salvataggio, logout.
-- 4. GitHub: run manuale del cron con mode "injuries", deve risultare verde.


-- =====================================================================================================
-- ROLLBACK (solo in emergenza)
-- =====================================================================================================
--
-- a) Ripristina solo le letture (es. una schermata dell'app non carica più). Le password restano protette.
-- begin;
-- grant select on all tables in schema public to anon, authenticated;
-- revoke select on table public.profiles, public.login_tokens from anon, authenticated;
-- do $$ declare r record; begin
--     for r in select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
--              where n.nspname = 'public' and c.relkind in ('r', 'p') and c.relname not in ('profiles', 'login_tokens')
--     loop
--         execute format('drop policy if exists "rollback lettura" on public.%I', r.relname);
--         execute format('create policy "rollback lettura" on public.%I for select to anon, authenticated using (true)', r.relname);
--     end loop;
-- end $$;
-- commit;
-- notify pgrst, 'reload schema';
--
-- b) Ritorno completo allo stato prima della Fase 1 (INSICURO: password di nuovo leggibili da chiunque).
--    Solo se si torna anche al codice di prima su main.
-- begin;
-- do $$ declare r record; begin
--     for r in select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
--              where n.nspname = 'public' and c.relkind in ('r', 'p') and c.relname <> 'standings_adjustments'
--     loop
--         execute format('alter table public.%I disable row level security', r.relname);
--     end loop;
-- end $$;
-- grant all on all tables in schema public to anon, authenticated;
-- commit;
-- notify pgrst, 'reload schema';
