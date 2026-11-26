-- Prova del mercato sui dati veri SENZA modificarli: tutto è dentro begin ... rollback.
-- Da eseguire nello SQL Editor di Supabase dopo la parte 1 di sql/2026-11_mercato.sql e carica_giocatori.py,
-- PRIMA che qualcuno faccia offerte vere (market_plan mostra le offerte di tutti).
-- Esegui il file intero: l'ultimo risultato mostrato è quello del passo 5; per vedere gli altri passi
-- eseguili uno alla volta selezionandoli (sempre partendo da "begin;").
--
-- Scenario: le due squadre ultime in classifica vogliono lo stesso free agent (il migliore libero con ID ESPN,
-- in ordine alfabetico per avere un risultato ripetibile). Ognuna offre il primo giocatore del suo roster;
-- la penultima fa anche una seconda offerta su un altro free agent.
-- Atteso: l'ultima prende il giocatore conteso; la penultima lo perde ("Preso da ...") e ottiene la seconda.

begin;

-- 1. Offerte finte
with ultime as (
    select s.fanta_team_id, row_number() over (order by s.standing_points asc, s.total_score asc, s.team_name desc) as pos
    from public.v_standings s
),
liberi as (
    select p.id, row_number() over (order by p.full_name) as n
    from public.nba_players p
    where p.espn_id is not null and not exists (select 1 from public.rosters r where r.nba_player_id = p.id)
      and p.position ilike '%guard%'
),
primo as (
    select r.fanta_team_id, min(r.nba_player_id) filter (where p.position ilike '%guard%') as out_id
    from public.rosters r join public.nba_players p on p.id = r.nba_player_id
    group by r.fanta_team_id
)
insert into public.market_offers (window_gw, fanta_team_id, out_player_id, in_player_id)
select 6, u.fanta_team_id, pr.out_id, l.id
from ultime u
join primo pr on pr.fanta_team_id = u.fanta_team_id
join liberi l on (u.pos in (1, 2) and l.n = 1) or (u.pos = 2 and l.n = 2)
where u.pos in (1, 2)
order by u.pos, l.n;

-- 2. Offerte inserite (atteso: 3 righe)
select t.name as squadra, po.full_name as cede, pi.full_name as prende, o.id as ordine
from public.market_offers o
join public.fanta_teams t on t.id = o.fanta_team_id
join public.nba_players po on po.id = o.out_player_id
join public.nba_players pi on pi.id = o.in_player_id
where o.window_gw = 6 order by o.id;

-- 3. Piano senza scrivere nulla
select * from private.market_plan(6) order by priority, offer_id;

-- 4. Esecuzione vera (dentro la transazione)
select public.market_close(6);

-- 5. Roster dopo lo scambio: le due squadre e i giocatori coinvolti
select t.name as squadra, o.status as esito, o.note as motivo, po.full_name as cede, pi.full_name as prende,
       (select count(*) from public.lineup_players lp
        where lp.fanta_team_id = o.fanta_team_id and lp.nba_player_id = o.in_player_id) as giornate_col_nuovo
from public.market_offers o
join public.fanta_teams t on t.id = o.fanta_team_id
join public.nba_players po on po.id = o.out_player_id
join public.nba_players pi on pi.id = o.in_player_id
where o.window_gw = 6 order by o.id;

rollback;

-- Dopo il rollback non resta niente. Controllo (atteso: 0 e finestra 6 con closed_at vuoto):
-- select count(*) from public.market_offers;
-- select gameweek, closed_at from public.market_windows where gameweek = 6;
