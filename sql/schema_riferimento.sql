-- Schema di riferimento del database Supabase di FantaNBA (tabelle dello schema public).
-- SOLO CONTESTO: non è pensato per essere eseguito (ordine delle tabelle e vincoli possono non essere validi).
-- Esportato da Supabase il 09/11/2026, prima della migrazione all'app nativa.
-- RLS, permessi, funzioni, vincoli, indici, estensioni e job di pg_cron: in fondo al file
-- (risultato di sql/2026-11_ricognizione_schema.sql del 12/11/2026).
-- La vista v_standings è in sql/v_standings.sql.
-- Da aggiornare ogni volta che una migrazione in sql/ cambia tabelle o colonne.
-- Aggiornato il 14/11/2026 dopo le migrazioni A, B e C della Fase 1 (stato attuale in fondo al file).
-- CREATE TABLE allineate all'export di Supabase del 26/11/2026: tutte le 17 tabelle di public, comprese
-- quelle delle Fasi 2, 5 e 6. A quella data la migrazione 2026-11_fase6_app_release_macos.sql
-- NON risulta eseguita (app_release accetta solo android e windows).

CREATE TABLE public.profiles (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  username character varying NOT NULL,
  password_hash text,  -- bcrypt (extensions.crypt), Fase 1; la password in chiaro è stata eliminata (migrazione C)
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
  expires_at timestamp with time zone NOT NULL DEFAULT (now() + '90 days'::interval),  -- Fase 1: 90 giorni con "Ricordami", 7 senza
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
CREATE TABLE public.edit_override (  -- Fase 2: deroga ai cambi, al massimo una riga
  id boolean NOT NULL DEFAULT true CHECK (id),
  gameweek integer NOT NULL,
  until_at timestamp with time zone NOT NULL,
  note text,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT edit_override_pkey PRIMARY KEY (id)
);
CREATE TABLE public.app_snapshot (  -- Fase 2: dati uguali per tutti, per parti con versione
  part text NOT NULL CHECK (part = ANY (ARRAY['calendar'::text, 'standings'::text, 'injuries'::text, 'lineups'::text])),
  version text NOT NULL,
  data jsonb NOT NULL,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  checked_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT app_snapshot_pkey PRIMARY KEY (part)
);
CREATE TABLE public.app_release (  -- Fase 5: aggiornamenti dell'app installata, una riga per piattaforma
  platform text NOT NULL CHECK (platform = ANY (ARRAY['android'::text, 'windows'::text])),
  latest_version text NOT NULL CHECK (latest_version ~ '^\d+\.\d+\.\d+$'::text),
  min_version text NOT NULL CHECK (min_version ~ '^\d+\.\d+\.\d+$'::text),
  url text NOT NULL,
  note text,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT app_release_pkey PRIMARY KEY (platform)
);
CREATE TABLE public.client_usage (  -- Fase 6: chi usa cosa, una riga per utente e client
  user_id uuid NOT NULL,
  client text NOT NULL CHECK (client ~ '^[a-z0-9-]{1,30}$'::text),
  app_version text CHECK (app_version ~ '^\d+\.\d+\.\d+$'::text),
  first_seen_at timestamp with time zone NOT NULL DEFAULT now(),
  last_seen_at timestamp with time zone NOT NULL DEFAULT now(),
  accessi integer NOT NULL DEFAULT 1,
  CONSTRAINT client_usage_pkey PRIMARY KEY (user_id, client),
  CONSTRAINT client_usage_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id)
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

-- =====================================================================================================
-- FASE 1 (migrazioni A, B e C eseguite il 14/11/2026)
-- =====================================================================================================
--
-- sql/2026-11_fase1a_password_rpc.sql
--   profiles.password_hash (bcrypt), login_tokens.expires_at.
--   Schema private (non esposto da PostgREST, nessun permesso per anon): token_hash, token_user,
--   check_password, require_password, set_password (scrive solo l'hash), validate_name, profile_json.
--   RPC in public, tutte SECURITY DEFINER con search_path vuoto:
--     login(p_username, p_password, p_remember)            anon, authenticated
--     login_with_token(p_token)                            anon, authenticated
--     logout(p_token)                                      anon, authenticated
--     change_password(p_token, p_old_password, p_new_password)
--     change_username(p_token, p_password, p_new_username)
--     change_team_name(p_token, p_password, p_new_name)
--     save_lineup(p_token, p_gameweek, p_players, p_lineup)
--     admin_set_password(p_user_id, p_password)            solo service_role
--
-- sql/2026-11_fase1b_rls_revoche.sql
--   RLS attiva su tutte le tabelle di public. anon e authenticated: nessuna scrittura; SELECT solo su
--   matchups, lineup_players, nba_games, nba_players, player_injuries, cron_runs, rosters, v_standings
--   e fanta_teams(id, name), con policy "lettura dati di lega" (using true). Nessun accesso a profiles,
--   login_tokens, player_stats, standings_adjustments. Default privileges di postgres in public: nessun
--   permesso per anon e authenticated su tabelle, sequenze e funzioni create in futuro.
--   Cron e script di amministrazione usano la chiave segreta (service_role), che scavalca le RLS.
--
-- sql/2026-11_fase1c_drop_password_chiaro.sql
--   Eliminati profiles.password (in chiaro), il trigger profiles_sync_password_hash e private.sync_password_hash.
--   Password dimenticata: non si recupera; si reimposta con
--   select public.admin_set_password((select id from public.profiles where username = '...'), '<temporanea>');

-- =====================================================================================================
-- FASE 2 (migrazioni scritte il 14/11/2026; A da eseguire prima del codice su main, B dopo)
-- =====================================================================================================
--
-- sql/2026-11_fase2a_snapshot_bundle.sql
--   CREATE TABLE public.edit_override (           -- deroga ai cambi, al massimo una riga (prima: variabili su Render)
--     id boolean PRIMARY KEY DEFAULT true CHECK (id),
--     gameweek integer NOT NULL,
--     until_at timestamptz NOT NULL,
--     note text,
--     updated_at timestamptz NOT NULL DEFAULT now()
--   );
--   CREATE TABLE public.app_snapshot (             -- dati uguali per tutti, per parti con versione
--     part text PRIMARY KEY CHECK (part IN ('calendar', 'standings', 'injuries', 'lineups')),
--     version text NOT NULL,                       -- md5 di data: cambia solo se i dati cambiano
--     data jsonb NOT NULL,
--     updated_at timestamptz NOT NULL DEFAULT now(),   -- ultima modifica del contenuto
--     checked_at timestamptz NOT NULL DEFAULT now()    -- ultima rigenerazione
--   );
--   Entrambe con RLS e nessun permesso per anon/authenticated: si leggono solo dalle RPC.
--   lineup_players_team_gw_slot_key  UNIQUE (fanta_team_id, gameweek, slot) DEFERRABLE INITIALLY IMMEDIATE
--   private: league_context(p_now), snapshot_part, lineup_row_json, refresh_snapshot(p_parts), ensure_snapshot,
--            snapshot_since, team_lineup_json, bundle_data.
--   RPC (SECURITY DEFINER, search_path vuoto):
--     login_bundle(p_username, p_password, p_remember, p_versions)   anon, authenticated
--     token_bundle(p_token, p_versions)                              anon, authenticated
--     get_snapshot(p_versions)                                       anon, authenticated
--     league_context()                                               anon, authenticated
--     record_run(p_mode, p_ok)       cron_runs + snapshot             solo service_role
--     refresh_snapshot()                                             solo service_role (e SQL Editor)
--   change_team_name rigenera le parti con i nomi.
--   Dopo una correzione a mano nello SQL Editor: select public.refresh_snapshot();
--
-- sql/2026-11_fase2b_save_lineup_scadenza.sql
--   save_lineup: solo la giornata modificabile e prima della scadenza (private.league_context, con la deroga),
--   errore CAMBI_CHIUSI; un solo UPDATE degli slot (niente slot temporanei +100).
--
-- =====================================================================================================
-- FASE 5 (migrazione scritta il 19/11/2026; ordine rispetto al codice indifferente)
-- =====================================================================================================
--
-- sql/2026-11_fase5_app_release.sql
--   CREATE TABLE public.app_release (              -- aggiornamenti dell'app installata, una riga per piattaforma
--     platform text PRIMARY KEY CHECK (platform IN ('android', 'windows')),
--     latest_version text NOT NULL,                -- X.Y.Z: sotto questa l'app avvisa
--     min_version text NOT NULL,                   -- X.Y.Z: sotto questa l'app non si usa
--     url text NOT NULL,                           -- link di download (release di GitHub)
--     note text,
--     updated_at timestamptz NOT NULL DEFAULT now()
--   );
--   RLS e nessun permesso per anon/authenticated: si legge solo dalla RPC.
--   RPC app_release(p_platform)  (SECURITY DEFINER, search_path vuoto)  anon, authenticated
--   Si aggiorna a mano dopo ogni release pubblicata (snippet in fondo alla migrazione).


-- =====================================================================================================
-- FASE 6 (migrazione scritta il 23/11/2026; ordine rispetto al codice indifferente)
-- =====================================================================================================
--
-- sql/2026-11_fase6_client_usage.sql
--   CREATE TABLE public.client_usage (             -- chi usa cosa: una riga per utente e client
--     user_id uuid NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
--     client text NOT NULL,                        -- android, windows, web-ios, web-android, web-windows...,
--                                                  -- sviluppo, non-indicato (app 1.0.0), non-valido
--     app_version text,                            -- X.Y.Z dell'app installata, null per la webapp
--     first_seen_at timestamptz NOT NULL DEFAULT now(),
--     last_seen_at timestamptz NOT NULL DEFAULT now(),
--     accessi integer NOT NULL DEFAULT 1,          -- aperture (login o accesso automatico)
--     PRIMARY KEY (user_id, client)
--   );
--   RLS e nessun permesso per anon/authenticated: si legge solo dallo SQL Editor (query nella migrazione).
--   private.record_client(p_user, p_client)  registra l'accesso, non fa mai fallire il login
--   login_bundle(p_username, p_password, p_remember, p_versions, p_client jsonb DEFAULT NULL)
--   token_bundle(p_token, p_versions, p_client jsonb DEFAULT NULL)
--     (sostituiscono le firme della Fase 2; p_client = {"client": "...", "version": "X.Y.Z"})


-- =====================================================================================================
-- MIGRAZIONE 2C (scritta il 23/11/2026; ordine rispetto al codice indifferente)
-- =====================================================================================================
--
-- sql/2026-11_2C_chiusura_letture.sql  (sostituisce quanto detto sopra per la Fase 1, migrazione B)
--   anon e authenticated NON leggono più nessuna tabella o vista di public: tolti i SELECT su matchups,
--   lineup_players, nba_games, nba_players, player_injuries, cron_runs, rosters, v_standings e
--   fanta_teams(id, name), cancellate le policy "lettura dati di lega". RLS sempre attiva.
--   I dati di lega arrivano solo dalle RPC (SECURITY DEFINER).
--   login_with_token cancellata. login: nessun permesso per anon/authenticated (solo service_role);
--   la usa login_bundle al suo interno. update_updated_at_column(): tolto l'EXECUTE ad anon (pulizia).
--   RPC chiamabili con la chiave pubblicabile: app_release, change_password, change_team_name,
--   change_username, get_snapshot, league_context, login_bundle, logout, save_lineup, token_bundle.
