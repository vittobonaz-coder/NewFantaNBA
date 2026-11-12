-- Fase 1, migrazione C: eliminazione delle password in chiaro (novembre 2026).
-- Da eseguire nello SQL Editor di Supabase dopo la migrazione B, quando la versione web e il cron
-- hanno funzionato per qualche giorno con il nuovo codice (daily e rollover verdi).
--
-- Prerequisito: il codice su main non legge né scrive profiles.password (vero dalla Fase 1:
-- login e cambi passano dalle RPC, setup_fanta_championship.py usa admin_set_password).
-- Dopo questa migrazione chiedi a tutti gli utenti di cambiare password dall'app (Impostazioni > Profilo):
-- le password attuali sono state leggibili da chiunque prima della Fase 1.

begin;

-- 1. Le RPC scrivono solo l'hash (prima scrivevano il chiaro e il trigger calcolava l'hash)
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
    update public.profiles
    set password_hash = extensions.crypt(p_password, extensions.gen_salt('bf', 10))
    where id = p_user;
end;
$$;

revoke all on function private.set_password(uuid, text) from public, anon, authenticated;

-- 2. Via il trigger di transizione e la colonna in chiaro
drop trigger if exists profiles_sync_password_hash on public.profiles;
drop function if exists private.sync_password_hash();
alter table public.profiles drop column if exists password;

commit;

notify pgrst, 'reload schema';


-- =====================================================================================================
-- VERIFICA
-- =====================================================================================================
-- select column_name from information_schema.columns
-- where table_schema = 'public' and table_name = 'profiles' order by ordinal_position;
--   Attese: id, username, password_hash.
-- Poi: login dall'app con la tua password, cambio password e nuovo login.


-- =====================================================================================================
-- ROLLBACK
-- =====================================================================================================
-- Le password in chiaro non si possono ricostruire. Si può solo ricreare la colonna (vuota) se un vecchio
-- script la cercasse; il login continua a funzionare con password_hash.
-- alter table public.profiles add column if not exists password character varying;
