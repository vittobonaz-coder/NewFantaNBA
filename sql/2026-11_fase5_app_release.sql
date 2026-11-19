-- Fase 5: configurazione degli aggiornamenti dell'app installata (novembre 2026, docs/fase5_piano.md).
-- Da eseguire una volta nello SQL Editor di Supabase. Ordine rispetto al codice: indifferente (consigliato prima):
-- il nuovo codice, se la RPC non c'è, salta il controllo; Render, il cron e le app già installate non la usano.
--
-- SOLO AGGIUNTE:
--   - tabella app_release, una riga per piattaforma (android, windows), chiusa ad anon (si legge solo dalla RPC);
--   - RPC app_release(p_platform): la chiama l'app installata all'avvio, in parallelo con il caricamento.
--
-- Significato dei campi:
--   latest_version  ultima versione pubblicata (X.Y.Z): sotto questa l'app mostra "Disponibile la versione ..."
--   min_version     versione minima: sotto questa l'app NON si usa finché non si aggiorna (la webapp resta usabile).
--                   Attenzione: un valore troppo alto blocca tutti gli utenti dell'app; si corregge da qui.
--   url             link di download aperto dal pulsante "Scarica"
-- Si aggiorna a mano DOPO aver pubblicato la release su GitHub (snippet in fondo), non prima.

begin;

create table if not exists public.app_release (
    platform text primary key check (platform in ('android', 'windows')),
    latest_version text not null check (latest_version ~ '^\d+\.\d+\.\d+$'),
    min_version text not null check (min_version ~ '^\d+\.\d+\.\d+$'),
    url text not null,
    note text,
    updated_at timestamptz not null default now()
);
alter table public.app_release enable row level security;
revoke all on public.app_release from public, anon, authenticated;

-- Valori iniziali: nessuna versione pubblicata ancora (0.0.0 = nessun avviso, nessun blocco)
insert into public.app_release (platform, latest_version, min_version, url) values
    ('android', '0.0.0', '0.0.0', 'https://github.com/vittobonaz-coder/NewFantaNBA/releases/latest/download/bonkest.apk'),
    ('windows', '0.0.0', '0.0.0', 'https://github.com/vittobonaz-coder/NewFantaNBA/releases/latest/download/Bonkest-Setup.exe')
on conflict (platform) do nothing;

-- Configurazione per una piattaforma: {"platform", "latest_version", "min_version", "url", "note"}, null se assente
create or replace function public.app_release(p_platform text)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select jsonb_build_object('platform', r.platform, 'latest_version', r.latest_version,
                              'min_version', r.min_version, 'url', r.url, 'note', r.note)
    from public.app_release r
    where r.platform = p_platform;
$$;

revoke all on function public.app_release(text) from public, anon, authenticated;
grant execute on function public.app_release(text) to anon, authenticated, service_role;

commit;
notify pgrst, 'reload schema';


-- =====================================================================================================
-- VERIFICHE (dopo l'esecuzione)
-- =====================================================================================================
--
-- 1. Valori attuali
-- select * from public.app_release order by platform;
--
-- 2. Quello che riceve l'app (atteso: jsonb con 0.0.0; null per una piattaforma sconosciuta)
-- select public.app_release('android'), public.app_release('windows'), public.app_release('ios');
--
-- 3. Permessi (attesi: false per la tabella, true per la funzione)
-- select has_table_privilege('anon', 'public.app_release', 'select') as anon_select,
--        has_function_privilege('anon', 'public.app_release(text)', 'execute') as anon_execute;


-- =====================================================================================================
-- DOPO OGNI RELEASE PUBBLICATA SU GITHUB (es. 1.0.0)
-- =====================================================================================================
--
-- Nuova versione disponibile (avviso, nessun blocco):
-- update public.app_release set latest_version = '1.0.0', updated_at = now();
--
-- Versione minima (blocca le versioni precedenti; solo se servono davvero, es. dopo un cambio del database):
-- update public.app_release set min_version = '1.0.0', updated_at = now();
--
-- Una sola piattaforma:  ... where platform = 'android';
--
-- Prova del blocco sui propri dispositivi (poi rimettere i valori giusti!):
-- update public.app_release set min_version = '9.0.0' where platform = 'android';


-- =====================================================================================================
-- ROLLBACK (le app con il controllo continuano a funzionare: RPC assente = nessun controllo)
-- =====================================================================================================
--
-- begin;
-- drop function if exists public.app_release(text);
-- drop table if exists public.app_release;
-- commit;
-- notify pgrst, 'reload schema';
