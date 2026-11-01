-- Sostituzioni automatiche di fine giornata e infortuni (novembre 2026).
-- Da eseguire una volta nello SQL Editor di Supabase, PRIMA di pubblicare il nuovo codice.

-- 1. lineup_players: chi è sceso in campo nella giornata e sostituzioni automatiche
alter table lineup_players
    add column if not exists entered_game boolean not null default false;  -- sceso in campo almeno una volta (non solo DNP)
alter table lineup_players
    add column if not exists auto_sub text check (auto_sub in ('IN', 'OUT'));  -- entrato/uscito a fine giornata

-- 2. Infortuni attuali (riscritta per intero dal cron "injuries")
create table if not exists player_injuries (
    nba_player_id  bigint primary key,
    status         text not null default '',   -- "Out" / "Day-To-Day" (ESPN)
    fantasy_status text not null default '',   -- "OUT" / "GTD" / "OFS"
    injury_type    text not null default '',   -- es. "Knee"
    return_date    date,                       -- rientro stimato
    updated_at     timestamptz not null default now()
);

-- App e cron usano la chiave publishable (ruolo anon): stessi permessi delle altre tabelle
alter table player_injuries enable row level security;
drop policy if exists "player_injuries lettura" on player_injuries;
create policy "player_injuries lettura" on player_injuries for select to anon, authenticated using (true);
drop policy if exists "player_injuries scrittura" on player_injuries;
create policy "player_injuries scrittura" on player_injuries for all to anon, authenticated using (true) with check (true);

-- 3. pg_cron: due lanci del workflow con mode "injuries" (21:10 e 22:10 UTC = 22:10 e 23:10 italiane
--    con l'ora solare, 23:10 e 00:10 con l'ora legale). Copiare il comando del job "daily" esistente
--    (select jobname, schedule, command from cron.job;) sostituendo "daily" con "injuries", ad esempio:
--
-- select cron.schedule('fantanba-injuries-2110', '10 21 * * *', $$ <comando del job daily con "mode":"injuries"> $$);
-- select cron.schedule('fantanba-injuries-2210', '10 22 * * *', $$ <comando del job daily con "mode":"injuries"> $$);
