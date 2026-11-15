# Piano di migrazione ad app nativa Flet (opzione C1)

Le regole di lavoro sono in `CLAUDE.md`. Lo schema del database è in `sql/schema_riferimento.sql`.

## Perché

L'app web è lenta:
- con Flet in modalità web l'interfaccia gira sul server: ogni tocco è un'andata e ritorno verso un'istanza Render da 0,1 CPU;
- il server si addormenta dopo 15 minuti;
- il client Flutter da circa 20 MB va scaricato e avviato.

Con **`flet build`** lo stesso codice Python gira sul dispositivo (Android e Windows per primi, forse iOS in futuro) e parla direttamente con Supabase.

## Obiettivo

App nativa **veloce e fluida**: avvio rapido, interazioni senza attese, al massimo 1-2 richieste a Supabase al login, nessun server applicativo. La versione web su Render resta attiva, con lo stesso codice.

## Piattaforme (requisito, non facoltativo)

L'app deve essere pienamente utilizzabile **sia da telefono Android sia da PC Windows**: stesse funzioni, stessi dati, stesso account.

- **Windows è una piattaforma principale, non un ripiego.** Ogni fase si considera conclusa solo se è verificata sia su Android sia sull'app Windows (`flet build windows`).
- **Layout desktop:** finestra ridimensionabile e massimizzabile, contenuto leggibile su schermi larghi (non una striscia da telefono stirata), uso con mouse e tastiera (Invio per confermare il login, rotellina per scorrere, niente azioni raggiungibili solo con gesti touch).
- **Dati e accesso su Windows:** cache nella cartella dati dell'utente (es. `%APPDATA%`), non nella cartella del programma. Il "Ricordami" deve funzionare anche sul desktop. Installazione e avvio senza diritti di amministratore.
- **Mac e Linux:** non obbligatori. Se servissero, `flet build macos` richiede un Mac: solo un report su cosa servirebbe.
- **Riserva:** da qualunque PC resta sempre utilizzabile anche la versione web su Render, dal browser.

Già fatto in un'analisi precedente (ottobre 2026): client Supabase unico, salvataggio formazione in parallelo, tab costruiti alla prima apertura.

Situazione da tenere presente:
- **cron e app usano oggi la stessa chiave pubblicabile**, scritta in `supabase_manager.py`;
- le password sono in chiaro in `profiles` e vengono confrontate via REST.

## Fasi

### Fase 0 — Ricognizione e prova di fattibilità (prima di toccare l'app)

1. Leggi il codice e riassumi in poche righe il flusso di login, di sincronizzazione e di salvataggio, segnalando quello che non torna con questo piano.
2. Preparami una query da eseguire nello SQL Editor che elenchi tabelle, stato delle RLS, policy, funzioni e trigger esistenti. Il risultato lo aggiungiamo a `sql/schema_riferimento.sql`.
3. **Prova tecnica decisiva:** crea in una cartella separata (`spike_android/`) una mini-app Flet che fa login e legge una tabella con le stesse dipendenze dell'app vera. Costruiscila con `flet build apk` e con `flet build windows`.
   - Il punto critico è supabase-py su Android: tra le sue dipendenze ci sono pacchetti con codice nativo (es. pydantic-core) che devono avere una versione per Android, per esempio dal repository di pacchetti di Flet.
   - Se non compila, confronta:
     a) chiamate dirette all'API REST di Supabase (PostgREST e RPC) con `httpx` o `requests`, con un piccolo modulo che sostituisce le poche funzioni di supabase-py usate dall'app;
     b) altre versioni dei pacchetti.
4. Misura l'avvio a freddo della mini-app sul telefono (dal tocco dell'icona alla prima schermata) e sul PC Windows (dal doppio clic alla prima schermata).
5. Dimmi cosa serve installare sul mio PC Windows per compilare (Flutter SDK, Android SDK/JDK, Visual Studio per Windows) e se conviene compilare su GitHub Actions invece che in locale.

**Fine fase:** report di fattibilità e scelta del client Supabase.

### Fase 1 — Sicurezza del database (la chiave finirà dentro un APK)

1. **Password:**
   - hash con `pgcrypto` (`crypt` / `gen_salt('bf')`) e migrazione delle password esistenti;
   - login tramite una funzione `SECURITY DEFINER` (es. `login(username, password)`) che restituisce profilo e squadra;
   - lo stesso per token "Ricordami", cambio password, cambio username e nome squadra: tutte RPC con `search_path` fissato e permessi `EXECUTE` solo dove servono.
2. **RLS su tutte le tabelle:**
   - lettura con la chiave anon solo dei dati di lega che servono all'app (squadre senza dati personali, matchups, lineup_players, nba_games, nba_players, player_injuries, classifica);
   - nessuna lettura diretta di `profiles` e `login_tokens`;
   - nessuna scrittura diretta con la chiave anon: le scritture dell'app passano solo da RPC che controllano il token dell'utente.
3. **Cron e script di amministrazione:**
   - passano alla chiave segreta (service role) letta da variabile d'ambiente: segreto GitHub per il workflow, `.env` locale non versionato per gli script;
   - **ordine:** prima il cron con la chiave segreta, poi l'attivazione delle RLS, altrimenti il cron smette di scrivere.
4. **Pulizia:** `todo.txt` contiene una password del database e `data/profiles.json` credenziali in chiaro, entrambi versionati. Dimmi cosa togliere dai file, cosa ruotare su Supabase e come gestire la cronologia git: decido io se riscriverla.
5. La versione web su Render deve usare le stesse RPC e continuare a funzionare.

### Fase 2 — Meno richieste: save_lineup, login unico, snapshot

1. **RPC `save_lineup`:**
   - salva slot, ruoli, posizioni nel roster e modulo della squadra in **una transazione e una richiesta**;
   - valuta il vincolo unico (squadra, giornata, slot) `DEFERRABLE INITIALLY DEFERRED` per evitare gli slot temporanei;
   - controlla token e scadenza dei cambi lato database;
   - mantiene il riallineamento delle giornate future che fa oggi `update_lineup_slots`.
2. **Login in un colpo solo:** una RPC (es. `login_bundle`) che in una risposta restituisce profilo, squadra, versione dei dati e formazione modificabile. Lo stesso per l'accesso con token.
3. **Snapshot preparato dal cron:**
   - a fine run il cron scrive in un unico posto tutto ciò che è uguale per tutti: calendario con partite NBA raggruppate, classifica, infortuni, formazioni e moduli della giornata in corso. Può essere una tabella `app_snapshot` (una riga jsonb con versione) o un file in Supabase Storage: proponi e motiva;
   - l'app scarica lo snapshot solo se la versione è cambiata;
   - `cron_runs` / `mark_data_changed` vanno integrati con la versione dello snapshot, così anche le modifiche manuali (`swap_players.py`) lo rigenerano.
4. Misura il numero di richieste e i tempi del login. Il caso peggiore attuale è di circa 11 richieste in sequenza dopo un cron.

### Fase 3 — App pronta per girare sul dispositivo

1. **Percorsi dei file:** centralizza i percorsi di `data/` in una funzione: cartella dati dell'app sul dispositivo, `data/` sul server e in sviluppo. Usala ovunque, cron e script esclusi.
   - La cache ora è per singolo dispositivo: tienine conto nella logica "riscarica solo se è girato un cron".
   - Valuta di togliere dal versionamento i JSON di cache (`calendar`, `standings`, `injuries`) con `.gitignore` + `git rm --cached`, dopo aver verificato che l'app parta senza.
2. **File inclusi nel pacchetto:** decidi per `rules.json`, `giocatori_nba.json` e gli avatar in `assets/` se includerli nell'app o scaricarli (in base a dimensione e frequenza di aggiornamento). Non includere file con dati personali.
3. **Separazione server/app:**
   - `main.py` resta solo per Render; l'app nativa ha il suo punto d'ingresso;
   - aggiungi `pyproject.toml` per `flet build`: nome, versione, icona, dipendenze, permesso di rete Android.
4. **Interfaccia:**
   - finestra non fissa a 358×757 sul desktop: layout adattivo per PC secondo la sezione "Piattaforme";
   - layout corretto su telefoni di dimensioni diverse;
   - tasto Indietro su Android;
   - ripresa dal background: dati vecchi → aggiornamento silenzioso.
5. **Senza rete:** ultimi dati in cache con un avviso, invece di bloccarsi.

### Fase 4 — Fluidità dell'interfaccia (ora la CPU è quella del telefono)

1. Misura sul telefono e sul PC Windows login, apertura dei tab e scambio di giocatori, e individua cosa costa di più.
2. **Menu di scambio:** `refresh_menus` crea circa 150 `PopupMenuItem` per formazione e li ricrea a ogni scambio, e `update_data` ricostruisce tutta la card. Proponi e implementa l'alternativa migliore:
   - interazione "tocca A, poi tocca B";
   - oppure aggiornamento solo delle card cambiate, modificando i controlli esistenti.
3. **Problemi minori noti:**
   - LoadingOverlay inutile sulle operazioni senza rete;
   - `show_message` che aggiunge SnackBar a `page.overlay` senza mai toglierli;
   - doppio `update()` negli scambi;
   - `json.dump` con indent sui file grandi.
4. Verifica che la versione web non peggiori.

### Fase 5 — Build, firma, distribuzione e aggiornamenti

1. **Keystore Android:**
   - crealo e dimmi dove conservarlo: mai nella repository, eventualmente come segreto GitHub;
   - ricordami che senza lo stesso keystore gli aggiornamenti non si installano sopra la versione precedente.
2. **Workflow GitHub Actions:** su un tag `vX.Y.Z` compila APK e app Windows e li pubblica nelle Release della repository.
3. **Controllo aggiornamenti:**
   - configurazione su Supabase (es. `app_config`) con ultima versione, versione minima e link di download;
   - all'avvio l'app mostra "Nuova versione disponibile" e blocca l'uso sotto la versione minima;
   - la versione web ignora il controllo.
4. **Istruzioni brevi per gli utenti della lega:** installare l'APK (fonti sconosciute), installare su Windows (avviso SmartScreen), aggiornare.
5. **Windows:** valuta se basta una cartella zip o se conviene un installer.

### Fase 6 — (Facoltativa) iOS e dismissione

- **iOS:** report su cosa servirebbe (Mac, account sviluppatore Apple, TestFlight). Nessuna implementazione.
- **Render:** quando tutti gli utenti Android/PC sono passati all'app, valuta come ridurre il carico della versione web senza toglierla a chi ha l'iPhone.

## Stato di avanzamento

Aggiornare a fine di ogni fase: data, cosa è stato fatto, commit, cosa resta da fare da parte mia, decisioni prese.

- **Fase 0 (12/11/2026):** fattibilità confermata, dettagli in `docs/fase0_report.md`.
  - **Fatto:**
    - ricognizione dei flussi;
    - query di schema `sql/2026-11_ricognizione_schema.sql`;
    - mini-app `spike_android/` compilata e provata su Android (Galaxy A52s, Android 14) e Windows 11;
    - misure di avvio a freddo con supabase-py e REST diretto.
  - **Esiti:**
    - supabase-py compila per Android solo con `pydantic==2.13.4`;
    - con REST diretto i dati arrivano circa 1 s prima;
    - le Build Tools di Visual Studio hanno un CMake a 32 bit che richiede un aggiramento;
    - su Windows la cartella dati predefinita di Flet è Documenti (OneDrive): l'app vera userà `%APPDATA%`;
    - la repository GitHub è pubblica, con password versionate.
  - **Versione web:** a server addormentato servono 32,6 s solo per la prima risposta; a server sveglio, circa 4,5 s per scaricare il client Flutter.
  - **Fatto da me (12/11):**
    - password del database cambiata;
    - query di schema eseguita, risultato in `sql/schema_riferimento.sql`;
    - verifiche Windows (finestra, Invio) OK.
  - **Database:** RLS spenta quasi ovunque e `anon` con tutti i privilegi. Con la chiave pubblicabile (pubblica) oggi si leggono le password da `profiles` e si può svuotare qualunque tabella: priorità della Fase 1.
  - **Da fare:** niente per la Fase 0.
- **Fase 1 (13-14/11/2026): conclusa.** Password con hash bcrypt, accesso e scritture dell'app solo tramite RPC, RLS su tutte le tabelle, cron e script sulla chiave segreta. Commit `0a0f4129` (codice, su `main` dal 14/11) e successivi di stato su `app-nativa`.
  - **Fatto:**
    - migrazioni `sql/2026-11_fase1a_password_rpc.sql` (hash, scadenza dei token, RPC `login`, `login_with_token`, `logout`, `change_password`, `change_username`, `change_team_name`, `save_lineup`, `admin_set_password`), `sql/2026-11_fase1b_rls_revoche.sql` (RLS, sola lettura dei dati di lega, default privileges chiusi), `sql/2026-11_fase1c_drop_password_chiaro.sql` (via le password in chiaro);
    - `supabase_rest.py` (RPC con httpx); login, profilo e salvataggio formazione passano dalle RPC: il salvataggio da 48 richieste a 1;
    - cron e script con `SupabaseSync(admin=True)` e `SUPABASE_SECRET_KEY`; workflow con il segreto, input `dry_run` e versioni fissate; `reset_pre_setup.py` con `--conferma`; `.env.example`; `tools/verifica_permessi.py`.
  - **Verifiche:**
    - prima della pubblicazione: le tre migrazioni su un Postgres locale usa e getta (pgcrypto simulato) e il codice Python con un server finto;
    - migrazione A: nessun profilo senza hash, 23 token "Ricordami" esistenti rimasti validi;
    - codice su `main` il 14/11 alle 18:47 (avanzamento diretto): deploy su Render, login e salvataggio, run manuale `injuries` verde con la chiave segreta;
    - migrazione B: `tools/verifica_permessi.py` 17/17, letture dell'app verificate (8 squadre, classifica, 96 matchups, 1206 partite NBA), webapp e run `injuries` di nuovo ok;
    - migrazione C: colonna in chiaro assente; login, cambio password, logout e nuovo login sulla webapp ok.
  - **Verifica Android/Windows:** in questa fase solo webapp e script; l'app installata è provabile dalla Fase 3. Lo spike Android usa già `rpc/login`.
  - **Da fare da parte tua:**
    - controllare nei prossimi giorni che i run automatici di daily, rollover e injuries siano verdi;
    - far cambiare la password a tutti gli utenti (prima chi ha ancora quella iniziale);
    - facoltativo: disattivare le chiavi API legacy (JWT), che nessun componente usa.
  - **Password dimenticata:** non si recupera; si reimposta con `admin_set_password` dallo SQL Editor (esempio in `sql/schema_riferimento.sql`).
- **Fase 2 (14/11/2026): codice e migrazioni pronti su `app-nativa`, da pubblicare.** Piano approvato in `docs/fase2_piano.md`.
  - **Fatto:**
    - migrazione A `sql/2026-11_fase2a_snapshot_bundle.sql` (solo aggiunte): contesto della lega e deroga nel database (`private.league_context`, tabella `edit_override`), vincolo unico DEFERRABLE INITIALLY IMMEDIATE, tabella `app_snapshot` con 4 parti versionate (md5 del contenuto) e auto-riparazione, RPC `login_bundle`, `token_bundle`, `get_snapshot`, `league_context`, `record_run`, `refresh_snapshot`;
    - migrazione B `sql/2026-11_fase2b_save_lineup_scadenza.sql` (restrittiva): `save_lineup` controlla giornata e scadenza (`CAMBI_CHIUSI`) e scambia gli slot con un solo UPDATE;
    - app: accesso in una richiesta (bundle), nessuna lettura di tabelle, tab "Altre squadre" senza richieste, scadenza e ora dal database; nuovo `league_cache.py` (cache e trasformazioni, usato anche dagli script); `supabase_rest.py` con tutte le RPC dell'app e le misure (`FANTANBA_MISURE=1`); via supabase-py dall'app e da `requirements.txt`;
    - cron e `swap_players.py`: `record_run` (cron_runs + snapshot; se la RPC manca, solo cron_runs come prima); `swap_players.py` prende la giornata modificabile dal database;
    - `EDIT_OVERRIDE_*` non si legge più dalle variabili d'ambiente: la deroga è in `edit_override` (snippet in fondo alla migrazione A);
    - `tools/misura_login.py`, nuovi controlli in `tools/verifica_permessi.py`.
  - **Verifiche (prima della pubblicazione):**
    - migrazioni Fase 1 + 2A + 2B su Postgres 16 locale usa e getta con le 24 giornate vere: 64/64 controlli; `league_context` uguale a `TimeManager.get_league_context` su 22.440 istanti (ogni 30 minuti della stagione e al secondo intorno alle 23:59 di Roma, compresi i cambi d'ora, con e senza deroga); A rieseguibile; la `save_lineup` di Fase 1 funziona con il vincolo deferrable;
    - cache: sugli stessi dati reali i file prodotti da `league_cache` sono identici a quelli del codice vecchio (classifica, infortuni, 8 formazioni); il calendario differisce solo per l'ordine dei matchup dentro la giornata (ora per nome della squadra di casa: serve un ordine fisso per la versione);
    - l'app non importa più supabase-py.
  - **Misure prima** (PC, codice `9f213df0`, 5 prove, solo letture anonime; in più c'è sempre la RPC di login):
    - dopo un cron (cache vuota): 11 richieste in sequenza, 1,51 s (1,48–1,76); tab "Altre squadre": 3 richieste, 0,36 s;
    - cache aggiornata: 1 richiesta (`cron_runs`), 0,14 s; tab "Altre squadre": 1 richiesta, 0,12 s;
    - import dell'app (flet + supabase-py): 1,00 s (0,97–1,26).
  - **Migrazione A eseguita (14/11, 22:55 italiane):** query di verifica ok (4 parti: calendar 251 KB di testo, lineups 37 KB, injuries 4 KB, standings 2 KB; contesto GW 4 in corso, GW 5 modificabile fino al 17/11 alle 23:59; vincolo deferrable; permessi come previsto; `get_snapshot` con le versioni attuali 0,7 ms nel database). `tools/verifica_permessi.py`: tutto a posto. Lo snapshot vero produce file di cache identici a quelli del codice vecchio (calendario a meno dell'ordine dei matchup).
  - **Misure dopo** (PC, `tools/misura_login.py`, 3 serie da 5 prove, solo letture con `get_snapshot`; `token_bundle`/`login_bundle` aggiungono profilo e formazione nella stessa richiesta):
    - dopo un cron che cambia tutto: **1 richiesta**, 0,15–0,20 s di rete (mediane), 0,17–0,23 s con la scrittura della cache; 295 KB di JSON, **20 KB trasferiti** (gzip);
    - cache aggiornata: **1 richiesta**, 0,11–0,13 s, 255 byte trasferiti;
    - tab "Altre squadre": **0 richieste** (dalla cache);
    - import dell'app 0,70 s (0,69–0,73), cioè −0,3 s.
  - **Da fare da parte tua, in ordine:**
    1. ~~eseguire la migrazione A e le query di verifica~~ (fatto il 14/11);
    2. ~~verifiche e misure contro il database vero~~ (fatto il 14/11);
    3. ~~controllare che su Render non ci siano `EDIT_OVERRIDE_GW` / `EDIT_OVERRIDE_UNTIL`~~ (15/11: nessuna deroga); ~~prova di login sull'app desktop locale~~ (15/11: ok);
    4. OK per portare il codice su `main` (deploy Render e cron);
    5. eseguire `sql/2026-11_fase2b_save_lineup_scadenza.sql` e provare un salvataggio dalla webapp.
  - **Verifica Android/Windows:** come in Fase 1, solo webapp e desktop locale; l'app installata si prova dalla Fase 3.
- **Fase 3:** —
- **Fase 4:** —
- **Fase 5:** —
- **Fase 6:** —

## Decisioni prese

- **12/11/2026 — Client Supabase dell'app: REST diretto con `httpx`** (opzione a della Fase 0), al posto di supabase-py.
  - Motivo: circa 1 s in meno a ogni avvio, e nessuna dipendenza nativa vincolata (pydantic-core per Android).
  - Riguarda l'app, nativa e web. Cron e script di amministrazione possono restare su supabase-py.
  - Il modulo sostitutivo si scrive quando si toccano le query (Fasi 1-3).
- **12/11/2026 — La repository resta pubblica** (minuti GitHub Actions illimitati). Si cambia la password del database e si elimina `data/profiles.json`; la cronologia non si riscrive.
- **13/11/2026 — Fase 1:**
  - `save_lineup` anticipata dalla Fase 2, senza controllo della scadenza dei cambi (resta lato app fino alla Fase 2);
  - RPC chiamate con httpx (`supabase_rest.py`), primo pezzo del modulo REST;
  - ogni accesso crea un token di sessione: 90 giorni con "Ricordami", 7 senza;
  - nessun limite ai tentativi di login;
  - `rosters` leggibile con la chiave pubblicabile;
  - versioni dei pacchetti fissate nel workflow del cron;
  - `reset_pre_setup.py` cancella solo con `--conferma`;
  - la versione web resta sempre utilizzabile: l'unica finestra di possibile disservizio è il deploy su Render.
- **14/11/2026 — Fase 2:**
  - snapshot in una tabella (`app_snapshot`), non in Supabase Storage: una richiesta in meno, aggiornabile dalle RPC e dallo SQL Editor, niente cache CDN;
  - snapshot costruito in SQL con righe "grezze"; le trasformazioni restano in Python (`league_cache.py`), uguali per app e script;
  - 4 parti con versione = md5 del contenuto: il cron injuries cambia solo la sua parte, un run senza modifiche non fa scaricare nulla;
  - vincolo unico DEFERRABLE INITIALLY IMMEDIATE;
  - deroga ai cambi nella tabella `edit_override`, impostata dallo SQL Editor;
  - supabase-py tolto da `requirements.txt` (l'app non lo importa più);
  - la SELECT diretta di anon sulle tabelle di lega resta per ora: si decide a fine Fase 3;
  - l'app usa l'ora del server per il blocco dei cambi a video; `TimeManager.simulate_now` cambia solo quello.
