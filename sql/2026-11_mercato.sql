-- Mercato (novembre 2026): offerte di scambio con i free agent e chiusura automatica delle finestre.
-- Da eseguire nello SQL Editor di Supabase, in due passi:
--   1. la PARTE 1 (tabelle e funzioni), poi lo script carica_giocatori.py (tutti i giocatori in nba_players);
--   2. la PARTE 2 (job di pg_cron), solo dopo aver controllato la PARTE 1 con le query di VERIFICA.
--
-- SOLO AGGIUNTE: webapp e app già pubblicate continuano a funzionare (nessuna firma esistente cambia).
--
-- Regole (decise il 26/11/2026):
--   - una finestra chiude alle 19:00 (ora di Roma) dell'ultimo giorno delle giornate 6, 8, ..., 22;
--     i nuovi giocatori valgono dalla giornata successiva;
--   - un'offerta = "cedo un giocatore del mio roster, prendo un free agent" (giocatore in nessun roster);
--   - offerte attive per squadra <= numero di squadre + 1; le annullate non contano;
--   - alla chiusura si procede dall'ultimo al primo di v_standings (stesso ordine della classifica):
--     ogni squadra ottiene la sua prima offerta (in ordine di inserimento) ancora realizzabile, al massimo una;
--   - realizzabile = free agent non ancora preso, e dopo lo scambio il roster ha almeno una guardia, un'ala
--     e un centro, tre giocatori diversi (un "Guard-Forward" o "G/A" vale come guardia o come ala, non tutte e due);
--   - le offerte restano segrete: anon e authenticated non leggono le tabelle; dalle RPC ognuno vede solo
--     le proprie, e dopo la chiusura gli scambi eseguiti di tutti.
--
-- Nuovo in nba_players: espn_id (senza, il cron non saprebbe dare il punteggio al giocatore) e search_name
-- (nome normalizzato con nomi.normalize_name, per trovare il giocatore incollato dall'Excel).


-- =====================================================================================================
-- PARTE 1: tabelle e funzioni
-- =====================================================================================================

begin;

-- 1. Giocatori: ID ESPN e nome per la ricerca (li riempie carica_giocatori.py) ---------------------------

alter table public.nba_players add column if not exists espn_id text;
alter table public.nba_players add column if not exists search_name text;
create index if not exists nba_players_search_name_idx on public.nba_players (search_name);


-- 2. Finestre di mercato ----------------------------------------------------------------------------------

create table if not exists public.market_windows (
    gameweek integer primary key,           -- la finestra chiude alla fine di questa giornata
    closes_at timestamptz not null,         -- dopo questo istante niente più offerte
    first_gameweek integer not null,        -- prima giornata con i nuovi giocatori
    closed_at timestamptz,                  -- quando gli scambi sono stati eseguiti (null = da eseguire)
    result jsonb                            -- riepilogo dell'esecuzione (ordine usato, scambi)
);
alter table public.market_windows enable row level security;
revoke all on public.market_windows from public, anon, authenticated;

-- Giornate pari dalla 6 alla penultima, 19:00 di Roma dell'ultimo giorno (ora legale compresa)
insert into public.market_windows (gameweek, closes_at, first_gameweek)
select m.gameweek, (max(m.end_date) + time '19:00') at time zone 'Europe/Rome', m.gameweek + 1
from public.matchups m
where m.gameweek >= 6 and m.gameweek % 2 = 0
  and m.gameweek < (select max(gameweek) from public.matchups)
group by m.gameweek
on conflict (gameweek) do nothing;


-- 3. Offerte ------------------------------------------------------------------------------------------------

create table if not exists public.market_offers (
    id bigint generated always as identity primary key,    -- ordine di inserimento = priorità
    window_gw integer not null references public.market_windows (gameweek),
    fanta_team_id uuid not null references public.fanta_teams (id) on delete cascade,
    out_player_id integer not null references public.nba_players (id),
    in_player_id integer not null references public.nba_players (id),
    status text not null default 'attiva'
        check (status in ('attiva', 'annullata', 'eseguita', 'non_eseguita')),
    note text,                                              -- motivo, se non eseguita
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
alter table public.market_offers enable row level security;
revoke all on public.market_offers from public, anon, authenticated;

create unique index if not exists market_offers_attiva_key
    on public.market_offers (window_gw, fanta_team_id, out_player_id, in_player_id) where status = 'attiva';
create index if not exists market_offers_window_idx on public.market_offers (window_gw, fanta_team_id, id);


-- 4. Regole -------------------------------------------------------------------------------------------------

-- Squadra del profilo (stessa scelta di save_lineup)
create or replace function private.user_team(p_user uuid)
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
    select t.id from public.fanta_teams t where t.user_id = p_user order by t.name limit 1;
$$;

-- Dopo lo scambio (p_out esce, p_in entra) il roster ha una guardia, un'ala e un centro, tre giocatori diversi
-- Ruoli di un giocatore come codici dell'app: 'Forward-Guard' -> {A,G}, 'G/A' -> {G,A}, 'Center' -> {C}.
-- Nel database convivono i due formati (vedi Player.get_clean_position in fanta_obj.py, stessa traduzione).
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

-- Finestra in cui si fanno offerte adesso. Errore se una finestra è scaduta ma non ancora eseguita
-- (i free agent stanno per cambiare) o se non ce ne sono altre.
create or replace function private.market_open_window(p_now timestamptz default now())
returns public.market_windows
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_window public.market_windows;
begin
    if exists (select 1 from public.market_windows w where w.closed_at is null and w.closes_at <= p_now) then
        raise exception 'Mercato in chiusura: riprova tra qualche minuto'
            using errcode = 'P0001', hint = 'MERCATO_CHIUSO';
    end if;
    select * into v_window from public.market_windows w
    where w.closed_at is null and w.closes_at > p_now
    order by w.closes_at limit 1;
    if not found then
        raise exception 'Non ci sono altre finestre di mercato' using errcode = 'P0001', hint = 'MERCATO_CHIUSO';
    end if;
    return v_window;
end;
$$;


-- 5. Stato del mercato per l'app ----------------------------------------------------------------------------
-- Finestra aperta (o null), massimo di offerte, le mie offerte (in ordine), l'ultima finestra eseguita
-- con i miei esiti e gli scambi eseguiti da tutti.

create or replace function private.market_state(p_team uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_open public.market_windows;
    v_last public.market_windows;
    v_closing boolean;
begin
    v_closing := exists (select 1 from public.market_windows w where w.closed_at is null and w.closes_at <= now());
    if not v_closing then
        select * into v_open from public.market_windows w
        where w.closed_at is null and w.closes_at > now() order by w.closes_at limit 1;
    end if;
    select * into v_last from public.market_windows w where w.closed_at is not null order by w.gameweek desc limit 1;

    return jsonb_build_object(
        'now', now(),
        'closing', v_closing,
        'window', case when v_open.gameweek is null then null else jsonb_build_object(
            'gameweek', v_open.gameweek, 'closes_at', v_open.closes_at, 'first_gameweek', v_open.first_gameweek)
        end,
        'max_offers', (select count(*) + 1 from public.fanta_teams),
        'offers', coalesce((
            select jsonb_agg(jsonb_build_object(
                'id', o.id, 'out_id', o.out_player_id, 'out_name', po.full_name,
                'in_id', o.in_player_id, 'in_name', pi.full_name, 'in_team', pi.nba_team,
                'in_position', pi.position, 'created_at', o.created_at) order by o.id)
            from public.market_offers o
            join public.nba_players po on po.id = o.out_player_id
            join public.nba_players pi on pi.id = o.in_player_id
            where o.window_gw = v_open.gameweek and o.fanta_team_id = p_team and o.status = 'attiva'
        ), '[]'::jsonb),
        'last', case when v_last.gameweek is null then null else jsonb_build_object(
            'gameweek', v_last.gameweek, 'closed_at', v_last.closed_at,
            'my_offers', coalesce((
                select jsonb_agg(jsonb_build_object(
                    'out_name', po.full_name, 'in_name', pi.full_name, 'status', o.status, 'note', o.note)
                    order by o.id)
                from public.market_offers o
                join public.nba_players po on po.id = o.out_player_id
                join public.nba_players pi on pi.id = o.in_player_id
                where o.window_gw = v_last.gameweek and o.fanta_team_id = p_team and o.status <> 'annullata'
            ), '[]'::jsonb),
            'trades', coalesce((
                select jsonb_agg(jsonb_build_object(
                    'team', t.name, 'out_name', po.full_name, 'in_name', pi.full_name) order by t.name)
                from public.market_offers o
                join public.fanta_teams t on t.id = o.fanta_team_id
                join public.nba_players po on po.id = o.out_player_id
                join public.nba_players pi on pi.id = o.in_player_id
                where o.window_gw = v_last.gameweek and o.status = 'eseguita'
            ), '[]'::jsonb))
        end
    );
end;
$$;

create or replace function public.market_state(p_token text)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_team uuid := private.user_team(private.token_user(p_token));
begin
    if v_team is null then
        raise exception 'Nessuna squadra associata al profilo' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    return private.market_state(v_team);
end;
$$;


-- 6. Fare e annullare un'offerta ----------------------------------------------------------------------------
-- p_in_name: nome del free agent già normalizzato dall'app (nomi.normalize_name), confrontato con search_name.
-- Restituisce lo stato aggiornato (come market_state).

create or replace function public.market_offer(p_token text, p_out_player integer, p_in_name text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_team uuid := private.user_team(private.token_user(p_token));
    v_window public.market_windows := private.market_open_window();
    v_in integer;
    v_matches integer;
    v_espn text;
begin
    if v_team is null then
        raise exception 'Nessuna squadra associata al profilo' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    -- Un'offerta alla volta per squadra: due richieste insieme non superano il limite
    perform pg_advisory_xact_lock(hashtext('fantanba.market_offer.' || v_team::text));

    if not exists (select 1 from public.rosters r where r.fanta_team_id = v_team and r.nba_player_id = p_out_player) then
        raise exception 'Il giocatore da cedere non è nel tuo roster' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;

    select count(*), min(p.id) into v_matches, v_in
    from public.nba_players p where p.search_name = btrim(coalesce(p_in_name, ''));
    if v_matches = 0 then
        raise exception 'Giocatore non trovato: copia il nome esattamente come nell''Excel'
            using errcode = 'P0001', hint = 'NON_TROVATO';
    elsif v_matches > 1 then
        raise exception 'Nome ambiguo: più giocatori con lo stesso nome, scrivi all''amministratore'
            using errcode = 'P0001', hint = 'NON_TROVATO';
    end if;

    if exists (select 1 from public.rosters r where r.nba_player_id = v_in) then
        raise exception 'Il giocatore richiesto non è libero: è già in un roster'
            using errcode = 'P0001', hint = 'NON_LIBERO';
    end if;
    select p.espn_id into v_espn from public.nba_players p where p.id = v_in;
    if v_espn is null then
        raise exception 'Giocatore non ancora gestito dal calcolo dei punteggi: scrivi all''amministratore'
            using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    if not private.market_roles_ok(v_team, p_out_player, v_in) then
        raise exception 'Con questo scambio il roster resterebbe senza una guardia, un''ala o un centro'
            using errcode = 'P0001', hint = 'RUOLI';
    end if;
    if exists (select 1 from public.market_offers o
               where o.window_gw = v_window.gameweek and o.fanta_team_id = v_team and o.status = 'attiva'
                 and o.out_player_id = p_out_player and o.in_player_id = v_in) then
        raise exception 'Hai già fatto questa offerta' using errcode = 'P0001', hint = 'DOPPIONE';
    end if;
    if (select count(*) from public.market_offers o
        where o.window_gw = v_window.gameweek and o.fanta_team_id = v_team and o.status = 'attiva')
       >= (select count(*) + 1 from public.fanta_teams) then
        raise exception 'Hai raggiunto il numero massimo di offerte: annullane una per farne un''altra'
            using errcode = 'P0001', hint = 'LIMITE';
    end if;

    insert into public.market_offers (window_gw, fanta_team_id, out_player_id, in_player_id)
    values (v_window.gameweek, v_team, p_out_player, v_in);
    return private.market_state(v_team);
end;
$$;

create or replace function public.market_cancel(p_token text, p_offer_id bigint)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_team uuid := private.user_team(private.token_user(p_token));
    v_window public.market_windows := private.market_open_window();
begin
    update public.market_offers o set status = 'annullata', updated_at = now()
    where o.id = p_offer_id and o.fanta_team_id = v_team and o.window_gw = v_window.gameweek
      and o.status = 'attiva';
    if not found then
        raise exception 'Offerta non trovata o già annullata' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    return private.market_state(v_team);
end;
$$;


-- 7. Esecuzione -----------------------------------------------------------------------------------------------
-- market_plan: cosa succederebbe chiudendo la finestra adesso, senza scrivere nulla. Una riga per offerta
-- attiva, nell'ordine di elaborazione (dall'ultimo in classifica al primo, poi ordine di inserimento).
-- ATTENZIONE: mostra le offerte di tutti. Serve alle prove (dentro begin ... rollback), non per sbirciare.

create or replace function private.market_plan(p_gameweek integer)
returns table (priority integer, team_name text, offer_id bigint, out_player_id integer, out_name text,
               in_player_id integer, in_name text, outcome text, note text)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_team record;
    v_offer record;
    v_taken integer[];
    v_done boolean;
    v_priority integer := 0;
    v_taken_by jsonb := '{}'::jsonb;   -- {id giocatore: squadra che l'ha preso in questa chiusura}
begin
    v_taken := array(select r.nba_player_id from public.rosters r where r.nba_player_id is not null);
    -- Dall'ultimo al primo: ordine di v_standings rovesciato
    for v_team in
        select s.fanta_team_id, s.team_name
        from public.v_standings s
        order by s.standing_points asc, s.total_score asc, s.team_name desc  -- nome: solo per parità totale
    loop
        v_priority := v_priority + 1;
        v_done := false;
        for v_offer in
            select o.id, o.out_player_id, po.full_name as out_name, o.in_player_id, pi.full_name as in_name,
                   pi.espn_id
            from public.market_offers o
            join public.nba_players po on po.id = o.out_player_id
            join public.nba_players pi on pi.id = o.in_player_id
            where o.window_gw = p_gameweek and o.fanta_team_id = v_team.fanta_team_id and o.status = 'attiva'
            order by o.id
        loop
            priority := v_priority; team_name := v_team.team_name; offer_id := v_offer.id;
            out_player_id := v_offer.out_player_id; out_name := v_offer.out_name;
            in_player_id := v_offer.in_player_id; in_name := v_offer.in_name;
            if v_done then
                outcome := 'non_eseguita'; note := 'Eseguito un altro scambio con priorità più alta';
            elsif v_offer.in_player_id = any (v_taken) then
                outcome := 'non_eseguita';
                note := coalesce('Preso da ' || (v_taken_by ->> v_offer.in_player_id::text) || ', più in basso in classifica',
                                 'Giocatore non più libero');
            elsif not exists (select 1 from public.rosters r
                              where r.fanta_team_id = v_team.fanta_team_id
                                and r.nba_player_id = v_offer.out_player_id) then
                outcome := 'non_eseguita'; note := 'Il giocatore da cedere non è più nel roster';
            elsif v_offer.espn_id is null then
                outcome := 'non_eseguita'; note := 'Giocatore non gestito dal calcolo dei punteggi';
            elsif not private.market_roles_ok(v_team.fanta_team_id, v_offer.out_player_id, v_offer.in_player_id) then
                outcome := 'non_eseguita'; note := 'Il roster resterebbe senza una guardia, un''ala o un centro';
            else
                outcome := 'eseguita'; note := null;
                v_done := true;
                v_taken := v_taken || v_offer.in_player_id;
                v_taken_by := v_taken_by || jsonb_build_object(v_offer.in_player_id::text, v_team.team_name);
            end if;
            return next;
        end loop;
    end loop;
end;
$$;

-- Esegue gli scambi della finestra p_gameweek: roster, formazioni dalla first_gameweek in poi, esiti delle
-- offerte, finestra chiusa, run "manual" (le app riscaricano i dati) e snapshot rigenerato.
-- Tutto nella stessa transazione: o tutto o niente. Restituisce il riepilogo salvato in market_windows.result.
create or replace function private.market_close(p_gameweek integer)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_window public.market_windows;
    v_plan record;
    v_trades jsonb := '[]'::jsonb;
    v_order jsonb;
    v_result jsonb;
begin
    select * into v_window from public.market_windows w where w.gameweek = p_gameweek for update;
    if not found then
        raise exception 'Finestra % inesistente', p_gameweek;
    end if;
    if v_window.closed_at is not null then
        raise exception 'Finestra % già eseguita il %', p_gameweek, v_window.closed_at;
    end if;

    v_order := (select jsonb_agg(s.team_name order by s.standing_points asc, s.total_score asc, s.team_name desc)
                from public.v_standings s);

    for v_plan in select * from private.market_plan(p_gameweek) order by priority, offer_id loop
        update public.market_offers o set status = v_plan.outcome, note = v_plan.note, updated_at = now()
        where o.id = v_plan.offer_id;
        if v_plan.outcome = 'eseguita' then
            update public.rosters r
            set nba_player_id = v_plan.in_player_id, player_name = v_plan.in_name
            where r.nba_player_id = v_plan.out_player_id
              and r.fanta_team_id = (select o.fanta_team_id from public.market_offers o where o.id = v_plan.offer_id);
            update public.lineup_players lp
            set nba_player_id = v_plan.in_player_id, player_name = v_plan.in_name
            where lp.nba_player_id = v_plan.out_player_id
              and lp.gameweek >= v_window.first_gameweek
              and lp.fanta_team_id = (select o.fanta_team_id from public.market_offers o where o.id = v_plan.offer_id);
            v_trades := v_trades || jsonb_build_object(
                'team', v_plan.team_name, 'out', v_plan.out_name, 'in', v_plan.in_name);
        end if;
    end loop;

    v_result := jsonb_build_object('order', v_order, 'trades', v_trades);
    update public.market_windows w set closed_at = now(), result = v_result where w.gameweek = p_gameweek;
    perform public.record_run('manual', true);
    return v_result;
end;
$$;

-- Lanciata da pg_cron: esegue le finestre scadute, solo se il cron dei punteggi di oggi è andato a buon fine
-- (altrimenti la classifica, e quindi la priorità, potrebbe essere sbagliata). Il job gira più volte: le
-- finestre già eseguite non vengono toccate. Restituisce cosa ha fatto.
create or replace function private.market_close_due()
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_gw integer;
    v_daily_ok boolean;
begin
    select w.gameweek into v_gw from public.market_windows w
    where w.closed_at is null and w.closes_at <= now() order by w.closes_at limit 1;
    if v_gw is null then
        return 'nessuna finestra da eseguire';
    end if;
    select c.ok and (c.finished_at at time zone 'Europe/Rome')::date = (now() at time zone 'Europe/Rome')::date
    into v_daily_ok from public.cron_runs c where c.mode = 'daily';
    if not coalesce(v_daily_ok, false) then
        return format('finestra %s in attesa: cron dei punteggi di oggi non riuscito', v_gw);
    end if;
    perform private.market_close(v_gw);
    return format('finestra %s eseguita', v_gw);
end;
$$;

-- Esecuzione manuale dallo SQL Editor (es. dopo aver sistemato il cron dei punteggi). Solo chiave segreta.
create or replace function public.market_close(p_gameweek integer)
returns jsonb
language sql
security definer
set search_path = ''
as $$
    select private.market_close(p_gameweek);
$$;


-- 8. Permessi -------------------------------------------------------------------------------------------------
-- Le RPC dell'app con la chiave pubblicabile; market_close solo service_role (e SQL Editor).

revoke all on function public.market_state(text) from public;
revoke all on function public.market_offer(text, integer, text) from public;
revoke all on function public.market_cancel(text, bigint) from public;
revoke all on function public.market_close(integer) from public;
grant execute on function public.market_state(text) to anon, authenticated, service_role;
grant execute on function public.market_offer(text, integer, text) to anon, authenticated, service_role;
grant execute on function public.market_cancel(text, bigint) to anon, authenticated, service_role;
grant execute on function public.market_close(integer) to service_role;

commit;

notify pgrst, 'reload schema';


-- =====================================================================================================
-- PARTE 2: job di pg_cron (dopo la VERIFICA della parte 1 e dopo carica_giocatori.py)
-- =====================================================================================================
-- Il martedì ogni ora dalle 17:00 alle 22:00 UTC: il primo run dopo le 19:00 di Roma (17:00 UTC con l'ora
-- legale, 18:00 con l'ora solare) esegue la finestra; i successivi non fanno nulla, oppure riprovano se il
-- cron dei punteggi non era riuscito. L'ultimo run (22:00 UTC) è prima delle 23:59 di Roma, scadenza dei
-- cambi della giornata successiva: chi riceve un giocatore ha tempo di sistemare la formazione.
--
-- select cron.schedule('fanta-mercato', '0 17-22 * * 2', $$select private.market_close_due()$$);
--
-- Esiti dei run:  select * from cron.job_run_details
--                 where jobid = (select jobid from cron.job where jobname = 'fanta-mercato')
--                 order by start_time desc limit 10;


-- =====================================================================================================
-- VERIFICA (dopo la parte 1)
-- =====================================================================================================
--
-- 1. Finestre: atteso 9 righe, giornate 6, 8, ..., 22; la 6 chiude il 01/12 alle 19:00 di Roma
-- select gameweek, closes_at at time zone 'Europe/Rome' as chiude_roma, first_gameweek, closed_at
-- from public.market_windows order by gameweek;
--
-- 2. Tabelle chiuse alla chiave pubblicabile: atteso nessuna riga
-- select table_name, privilege_type, grantee from information_schema.table_privileges
-- where table_name in ('market_windows', 'market_offers') and grantee in ('anon', 'authenticated');
--
-- 3. Dopo carica_giocatori.py: giocatori con search_name e con espn_id (atteso circa 526 e 519)
-- select count(*) filter (where search_name is not null) as con_nome,
--        count(*) filter (where espn_id is not null) as con_espn from public.nba_players;
--
-- 4. Prova completa senza modificare nulla: sql/2026-11_mercato_prova.sql (dentro begin ... rollback).


-- =====================================================================================================
-- ROLLBACK
-- =====================================================================================================
-- select cron.unschedule('fanta-mercato');
-- drop function if exists public.market_close(integer), private.market_close_due(), private.market_close(integer),
--     private.market_plan(integer), public.market_cancel(text, bigint), public.market_offer(text, integer, text),
--     public.market_state(text), private.market_state(uuid), private.market_open_window(timestamptz),
--     private.market_roles_ok(uuid, integer, integer), private.position_codes(text), private.user_team(uuid);
-- drop table if exists public.market_offers, public.market_windows;
-- alter table public.nba_players drop column if exists search_name, drop column if exists espn_id;
-- Attenzione: gli scambi già eseguiti restano nei roster e nelle formazioni.
