-- Fase 1, migrazione A: hash delle password, scadenza dei token e RPC dell'app (novembre 2026).
-- Da eseguire nello SQL Editor di Supabase, PRIMA di pubblicare il nuovo codice su main.
--
-- SOLO AGGIUNTE: la versione web su Render e il cron attuali continuano a funzionare senza modifiche.
--   - profiles.password (in chiaro) resta, e un trigger tiene allineato l'hash se il vecchio codice la cambia;
--   - le RPC scrivono ancora anche la password in chiaro (private.set_password), così un eventuale
--     revert del codice su main non blocca chi ha cambiato password. La migrazione C toglie il chiaro.
--
-- Ordine della Fase 1:  A (questo file) -> nuovo codice su main -> B (RLS e revoche) -> C (via il chiaro).
--
-- Convenzioni delle RPC (POST /rest/v1/rpc/<nome>, argomenti JSON con nome, risposta jsonb):
--   - SECURITY DEFINER, search_path vuoto, nomi sempre qualificati (public., extensions., private.);
--   - errori per l'utente: errcode P0001 (HTTP 400), messaggio in italiano, codice macchina nell'hint
--     (SESSIONE_SCADUTA, PASSWORD_ERRATA, ROSA_CAMBIATA, NON_VALIDO).

begin;

-- 1. Colonne nuove ------------------------------------------------------------------------------------

alter table public.profiles add column if not exists password_hash text;  -- bcrypt (extensions.crypt)

update public.profiles
set password_hash = extensions.crypt(password, extensions.gen_salt('bf', 10))
where password_hash is null and password is not null;

-- Scadenza esplicita del token: 90 giorni con "Ricordami", 7 senza (la decide la RPC login).
-- Il default a 90 giorni vale per i token creati dal vecchio codice durante la transizione.
alter table public.login_tokens add column if not exists expires_at timestamptz;
update public.login_tokens set expires_at = created_at + interval '90 days' where expires_at is null;
alter table public.login_tokens alter column expires_at set default now() + interval '90 days';
alter table public.login_tokens alter column expires_at set not null;


-- 2. Schema privato per le funzioni interne (PostgREST espone solo public) -------------------------------

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;


-- 3. Funzioni interne ------------------------------------------------------------------------------------

-- Trigger di transizione: se il vecchio codice scrive la password in chiaro, ricalcola l'hash
create or replace function private.sync_password_hash()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.password is not null
       and (tg_op = 'INSERT' or new.password is distinct from old.password) then
        new.password_hash := extensions.crypt(new.password, extensions.gen_salt('bf', 10));
    end if;
    return new;
end;
$$;

drop trigger if exists profiles_sync_password_hash on public.profiles;
create trigger profiles_sync_password_hash
    before insert or update of password on public.profiles
    for each row execute function private.sync_password_hash();

-- Hash del token come quello calcolato finora in Python (hashlib.sha256(token).hexdigest()):
-- i token "Ricordami" già salvati sui dispositivi restano validi
create or replace function private.token_hash(p_token text)
returns text
language sql
immutable
set search_path = ''
as $$
    select encode(extensions.digest(p_token, 'sha256'), 'hex');
$$;

-- Utente del token di sessione; errore SESSIONE_SCADUTA se inesistente, revocato o scaduto
create or replace function private.token_user(p_token text)
returns uuid
language plpgsql
stable
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
        raise exception 'Sessione scaduta, rifai l''accesso' using errcode = 'P0001', hint = 'SESSIONE_SCADUTA';
    end if;
    return v_user;
end;
$$;

-- True se la password è quella del profilo
create or replace function private.check_password(p_user uuid, p_password text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce((
        select p.password_hash = extensions.crypt(coalesce(p_password, ''), p.password_hash)
        from public.profiles p
        where p.id = p_user and p.password_hash is not null
    ), false);
$$;

-- Errore PASSWORD_ERRATA se la password non è quella attuale
create or replace function private.require_password(p_user uuid, p_password text)
returns void
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    if not private.check_password(p_user, p_password) then
        raise exception 'Password attuale errata' using errcode = 'P0001', hint = 'PASSWORD_ERRATA';
    end if;
end;
$$;

-- Imposta la password. TRANSIZIONE: scrive il chiaro e il trigger calcola l'hash.
-- La migrazione C la sostituisce con la scrittura del solo hash.
create or replace function private.set_password(p_user uuid, p_password text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    if coalesce(p_password, '') = '' then
        raise exception 'La password non può essere vuota' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    if octet_length(p_password) > 72 then  -- bcrypt ignora i byte oltre il 72°
        raise exception 'La password può avere al massimo 72 caratteri' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    update public.profiles set password = p_password where id = p_user;
end;
$$;

-- Validazione comune di username e nome squadra (stesse regole di supabase_manager._validate_name)
create or replace function private.validate_name(p_value text, p_label text)
returns void
language plpgsql
immutable
set search_path = ''
as $$
begin
    if coalesce(p_value, '') = '' then
        raise exception '% non può essere vuoto', p_label using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    if char_length(p_value) > 20 then
        raise exception '% può avere al massimo 20 caratteri', p_label using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
end;
$$;

-- Profilo nel formato usato dall'app: {"id", "username", "fanta_teams": [{"id", "name"}]}
create or replace function private.profile_json(p_user uuid)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select jsonb_build_object(
        'id', p.id,
        'username', p.username,
        'fanta_teams', coalesce((
            select jsonb_agg(jsonb_build_object('id', t.id, 'name', t.name) order by t.name)
            from public.fanta_teams t
            where t.user_id = p.id
        ), '[]'::jsonb)
    )
    from public.profiles p
    where p.id = p_user;
$$;

revoke all on all functions in schema private from public, anon, authenticated;


-- 4. RPC dell'app -----------------------------------------------------------------------------------------

-- Login con username e password. Crea sempre un token di sessione (serve alle RPC di scrittura):
-- con "Ricordami" dura 90 giorni e l'app lo salva sul dispositivo, senza dura 7 giorni e resta in memoria.
-- Restituisce il profilo + {"token", "expires_at"}, oppure null se le credenziali sono errate.
create or replace function public.login(p_username text, p_password text, p_remember boolean default false)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_user uuid;
    v_token text;
    v_expires timestamptz;
begin
    select p.id into v_user
    from public.profiles p
    where p.username = p_username
      and p.password_hash is not null
      and p.password_hash = extensions.crypt(coalesce(p_password, ''), p.password_hash)
    limit 1;

    if v_user is null then
        -- Stesso tempo di risposta con username inesistente (niente indizi su quali username esistono)
        perform extensions.crypt(coalesce(p_password, ''), extensions.gen_salt('bf', 10));
        return null;
    end if;

    delete from public.login_tokens where expires_at <= now();  -- pulizia dei token scaduti

    v_token := encode(extensions.gen_random_bytes(32), 'hex');
    v_expires := now() + case when p_remember then interval '90 days' else interval '7 days' end;
    insert into public.login_tokens (token_hash, user_id, expires_at)
    values (private.token_hash(v_token), v_user, v_expires);

    return private.profile_json(v_user) || jsonb_build_object('token', v_token, 'expires_at', v_expires);
end;
$$;

-- Accesso automatico con il token salvato sul dispositivo: profilo, oppure null se scaduto o revocato
create or replace function public.login_with_token(p_token text)
returns jsonb
language plpgsql
stable
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
    return case when v_user is null then null else private.profile_json(v_user) end;
end;
$$;

-- Logout: il token non vale più
create or replace function public.logout(p_token text)
returns void
language sql
security definer
set search_path = ''
as $$
    delete from public.login_tokens where token_hash = private.token_hash(coalesce(p_token, ''));
$$;

-- Cambio password: gli altri dispositivi devono rifare l'accesso, questo resta collegato
create or replace function public.change_password(p_token text, p_old_password text, p_new_password text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_user uuid := private.token_user(p_token);
begin
    perform private.require_password(v_user, p_old_password);
    perform private.set_password(v_user, p_new_password);
    delete from public.login_tokens
    where user_id = v_user and token_hash <> private.token_hash(p_token);
end;
$$;

-- Cambio username: unico senza distinguere maiuscole e minuscole
create or replace function public.change_username(p_token text, p_password text, p_new_username text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_user uuid := private.token_user(p_token);
    v_name text := btrim(coalesce(p_new_username, ''));
begin
    perform private.require_password(v_user, p_password);
    perform private.validate_name(v_name, 'Lo username');
    if exists (select 1 from public.profiles p where lower(p.username) = lower(v_name) and p.id <> v_user) then
        raise exception 'Lo username ''%'' è già in uso', v_name using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    update public.profiles set username = v_name where id = v_user;
end;
$$;

-- Cambio nome della squadra dell'utente. Il nome identifica la squadra anche nei file locali
-- (<nome minuscolo con _ al posto degli spazi>_gwN_state.json): unico con la stessa regola (Team.filename)
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
end;
$$;

-- Salvataggio della formazione in una transazione e una richiesta (prima 48 richieste in 5 ondate).
-- p_players: [{"nba_player_id": 123, "slot": 1, "role": "STARTER"}, ...] con tutti i giocatori della rosa.
-- Scrive, dalla giornata p_gameweek in poi (mai le precedenti): ruolo in rosters, slot e ruolo in
-- lineup_players, modulo in matchups. La squadra è quella dell'utente del token.
-- Il controllo della scadenza dei cambi resta nell'app fino alla Fase 2.
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
begin
    select t.id into v_team from public.fanta_teams t where t.user_id = v_user order by t.name limit 1;
    if v_team is null then
        raise exception 'Nessuna squadra associata al profilo' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    if p_lineup is null or p_lineup not in ('2-2-1', '2-1-2', '1-2-2', '3-1-1', '1-3-1') then  -- LINEUP_ROLES
        raise exception 'Modulo non valido: %', p_lineup using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;
    if p_gameweek is null or p_gameweek < 1 or jsonb_typeof(p_players) is distinct from 'array' then
        raise exception 'Dati della formazione non validi' using errcode = 'P0001', hint = 'NON_VALIDO';
    end if;

    -- Giocatori ricevuti, letti sempre con jsonb_to_recordset(p_players) (nessuna tabella temporanea)
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

    -- Slot e ruolo dalla giornata p_gameweek in poi. Il vincolo unico (squadra, giornata, slot) non è
    -- DEFERRABLE e si controlla riga per riga: prima slot temporanei (+100), poi quelli definitivi
    update public.lineup_players lp set slot = i.slot + 100
    from jsonb_to_recordset(p_players) as i(nba_player_id integer, slot integer, role text)
    where lp.fanta_team_id = v_team and lp.gameweek >= p_gameweek and lp.nba_player_id = i.nba_player_id;

    update public.lineup_players lp set slot = i.slot, role = i.role
    from jsonb_to_recordset(p_players) as i(nba_player_id integer, slot integer, role text)
    where lp.fanta_team_id = v_team and lp.gameweek >= p_gameweek and lp.nba_player_id = i.nba_player_id;

    -- Modulo: le giornate precedenti restano come storico
    update public.matchups set home_lineup = p_lineup where home_team_id = v_team and gameweek >= p_gameweek;
    update public.matchups set away_lineup = p_lineup where away_team_id = v_team and gameweek >= p_gameweek;
end;
$$;

-- Solo per gli script di amministrazione (chiave segreta): password di un profilo
create or replace function public.admin_set_password(p_user_id uuid, p_password text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    perform private.set_password(p_user_id, p_password);
end;
$$;


-- 5. Permessi delle funzioni -----------------------------------------------------------------------------
-- Supabase dà EXECUTE a tutti sulle funzioni nuove: si toglie e si ridà solo dove serve

revoke all on function public.login(text, text, boolean)                         from public, anon, authenticated;
revoke all on function public.login_with_token(text)                             from public, anon, authenticated;
revoke all on function public.logout(text)                                       from public, anon, authenticated;
revoke all on function public.change_password(text, text, text)                  from public, anon, authenticated;
revoke all on function public.change_username(text, text, text)                  from public, anon, authenticated;
revoke all on function public.change_team_name(text, text, text)                 from public, anon, authenticated;
revoke all on function public.save_lineup(text, integer, jsonb, text)            from public, anon, authenticated;
revoke all on function public.admin_set_password(uuid, text)                     from public, anon, authenticated;

grant execute on function public.login(text, text, boolean)              to anon, authenticated, service_role;
grant execute on function public.login_with_token(text)                  to anon, authenticated, service_role;
grant execute on function public.logout(text)                            to anon, authenticated, service_role;
grant execute on function public.change_password(text, text, text)       to anon, authenticated, service_role;
grant execute on function public.change_username(text, text, text)       to anon, authenticated, service_role;
grant execute on function public.change_team_name(text, text, text)      to anon, authenticated, service_role;
grant execute on function public.save_lineup(text, integer, jsonb, text) to anon, authenticated, service_role;
grant execute on function public.admin_set_password(uuid, text)          to service_role;

commit;

-- PostgREST rilegge lo schema: le RPC sono subito chiamabili
notify pgrst, 'reload schema';


-- =====================================================================================================
-- VERIFICA (da eseguire dopo, una query alla volta)
-- =====================================================================================================
--
-- 1. Nessun profilo senza hash (atteso: 0)
-- select count(*) as senza_hash from public.profiles where password_hash is null;
--
-- 2. Utenti che hanno ancora una password iniziale (solo gli username, mai le password):
--    vanno avvisati di cambiarla DOPO la migrazione C
-- select username from public.profiles
-- where password_hash in (extensions.crypt('1', password_hash), extensions.crypt('fanta2026', password_hash))
-- order by username;
--
-- 3. Login con credenziali sbagliate (atteso: null)
-- select public.login('utente_inesistente', 'x');
--
-- 4. Token esistenti con scadenza (atteso: nessuna riga con expires_at nullo)
-- select count(*) as token, min(expires_at), max(expires_at) from public.login_tokens;
--
-- 5. Funzioni create e chi può eseguirle
-- select p.proname, p.prosecdef as security_definer, p.proconfig,
--        has_function_privilege('anon', p.oid, 'execute') as anon_execute
-- from pg_proc p join pg_namespace n on n.oid = p.pronamespace
-- where n.nspname in ('public', 'private') order by n.nspname, p.proname;
--   Attesi: anon_execute = true per login, login_with_token, logout, change_*, save_lineup;
--           false per admin_set_password e per tutte quelle di private (update_updated_at_column: ignorare).


-- =====================================================================================================
-- ROLLBACK (solo se serve tornare indietro; il codice in produzione PRIMA della Fase 1 non usa nulla di questo)
-- =====================================================================================================
--
-- begin;
-- drop function if exists public.login(text, text, boolean);
-- drop function if exists public.login_with_token(text);
-- drop function if exists public.logout(text);
-- drop function if exists public.change_password(text, text, text);
-- drop function if exists public.change_username(text, text, text);
-- drop function if exists public.change_team_name(text, text, text);
-- drop function if exists public.save_lineup(text, integer, jsonb, text);
-- drop function if exists public.admin_set_password(uuid, text);
-- drop trigger if exists profiles_sync_password_hash on public.profiles;
-- drop schema if exists private cascade;
-- alter table public.login_tokens drop column if exists expires_at;
-- alter table public.profiles drop column if exists password_hash;
-- commit;
-- notify pgrst, 'reload schema';
