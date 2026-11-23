-- Migrazione 2C: chiusura delle vecchie strade d'accesso della chiave pubblicabile (novembre 2026,
-- docs/migrazione_2C_piano.md). Da eseguire una volta nello SQL Editor di Supabase.
-- Ordine rispetto al codice: indifferente. Nessun codice in produzione (webapp su Render, app 1.0.0, cron,
-- script con la chiave segreta) usa ciò che si chiude.
--
-- COSA FA (solo ruoli anon e authenticated, cioè chi usa la chiave pubblicabile; la chiave segreta non cambia):
--   1. niente più lettura diretta di matchups, lineup_players, nba_games, nba_players, player_injuries,
--      cron_runs, rosters, v_standings, fanta_teams (aperta in sql/2026-11_fase1b_rls_revoche.sql, sezione 2):
--      i dati di lega arrivano solo dalle RPC (get_snapshot, login_bundle, token_bundle);
--   2. cancella la RPC login_with_token (sostituita da token_bundle nella Fase 2);
--   3. la RPC login non si chiama più da fuori; resta come pezzo interno di login_bundle, che gira con i
--      permessi del proprietario (SECURITY DEFINER) e quindi può ancora usarla.
--
-- PRIMA DI ESEGUIRE: lancia da sola la query RICOGNIZIONE qui sotto (sola lettura) e mandami il risultato.
-- Elenca le funzioni di public che anon può chiamare e le tabelle/viste che anon può leggere. Attesi:
--   funzioni: app_release, change_password, change_team_name, change_username, get_snapshot, league_context,
--             login, login_bundle, login_with_token, logout, save_lineup, token_bundle
--   tabelle:  cron_runs, fanta_teams, lineup_players, matchups, nba_games, nba_players, player_injuries,
--             rosters, v_standings
-- Se compare altro, non eseguire la migrazione: ne parliamo.
--
-- RICOGNIZIONE (sola lettura):
-- select 'funzione' as tipo, p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' as nome
-- from pg_proc p join pg_namespace n on n.oid = p.pronamespace
-- where n.nspname = 'public' and has_function_privilege('anon', p.oid, 'execute')
-- union all
-- select 'tabella', c.relname
-- from pg_class c join pg_namespace n on n.oid = c.relnamespace
-- where n.nspname = 'public' and c.relkind in ('r', 'p', 'v', 'm')
--   and (has_table_privilege('anon', c.oid, 'select') or has_any_column_privilege('anon', c.oid, 'select'))
-- order by 1, 2;

begin;

-- 1. Letture dirette ------------------------------------------------------------------------------------

revoke select on table
    public.matchups,
    public.lineup_players,
    public.nba_games,
    public.nba_players,
    public.player_injuries,
    public.cron_runs,
    public.rosters,
    public.v_standings
from anon, authenticated;

-- fanta_teams aveva il permesso solo sulle colonne id e name
revoke select (id, name) on table public.fanta_teams from anon, authenticated;

-- Le policy "lettura dati di lega" non servono più (le RLS restano attive: senza policy nessuna riga è visibile)
do $$
declare
    t text;
begin
    foreach t in array array['matchups', 'lineup_players', 'nba_games', 'nba_players', 'player_injuries',
                             'cron_runs', 'rosters', 'fanta_teams']
    loop
        execute format('drop policy if exists "lettura dati di lega" on public.%I', t);
    end loop;
end $$;

-- 2. login_with_token -----------------------------------------------------------------------------------

drop function if exists public.login_with_token(text);

-- 3. login solo dall'interno ----------------------------------------------------------------------------

revoke all on function public.login(text, text, boolean) from public, anon, authenticated;

commit;
notify pgrst, 'reload schema';


-- =====================================================================================================
-- VERIFICHE (dopo l'esecuzione)
-- =====================================================================================================
--
-- 1. La query RICOGNIZIONE qui sopra. Attesi: nessuna tabella; funzioni app_release, change_password,
--    change_team_name, change_username, get_snapshot, league_context, login_bundle, logout, save_lineup,
--    token_bundle (né login né login_with_token).
--
-- 2. Da PC: python tools/verifica_permessi.py  (solo chiave pubblicabile, non modifica nulla): tutto OK.
--
-- 3. Webapp e app: accesso, cambio formazione e salvataggio. Il giorno dopo: run del cron verde.


-- =====================================================================================================
-- ROLLBACK (riapre tutto com'era prima della 2C)
-- =====================================================================================================
--
-- begin;
-- grant select on table public.matchups, public.lineup_players, public.nba_games, public.nba_players,
--     public.player_injuries, public.cron_runs, public.rosters, public.v_standings to anon, authenticated;
-- grant select (id, name) on table public.fanta_teams to anon, authenticated;
-- do $$ declare t text; begin
--     foreach t in array array['matchups', 'lineup_players', 'nba_games', 'nba_players', 'player_injuries',
--                              'cron_runs', 'rosters', 'fanta_teams']
--     loop
--         execute format('drop policy if exists "lettura dati di lega" on public.%I', t);
--         execute format('create policy "lettura dati di lega" on public.%I for select to anon, authenticated using (true)', t);
--     end loop;
-- end $$;
-- grant execute on function public.login(text, text, boolean) to anon, authenticated, service_role;
-- commit;
-- notify pgrst, 'reload schema';
-- -- login_with_token: se mai servisse, rieseguire la sua definizione da sql/2026-11_fase1a_password_rpc.sql
-- -- (sezione 4) con le righe di revoke/grant corrispondenti.
