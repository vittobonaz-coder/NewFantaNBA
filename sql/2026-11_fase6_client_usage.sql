-- Fase 6: chi usa cosa (novembre 2026, docs/fase6_piano.md, B2).
-- Da eseguire una volta nello SQL Editor di Supabase. Ordine rispetto al codice: indifferente.
--   - prima della migrazione il codice nuovo (webapp, app 1.0.1+) prova a mandare p_client, riceve "funzione
--     non trovata" e ripete la chiamata senza (una volta sola per processo): l'accesso funziona;
--   - dopo la migrazione il codice già in produzione (webapp attuale, app 1.0.0, cron, script) chiama
--     login_bundle/token_bundle senza p_client: il parametro è facoltativo, l'accesso funziona.
--
-- COSA FA:
--   - tabella client_usage: una riga per utente e "client" (webapp da iPhone, app Android...), con versione
--     dell'app, primo e ultimo accesso e numero di accessi; chiusa ad anon (si legge solo dallo SQL Editor);
--   - login_bundle e token_bundle ricevono il parametro facoltativo p_client {"client": "...", "version": "X.Y.Z"}
--     e registrano l'accesso. Senza p_client registrano il client "non-indicato": dopo il deploy della webapp
--     nuova sono le app 1.0.0 (e gli script di misura).
--   - Valori di client mandati dal codice: android, windows (app installata); web-ios, web-android,
--     web-windows, web-macos, web-linux (webapp dal browser di quel sistema); sviluppo (test.py).
--
-- Perché DROP della vecchia firma e non solo CREATE OR REPLACE: aggiungere un parametro cambia la "firma" della funzione;
-- CREATE OR REPLACE creerebbe una seconda funzione con lo stesso nome (PostgREST non saprebbe quale chiamare).
-- Tutto in una transazione: nessun istante senza funzione.
-- Un errore nella registrazione non blocca mai l'accesso (blocco exception in private.record_client).

begin;

-- 1. Tabella ---------------------------------------------------------------------------------------------

create table if not exists public.client_usage (
    user_id uuid not null references public.profiles(id) on delete cascade,
    client text not null check (client ~ '^[a-z0-9-]{1,30}$'),
    app_version text check (app_version ~ '^\d+\.\d+\.\d+$'),
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    accessi integer not null default 1,
    primary key (user_id, client)
);
alter table public.client_usage enable row level security;
revoke all on public.client_usage from public, anon, authenticated;

-- 2. Registrazione (privata) -----------------------------------------------------------------------------

-- Valori non validi (client strano, versione malformata) non fanno fallire nulla: client "non-valido",
-- versione vuota. Qualunque errore imprevisto viene ignorato: l'accesso conta più della statistica.
create or replace function private.record_client(p_user uuid, p_client jsonb)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_client text := lower(coalesce(p_client ->> 'client', 'non-indicato'));
    v_version text := p_client ->> 'version';
begin
    if p_user is null then
        return;
    end if;
    if v_client !~ '^[a-z0-9-]{1,30}$' then
        v_client := 'non-valido';
    end if;
    if v_version !~ '^\d+\.\d+\.\d+$' then
        v_version := null;
    end if;
    insert into public.client_usage as c (user_id, client, app_version)
    values (p_user, v_client, v_version)
    on conflict (user_id, client) do update
        set app_version = excluded.app_version, last_seen_at = now(), accessi = c.accessi + 1;
exception when others then
    raise warning 'record_client: %', sqlerrm;
end;
$$;

revoke all on function private.record_client(uuid, jsonb) from public, anon, authenticated;

-- 3. RPC dell'app con p_client ---------------------------------------------------------------------------

drop function if exists public.login_bundle(text, text, boolean, jsonb);
drop function if exists public.token_bundle(text, jsonb);

-- Come sql/2026-11_fase2a_snapshot_bundle.sql, più la registrazione dell'accesso riuscito
create or replace function public.login_bundle(p_username text, p_password text, p_remember boolean default false,
                                    p_versions jsonb default '{}'::jsonb, p_client jsonb default null)
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
    perform private.record_client((v_login ->> 'id')::uuid, p_client);
    return v_login || private.bundle_data((v_login ->> 'id')::uuid, p_versions);
end;
$$;

create or replace function public.token_bundle(p_token text, p_versions jsonb default '{}'::jsonb, p_client jsonb default null)
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
    perform private.record_client(v_user, p_client);
    return private.profile_json(v_user) || private.bundle_data(v_user, p_versions);
end;
$$;

revoke all on function public.login_bundle(text, text, boolean, jsonb, jsonb) from public, anon, authenticated;
revoke all on function public.token_bundle(text, jsonb, jsonb)                from public, anon, authenticated;
grant execute on function public.login_bundle(text, text, boolean, jsonb, jsonb) to anon, authenticated, service_role;
grant execute on function public.token_bundle(text, jsonb, jsonb)                to anon, authenticated, service_role;

commit;
notify pgrst, 'reload schema';


-- =====================================================================================================
-- VERIFICHE (dopo l'esecuzione)
-- =====================================================================================================
--
-- 1. Una sola versione di ciascuna funzione, con p_client (attese 2 righe)
-- select p.proname, pg_get_function_identity_arguments(p.oid)
-- from pg_proc p join pg_namespace n on n.oid = p.pronamespace
-- where n.nspname = 'public' and p.proname in ('login_bundle', 'token_bundle');
--
-- 2. Permessi (attesi: false per la tabella, true per le funzioni)
-- select has_table_privilege('anon', 'public.client_usage', 'select') as anon_tabella,
--        has_function_privilege('anon', 'public.token_bundle(text, jsonb, jsonb)', 'execute') as anon_token_bundle;
--
-- 3. Dopo aver aperto webapp e app: le righe compaiono (vedi query sotto)


-- =====================================================================================================
-- CHI USA COSA (da eseguire quando vuoi)
-- =====================================================================================================
--
-- Per utente: ogni client usato, versione, ultimo accesso (ora italiana)
-- select p.username, c.client, c.app_version, c.accessi,
--        to_char(c.last_seen_at at time zone 'Europe/Rome', 'DD/MM HH24:MI') as ultimo_accesso
-- from public.client_usage c join public.profiles p on p.id = c.user_id
-- order by p.username, c.last_seen_at desc;
--
-- Riepilogo: quanti utenti per client negli ultimi 14 giorni
-- select client, count(*) as utenti, max(app_version) as versione_max
-- from public.client_usage where last_seen_at > now() - interval '14 days'
-- group by client order by utenti desc;
--
-- Prima di alzare min_version: chi ha una versione dell'app più vecchia di X.Y.Z (qui 1.0.1)
-- select p.username, c.client, c.app_version from public.client_usage c join public.profiles p on p.id = c.user_id
-- where c.client in ('android', 'windows', 'non-indicato')
--   and coalesce(string_to_array(c.app_version, '.')::int[], '{0,0,0}') < '{1,0,1}';


-- =====================================================================================================
-- ROLLBACK (torna alle funzioni della Fase 2; il codice nuovo se ne accorge e smette di mandare p_client)
-- =====================================================================================================
--
-- begin;
-- drop function if exists public.login_bundle(text, text, boolean, jsonb, jsonb);
-- drop function if exists public.token_bundle(text, jsonb, jsonb);
-- -- poi rieseguire dalla sezione 5 di sql/2026-11_fase2a_snapshot_bundle.sql le due funzioni
-- -- login_bundle e token_bundle e le loro righe di revoke/grant (sezione 6)
-- drop function if exists private.record_client(uuid, jsonb);
-- drop table if exists public.client_usage;
-- commit;
-- notify pgrst, 'reload schema';
