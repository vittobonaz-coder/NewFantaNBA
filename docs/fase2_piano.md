# Fase 2 — Meno richieste: save_lineup, login unico, snapshot (piano approvato il 14/11/2026)

Preparato e approvato il 14/11/2026 (branch `app-nativa`). Stato di avanzamento e misure: `docs/piano_migrazione_C1.md`.
Basato su: `docs/piano_migrazione_C1.md`, `docs/fase0_report.md` (sez. 1 e 2.2), `sql/schema_riferimento.sql`,
`sql/2026-11_fase1a_password_rpc.sql`, `app.py`, `supabase_manager.py`, `supabase_rest.py`, `cron_test_script.py`,
`time_manager.py`, `swap_players.py`, `ui_court.py`.

## 0. Idea in una riga

Tutto ciò che l'app legge passa da **due RPC** (`login_bundle` all'accesso, `get_snapshot` per gli aggiornamenti):
una richiesta per il login in ogni caso, zero per il tab "Altre squadre". I dati uguali per tutti stanno in una
tabella `app_snapshot` divisa in **parti con versione = hash del contenuto**, costruita **in SQL** e rigenerata a
fine di ogni run del cron, da `swap_players.py` e dalle RPC che cambiano dati condivisi. Un run fallito che non
ha cambiato nulla o il cron degli infortuni non fanno più riscaricare tutto: cambia solo la versione delle parti
il cui contenuto è davvero diverso.

## 1. Situazione attuale (dal codice)

| Flusso | Richieste in sequenza |
|---|---|
| Login manuale dopo un cron (cache vecchia, 2 giornate) | 1 `rpc/login` + 1 `cron_runs` + `matchups` + 3 `nba_games` (2 pagine + 1 vuota) + `v_standings` + `player_injuries` + 2×(`lineup_players` + `matchups` per il modulo) = **12** |
| Accesso con token dopo un cron | 1 `rpc/login_with_token` + 11 = **12** (il report di Fase 0 ne contava 13 col vecchio `create_login_token`, che non c'è più) |
| Login a dati aggiornati | `rpc/login` + `cron_runs` = **2** (3 se manca `injuries.json` o un file di squadra) |
| Primo tab "Altre squadre" | `fanta_teams` + `lineup_players` + `matchups` = **3** |
| Salvataggio formazione | **1** (`rpc/save_lineup`, Fase 1) |
| Cambio nome squadra | 1 RPC + `matchups` + 3 `nba_games` + `v_standings` = **6** |

Problemi da risolvere oltre al numero:
- `get_last_cron_run` prende il run più recente di **qualunque** modalità: `injuries` (2 volte al giorno) e i run falliti (registrati nel `finally`, cron_test_script.py:497-500) invalidano tutta la cache.
- La scadenza dei cambi la controlla solo l'app (`Court.handle_save`, ui_court.py:467) con l'orologio del dispositivo; la deroga `EDIT_OVERRIDE_GW/UNTIL` è nelle variabili d'ambiente di Render, quindi l'app nativa non la vedrebbe.
- `save_lineup` usa gli slot temporanei +100 perché `lineup_players_team_gw_slot_key` non è DEFERRABLE.
- L'app importa `supabase_manager` (quindi supabase-py, ~0,5 s su Windows e ~1,1 s su Android di solo import) anche per chiamate che sono già RPC.

## 2. Progetto

### 2.1 Contesto della lega e scadenza nel database

`private.league_context(p_now timestamptz default now()) returns jsonb` — `{"current_gw", "edit_gw", "deadline", "now"}`,
stessa regola di `TimeManager.get_league_context`:
- giornate = `matchups` raggruppate per `gameweek` con `min(start_date)` (date italiane), ordinate per data;
- `today` = `(p_now at time zone 'Europe/Rome')::date`; `rollover` = `(today + time '23:59') at time zone 'Europe/Rome'`;
- `league_day` = `today` se `p_now < rollover`, altrimenti `today + 1`;
- `current_gw` = ultima giornata con `start_date <= league_day`; `edit_gw` = prima con `start_date > league_day`;
  `deadline` = `((start_date - 1) + time '23:59') at time zone 'Europe/Rome'`;
- **deroga**: tabella `public.edit_override` (una riga al massimo: `gameweek int`, `until_at timestamptz`, `note text`);
  se `current_gw = gameweek` e `p_now < until_at` → `edit_gw = gameweek`, `deadline = until_at`.
  RLS attiva, nessun permesso ad anon: si imposta dallo SQL Editor con uno snippet nel file di migrazione
  (`insert ... on conflict ... do update`, ora italiana scritta come `'2026-11-04 23:59'::timestamp at time zone 'Europe/Rome'`).
- `"now"` = ora del server: l'app la usa per correggere l'orologio del dispositivo nel blocco dei cambi a video.

Esposta anche come `public.league_context()` (anon, service_role): serve a `swap_players.py` (`default_from_gw`)
e a qualunque script, così la regola vive in un posto solo.

`save_lineup` (migrazione B): rifiuta se `p_gameweek <> edit_gw` oppure `now() >= deadline`, con
`hint = 'CAMBI_CHIUSI'` e messaggio "Cambi chiusi: formazione non salvata". Chiude anche la corsa delle 23:59
(salvataggio mentre il rollover riallinea la giornata).

### 2.2 Vincolo unico DEFERRABLE

```sql
alter table public.lineup_players
  drop constraint lineup_players_team_gw_slot_key,
  add constraint lineup_players_team_gw_slot_key unique (fanta_team_id, gameweek, slot)
      deferrable initially immediate;
```
- In una sola istruzione (tabella di ~3000 righe: ricostruzione dell'indice istantanea).
- **INITIALLY IMMEDIATE invece di DEFERRED** (proposta): un vincolo DEFERRABLE si controlla a fine istruzione,
  quindi basta un solo `UPDATE ... FROM jsonb_to_recordset` che permuta gli slot, senza +100; per cron e script
  il comportamento resta quasi identico (errore a fine istruzione invece che riga per riga). Se servisse, la RPC
  può comunque fare `set constraints ... deferred`.
- Verificato nel codice: nessun `upsert`/`on_conflict` su `lineup_players` (un vincolo deferrable non può fare da
  arbitro di `ON CONFLICT`). Il vincolo `unique_lineup_entry` resta com'è.
- È compatibile con il codice su `main` (la RPC attuale con +100 continua a funzionare): va nella migrazione A.

### 2.3 Snapshot

**Tabella `public.app_snapshot`**: `part text primary key` (`calendar`, `standings`, `injuries`, `lineups`),
`version text not null` (md5 del jsonb), `data jsonb not null`, `updated_at timestamptz`. RLS attiva,
nessun permesso ad anon: si legge solo dalle RPC `SECURITY DEFINER`.

Contenuto delle parti (righe "grezze" nella stessa forma che oggi restituisce PostgREST, così l'app riusa le
trasformazioni Python esistenti invece di riscriverle in SQL):
- `calendar`: righe di `matchups` con `home_team`/`away_team` (nomi) come in `pull_calendar`, più le partite di
  `nba_games` (solo le colonne usate: `gameweek, nba_date, start_time, home_team, away_team, home_score, away_score, status`),
  ordinate come oggi. Niente più pagine da 1000: una RPC restituisce un solo valore jsonb.
- `standings`: righe di `v_standings`.
- `injuries`: righe di `player_injuries` (colonne di `pull_injuries`).
- `lineups`: `{"gameweek": current_gw, "teams": [{id, name}], "rows": lineup_players della giornata in corso di
  tutte le squadre con nba_players(nba_team, position), "lineups": {team_id: modulo}}` → serve al tab
  "Altre squadre" (0 richieste) e alla squadra dell'utente nella giornata in corso.

**Rigenerazione** — `private.refresh_snapshot(p_parts text[] default null) returns jsonb` (versioni):
calcola ogni parte, `version = md5(data::text)`, e fa `update` **solo se la versione è diversa**
(`pg_advisory_xact_lock` contro due refresh contemporanei). Idempotente e economica (pochi ms): si può
chiamare sempre.

Chi la chiama:
| Chi | Come |
|---|---|
| Cron (ogni run, anche fallito) | `record_cron_run` → nuova RPC `public.record_run(p_mode, p_ok)` (solo service_role) = upsert su `cron_runs` + `refresh_snapshot()` nella stessa transazione |
| `swap_players.py` e altri script | `mark_data_changed()` → `record_run('manual', true)` |
| SQL Editor (correzioni a mano, `standings_adjustments`, deroga) | `select public.refresh_snapshot();` (solo service_role/postgres), snippet nel file |
| `change_team_name` | rigenera `calendar`, `standings`, `lineups` (i nomi cambiano) |
| `save_lineup` | rigenera `lineups` e `calendar` solo se `p_gameweek <= current_gw` (caso deroga: tocca la giornata in corso) |

**Rete di sicurezza (auto-riparazione)**: `login_bundle`/`get_snapshot` rigenerano prima di rispondere se
(a) `lineups.gameweek <> current_gw` (passata la mezzanotte della giornata ma il rollover non è ancora finito),
oppure (b) qualche parte ha `updated_at` < `max(cron_runs.finished_at)` (es. cron ancora sul vecchio codice
durante la transizione). Costa una lettura di 4 righe; garantisce che lo snapshot non resti indietro.

Conseguenze sul problema "tutto si riscarica":
- run `injuries` → cambia solo la parte `injuries` (~4 KB);
- run fallito senza scritture, rollover saltato, run identici → nessuna versione cambia, nessun download;
- run `daily` → cambiano `calendar`, `standings`, `lineups`: si scaricano in **una** risposta.

**Confronto richiesto: tabella vs Supabase Storage vs calcolo al volo**

| | Tabella `app_snapshot` (proposta) | File in Storage | Calcolo al volo con hash, senza tabella |
|---|---|---|---|
| Richieste al login | **1** (dentro `login_bundle`) | 2 (bundle + download del file) | **1** |
| Chi può rigenerarlo | SQL: cron, script, RPC, SQL Editor | solo codice Python con la chiave segreta (upload API): non le RPC né lo SQL Editor | nessuno (sempre attuale) |
| Rischio di dati vecchi | basso, con auto-riparazione | CDN: sul piano Free niente invalidazione "smart"; servono nomi versionati, quindi una lettura in più per sapere il nome | nullo |
| Download parziale (solo parti cambiate) | sì | no (o un file per parte = più richieste) | sì |
| Costo per login | lettura di 4 righe | lettura + file da CDN | costruzione di ~1300 righe e md5 a ogni login (decine di ms sul DB Free) |
| Permessi | tabella chiusa, solo RPC | bucket pubblico o URL firmati, policy di Storage in più | nessuna tabella |
| Lavoro | medio | medio-alto (bucket, policy, upload dal cron e da swap_players) | basso |

Raccomandazione: **tabella**. Storage aggiunge una richiesta, un sistema di permessi e problemi di cache CDN per
~200 KB di dati, e non si può aggiornare dalle RPC. Il calcolo al volo è la riserva se la rigenerazione si
rivelasse fragile: le funzioni che costruiscono le parti sono le stesse, quindi si passa dall'uno all'altro
cambiando poche righe di SQL.

### 2.4 Login in un colpo solo

`public.login_bundle(p_username text, p_password text, p_remember boolean, p_versions jsonb)` e
`public.token_bundle(p_token text, p_versions jsonb)` (anon, authenticated, service_role).
`p_versions` = `{"calendar": "<md5>", ...}` letto dalla cache del dispositivo (`{}` se assente).
Restituiscono `null` con credenziali errate / token scaduto, altrimenti:
```json
{
  "id", "username", "fanta_teams": [{"id","name"}],     // come oggi (private.profile_json)
  "token", "expires_at",                                // solo login_bundle
  "context": {"current_gw", "edit_gw", "deadline", "now"},
  "my_team": {"<gw>": {"lineup": "2-2-1", "rows": [...]}},   // edit_gw (e current_gw se diversa): sempre, ~3-6 KB
  "versions": {"calendar": "...", "standings": "...", "injuries": "...", "lineups": "..."},
  "parts": {"calendar": [...], ...}                     // solo le parti con versione diversa da p_versions
}
```
- `login_bundle` riusa il corpo di `login` (stessa protezione sui tempi con username inesistente, stessa pulizia dei token).
- `token_bundle` sostituisce `login_with_token`; non è `stable` perché può rigenerare lo snapshot.
- La formazione della propria squadra torna **sempre** aggiornata: niente più file di squadra vecchi né
  `ROSA_CAMBIATA` dopo `swap_players.py` (il controllo nella RPC resta).
- `public.get_snapshot(p_versions jsonb)` (anon): `{context, versions, parts}` senza profilo; per ripresa dal
  background (Fase 3), dopo il cambio nome squadra e per il pulsante di aggiornamento.
- `login`, `login_with_token` restano (le usa il codice su `main` fino al deploy e lo spike Android).

### 2.5 App: via supabase-py

Dopo questa fase l'app **non legge più nessuna tabella direttamente**: tutto passa da 4 RPC (`login_bundle`,
`token_bundle`, `get_snapshot`, `save_lineup`) più quelle di profilo già esistenti. Quindi non serve un
"query builder" httpx: basta `supabase_rest.rpc`.
- Le funzioni dell'app (`authenticate`, `save_lineup`, `update_*`, `logout`) escono da `SupabaseSync` e vanno in
  `supabase_rest.py` (o un nuovo `app_api.py` sopra di esso).
- Le trasformazioni pure (`_write_lineup_state`, raggruppamento del calendario di `pull_calendar`/`_attach_nba_games`,
  scrittura di standings e injuries) vanno in un nuovo modulo senza supabase-py (`league_cache.py`), che
  `supabase_manager.py` importa per gli script: un solo codice di formattazione.
- `ui_court.py` e `app.py` non importano più `supabase_manager`. Verifica: `python -X importtime test.py` senza `supabase`.
- `requirements.txt` (Render): si toglie `supabase==2.31.0` (il cron la installa già nel workflow; gli script
  locali la hanno nella .venv). Da confermare (decisione 6).

## 3. Misure prima e dopo

**Metodo** (strumentazione attivata solo con `FANTANBA_MISURE=1`, nessun effetto in produzione):
- conteggio richieste: event hook sul client httpx di `supabase_rest.py` e logger `httpx` a livello INFO (supabase-py
  usa httpx, quindi conta anche le vecchie letture); per ogni richiesta metodo, percorso, stato, ms, byte ricevuti e
  `Content-Encoding` (per sapere se Supabase comprime il jsonb);
- tempo: `perf_counter` dal clic su "Accedi" (o dall'avvio per il token) alla dashboard mostrata, stampato in console;
- `tools/misura_login.py`: ripete senza interfaccia il flusso di caricamento con un **token** preso da `.env`
  (`FANTANBA_TOKEN_MISURE`, non versionato), quindi solo letture, 5 prove per scenario, mediana e min-max;
- import a freddo: `python -X importtime -c "import app"` (5 prove).

**Scenari** (PC Windows con `test.py`, poi webapp su Render dai log):
1. login manuale a cache aggiornata; 2. login manuale con cache vecchia (si cancellano `sync_meta.json` /
`snapshot_meta.json` e i `*_state.json`); 3. accesso con token nei due casi; 4. primo tab "Altre squadre";
5. salvataggio formazione (lo misura l'utente dall'app: è una scrittura); 6. cambio nome squadra (idem, facoltativo).

**Attese**

| Scenario | Prima | Dopo |
|---|---|---|
| Login/token dopo un cron | 12 in sequenza | **1** (risposta più grande, ~150-200 KB non compressi; da misurare compressi) |
| Login/token a dati aggiornati | 2-3 | **1** |
| Dopo il solo cron injuries | 12 | 1 (solo la parte `injuries`) |
| Tab "Altre squadre" | 3 | **0** |
| Salvataggio | 1 | 1 (stesso tempo ± controllo scadenza) |
| Cambio nome squadra | 6 | 2 (RPC + `get_snapshot`) |
| Import dell'app | con supabase-py | −0,5 s Windows / −1,1 s Android (Fase 0) |

La prima misura "prima" si fa sul codice attuale con la sola strumentazione (primo commit della fase).

## 4. Migrazioni SQL (le esegue l'utente)

**A — `sql/2026-11_fase2a_snapshot_bundle.sql` (solo aggiunte, compatibile con `main` e con il cron attuale)**
1. tabella `edit_override` (RLS, nessun permesso ad anon);
2. `private.league_context`, `public.league_context`;
3. vincolo `lineup_players_team_gw_slot_key` DEFERRABLE INITIALLY IMMEDIATE;
4. tabella `app_snapshot` (RLS, nessun permesso ad anon), `private.snapshot_part`, `private.refresh_snapshot`,
   `public.refresh_snapshot` e `public.record_run` (solo service_role);
5. `login_bundle`, `token_bundle`, `get_snapshot` (anon, authenticated, service_role);
6. `change_team_name` aggiornata (rigenera le parti con i nomi: stesso comportamento visto dal vecchio codice);
7. prima rigenerazione `select private.refresh_snapshot();`, `notify pgrst`;
8. verifiche (permessi come in Fase 1; dimensione delle parti `pg_column_size`; confronto del contesto) e rollback.

Compatibilità: il codice su `main` non usa nulla di nuovo; il cron vecchio continua a scrivere `cron_runs` e
l'auto-riparazione tiene lo snapshot aggiornato anche prima del deploy.

**Poi: codice su `main`** (con l'OK dell'utente): app con bundle, cron e script con `record_run`.

**B — `sql/2026-11_fase2b_save_lineup_scadenza.sql` (restrittiva, dopo il codice su `main`)**
- `save_lineup` con il controllo `CAMBI_CHIUSI`, un solo `UPDATE` degli slot (via il +100), rigenerazione delle
  parti nel caso deroga. Firma invariata (`returns void`): l'app nuova e quella vecchia la chiamano allo stesso modo.
- Va dopo il codice perché da quel momento la deroga vale solo se è nella tabella `edit_override`, non nelle
  variabili di Render: prima di eseguirla l'utente controlla che su Render `EDIT_OVERRIDE_*` non siano impostate
  (o le copia nella tabella).

**C — più avanti, facoltativa** (fine Fase 3): via `login`, `login_with_token` e la SELECT di anon sulle tabelle
di lega (decisione 7).

Dopo A e B: aggiornare `sql/schema_riferimento.sql` (`app_snapshot`, `edit_override`, vincolo, funzioni).

## 5. File Python da cambiare

| File | Modifica |
|---|---|
| `supabase_rest.py` | `login_bundle`, `token_bundle`, `get_snapshot`, `save_lineup`, `logout`, `change_*` come funzioni; strumentazione `FANTANBA_MISURE` |
| `league_cache.py` (nuovo) | percorsi della cache, `snapshot_meta.json` con le versioni, applicazione delle parti (scrive `calendar.json`, `standings.json`, `injuries.json`, `*_gwN_state.json`), trasformazioni spostate da `supabase_manager` |
| `app.py` | `load_user_data` applica il bundle (nessuna richiesta); `league_loader` legge la parte `lineups` dalla cache; contesto e scadenza dal bundle; via `get_last_update`/`sync_*`/`sync_meta.json` |
| `ui_court.py` | `LoginView` chiama `login_bundle`; `Court` usa `deadline` e `now` del server e gestisce `CAMBI_CHIUSI`; cambio nome con `get_snapshot`; nessun import di `supabase_manager` |
| `time_manager.py` | via `edit_override()` dalle variabili d'ambiente; `get_league_context` resta come riserva senza rete (Fase 3) e per i test; `offset` dell'orologio del server |
| `supabase_manager.py` | `record_cron_run` e `mark_data_changed` → `rpc("record_run")`; importa le trasformazioni da `league_cache.py`; via `get_last_cron_run` e le letture usate solo dall'app |
| `cron_test_script.py` | nessuna modifica di logica (il `finally` chiama già `record_cron_run`); aggiornare il commento |
| `swap_players.py` | `default_from_gw` con `league_context` del DB; messaggi aggiornati |
| `tools/verifica_permessi.py` | nuovi controlli: anon non legge `app_snapshot`/`edit_override`, non esegue `refresh_snapshot`/`record_run`, esegue i bundle |
| ~~`tools/verifica_contesto.py`~~ | **cambiato in corso d'opera:** il confronto `private.league_context(t)` / `TimeManager.get_league_context` (ogni mezz'ora della stagione e al secondo intorno alle 23:59, compresi i cambi d'ora, con e senza deroga) è nella prova su Postgres locale usa e getta, come in Fase 1, e non nella repository (richiede pgserver e psycopg) |
| `tools/misura_login.py` (nuovo) | misure (solo letture con token) |
| `requirements.txt` | via `supabase` (decisione 6) |
| `docs/piano_migrazione_C1.md`, `sql/schema_riferimento.sql` | stato e schema a fine fase |

Verifica prima della pubblicazione (come in Fase 1): migrazioni A e B su Postgres locale usa e getta con i dati
di `data/calendar.json`; test della RPC `save_lineup` con permutazione degli slot, giornata sbagliata, oltre la
scadenza, con deroga; app su Windows (`test.py`) e webapp locale (`main.py`) contro il DB reale dopo la migrazione A.
Android: l'app vera è installabile solo dalla Fase 3 (come per la Fase 1); lo spike resta su `rpc/login`.

## 6. Ordine e cosa deve fare l'utente

1. Approvare il piano e le decisioni del punto 7.
2. (io) Commit con la strumentazione e misure "prima" su PC; l'utente misura il salvataggio dall'app.
3. (io) Migrazioni A e B e codice su `app-nativa`, verificati in locale.
4. **Utente:** eseguire A nello SQL Editor e le query di verifica; controllare che su Render non ci siano `EDIT_OVERRIDE_*`.
5. (io) Verifica di app desktop e webapp locale contro il DB reale; misure "dopo".
6. **Utente:** OK per portare il codice su `main` (deploy Render; il cron usa `record_run` dal run successivo); provare login, "Altre squadre", salvataggio sulla webapp; lanciare a mano un run `injuries` e controllare che cambi solo quella parte.
7. **Utente:** eseguire B; provare un salvataggio a cambi aperti; da quel momento la deroga si imposta con lo snippet SQL e si toglie da Render.
8. (io) Aggiornare stato del piano e schema, commit.

## 7. Decisioni aperte

1. **Snapshot in tabella** (proposta) vs Storage vs calcolo al volo: vedi tabella in 2.3.
2. **Snapshot costruito in SQL con righe grezze** (proposta; formattazione in Python nell'app, un solo codice)
   vs costruito in Python dal cron (riusa `pull_calendar` così com'è, ma RPC e SQL Editor non potrebbero
   rigenerarlo e `swap_players.py` dovrebbe ricostruire tutto).
3. **Parti separate con versione** (proposta) vs un unico blocco: con un blocco unico ogni run infortuni fa
   riscaricare ~150 KB; con le parti ~4 KB. Costo: un po' più di SQL.
4. **Vincolo DEFERRABLE INITIALLY IMMEDIATE** (proposta) vs INITIALLY DEFERRED: il secondo sposta al commit gli
   errori anche per cron e script (meno chiari da diagnosticare); per la permutazione in un solo UPDATE basta il primo.
5. **Deroga in una tabella** gestita dallo SQL Editor (proposta) vs uno script `tools/deroga_cambi.py` con la
   chiave segreta (più comodo, un file in più). Si possono avere entrambi.
6. **Togliere `supabase` da `requirements.txt` ora** (proposta: Render avvia più leggero e si verifica subito che
   l'app non lo importi) vs in Fase 3 con `pyproject.toml`.
7. **Chiudere la SELECT diretta di anon sulle tabelle di lega** (fase 2C/3): pro, la chiave pubblica non legge più
   niente direttamente; contro, servono RPC anche per debug e per lo spike. Proposta: decidere a fine Fase 3.
8. **Orologio**: l'app usa `now` del server per il blocco a video (proposta) vs orologio del dispositivo; in ogni
   caso decide il DB.

## 8. Rischi

- **Regola della scadenza duplicata** (SQL e Python): mitigata da `tools/verifica_contesto.py` e dal fatto che
  l'app nuova usa il contesto del DB; Python resta solo come riserva offline.
- **Dimensione della risposta dopo un cron** (~150-200 KB non compressi): da misurare se Supabase la comprime
  (httpx manda già `Accept-Encoding: gzip`); se no, colonne ridotte di `nba_games` o parte separata per le partite NBA.
- **`statement_timeout` di anon su Supabase (3 s)**: il bundle con rigenerazione deve restare ben sotto; misurato
  con `explain analyze` nella verifica di A.
- **Snapshot non rigenerato dopo una correzione manuale in SQL**: lo snippet `select public.refresh_snapshot();` va
  ricordato (scritto nel file e in `schema_riferimento.sql`); l'auto-riparazione copre solo cron e cambio giornata.
- **Render condivide `data/` fra tutti gli utenti**: invariato rispetto a oggi; i file di squadra ora si riscrivono
  a ogni login dal bundle, quindi non restano più indietro.
- **Ritardo del rollover**: tra le 23:59 e la fine del cron la giornata in corso cambia senza dati azzerati;
  oggi l'app fa lo stesso; con l'auto-riparazione lo snapshot segue `current_gw` appena il rollover scrive.
