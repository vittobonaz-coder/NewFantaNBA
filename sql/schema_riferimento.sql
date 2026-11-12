-- Schema di riferimento del database Supabase di FantaNBA (tabelle dello schema public).
-- SOLO CONTESTO: non è pensato per essere eseguito (ordine delle tabelle e vincoli possono non essere validi).
-- Esportato da Supabase il 09/11/2026, prima della migrazione all'app nativa.
-- RLS, permessi, funzioni, vincoli, indici, estensioni e job di pg_cron: in fondo al file
-- (risultato di sql/2026-11_ricognizione_schema.sql del 12/11/2026).
-- La vista v_standings è in sql/v_standings.sql.
-- Da aggiornare ogni volta che una migrazione in sql/ cambia tabelle o colonne.

CREATE TABLE public.profiles (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  username character varying NOT NULL,
  password character varying NOT NULL DEFAULT 'fanta2026'::character varying,
  CONSTRAINT profiles_pkey PRIMARY KEY (id)
);
CREATE TABLE public.nba_players (
  id integer NOT NULL,
  full_name character varying NOT NULL,
  nba_team character varying NOT NULL,
  position character varying NOT NULL,
  CONSTRAINT nba_players_pkey PRIMARY KEY (id)
);
CREATE TABLE public.fanta_teams (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid,
  name character varying NOT NULL,
  last_updated_date date DEFAULT '1970-01-01'::date,
  CONSTRAINT fanta_teams_pkey PRIMARY KEY (id),
  CONSTRAINT fanta_teams_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id)
);
CREATE TABLE public.rosters (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  fanta_team_id uuid,
  nba_player_id integer UNIQUE,
  assigned_position character varying NOT NULL,
  player_name character varying,
  CONSTRAINT rosters_pkey PRIMARY KEY (id),
  CONSTRAINT rosters_fanta_team_id_fkey FOREIGN KEY (fanta_team_id) REFERENCES public.fanta_teams(id),
  CONSTRAINT rosters_nba_player_id_fkey FOREIGN KEY (nba_player_id) REFERENCES public.nba_players(id)
);
CREATE TABLE public.matchups (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  gameweek integer NOT NULL,
  home_team_id uuid,
  away_team_id uuid,
  home_score numeric DEFAULT 0.00,
  away_score numeric DEFAULT 0.00,
  was_played boolean DEFAULT false,
  home_lineup character varying DEFAULT '2-2-1'::character varying,
  away_lineup character varying DEFAULT '2-2-1'::character varying,
  start_date date,
  end_date date,
  CONSTRAINT matchups_pkey PRIMARY KEY (id),
  CONSTRAINT matchups_home_team_id_fkey FOREIGN KEY (home_team_id) REFERENCES public.fanta_teams(id),
  CONSTRAINT matchups_away_team_id_fkey FOREIGN KEY (away_team_id) REFERENCES public.fanta_teams(id)
);
CREATE TABLE public.lineup_players (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  fanta_team_id uuid,
  gameweek integer NOT NULL,
  nba_player_id integer,
  slot integer NOT NULL,
  score numeric DEFAULT NULL::numeric,
  player_name character varying,
  role character varying,
  target_date date,
  entered_game boolean NOT NULL DEFAULT false,
  auto_sub text CHECK (auto_sub = ANY (ARRAY['IN'::text, 'OUT'::text])),
  CONSTRAINT lineup_players_pkey PRIMARY KEY (id),
  CONSTRAINT lineup_players_fanta_team_id_fkey FOREIGN KEY (fanta_team_id) REFERENCES public.fanta_teams(id),
  CONSTRAINT lineup_players_nba_player_id_fkey FOREIGN KEY (nba_player_id) REFERENCES public.nba_players(id)
);
CREATE TABLE public.player_stats (
  player_id integer NOT NULL,
  game_id text NOT NULL,
  game_date date,
  matchup text,
  wl text,
  min integer,
  fgm integer,
  fga integer,
  fg3m integer,
  fg3a integer,
  ftm integer,
  fta integer,
  oreb integer,
  dreb integer,
  reb integer,
  ast integer,
  stl integer,
  blk integer,
  tov integer,
  pf integer,
  pts integer,
  plus_minus integer,
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT player_stats_pkey PRIMARY KEY (player_id, game_id)
);
CREATE TABLE public.cron_runs (
  mode text NOT NULL CHECK (mode = ANY (ARRAY['daily'::text, 'rollover'::text, 'injuries'::text, 'manual'::text])),
  finished_at timestamp with time zone NOT NULL,
  ok boolean NOT NULL,
  CONSTRAINT cron_runs_pkey PRIMARY KEY (mode)
);
CREATE TABLE public.nba_games (
  game_id text NOT NULL,
  gameweek integer,
  nba_date date NOT NULL,
  start_time timestamp with time zone,
  home_team character varying NOT NULL,
  away_team character varying NOT NULL,
  home_score integer,
  away_score integer,
  status text NOT NULL DEFAULT 'scheduled'::text,
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT nba_games_pkey PRIMARY KEY (game_id)
);
CREATE TABLE public.login_tokens (
  token_hash text NOT NULL,
  user_id uuid NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT login_tokens_pkey PRIMARY KEY (token_hash),
  CONSTRAINT login_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id)
);
CREATE TABLE public.player_injuries (
  nba_player_id bigint NOT NULL,
  status text NOT NULL DEFAULT ''::text,
  fantasy_status text NOT NULL DEFAULT ''::text,
  injury_type text NOT NULL DEFAULT ''::text,
  return_date date,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT player_injuries_pkey PRIMARY KEY (nba_player_id)
);
CREATE TABLE public.standings_adjustments (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  fanta_team_id uuid NOT NULL,
  gameweek integer NOT NULL,
  wins_delta integer NOT NULL DEFAULT 0,
  losses_delta integer NOT NULL DEFAULT 0,
  reason text,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT standings_adjustments_pkey PRIMARY KEY (id),
  CONSTRAINT standings_adjustments_fanta_team_id_fkey FOREIGN KEY (fanta_team_id) REFERENCES public.fanta_teams(id)
);

-- =====================================================================================================
-- RICOGNIZIONE DEL 12/11/2026 (sql/2026-11_ricognizione_schema.sql), prima della Fase 1
-- =====================================================================================================
--
-- RLS
--   Disattivata su tutte le tabelle tranne standings_adjustments (attiva, ma senza policy: la legge
--   solo la vista v_standings, che gira con i permessi del proprietario).
--   Nessuna policy definita.
--
-- Permessi
--   anon e authenticated hanno TUTTI i privilegi (SELECT, INSERT, UPDATE, DELETE, TRUNCATE,
--   REFERENCES, TRIGGER) su tutte le tabelle e su v_standings.
--   Con la chiave pubblicabile si può quindi leggere profiles (password comprese) e svuotare qualunque tabella.
--
-- Funzioni di public
--   update_updated_at_column(): trigger function (NEW.updated_at = NOW()), SECURITY INVOKER.
--   Non è collegata a nessun trigger. Nessuna RPC.
--
-- Trigger
--   Nessuno (esclusi quelli interni di Postgres).
--
-- Vincoli e indici non riportati (o riportati diversamente) nelle CREATE TABLE sopra
--   fanta_teams.user_id      -> profiles(id)     ON DELETE CASCADE
--   rosters.fanta_team_id    -> fanta_teams(id)  ON DELETE CASCADE
--   rosters.nba_player_id    -> nba_players(id)  ON DELETE CASCADE
--   lineup_players.fanta_team_id -> fanta_teams(id) ON DELETE CASCADE
--   login_tokens.user_id     -> profiles(id)     ON DELETE CASCADE
--   lineup_players_team_gw_slot_key  UNIQUE (fanta_team_id, gameweek, slot)          -- non DEFERRABLE (Fase 2)
--   unique_lineup_entry              UNIQUE (fanta_team_id, gameweek, nba_player_id)
--   unique_matchup_per_gameweek      UNIQUE (gameweek, home_team_id, away_team_id)
--   idx_lineup_players_gw            (gameweek)
--   idx_lineup_players_gw_team       (gameweek, fanta_team_id)
--   idx_matchups_gameweek            (gameweek)
--   nba_games_gameweek_idx           (gameweek)
--
-- Estensioni
--   pg_cron 1.6.4 (pg_catalog), pg_net 0.20.4 (public), pg_stat_statements 1.11 (extensions),
--   pgcrypto 1.3 (extensions: crypt() e gen_salt() vanno chiamate come extensions.crypt / extensions.gen_salt
--   oppure con extensions nel search_path), plpgsql, supabase_vault 0.3.1 (vault), uuid-ossp 1.1 (extensions).
--
-- Job di pg_cron (orari UTC). Tutti fanno net.http_post verso il workflow_dispatch di
-- .github/workflows/cron-test.yml (ref main), con il token GitHub letto dal Vault (secret 'github_token').
--   7  fanta-daily                 0 8 * * *          mode=daily
--   8  fanta-rollover              59 21,22 * * *     mode=rollover
--   9  github-cron-injuries-2110   10 21 * * *        mode=injuries
--   10 github-cron-injuries-2210   10 22 * * *        mode=injuries
