-- Classifica del campionato.
-- Punti classifica = vittorie + 0.2 per ogni giornata chiusa col miglior punteggio
-- (a pari miglior punteggio il bonus va a tutte le squadre a pari merito).
-- Da eseguire nello SQL Editor di Supabase.

create or replace view public.v_standings as
with team_games as (
  -- Una riga per squadra per matchup, dal punto di vista della squadra
  select m.id, m.gameweek, m.was_played,
         m.home_team_id as team_id, m.home_score as score, m.away_score as opp_score
  from public.matchups m
  union all
  select m.id, m.gameweek, m.was_played,
         m.away_team_id, m.away_score, m.home_score
  from public.matchups m
),
team_games_best as (
  select tg.*,
         max(tg.score) over (partition by tg.gameweek) as gw_max_score
  from team_games tg
),
team_totals as (
  select
    ft.id as fanta_team_id,
    ft.name as team_name,
    count(g.id) filter (where g.was_played = true) as played,
    count(g.id) filter (where g.score > g.opp_score) as wins,
    count(g.id) filter (where g.score < g.opp_score) as losses,
    coalesce(sum(g.score), 0.00) as total_score,
    coalesce(sum(g.opp_score), 0.00) as total_points_against,
    -- gw_max_score > 0 esclude le giornate non ancora iniziate (tutti a 0 = tutti "migliori")
    count(g.id) filter (where g.gw_max_score > 0 and g.score = g.gw_max_score) as best_scores
  from public.fanta_teams ft
  left join team_games_best g on g.team_id = ft.id
  group by ft.id, ft.name
)
select
  tt.*,
  tt.wins + 0.2 * tt.best_scores as standing_points
from team_totals tt
order by standing_points desc, total_score desc;
