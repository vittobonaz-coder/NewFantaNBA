-- Fase 2, migrazione A: contesto della lega, snapshot e login in un colpo solo (novembre 2026).
-- Da eseguire nello SQL Editor di Supabase, PRIMA di pubblicare il nuovo codice su main.
--
-- SOLO AGGIUNTE: la versione web su Render e il cron attuali continuano a funzionare senza modifiche.
--   - nuove tabelle edit_override e app_snapshot, chiuse ad anon (si leggono solo dalle RPC);
--   - vincolo unico (squadra, giornata, slot) reso DEFERRABLE INITIALLY IMMEDIATE: la save_lineup
--     attuale (slot temporanei +100) continua a funzionare;
--   - change_team_name rigenera anche lo snapshot (stesso comportamento visto dal vecchio codice);
--   - nuove RPC: login_bundle, token_bundle, get_snapshot, league_context (app);
--     record_run, refresh_snapshot (solo service_role: cron, script, SQL Editor).
--
-- Ordine della Fase 2:  A (questo file) -> nuovo codice su main -> B (scadenza dei cambi in save_lineup).
--
-- Snapshot: i dati uguali per tutti, divisi in parti con versione = md5 del contenuto.
--   calendar   matchups (con i nomi delle squadre) e partite NBA
--   standings  righe di v_standings
--   injuries   righe di player_injuries
--   lineups    formazioni di tutte le squadre nella giornata in corso (tab "Altre squadre")
-- La versione cambia solo se il contenuto cambia: un run del cron che non scrive nulla (fallito, saltato)
-- non fa riscaricare niente; il cron degli infortuni cambia solo la parte injuries.
-- Dopo una correzione fatta a mano nello SQL Editor:  select public.refresh_snapshot();

begin;

-- 1. Deroga ai cambi (prima: variabili EDIT_OVERRIDE_GW / EDIT_OVERRIDE_UNTIL su Render) -----------------
-- Al massimo una riga. Riapre i cambi sulla giornata in corso fino a until_at. Esempio in fondo al file.

create table if not exists public.edit_override (
    id boolean primary key default true check (id),
    gameweek integer not null,
    until_at timestamptz not null,
    note text,
    updated_at timestamptz not null default now()
);
alter table public.edit_override enable row level security;
revoke all on public.edit_override from public, anon, authenticated;


-- 2. Contesto della lega: stessa regola di TimeManager.get_league_context ---------------------------------
-- current_gw: giornata in corso (null prima del campionato); edit_gw: prima giornata non iniziata, a cui si
-- applicano i cambi (null a fine campionato); deadline: rollover (23:59 di Roma) della vigilia di edit_gw.
-- Dalle 23:59 di Roma conta già il giorno dopo. now: ora del server (l'app corregge l'orologio del dispositivo).

create or replace function private.league_context(p_now timestamptz default now())
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_today date := (p_now at time zone 'Europe/Rome')::date;
    v_league_day date;
    v_current integer;
    v_edit integer;
    v_edit_start date;
    v_deadline timestamptz;
    v_override record;
begin
    v_league_day := case when p_now < ((v_today + time '23:59') at time zone 'Europe/Rome')
                         then v_today else v_today + 1 end;

    select r.gameweek into v_current
    from (select m.gameweek, min(m.start_date) as start_date
          from public.matchups m where m.start_date is not null group by m.gameweek) r
    where r.start_date <= v_league_day
    order by r.start_date desc, r.gameweek desc
    limit 1;

    select r.gameweek, r.start_date into v_edit, v_edit_start
    from (select m.gameweek, min(m.start_date) as start_date
          from public.matchups m where m.start_date is not null group by m.gameweek) r
    where r.start_date > v_league_day
    order by r.start_date, r.gameweek
    limit 1;
    if v_edit is not null then
        v_deadline := ((v_edit_start - 1) + time '23:59') at time zone 'Europe/Rome';
    end if;

    -- Deroga: cambi riaperti sulla giornata in corso fino a until_at
    select o.gameweek, o.until_at into v_override from public.edit_override o limit 1;
    if found and v_current = v_override.gameweek and p_now < v_override.until_at then
        v_edit := v_override.gameweek;
        v_deadline := v_override.until_at;
    end if;

    return jsonb_build_object('current_gw', v_current, 'edit_gw', v_edit, 'deadline', v_deadline, 'now', p_now);
end;
$$;


-- 3. Vincolo unico DEFERRABLE ------------------------------------------------------------------------------
-- INITIALLY IMMEDIATE: si controlla a fine istruzione invece che riga per riga, quindi un solo UPDATE può
-- scambiare gli slot (migrazione B). Per cron e script non cambia nulla. Nessun upsert usa questo vincolo.

alter table public.lineup_players
    drop constraint if exists lineup_players_team_gw_slot_key,
    add constraint lineup_players_team_gw_slot_key unique (fanta_team_id, gameweek, slot)
        deferrable initially immediate;


-- 4. Snapshot ------------------------------------------------------------------------------------------------

create table if not exists public.app_snapshot (
    part text primary key check (part in ('calendar', 'standings', 'injuries', 'lineups')),
    version text not null,                              -- md5 di data
    data jsonb not null,
    updated_at timestamptz not null default now(),      -- ultima modifica del contenuto
    checked_at timestamptz not null default now()       -- ultima rigenerazione (anche senza modifiche)
);
alter table public.app_snapshot enable row level security;
revoke all on public.app_snapshot from public, anon, authenticated;

-- Contenuto di una parte: righe nella stessa forma delle letture PostgREST che l'app faceva prima,
-- così l'app le trasforma con lo stesso codice Python. Ordine fisso: la versione dipende solo dai dati.
create or replace function private.snapshot_part(p_part text)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_gw integer;
begin
    if p_part = 'calendar' then
        return jsonb_build_object(
            'matchups', coalesce((
                select jsonb_agg(jsonb_build_object(
                    'gameweek', m.gameweek, 'start_date', m.start_date, 'end_date', m.end_date,
                    'home_score', m.home_score, 'away_score', m.away_score, 'was_played', m.was_played,
                    'home_lineup', m.home_lineup, 'away_lineup', m.away_lineup,
                    'home_team', case when h.id is null then null else jsonb_build_object('name', h.name) end,
                    'away_team', case when a.id is null then null else jsonb_build_object('name', a.name) end
                ) order by m.gameweek, h.name, a.name, m.id)
                from public.matchups m
                left join public.fanta_teams h on h.id = m.home_team_id
                left join public.fanta_teams a on a.id = m.away_team_id
            ), '[]'::jsonb),
            'nba_games', coalesce((
                select jsonb_agg(jsonb_build_object(
                    'gameweek', g.gameweek, 'nba_date', g.nba_date, 'start_time', g.start_time,
                    'home_team', g.home_team, 'away_team', g.away_team,
                    'home_score', g.home_score, 'away_score', g.away_score, 'status', g.status
                ) order by g.start_time, g.game_id)
                from public.nba_games g
            ), '[]'::jsonb)
        );
    elsif p_part = 'standings' then
        return coalesce((
            select jsonb_agg(to_jsonb(s) order by s.standing_points desc, s.total_score desc, s.team_name)
            from public.v_standings s
        ), '[]'::jsonb);
    elsif p_part = 'injuries' then
        return coalesce((
            select jsonb_agg(jsonb_build_object(
                'nba_player_id', i.nba_player_id, 'status', i.status, 'fantasy_status', i.fantasy_status,
                'injury_type', i.injury_type, 'return_date', i.return_date
            ) order by i.nba_player_id)
            from public.player_injuries i
        ), '[]'::jsonb);
    elsif p_part = 'lineups' then
        v_gw := (private.league_context() ->> 'current_gw')::integer;
        return jsonb_build_object(
            'gameweek', v_gw,
            'teams', coalesce((
                select jsonb_agg(jsonb_build_object('id', t.id, 'name', t.name) order by t.name)
                from public.fanta_teams t
            ), '[]'::jsonb),
            'rows', coalesce((
                select jsonb_agg(private.lineup_row_json(lp) order by lp.fanta_team_id, lp.slot)
                from public.lineup_players lp
                where lp.gameweek = v_gw
            ), '[]'::jsonb),
            'lineups', coalesce((
                select jsonb_object_agg(x.team_id, x.lineup)
                from (select m.home_team_id as team_id, m.home_lineup as lineup
                      from public.matchups m where m.gameweek = v_gw and m.home_team_id is not null
                      union all
                      select m.away_team_id, m.away_lineup
                      from public.matchups m where m.gameweek = v_gw and m.away_team_id is not null) x
            ), '{}'::jsonb)
        );
    end if;
    raise exception 'Parte dello snapshot sconosciuta: %', p_part;
end;
$$;

-- Riga di lineup_players come la leggeva l'app: select("*, nba_players(nba_team, position)")
create or replace function private.lineup_row_json(lp public.lineup_players)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select jsonb_build_object(
        'fanta_team_id', lp.fanta_team_id, 'gameweek', lp.gameweek, 'nba_player_id', lp.nba_player_id,
        'slot', lp.slot, 'score', lp.score, 'player_name', lp.player_name, 'role', lp.role,
        'target_date', lp.target_date, 'entered_game', lp.entered_game, 'auto_sub', lp.auto_sub,
        'nba_players', (select jsonb_build_object('nba_team', p.nba_team, 'position', p.position)
                        from public.nba_players p where p.id = lp.nba_player_id)
    );
$$;

-- Rigenera le parti indicate (tutte se null). Il contenuto e la versione cambiano solo se i dati sono diversi;
-- checked_at si aggiorna sempre. Restituisce {parte: versione}.
create or replace function private.refresh_snapshot(p_parts text[] default null)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_part text;
    v_data jsonb;
    v_version text;
begin
    perform pg_advisory_xact_lock(hashtext('fantanba.app_snapshot'));  -- un refresh alla volta
    foreach v_part in array coalesce(p_parts, array['calendar', 'standings', 'injuries', 'lineups']) loop
        v_data := private.snapshot_part(v_part);
        v_version := md5(v_data::text);
        update public.app_snapshot s
        set checked_at = now(),
            data = case when s.version = v_version then s.data else v_data end,
            updated_at = case when s.version = v_version then s.updated_at else now() end,
            version = v_version
        where s.part = v_part;
        if not found then
            insert into public.app_snapshot (part, version, data) values (v_part, v_version, v_data);
        end if;
    end loop;
    return (select jsonb_object_agg(s.part, s.version) from public.app_snapshot s);
end;
$$;

-- Rete di sicurezza: rigenera se manca qualche parte, se un run del cron è finito dopo l'ultima rigenerazione
-- (cron ancora sul vecchio codice) o se la giornata in corso non è più quella della parte lineups
-- (dalle 23:59 della vigilia, prima che finisca il rollover).
create or replace function private.ensure_snapshot(p_ctx jsonb)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    if (select count(*) from public.app_snapshot) < 4
       or (select min(s.checked_at) from public.app_snapshot s)
          < coalesce((select max(c.finished_at) from public.cron_runs c), '-infinity'::timestamptz) then
        perform private.refresh_snapshot();
    elsif (select (s.data ->> 'gameweek')::integer from public.app_snapshot s where s.part = 'lineups')
          is distinct from (p_ctx ->> 'current_gw')::integer then
        perform private.refresh_snapshot(array['lineups']);
    end if;
end;
$$;

-- {versions: {parte: versione}, parts: {parte: dati}} con le sole parti diverse da quelle che il client ha già
create or replace function private.snapshot_since(p_versions jsonb)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select jsonb_build_object(
        'versions', coalesce(jsonb_object_agg(s.part, s.version), '{}'::jsonb),
        'parts', coalesce(jsonb_object_agg(s.part, s.data)
                          filter (where s.version is distinct from (coalesce(p_versions, '{}'::jsonb) ->> s.part)),
                          '{}'::jsonb)
    )
    from public.app_snapshot s;
$$;

-- Formazione della squadra nella giornata: {gameweek, lineup, rows} (null se la giornata è null)
create or replace function private.team_lineup_json(p_team uuid, p_gw integer)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select case when p_gw is null then null else jsonb_build_object(
        'gameweek', p_gw,
        'lineup', (select case when m.home_team_id = p_team then m.home_lineup else m.away_lineup end
                   from public.matchups m
                   where m.gameweek = p_gw and (m.home_team_id = p_team or m.away_team_id = p_team)
                   limit 1),
        'rows', coalesce((select jsonb_agg(private.lineup_row_json(lp) order by lp.slot)
                          from public.lineup_players lp
                          where lp.fanta_team_id = p_team and lp.gameweek = p_gw), '[]'::jsonb)
    ) end;
$$;

-- Tutto ciò che serve all'app dopo l'accesso, tranne profilo e token
create or replace function private.bundle_data(p_user uuid, p_versions jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_ctx jsonb := private.league_context();
    v_team uuid;
begin
    perform private.ensure_snapshot(v_ctx);
    select t.id into v_team from public.fanta_teams t where t.user_id = p_user order by t.name limit 1;
    return jsonb_build_object(
        'context', v_ctx,
        'my_team', case when v_team is null then null
                        else private.team_lineup_json(v_team, (v_ctx ->> 'edit_gw')::integer) end
    ) || private.snapshot_since(p_versions);
end;
$$;

revoke all on all functions in schema private from public, anon, authenticated;


-- 5. RPC dell'app -----------------------------------------------------------------------------------------

-- Login in una richiesta: profilo e token (come login) + contesto, formazione modificabile della propria
-- squadra e parti dello snapshot diverse da p_versions ({"calendar": "<versione>", ...} della cache locale).
-- null con credenziali errate.
create or replace function public.login_bundle(p_username text, p_password text, p_remember boolean default false,
                                               p_versions jsonb default '{}'::jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_login jsonb := public.login(p_username, p_password, p_remember);
begin
    if v_login is null then
        return null;
    end if;
    return v_login || private.bundle_data((v_login ->> 'id')::uuid, p_versions);
end;
$$;

-- Accesso automatico con il token salvato sul dispositivo: come login_bundle, senza token nella risposta.
-- null se il token è scaduto o revocato.
create or replace function public.token_bundle(p_token text, p_versions jsonb default '{}'::jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_user uuid;
begin
    select t.user_id into v_user
    from public.login_tokens t
    where t.token_hash = private.token_hash(coalesce(p_token, ''))
      and t.expires_at > now();
    if v_user is null then
        return null;
    end if;
    return private.profile_json(v_user) || private.bundle_data(v_user, p_versions);
end;
$$;

-- Aggiornamento senza accesso (ripresa dall'app in background, dopo il cambio nome squadra):
-- {context, versions, parts}
create or replace function public.get_snapshot(p_versions jsonb default '{}'::jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_ctx jsonb := private.league_context();
begin
    perform private.ensure_snapshot(v_ctx);
    return jsonb_build_object('context', v_ctx) || private.snapshot_since(p_versions);
end;
$$;

-- Contesto della lega (giornate e scadenza dei cambi), per script e app
create or replace function public.league_context()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select private.league_context();
$$;

-- Fine di un run del cron o di una modifica manuale (swap_players.py): registra il run in cron_runs e
-- rigenera lo snapshot nella stessa transazione. Restituisce le versioni. Solo chiave segreta.
create or replace function public.record_run(p_mode text, p_ok boolean)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.cron_runs (mode, finished_at, ok) values (p_mode, now(), p_ok)
    on conflict (mode) do update set finished_at = excluded.finished_at, ok = excluded.ok;
    return private.refresh_snapshot();
end;
$$;

-- Rigenerazione manuale (SQL Editor, script). Solo chiave segreta.
create or replace function public.refresh_snapshot()
returns jsonb
language sql
security definer
set search_path = ''
as $$
    select private.refresh_snapshot();
$$;

-- Cambio nome squadra: come nella Fase 1, più la rigenerazione delle parti che contengono i nomi
create or replace function public.change_team_name(p_token text, p_password text, p_new_name text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_user uuid := private.token_user(p_token);
    v_name text := btrim(coalesce(p_new_name, ''));
    v_team uuid;
begin
    perform private.require_password(v_user, p_password);
    perform private.validate_name(v_name, 'Il nome squadra');
    if v_name ~ '[/\\:*?"<>|]' then
        raise exception 'Il nome squadra non può contenere / \ : * ? " < > |' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;

    select t.id into v_team from public.fanta_teams t where t.user_id = v_user order by t.name limit 1;
    if v_team is null then
        raise exception 'Nessuna squadra associata al profilo' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    if exists (select 1 from public.fanta_teams t
               where lower(replace(t.name, ' ', '_')) = lower(replace(v_name, ' ', '_')) and t.id <> v_team) then
        raise exception 'Il nome ''%'' è già usato da un''altra squadra', v_name using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    update public.fanta_teams set name = v_name where id = v_team;
    perform private.refresh_snapshot(array['calendar', 'standings', 'lineups']);
end;
$$;


-- 6. Permessi delle funzioni -----------------------------------------------------------------------------

revoke all on function public.login_bundle(text, text, boolean, jsonb) from public, anon, authenticated;
revoke all on function public.token_bundle(text, jsonb)                from public, anon, authenticated;
revoke all on function public.get_snapshot(jsonb)                      from public, anon, authenticated;
revoke all on function public.league_context()                         from public, anon, authenticated;
revoke all on function public.record_run(text, boolean)                from public, anon, authenticated;
revoke all on function public.refresh_snapshot()                       from public, anon, authenticated;

grant execute on function public.login_bundle(text, text, boolean, jsonb) to anon, authenticated, service_role;
grant execute on function public.token_bundle(text, jsonb)                to anon, authenticated, service_role;
grant execute on function public.get_snapshot(jsonb)                      to anon, authenticated, service_role;
grant execute on function public.league_context()                         to anon, authenticated, service_role;
grant execute on function public.record_run(text, boolean)                to service_role;
grant execute on function public.refresh_snapshot()                       to service_role;
-- change_team_name: permessi invariati (create or replace li conserva)


-- 7. Prima rigenerazione ---------------------------------------------------------------------------------

select private.refresh_snapshot();

commit;

-- PostgREST rilegge lo schema: le RPC sono subito chiamabili
notify pgrst, 'reload schema';


-- =====================================================================================================
-- VERIFICA (da eseguire dopo, una query alla volta)
-- =====================================================================================================
--
-- 1. Parti dello snapshot e dimensioni (attese 4 righe; calendar la più grande, qualche centinaio di KB)
-- select part, version, pg_column_size(data) as byte_compressi, length(data::text) as byte_testo, updated_at
-- from public.app_snapshot order by part;
--
-- 2. Contesto della lega adesso (confrontalo con quello che mostra l'app)
-- select public.league_context();
--
-- 3. Vincolo deferrable (atteso: condeferrable = true, condeferred = false)
-- select conname, condeferrable, condeferred from pg_constraint where conname = 'lineup_players_team_gw_slot_key';
--
-- 4. Funzioni e chi può eseguirle (attesi: anon_execute true per login_bundle, token_bundle, get_snapshot,
--    league_context; false per record_run, refresh_snapshot e per tutte quelle di private)
-- select n.nspname, p.proname, has_function_privilege('anon', p.oid, 'execute') as anon_execute
-- from pg_proc p join pg_namespace n on n.oid = p.pronamespace
-- where n.nspname in ('public', 'private') order by n.nspname, p.proname;
--
-- 5. Tabelle nuove chiuse ad anon (atteso: false, false)
-- select has_table_privilege('anon', 'public.app_snapshot', 'select'), has_table_privilege('anon', 'public.edit_override', 'select');
--
-- 6. Tempo del bundle senza versioni (tutte le parti) e con le versioni attuali (nessuna parte)
-- explain analyze select public.get_snapshot('{}');
-- explain analyze select public.get_snapshot((select jsonb_object_agg(part, version) from public.app_snapshot));


-- =====================================================================================================
-- DEROGA AI CAMBI (al posto di EDIT_OVERRIDE_GW / EDIT_OVERRIDE_UNTIL su Render)
-- =====================================================================================================
--
-- Riapre i cambi della giornata in corso (es. 3) fino alle 23:59 italiane del 04/11/2026:
-- insert into public.edit_override (id, gameweek, until_at, note)
-- values (true, 3, '2026-11-04 23:59'::timestamp at time zone 'Europe/Rome', 'rinvio partite')
-- on conflict (id) do update set gameweek = excluded.gameweek, until_at = excluded.until_at,
--                                note = excluded.note, updated_at = now();
-- select public.refresh_snapshot();
--
-- Toglie la deroga:
-- delete from public.edit_override;


-- =====================================================================================================
-- ROLLBACK (solo se serve tornare indietro; il codice in produzione prima della Fase 2 non usa nulla di questo)
-- =====================================================================================================
--
-- begin;
-- drop function if exists public.login_bundle(text, text, boolean, jsonb);
-- drop function if exists public.token_bundle(text, jsonb);
-- drop function if exists public.get_snapshot(jsonb);
-- drop function if exists public.league_context();
-- drop function if exists public.record_run(text, boolean);
-- drop function if exists public.refresh_snapshot();
-- drop function if exists private.bundle_data(uuid, jsonb);
-- drop function if exists private.team_lineup_json(uuid, integer);
-- drop function if exists private.snapshot_since(jsonb);
-- drop function if exists private.ensure_snapshot(jsonb);
-- drop function if exists private.refresh_snapshot(text[]);
-- drop function if exists private.snapshot_part(text);
-- drop function if exists private.lineup_row_json(public.lineup_players);
-- drop function if exists private.league_context(timestamptz);
-- drop table if exists public.app_snapshot;
-- drop table if exists public.edit_override;
-- -- change_team_name: rieseguire la sua definizione da sql/2026-11_fase1a_password_rpc.sql
-- -- Il vincolo deferrable può restare (compatibile con tutto il codice).
-- commit;
-- notify pgrst, 'reload schema';
