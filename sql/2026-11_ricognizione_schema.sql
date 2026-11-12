-- Ricognizione dello schema (novembre 2026, Fase 0 della migrazione ad app nativa).
-- SOLO LETTURE: non modifica nulla. Da eseguire nello SQL Editor di Supabase.
--
-- Il risultato (colonne sezione, oggetto, dettaglio) va aggiunto a sql/schema_riferimento.sql.
-- Lo SQL Editor mostra solo il risultato dell'ultima istruzione: le query sono due e vanno eseguite
-- una alla volta (selezionare il testo della query e premere Run), oppure esportando il risultato in CSV.
--
-- Sezioni della query 1:
-- - tabella:   tabelle e viste di public con stato delle RLS (abilitata / forzata)
-- - policy:    policy RLS con comando, ruoli, condizioni USING e WITH CHECK
-- - permesso:  privilegi di anon e authenticated sulle tabelle di public
-- - funzione:  funzioni di public (escluse quelle delle estensioni), SECURITY DEFINER, search_path, definizione
-- - trigger:   trigger non interni
-- - vincolo:   chiavi primarie, unici, CHECK, chiavi esterne (con DEFERRABLE se presente)
-- - indice:    indici di public
-- - estensione: estensioni installate (es. pgcrypto, pg_cron, pg_net)

-- ===== Query 1: schema public =====
select sezione, oggetto, dettaglio
from (
    -- Tabelle e viste con stato RLS
    select 1 as ord, 'tabella' as sezione, c.relname::text as oggetto,
           case c.relkind when 'r' then 'tabella' when 'v' then 'vista' when 'm' then 'vista materializzata'
                          when 'p' then 'tabella partizionata' else c.relkind::text end
           || ' | rls=' || c.relrowsecurity::text || ' | rls_forzata=' || c.relforcerowsecurity::text
           || ' | righe_stimate=' || c.reltuples::bigint::text as dettaglio
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r', 'v', 'm', 'p')

    union all
    -- Policy RLS
    select 2, 'policy', p.tablename || '.' || p.policyname,
           'comando=' || p.cmd || ' | permissiva=' || p.permissive
           || ' | ruoli=' || array_to_string(p.roles, ',')
           || ' | using=' || coalesce(p.qual, '-')
           || ' | with_check=' || coalesce(p.with_check, '-')
    from pg_policies p
    where p.schemaname = 'public'

    union all
    -- Privilegi dei ruoli usati dalle chiavi pubblicabili
    select 3, 'permesso', g.table_name || ' -> ' || g.grantee,
           string_agg(g.privilege_type, ',' order by g.privilege_type)
    from information_schema.role_table_grants g
    where g.table_schema = 'public' and g.grantee in ('anon', 'authenticated')
    group by g.table_name, g.grantee

    union all
    -- Funzioni di public (escluse quelle create dalle estensioni)
    select 4, 'funzione', p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
           'security_definer=' || p.prosecdef::text
           || ' | config=' || coalesce(array_to_string(p.proconfig, ','), '-')
           || ' | execute=' || coalesce(array_to_string(p.proacl, ','), 'default')
           || E'\n' || pg_get_functiondef(p.oid)
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.prokind in ('f', 'p')
      and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e')

    union all
    -- Trigger non interni (in tutti gli schemi utente, compreso auth per eventuali hook)
    select 5, 'trigger', n.nspname || '.' || c.relname || '.' || t.tgname,
           'abilitato=' || t.tgenabled::text || ' | ' || pg_get_triggerdef(t.oid)
    from pg_trigger t
    join pg_class c on c.oid = t.tgrelid
    join pg_namespace n on n.oid = c.relnamespace
    where not t.tgisinternal
      and n.nspname not in ('pg_catalog', 'information_schema', 'storage', 'realtime', 'supabase_functions', 'cron', 'net')

    union all
    -- Vincoli (PK, unici, CHECK, FK)
    select 6, 'vincolo', c.relname || '.' || k.conname,
           case k.contype when 'p' then 'PK' when 'u' then 'UNIQUE' when 'c' then 'CHECK'
                          when 'f' then 'FK' when 'x' then 'EXCLUDE' else k.contype::text end
           || ' | ' || pg_get_constraintdef(k.oid)
           || case when k.condeferrable then ' | deferrable, initially_deferred=' || k.condeferred::text else '' end
    from pg_constraint k
    join pg_class c on c.oid = k.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'

    union all
    -- Indici (compresi quelli unici non dichiarati come vincolo)
    select 7, 'indice', i.tablename || '.' || i.indexname, i.indexdef
    from pg_indexes i
    where i.schemaname = 'public'

    union all
    -- Estensioni installate
    select 8, 'estensione', e.extname, 'versione=' || e.extversion || ' | schema=' || x.nspname
    from pg_extension e
    join pg_namespace x on x.oid = e.extnamespace
) r
order by ord, oggetto;


-- ===== Query 2: job di pg_cron =====
-- Eseguirla a parte: se pg_cron non è installato o lo schema cron non è leggibile dà errore,
-- senza conseguenze sulla query 1.
select jobid, jobname, schedule, active, command
from cron.job
order by jobid;
