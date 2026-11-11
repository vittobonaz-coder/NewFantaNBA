# Migrazione di FantaNBA ad app nativa Flet (opzione C1)

## Contesto

Lavori sulla repository di FantaNBA, un'app per gestire un campionato privato di fantabasket NBA (una decina di squadre e utenti). Allegati: la cartella del progetto e lo schema del database Supabase (solo contesto, non eseguibile così com'è).

Com'è fatta oggi:
- **Interfaccia:** Flet 0.82 in modalità web. `main.py` avvia FastAPI + uvicorn su Render (piano Free: 0,1 CPU, 512 MB, si spegne dopo 15 minuti). `app.py` contiene la logica di avvio e login, `ui_court.py` l'interfaccia, `fanta_obj.py` i modelli (Team, Player), `time_manager.py` giornate e scadenze. `test.py` avvia la stessa app come desktop in locale.
- **Dati:** `supabase_manager.py` (supabase-py, client unico condiviso, `run_parallel` per le richieste parallele). La chiave è quella pubblicabile, scritta nel codice.
- **Cache locale:** file JSON in `data/` (calendario, classifica, infortuni, stato delle formazioni `*_state.json`, `sync_meta.json`). Si riscaricano solo se dopo il download è girato un cron (tabella `cron_runs`).
- **Cron:** `cron_test_script.py` gira su GitHub Actions (`.github/workflows/cron-test.yml`), lanciato da pg_cron di Supabase, e scrive punteggi, partite, infortuni e rollover delle giornate. **Usa la stessa chiave pubblicabile dell'app.**
- **Login:** username e password in chiaro nella tabella `profiles`, confrontati via REST. Il "Ricordami" usa `login_tokens` (hash SHA-256 del token) e `SharedPreferences`.
- **Script locali di amministrazione:** `setup_fanta_championship.py`, `swap_players.py`, `reset_pre_setup.py`, `backfill_lineups.py`, `generate_avg_excel.py`, `download_*`.
- **Migrazioni SQL:** stanno in `sql/` e le eseguo io a mano nello SQL Editor di Supabase (vedi `sql/2026-11_cron_runs_manual.sql` per lo stile).

Problema: l'app web è lenta perché l'interfaccia gira sul server (ogni tocco = andata e ritorno su un'istanza da 0,1 CPU) e il server si addormenta. Ho deciso di passare a un'**app nativa costruita con `flet build`**: Android (APK) e Windows per primi, in futuro forse iOS. Lo stesso codice Python gira sul dispositivo e parla direttamente con Supabase.

In un'analisi precedente sono già stati fatti: client Supabase unico, salvataggio formazione in parallelo, tab costruiti alla prima apertura. Restano aperti, e vanno integrati in questo piano: RPC `save_lineup` atomica, "snapshot" preparato dal cron, login con password cifrate.

## Obiettivo

App nativa Android e Windows **veloce e fluida**: avvio rapido, interazioni senza attese, al massimo 1-2 richieste a Supabase al login, nessun server applicativo.

La versione web su Render **deve continuare a funzionare per tutta la migrazione** (serve a chi ha l'iPhone e come riserva) e usa lo stesso codice.

## Regole di lavoro

- Lavora su un branch dedicato (es. `app-nativa`) e fai un commit per ogni passo completato, con messaggi in italiano. Non fare push su `main` e non fare merge senza il mio OK.
- Procedi **una fase alla volta**. Alla fine di ogni fase fermati e dammi: cosa hai fatto, come l'hai verificato, cosa devo fare io (SQL da eseguire, segreti da impostare, prove sul telefono). Poi aspetta il mio via.
- **Database:**
  - Non eseguire mai SQL su Supabase da solo. Scrivi le migrazioni in `sql/` con data nel nome, commenti in italiano, ordine di esecuzione e uno script di rollback quando ha senso.
  - Ogni migrazione deve essere compatibile con il codice già in produzione (web su Render e cron), oppure dimmi esplicitamente in che ordine pubblicare codice e SQL.
- Non cancellare file e non riscrivere la cronologia git senza chiedere.
- Mantieni lo stile del codice esistente: commenti e docstring in italiano, sintetici; type hint; nessuna dipendenza nuova senza motivarla.
- Ogni volta che dici "più veloce", **misura** (tempi di login, apertura tab, salvataggio) prima e dopo, sul PC e, quando possibile, sul telefono.
- Se un'ipotesi di questo piano si rivela sbagliata (per esempio un pacchetto non compila per Android), fermati e proponimi le alternative con pro e contro invece di aggirare il problema in silenzio.

## Piano a fasi

### Fase 0 — Ricognizione e prova di fattibilità (prima di toccare l'app)

1. Leggi il codice e riassumi in poche righe flusso di login, sincronizzazione e salvataggio, segnalando quello che non torna con questa descrizione.
2. Verifica se le RLS sono attive sulle tabelle. Non posso dartelo dallo schema: preparami una query da eseguire nello SQL Editor che elenchi tabelle, stato RLS e policy esistenti.
3. **Prova tecnica decisiva:** crea in una cartella separata (es. `spike_android/`) una mini-app Flet che fa login e legge una tabella con le stesse dipendenze dell'app vera. Costruiscila con `flet build apk` e con `flet build windows`.
   - Il punto critico è supabase-py su Android: tra le sue dipendenze ci sono pacchetti con codice nativo (es. pydantic-core) che devono avere una versione per Android, per esempio dal repository di pacchetti di Flet.
   - Se non compila, valuta e confronta:
     a) chiamate dirette all'API REST di Supabase (PostgREST e RPC) con `httpx` o `requests`, con un piccolo modulo che sostituisce le poche funzioni di supabase-py usate dall'app;
     b) altre versioni dei pacchetti.
4. Misura l'avvio a freddo della mini-app sul telefono (tempo dal tocco dell'icona alla prima schermata).
5. Dimmi cosa serve installare sul mio PC Windows per compilare (Flutter SDK, Android SDK/JDK, Visual Studio per Windows) e se conviene compilare su GitHub Actions invece che in locale.

**Fine fase 0:** report di fattibilità e scelta del client Supabase. Non andare avanti senza il mio OK.

### Fase 1 — Sicurezza del database (prerequisito: la chiave finirà dentro un APK)

Con l'app sul telefono chiunque può estrarre la chiave pubblicabile e chiamare il database. Prima di distribuire l'APK:

1. **Password:** hash con `pgcrypto` (`crypt` / `gen_salt('bf')`) e migrazione delle password esistenti. Il login passa da una funzione `SECURITY DEFINER`, per esempio `login(username, password)`, che restituisce profilo e squadra. Lo stesso vale per token "Ricordami", cambio password, cambio username e nome squadra: tutte RPC con `search_path` fissato e permessi `EXECUTE` dati solo dove servono.
2. **RLS su tutte le tabelle:**
   - lettura con la chiave anon solo dei dati di lega che servono all'app (squadre senza dati personali, calendario/matchups, lineup_players, nba_games, nba_players, player_injuries, classifica);
   - nessuna lettura diretta di `profiles` e `login_tokens`;
   - nessuna scrittura diretta con la chiave anon: le scritture dell'app passano solo da RPC che controllano il token dell'utente.
3. **Cron e script di amministrazione:**
   - passano alla chiave segreta (service role), letta da variabile d'ambiente: segreto GitHub per il workflow, file `.env` locale non versionato per gli script;
   - la chiave segreta non deve mai finire nel codice dell'app;
   - tieni presente l'ordine: prima il cron con la chiave segreta, poi l'attivazione delle RLS, altrimenti il cron si rompe.
4. **Pulizia:** `todo.txt` contiene una password del database e `data/profiles.json` contiene credenziali in chiaro, entrambi versionati. Dimmi cosa togliere dai file, cosa ruotare su Supabase e come gestire la cronologia git: decido io se riscriverla.
5. La versione web su Render deve usare le stesse RPC e continuare a funzionare.

### Fase 2 — Meno richieste: save_lineup, login unico, snapshot

1. **RPC `save_lineup`:** salva slot, ruoli, posizioni nel roster e modulo della squadra in **una transazione e una richiesta**. Valuta il vincolo unico (squadra, giornata, slot) `DEFERRABLE INITIALLY DEFERRED` per evitare gli slot temporanei. Deve controllare token e scadenza dei cambi lato database, non fidarsi del client, e mantenere il riallineamento delle giornate future che fa oggi `update_lineup_slots`.
2. **Login in un colpo solo:** una RPC (es. `login_bundle`) che restituisce in una risposta profilo, squadra, versione dei dati e formazione modificabile. Lo stesso per l'accesso con token.
3. **Snapshot preparato dal cron:**
   - alla fine di ogni run il cron scrive in un unico posto (tabella `app_snapshot` con una riga jsonb e una versione, oppure un file in Supabase Storage: proponi tu e motiva) tutto ciò che è uguale per tutti: calendario con partite NBA raggruppate, classifica, infortuni, formazioni e moduli della giornata in corso;
   - l'app chiede la versione e scarica lo snapshot solo se è cambiata;
   - `cron_runs` / `mark_data_changed` vanno integrati con la versione dello snapshot, così anche le modifiche manuali (`swap_players.py`) lo rigenerano.
4. Misura il numero di richieste e i tempi del login: prima, nel caso peggiore, erano circa 11 richieste in sequenza dopo un cron.

### Fase 3 — App pronta per girare sul dispositivo

1. **Percorsi dei file:** oggi i JSON stanno in `data/` relativo alla cartella di lavoro, che sul telefono non è scrivibile. Centralizza i percorsi in una funzione (cartella dati dell'app sul dispositivo, ad esempio quella indicata da Flet per lo storage dell'app; `data/` sul server e in sviluppo) e usala ovunque, cron e script esclusi. Ora la cache è per singolo dispositivo: tienine conto per la logica "riscarica solo se è girato un cron".
2. **Dati iniziali nell'app:** `rules.json`, `giocatori_nba.json`, gli avatar in `assets/` e simili vanno inclusi nel pacchetto o scaricati, secondo dimensione e frequenza di aggiornamento: valuta tu. Non includere nell'app file con dati personali.
3. **Codice server separato:** `main.py` (FastAPI, gzip, cache) resta solo per Render. L'app nativa ha il suo punto d'ingresso. Aggiungi la configurazione per `flet build` (`pyproject.toml` con nome, versione, icona, dipendenze, permesso di rete Android).
4. **Interfaccia:** finestra non fissa a 358×757 sul desktop, layout corretto su schermi di telefoni diversi, comportamento del tasto Indietro su Android, ripresa dopo che l'app è stata in background (dati vecchi → aggiornamento silenzioso).
5. **Senza rete:** se Supabase non risponde, mostra gli ultimi dati in cache con un avviso, invece di bloccarsi.

### Fase 4 — Fluidità dell'interfaccia (ora la CPU è quella del telefono)

1. Misura sul telefono login, apertura dei tab e scambio di giocatori, e individua cosa costa di più.
2. Menu di scambio: oggi `refresh_menus` crea circa 150 `PopupMenuItem` per formazione e li ricrea a ogni scambio, e `update_data` ricostruisce l'intera card. Proponi e implementa l'alternativa migliore: interazione "tocca A, poi tocca B" con validità calcolata in Python, oppure aggiornamento solo delle card cambiate modificando i controlli esistenti.
3. Problemi minori già noti:
   - LoadingOverlay inutile sulle operazioni senza rete;
   - `show_message` che aggiunge SnackBar a `page.overlay` senza mai toglierli;
   - doppio `update()` negli scambi;
   - `json.dump` con indent sui file grandi.
4. Verifica che la versione web non peggiori.

### Fase 5 — Build, firma, distribuzione e aggiornamenti

1. **Firma Android:**
   - crea il keystore e dimmi dove conservarlo: mai nella repository, eventualmente come segreto GitHub;
   - spiegami che **senza lo stesso keystore gli aggiornamenti non si installano** sopra la versione precedente.
2. **Workflow GitHub Actions** che, su un tag `vX.Y.Z`, compila APK e app Windows e li pubblica nelle Release della repository.
3. **Aggiornamenti:**
   - tabella o riga di configurazione su Supabase (es. `app_config`) con ultima versione, versione minima supportata e link di download;
   - all'avvio l'app confronta la propria versione: se è più vecchia mostra "Nuova versione disponibile" con il link; se è sotto la minima blocca l'uso finché non si aggiorna;
   - la versione web ignora il controllo.
4. **Istruzioni per gli utenti della lega** (breve, in italiano):
   - installare l'APK su Android (fonti sconosciute);
   - installare l'app su Windows (avviso SmartScreen);
   - aggiornare.
5. **Windows:** valuta se basta una cartella zip o se conviene un installer.

### Fase 6 — (Facoltativa, dopo) iOS e dismissione

- **iOS:** cosa servirebbe (Mac, account sviluppatore Apple, TestFlight). Solo un report, nessuna implementazione.
- **Render:** quando tutti gli utenti Android/PC sono passati all'app, valuta come ridurre il carico della versione web su Render senza toglierla a chi ha l'iPhone.

## Cosa voglio vedere alla fine di ogni fase

- Riepilogo breve di cosa è cambiato e perché.
- Misure prima/dopo quando la fase riguarda la velocità.
- Elenco di cosa devo fare io, in ordine (SQL da eseguire, segreti, prove).
- Rischi o decisioni aperte.

Inizia dalla Fase 0.
