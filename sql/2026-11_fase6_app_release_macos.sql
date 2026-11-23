-- Fase 6, A5: app per Mac (novembre 2026, docs/fase6_piano.md). Aggiunge la piattaforma "macos" alla
-- configurazione degli aggiornamenti (tabella app_release, sql/2026-11_fase5_app_release.sql).
-- Da eseguire una volta nello SQL Editor di Supabase. Ordine rispetto al codice: indifferente (consigliato prima
-- di pubblicare la prima release con l'app Mac): finché la riga manca, l'app Mac salta il controllo.
--
-- SOLO AGGIUNTE: il vincolo sulla colonna platform accetta anche 'macos'; nuova riga a 0.0.0 (nessun avviso,
-- nessun blocco). Le righe android e windows non cambiano.

begin;

alter table public.app_release drop constraint if exists app_release_platform_check;
alter table public.app_release add constraint app_release_platform_check
    check (platform in ('android', 'windows', 'macos'));

insert into public.app_release (platform, latest_version, min_version, url) values
    ('macos', '0.0.0', '0.0.0', 'https://github.com/vittobonaz-coder/NewFantaNBA/releases/latest/download/Bonkest-macOS.zip')
on conflict (platform) do nothing;

commit;


-- =====================================================================================================
-- VERIFICHE (dopo l'esecuzione)
-- =====================================================================================================
--
-- 1. Tre righe: android, macos, windows
-- select platform, latest_version, min_version, url from public.app_release order by platform;
--
-- 2. Quello che riceve l'app Mac (atteso: jsonb con 0.0.0)
-- select public.app_release('macos');
--
-- Dopo la prima release pubblicata con l'app Mac, come per le altre (es. 1.0.1):
-- update public.app_release set latest_version = '1.0.1', updated_at = now();


-- =====================================================================================================
-- ROLLBACK
-- =====================================================================================================
--
-- begin;
-- delete from public.app_release where platform = 'macos';
-- alter table public.app_release drop constraint if exists app_release_platform_check;
-- alter table public.app_release add constraint app_release_platform_check
--     check (platform in ('android', 'windows'));
-- commit;
