-- Mercato, correzione del controllo dei ruoli (novembre 2026).
-- Da eseguire una volta nello SQL Editor di Supabase, DOPO la parte 1 di sql/2026-11_mercato.sql.
-- (Chi esegue da zero sql/2026-11_mercato.sql ha già questa versione: il file è stato corretto.)
--
-- Problema: in nba_players i ruoli sono scritti in due formati.
--   - giocatori dei roster (caricati a inizio campionato): codici dell'app, 'G', 'A', 'C', 'G/A', 'C/A' ...
--   - giocatori caricati da carica_giocatori.py: formato NBA, 'Guard', 'Forward-Center' ...
-- market_roles_ok cercava solo 'guard', 'forward', 'center': con i roster veri avrebbe rifiutato ogni offerta
-- ("il roster resterebbe senza una guardia, un'ala o un centro").
-- Soluzione: private.position_codes traduce entrambi i formati negli stessi codici dell'app (G, A, C), con la
-- stessa regola di Player.get_clean_position in fanta_obj.py. Nessun dato viene modificato.
-- Compatibile col codice in produzione: le funzioni sono usate solo dal mercato, non ancora nell'app.

begin;

create or replace function private.position_codes(p_position text)
returns text[]
language sql
immutable
set search_path = ''
as $$
    select coalesce(array_agg(case trim(x) when 'Guard' then 'G' when 'Forward' then 'A' when 'Center' then 'C'
                                           else trim(x) end), '{}')
    from regexp_split_to_table(replace(coalesce(p_position, ''), '-', '/'), '/') as x
    where trim(x) <> '';
$$;

create or replace function private.market_roles_ok(p_team uuid, p_out integer, p_in integer)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    with r as (
        select p.id, private.position_codes(p.position) as codes
        from public.nba_players p
        where p.id in (select ro.nba_player_id from public.rosters ro
                       where ro.fanta_team_id = p_team and ro.nba_player_id <> p_out)
           or p.id = p_in
    )
    select exists (
        select 1 from r g, r a, r c
        where g.id <> a.id and g.id <> c.id and a.id <> c.id
          and 'G' = any(g.codes) and 'A' = any(a.codes) and 'C' = any(c.codes)
    );
$$;

commit;

-- VERIFICA (atteso: {G,A}  {A,C}  {C}  {G}  {})
-- select private.position_codes('G/A'), private.position_codes('Forward-Center'), private.position_codes('C'),
--        private.position_codes('Guard'), private.position_codes('');
-- VERIFICA (atteso: nessuna riga, cioè ogni roster attuale soddisfa già il vincolo)
-- select t.name from public.fanta_teams t
-- where exists (select 1 from public.rosters r where r.fanta_team_id = t.id)
--   and not private.market_roles_ok(t.id, -1, -1);

-- ROLLBACK: rieseguire la definizione di market_roles_ok della versione precedente di sql/2026-11_mercato.sql
-- (git show f927028d:sql/2026-11_mercato.sql), poi: drop function if exists private.position_codes(text);
