-- Prova del mercato sui dati veri SENZA modificarli.
-- Da eseguire nello SQL Editor di Supabase dopo la parte 1 di sql/2026-11_mercato.sql, sql/2026-11_mercato_ruoli.sql
-- e carica_giocatori.py,
-- PRIMA che qualcuno faccia offerte vere (il piano mostra le offerte di tutti).
--
-- Come funziona: tutto sta in un unico blocco DO che alla fine solleva apposta un errore. L'errore annulla
-- ogni modifica (offerte, roster, formazioni, finestra) e il suo messaggio contiene il resoconto della prova.
-- Si usa questo trucco perché lo SQL Editor mostra solo il risultato dell'ultima istruzione: con
-- "begin ... rollback" l'ultima sarebbe il rollback e non si vedrebbe niente.
-- Quindi il risultato ATTESO è un ERRORE che inizia con "PROVA RIUSCITA, TUTTO ANNULLATO".
-- Se l'editor chiede se eseguire con o senza RLS, scegli "Run without RLS": il file non crea tabelle.
--
-- Scenario: le due squadre ultime in classifica vogliono lo stesso free agent guardia (il primo in ordine
-- alfabetico tra i liberi con ID ESPN, per avere un risultato ripetibile). Ognuna cede la sua prima guardia;
-- la penultima fa anche una seconda offerta su un altro free agent guardia.
-- Atteso: l'ultima prende il giocatore conteso; la penultima lo perde ("Preso da ...") e ottiene la seconda.

do $$
declare
    v_offerte integer;
    v_piano text;
    v_esito text;
begin
    -- 1. Offerte finte
    with ultime as (
        select s.fanta_team_id,
               row_number() over (order by s.standing_points asc, s.total_score asc, s.team_name desc) as pos
        from public.v_standings s
    ),
    liberi as (
        select p.id, row_number() over (order by p.full_name) as n
        from public.nba_players p
        where p.espn_id is not null
          and not exists (select 1 from public.rosters r where r.nba_player_id = p.id)
          and 'G' = any(private.position_codes(p.position))
    ),
    primo as (
        select r.fanta_team_id, min(r.nba_player_id) filter (where 'G' = any(private.position_codes(p.position))) as out_id
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

    get diagnostics v_offerte = row_count;
    if v_offerte <> 3 then
        raise exception 'PROVA NON VALIDA: inserite % offerte invece di 3 (mancano giocatori liberi con ID ESPN o guardie nei roster?)', v_offerte;
    end if;

    -- 2. Piano calcolato senza scrivere nulla
    select string_agg(format('  %s. %s: cede %s, prende %s -> %s%s', priority, team_name, out_name, in_name,
                             outcome, coalesce(' (' || note || ')', '')),
                      E'\n' order by priority, offer_id)
    into v_piano
    from private.market_plan(6);

    -- 3. Esecuzione vera (verrà annullata dall'errore finale)
    perform public.market_close(6);

    -- 4. Esito registrato e giornate di formazione già col nuovo giocatore
    select string_agg(format('  %s: %s, cede %s, prende %s%s, giornate col nuovo giocatore: %s',
                             t.name, o.status, po.full_name, pi.full_name, coalesce(' (' || o.note || ')', ''),
                             (select count(*) from public.lineup_players lp
                              where lp.fanta_team_id = o.fanta_team_id and lp.nba_player_id = o.in_player_id)),
                      E'\n' order by o.id)
    into v_esito
    from public.market_offers o
    join public.fanta_teams t on t.id = o.fanta_team_id
    join public.nba_players po on po.id = o.out_player_id
    join public.nba_players pi on pi.id = o.in_player_id
    where o.window_gw = 6;

    raise exception E'PROVA RIUSCITA, TUTTO ANNULLATO\nPiano:\n%\nEsito:\n%', v_piano, v_esito;
end $$;

-- Controllo facoltativo dopo la prova (atteso: 0 offerte e finestra 6 con closed_at vuoto):
-- select count(*) from public.market_offers;
-- select gameweek, closed_at from public.market_windows where gameweek = 6;
