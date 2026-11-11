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

- **Fase 0:** da iniziare.
- **Fase 1:** —
- **Fase 2:** —
- **Fase 3:** —
- **Fase 4:** —
- **Fase 5:** —
- **Fase 6:** —

## Decisioni prese

(vuoto)
