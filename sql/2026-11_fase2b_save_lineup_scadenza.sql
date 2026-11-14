-- Fase 2, migrazione B: scadenza dei cambi controllata dal database in save_lineup (novembre 2026).
-- Da eseguire nello SQL Editor di Supabase DOPO la migrazione A e DOPO aver pubblicato su main il codice
-- della Fase 2 (che legge scadenza e deroga dal database).
--
-- RESTRITTIVA: da qui save_lineup accetta solo la giornata modificabile (edit_gw) e solo prima della
-- scadenza calcolate da private.league_context. Prima di eseguirla:
--   - controlla che su Render NON siano impostate EDIT_OVERRIDE_GW / EDIT_OVERRIDE_UNTIL; se c'è una deroga
--     in corso, copiala in public.edit_override (esempio in sql/2026-11_fase2a_snapshot_bundle.sql);
--   - la firma resta la stessa: il codice vecchio e quello nuovo la chiamano allo stesso modo.
--
-- Altre modifiche:
--   - un solo UPDATE degli slot (il vincolo unico è DEFERRABLE dalla migrazione A): via gli slot temporanei +100;
--   - se il salvataggio tocca la giornata in corso (deroga), rigenera le parti lineups e calendar dello snapshot.

begin;

create or replace function public.save_lineup(p_token text, p_gameweek integer, p_players jsonb, p_lineup text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_user uuid := private.token_user(p_token);
    v_team uuid;
    v_count integer;
    v_ctx jsonb := private.league_context();
begin
    select t.id into v_team from public.fanta_teams t where t.user_id = v_user order by t.name limit 1;
    if v_team is null then
        raise exception 'Nessuna squadra associata al profilo' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;

    -- Scadenza dei cambi: solo la giornata modificabile e solo prima del rollover della vigilia (o della deroga)
    if p_gameweek is distinct from (v_ctx ->> 'edit_gw')::integer
       or (v_ctx ->> 'deadline') is null
       or now() >= (v_ctx ->> 'deadline')::timestamptz then
        raise exception 'Cambi chiusi: formazione non salvata' using errcode = 'P0001', hint = 'CAMBI_CHIUSI';
    end if;

    if p_lineup is null or p_lineup not in ('2-2-1', '2-1-2', '1-2-2', '3-1-1', '1-3-1') then  -- LINEUP_ROLES
        raise exception 'Modulo non valido: %', p_lineup using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    if jsonb_typeof(p_players) is distinct from 'array' then
        raise exception 'Dati della formazione non validi' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;

    -- 15 giocatori diversi, slot 1-15 tutti diversi, ruoli ammessi (ROSTER_SIZE, ROLE_MULTIPLIERS)
    select count(*) into v_count from jsonb_to_recordset(p_players) as i(nba_player_id integer, slot integer, role text);
    if v_count <> 15
       or (select count(distinct i.nba_player_id)
           from jsonb_to_recordset(p_players) as i(nba_player_id integer, slot integer, role text)) <> 15
       or (select count(distinct i.slot)
           from jsonb_to_recordset(p_players) as i(nba_player_id integer, slot integer, role text)
           where i.slot between 1 and 15) <> 15
       or exists (select 1
                  from jsonb_to_recordset(p_players) as i(nba_player_id integer, slot integer, role text)
                  where i.nba_player_id is null
                     or i.role is null or i.role not in ('STARTER', 'SIXTH', 'BENCH', 'RESERVE')) then
        raise exception 'Dati della formazione non validi' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;

    -- La rosa in app deve coincidere con quella su Supabase per la giornata (es. dopo swap_players.py)
    if exists (
        (select lp.nba_player_id from public.lineup_players lp
         where lp.fanta_team_id = v_team and lp.gameweek = p_gameweek
         except
         select i.nba_player_id from jsonb_to_recordset(p_players) as i(nba_player_id integer, slot integer, role text))
        union all
        (select i.nba_player_id from jsonb_to_recordset(p_players) as i(nba_player_id integer, slot integer, role text)
         except
         select lp.nba_player_id from public.lineup_players lp
         where lp.fanta_team_id = v_team and lp.gameweek = p_gameweek)
    ) then
        raise exception 'La tua rosa è cambiata: ricarica la pagina e rifai i cambi'
            using errcode = 'P0001', hint = 'ROSA_CAMBIATA';
    end if;

    -- Ruolo nella rosa
    update public.rosters r set assigned_position = i.role
    from jsonb_to_recordset(p_players) as i(nba_player_id integer, slot integer, role text)
    where r.fanta_team_id = v_team and r.nba_player_id = i.nba_player_id;

    -- Slot e ruolo dalla giornata p_gameweek in poi, in un solo UPDATE: il vincolo unico (squadra, giornata,
    -- slot) è DEFERRABLE e si controlla a fine istruzione, quindi gli slot si possono scambiare direttamente
    update public.lineup_players lp set slot = i.slot, role = i.role
    from jsonb_to_recordset(p_players) as i(nba_player_id integer, slot integer, role text)
    where lp.fanta_team_id = v_team and lp.gameweek >= p_gameweek and lp.nba_player_id = i.nba_player_id;

    -- Modulo: le giornate precedenti restano come storico
    update public.matchups set home_lineup = p_lineup where home_team_id = v_team and gameweek >= p_gameweek;
    update public.matchups set away_lineup = p_lineup where away_team_id = v_team and gameweek >= p_gameweek;

    -- Deroga sulla giornata in corso: le altre squadre la vedono dallo snapshot
    if p_gameweek <= coalesce((v_ctx ->> 'current_gw')::integer, 0) then
        perform private.refresh_snapshot(array['lineups', 'calendar']);
    end if;
end;
$$;

-- Permessi invariati (create or replace li conserva): anon, authenticated, service_role

commit;

notify pgrst, 'reload schema';


-- =====================================================================================================
-- VERIFICA
-- =====================================================================================================
--
-- 1. Definizione aggiornata (atteso: true, true)
-- select prosrc like '%CAMBI_CHIUSI%' as scadenza, prosrc not like '%+ 100%' as senza_slot_temporanei
-- from pg_proc where proname = 'save_lineup';
--
-- 2. Dall'app: salvataggio a cambi aperti riuscito; con una giornata sbagliata (non provabile dall'app)
--    l'errore "Cambi chiusi" lo verifica la prova su Postgres locale.


-- =====================================================================================================
-- ROLLBACK: rieseguire la definizione di save_lineup in sql/2026-11_fase1a_password_rpc.sql (slot +100,
-- senza controllo della scadenza). Funziona anche con il vincolo deferrable.
-- =====================================================================================================
