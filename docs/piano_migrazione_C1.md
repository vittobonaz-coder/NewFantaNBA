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
- **Fase 2 (14–15/11/2026): conclusa.** Piano approvato in `docs/fase2_piano.md`. Codice su `main` dal 15/11 (`b4dbf7bb`), migrazioni A e B eseguite.
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
    4. ~~OK per portare il codice su `main`~~ (15/11: `main` = `b4dbf7bb`, deploy Render ok);
    5. ~~eseguire la migrazione B e provare un salvataggio dalla webapp~~ (15/11: ok);
    6. ~~run manuale `injuries`~~ (15/11: in `app_snapshot` si è aggiornata solo la parte `injuries`, 11:36 UTC; le altre tre restano alle 11:11).
  - **Da tenere d'occhio:** i prossimi run automatici di daily e rollover (il rollover cambia `edit_gw` e rigenera lo snapshot); la deroga ai cambi ora si mette solo in `edit_override` (snippet in fondo alla migrazione A), non più nelle variabili di Render.
  - **Verifica Android/Windows:** come in Fase 1, solo webapp e desktop locale; l'app installata si prova dalla Fase 3.
- **Fase 3 (15–16/11/2026): conclusa.** Verificata su Android e Windows; codice su `main` dal 16/11 (`9fcde878`, avanzamento diretto), stato aggiornato su `app-nativa`. Piano approvato in `docs/fase3_piano.md` (decisioni tutte come proposto). Nessuna migrazione SQL.
  - **Fatto:**
    - `app_paths.py`: cache in `data/` per Render, sviluppo, cron e script (invariati); nell'app installata in `%APPDATA%\Bonkest\Bonkest\cache` (Windows) o nella cartella interna (Android); `rules.json` spostato in `assets/`;
    - `data/calendar.json`, `standings.json`, `injuries.json` fuori dal versionamento (verificato: l'app li ricrea da una cartella vuota, il cron non li legge);
    - `pyproject.toml` (`it.bonkest.bonkest`, versione 0.3.0, ingresso `nativa.py`, arm64-v8a + armeabi-v7a, permesso INTERNET), `tools/prepara_build.py` (cartella `app_src/` con **lista di file ammessi** e controllo dei segreti: `flet build` impacchetterebbe tutta la cartella, `.env` compreso), `tools/build_windows.ps1` (aggiramento CMake della Fase 0), icona e segnaposto ridotto (577 → 48 KB);
    - interfaccia: area sicura, finestra libera sul PC (iniziale 1100×800, minima 380×600), contenuti con larghezza massima, campo e panchina affiancati da 760 dp, etichette dei tab leggibili da 600 dp, frecce accanto alle barre scorrevoli col mouse (anche web da PC), Invio al login, foto con riserva dal CDN NBA;
    - Android: Indietro (chiude il dialog → avvisa se la formazione non è salvata → torna a Squadra → esce), solo verticale;
    - ripresa: al ritorno in primo piano, se i dati hanno più di 5 minuti, una `token_bundle`; se è cambiato qualcosa la dashboard si ricostruisce sul tab corrente, salvo modifiche non salvate (barra "Dati aggiornati disponibili");
    - senza rete (solo app installata, con "Ricordami"): dashboard dalla cache con barra "Senza connessione — dati del …" e "Riprova"; salvataggi con messaggio "Senza connessione"; a sessione scaduta si cancellano token e profilo salvato;
    - `nativa.py` scrive i tempi di ogni avvio in `avvii.jsonl` nella cartella dati.
  - **Trovato in corso d'opera:** in Flet 0.82 una `SnackBar` aggiunta a `page.overlay` **non compare** (provato con una mini-app): i messaggi "Formazione salvata", errori di salvataggio e del profilo probabilmente non si vedevano neanche sulla webapp in produzione. Ora usano `page.show_dialog` (che li toglie anche dalla pagina alla chiusura: risolve il punto della Fase 4).
  - **Verifiche fatte da me:**
    - cache da cartella vuota (solo letture anonime): 13 file creati, seconda richiesta senza parti; script e `supabase_manager` importano come prima;
    - build: APK `build/apk/bonkest.apk` **66 MB** (2 architetture; spike con 3: 70,6 MB), primo build 8 min e poi ~3 min; app Windows `build/windows/` **78 MB** (spike: 99 MB), ~4 min;
    - APK e cartella Windows: contengono solo gli 8 moduli e `assets/` (138 file), nessun `.env`/`data/`, nessuna traccia di `sb_secret_` in tutto l'APK; le foto non sono duplicate;
    - webapp locale nel browser integrato a 320, 375 e 1280 px: login, Squadra, Altre squadre, Calendario (frecce), Campionato; passaggio largo/stretto al ridimensionamento;
    - app vera in modalità nativa su banco di prova con rete simulata assente: avvio dalla cache con barra, "Riprova" senza rete (avviso), rete tornata con modifiche non salvate (barra "Dati aggiornati", modifica conservata), "Ricarica", sessione scaduta → login con token e profilo cancellati;
    - `nativa.py` sul PC (client desktop di Flet): accesso automatico, cache nella cartella dati, `avvii.jsonl` scritto.
  - **Prove sul dispositivo (15/11, utente):** tutta la lista della sezione 11 di `docs/fase3_piano.md` superata su telefono Android e su app Windows installata (primo accesso, accesso automatico, salvataggio, Indietro, ripresa dal background, senza rete, finestra e mouse, cambio utente).
  - **Misure di avvio, app Windows** (`avvii.jsonl`, ms dall'inizio di Python, 5 avvii con "Ricordami" e cache piena): import di flet 637 (622–658), pagina pronta 949 (948–953), **dashboard 2.872 (2.575–3.248)**; primo avvio a cache vuota fino al login 1.155. Circa 1,9 s passano tra pagina pronta e dashboard (cartella dati, token, una richiesta, scrittura della cache, costruzione dei controlli): da analizzare nella Fase 4. Telefono: misure col cronometro non ancora riportate.
  - **16/11, dopo le prove:** l'app installata si chiama **Bonkest** (APK 67 MB, app Windows 79 MB; `it.bonkest.bonkest`, `bonkest.apk`, `bonkest.exe`, cartella dati `%APPDATA%\Bonkest\Bonkest\cache`; le misure sopra erano su `%APPDATA%\FantaNBA\FantaNBA`). Titolo e login dicono "Bonkest" anche sulla webapp; le chiavi dello storage (`fantanba.login_token`) restano, così il "Ricordami" della webapp non si perde. Aggiunte in `assets/players` le foto dei 33 giocatori con media FPTS ≥ 18 (file `nba_stats_2026_2027_2026-11-16.xlsx`) che non l'avevano: 160 foto, 2,8 MB.
  - **Da fare da parte tua, in ordine:**
    1. ~~prova veloce di `bonkest.apk` e `bonkest.exe`~~ (16/11: ok);
    2. ~~OK per portare il codice su `main`~~ (16/11: `main` = `9fcde878`, deploy Render ok);
    3. prova della webapp da iPhone (login, tab, messaggio "Formazione salvata!" dopo un salvataggio, margini) e da PC;
    4. facoltativo: tempi di avvio sul telefono col cronometro (tocco dell'icona → dashboard, 5 volte); cancellare la vecchia cartella `%APPDATA%\FantaNBA`.
  - **Da tenere d'occhio:** dopo `swap_players.py` la foto di un giocatore nuovo va committata e portata su `main` per la webapp; le app installate la prendono dal CDN NBA finché non si rifà il build.
- **Fase 4 (16–18/11/2026): conclusa.** Verificata su Android, Windows e webapp; piano e dettagli in `docs/fase4_piano.md`
  (sezione 14 "Cambiato in corso d'opera"). Codice su `main` dal 18/11 (`0e7171a0`); commit finale (via le misure
  temporanee) da portare su `main`. Nessuna migrazione SQL.
  - **Causa trovata:** non i menu ma un difetto di Flet 0.82: ogni `update()` faceva il `repr` di tutto il sottoalbero
    (`logger.debug` con f-string in `object_patch.py`), e Flet aggiornava da sé la pagina intera dopo ogni evento.
    Corretto a monte da Flet 0.83.0; qui con `flet_fix.py`.
  - **Fatto:**
    - `flet_fix.py` (solo Flet 0.82): `repr` brevi dei controlli e aggiornamento automatico spento per tutta l'app;
    - un solo `update()` per operazione; card, menu di scambio aggiornati sul posto (righe dei titolari ricreate a ogni
      cambio modulo: riusarle interrompeva la patch sul client);
    - velo di caricamento solo dove c'è rete o una prima costruzione; JSON compatto per i file grandi della cache;
      salvataggio della formazione atomico;
    - app installata: connessione a Supabase in parallelo con l'import di flet (`supabase_rest.warm_up`, nessun
      accesso al DB); profilo per l'uso senza rete salvato dopo la dashboard; foto mancanti scaricate una volta nella
      cartella dati (`foto.py`), una sola immagine per card;
    - `tools/prova_scambi.py` (operazioni casuali su tutte le formazioni in cache: card, menu, totale, patch);
    - misure temporanee (`misure.py`, tab "Tempi" nascosto) usate per il prima/dopo e tolte nel commit finale.
  - **Misure prima → dopo** (mediane; telefono Galaxy A52s, app Windows, webapp su Render da PC, tempo del server):
    | | Telefono | Windows | Webapp |
    |---|---|---|---|
    | Avvio / login → dashboard | 5,4 s → **2,4 s** | 2,7 s → **1,3 s** | 11,3 s → **1,6 s** |
    | Scambio | 3.237 → **48 ms** | 907 → **15 ms** | 9.697 → **54 ms** |
    | Cambio modulo | 6.466 → **52 ms** | → **17 ms** | 19.410 → **199 ms** |
    | Annulla | 6.970 → **45 ms** | 1.922 → **16 ms** | 19.567 → **135 ms** |
    | Giornata↔Formazione | 6.656 → **76 ms** | 1.833 → **28 ms** | 18.734 → **321 ms** |
    | Apertura dei tab | ~5 s → **26–162 ms** | ~1,3 s → **10–44 ms** | 13,5–15,3 s → **25–244 ms** |
    | Giornate Lega / NBA | 5,1 / 5,7 s → **67 / 230 ms** | 1,3 / 1,4 s → **54 / 109 ms** | 13,9 / 15,3 s → **57 / 406 ms** |
    | Salvataggio (di cui rete) | 5,9 s → **0,67 s** (0,57) | 2,0 s → **0,41 s** (0,33) | 15,1 s → **0,34 s** (0,17) |
    Sul telefono l'avvio è ora dominato dall'import di flet (~1,5 s); la connessione anticipata lì ha bilancio circa
    nullo (stessa CPU), su Windows toglie ~0,4 s. "Dashboard subito dalla cache" non fatta: toglierebbe solo 150–400 ms.
  - **Da fare da parte tua, in ordine:**
    1. ~~prove e misure su telefono e Windows~~ (18/11: ok, dopo la correzione di pallino e cambio modulo);
    2. ~~OK per `main` e misure della webapp~~ (18/11: `0e7171a0`, misure fatte);
    3. togliere `FANTANBA_MISURE` da Render, se non l'hai già fatto;
    4. OK per portare su `main` il commit finale (un deploy, nessun cambiamento visibile);
    5. installare i build normali (senza misure) su telefono e PC, sopra quelli di prova.
  - **Rischi e cose da tenere d'occhio:**
    - `flet_fix.py` vale solo per Flet 0.82 (controlla la versione e con un'altra non fa nulla): aggiornare Flet a fine
      migrazione, con una prova separata, e poi toglierlo (vedi "Decisioni prese", 16/11);
    - con `flet_fix` l'aggiornamento automatico di Flet è spento: ogni gestore di eventi nuovo deve chiamare da sé
      `update()` sui controlli che cambia (`show_dialog`/`pop_dialog` aggiornano da soli);
    - nelle sottoclassi dei controlli Flet non usare per gli attributi nomi di proprietà di Flet (es. `badge`, che
      disegna il pallino delle notifiche);
    - non spostare un controllo da una lista a un'altra nello stesso `update()`: il client può smontarlo dopo lo
      spostamento e la patch si interrompe (ricreare il contenitore, come le righe dei titolari);
    - `tools/prova_scambi.py` controlla la parte Python, non il client: dopo modifiche al campo serve sempre una prova a
      video (modulo, Annulla, Salva);
    - l'avvio sul telefono (~2,4 s) è dominato dall'import di flet (~1,5 s), che non dipende dal nostro codice;
    - foto: un giocatore nuovo senza foto inclusa si vede dal CDN NBA e, nell'app installata, resta offline dopo il primo
      avvio con rete; per la webapp la foto va comunque committata in `assets/players/`.
- **Fase 5 (19–22/11/2026): conclusa.** Piano approvato in `docs/fase5_piano.md` (decisioni in cima al file);
  procedura di rilascio in `tools/README_release.md`. Release `v1.0.0` pubblicata, `app_release` a 1.0.0.
  - **Fatto (19/11, `ad8ec062` su `app-nativa`):** versione unica 1.0.0 (build 10000) da `pyproject.toml`
    (`prepara_build.py` controlla versione, build e tag e scrive `versione.py`); versione nelle Impostazioni;
    controllo aggiornamenti (`aggiornamenti.py`, RPC `app_release` nella connessione anticipata, schermata
    "Aggiornamento necessario" e barra "Disponibile la versione …"; webapp esclusa); migrazione
    `sql/2026-11_fase5_app_release.sql` (solo aggiunte); `build_windows.ps1` portabile (DLL x64 con vswhere) con
    installer Inno Setup e zip; `build_apk.ps1` (firma dal `.env`); `controlla_build.py`; workflow
    `.github/workflows/release.yml` (tag → release in bozza); `docs/istruzioni_installazione.md`, `tools/README_release.md`.
  - **Verifiche fatte da me:** migrazione su Postgres usa e getta (rieseguibile, anon solo RPC, versioni malformate
    rifiutate); `warm_up` contro server finto (risposta, RPC assente, rete assente); banco di prova dell'app in
    modalità nativa (schermata bloccante, "Scarica", barra chiudibile, "Bonkest 1.0.0 (rc.1)"); build Windows
    locale con lo script nuovo (exe 1.0.0+10000, DLL x64); `build_apk.ps1` si ferma senza firma e con
    `-ChiaveDebug` produce un APK riconosciuto come "chiave di DEBUG"; `controlla_build.py` trova segreti e
    keystore dentro zip annidati. Non provati: workflow su GitHub, installer (Inno Setup non è sul PC), firma vera.
  - **Prove su GitHub (20–22/11):** `rc.1` apksigner di build-tools 37 non funzionante sul runner (errore nascosto
    dagli avvisi di Java) → `controlla_build.py` prova tutti gli apksigner e scrive gli errori come annotazioni;
    `rc.2`/`rc.3` impronta non corrispondente: nella variabile c'era tutto l'output di `keytool` (ora il controllo
    accetta anche il prefisso `SHA256:` e mostra entrambe le impronte); **`rc.4` (`93d2f130`) tutto verde**: APK firmato
    con la chiave vera (~7,5 min), Windows con installer e zip (~5 min, aggiramento CMake e Inno Setup funzionano anche
    su GitHub), pre-release in bozza con i 4 file.
  - **Fatto da te (20–22/11):** keystore e copie, segreti e variabile GitHub, migrazione SQL; prove della pre-release
    `rc.4` su telefono e PC (sezione 3.2-bis di `tools/README_release.md`): accesso e versione, installer senza
    amministratore e "Ricordami", barra "Disponibile la versione 1.0.1", blocco con versione minima, valori rimessi a
    0.0.0, avvio senza rete: **tutto ok**.
  - **22/11, rilascio:** con il tuo OK `main` = `a8011606` (avanzamento diretto da `app-nativa`, deploy di Render);
    tag `v1.0.0` sullo stesso commit, workflow verde (Android ~8,5 min, Windows ~7 min), release `v1.0.0` in bozza.
  - **Fatto da te (22/11):** release `v1.0.0` pubblicata; `app_release.latest_version` = 1.0.0 (nessuna barra con la
    `rc.4`, corretto: internamente è già 1.0.0).
  - **Restano da fare da parte tua (non bloccano la chiusura):** controllare la webapp dopo il deploy (in Gestione
    Profilo "Bonkest — versione web"); installare la 1.0.0 sopra la `rc.4` su telefono e PC senza disinstallare (in
    Impostazioni "Bonkest 1.0.0" senza "(rc.4)"); link `…/releases/latest` alla lega; facoltativo: cancellare le
    bozze `rc`.
  - **Rischi da tenere d'occhio:**
    - perdita del keystore o della sua password: nessun aggiornamento possibile, tutti dovrebbero disinstallare e
      reinstallare (le copie su GitHub non si possono rileggere: contano il file sul PC, le 2 copie e la password);
    - Play Protect / Smart App Control / SmartScreen possono avvisare o bloccare (exe non firmato, APK fuori dal Play
      Store): istruzioni in `docs/istruzioni_installazione.md`;
    - verifica degli sviluppatori Android (annunciata da Google per il 2026–2027): potrebbe servire registrarsi per
      continuare a distribuire l'APK fuori dal Play Store; da ricontrollare prima del prossimo rilascio importante;
    - Inno Setup fissato a 6.4.3 con choco sul runner, actions v4/v5 con avviso di deprecazione di Node 20:
      aggiornare quando GitHub lo richiede;
    - build lente (~8 min): eventuale cache di Gradle/Flutter se diventano un problema.
  - **Decisioni aperte per dopo:** migrazione 2C (ora si può imporre la versione minima con `min_version`);
    aggiornamento di Flet a fine migrazione; Fase 6 (iOS, facoltativa).
- **Fase 6 (23/11/2026): conclusa.** Piano e decisioni in `docs/fase6_piano.md`.
  - **Decisioni:** nessuna spesa → niente app iPhone (gli iPhone usano la webapp), niente Render a pagamento; app
    Mac gratuita rimandata (serve macOS 11+, da sapere dall'utente col Mac).
  - **Fatto (23/11, su `app-nativa`):** misura di Render (risveglio 22,9 s, da sveglio 0,2-0,3 s); tabella
    `client_usage` con chi usa cosa (`sql/2026-11_fase6_client_usage.sql`, ordine rispetto al codice
    indifferente); barra "C'è l'app" nella webapp aperta da Android o Windows. Verifiche in `docs/fase6_piano.md`
    sezione 7.
  - **23/11:** con il tuo OK `main` = `98197386` (avanzamento diretto da `app-nativa`, deploy di Render).
  - **Fatto da te (23/11):** migrazione SQL eseguita; webapp controllata (barra "per Windows" visibile, riga
    `web-windows` nella query "Per utente").
  - **Nessun rilascio dedicato:** nell'app installata l'unica differenza è che manda piattaforma e versione;
    arriverà con il prossimo rilascio che serve per altri motivi. Fino ad allora le app 1.0.0 compaiono come
    `non-indicato` in `client_usage`.
  - **Dopo la migrazione (in ordine proposto):** migrazione 2C, aggiornamento di Flet, eventuale app Mac (A5).
- **Migrazione 2C (23/11/2026): conclusa.** Piano, decisioni e verifiche in `docs/migrazione_2C_piano.md`;
  `sql/2026-11_2C_chiusura_letture.sql` eseguita: la chiave pubblicabile non legge più nessuna tabella (solo RPC),
  `login_with_token` cancellata, `login` solo interna a `login_bundle`. `tools/verifica_permessi.py`: tutto a posto;
  webapp e app provate. Da guardare: il cron del giorno dopo.
  - **Prossimi:** aggiornamento di Flet (rimandato, da ricordare).
- **App per Mac (Fase 6, A5, dal 23/11/2026): in prova.** Dettagli in `docs/fase6_piano.md` sezione 10. Build su
  GitHub verde con `v1.0.0-rc.11` (Xcode più recente, app universale Intel + Apple Silicon, macOS 11+).
  Da fare: migrazione `sql/2026-11_fase6_app_release_macos.sql`; prova dell'amico col Mac (Monterey 12.7.6);
  poi rilascio 1.0.1 con le tre app e OK per `main`.

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
- **15–16/11/2026 — Fase 3:**
  - cache dell'app installata nella cartella dati dell'utente (`app_paths.py`), `data/` per Render, sviluppo, cron e script;
  - `calendar.json`, `standings.json`, `injuries.json` non più versionati;
  - pacchetto costruito da `app_src/` con lista di file ammessi (`tools/prepara_build.py`), mai dalla radice;
  - foto incluse: quelle della lega più i giocatori con media FPTS ≥ 18; le altre dal CDN NBA;
  - Android arm64-v8a + armeabi-v7a, solo verticale; aggiornamento silenzioso al ritorno dopo 5 minuti, ricostruendo la dashboard sul tab corrente;
  - senza rete solo nell'app installata;
  - nome **Bonkest** (`it.bonkest.bonkest`), anche nel titolo della webapp; chiavi dello storage invariate;
  - migrazione 2C (via `login`, `login_with_token`, SELECT diretta di anon) rimandata a dopo la Fase 5.
- **16/11/2026 — Fase 4:**
  - difetto delle patch di Flet 0.82 corretto nel nostro codice (`flet_fix.py`), senza cambiare versione;
  - **aggiornare Flet (0.83 o l'ultima) alla fine della migrazione**, dopo l'ultima fase, con una prova separata
    (build Android/Windows, `flet-web` su Render): può portare altri miglioramenti; poi via `flet_fix.py`;
  - menu di scambio mantenuti, aggiornati sul posto (niente "tocca A, poi tocca B");
  - schermata dei tempi solo temporanea, nascosta agli utenti, tolta a fine fase;
  - all'avvio connessione anticipata; dashboard dalla cache solo se l'avvio sul telefono resta > 2 s;
  - strumentazione pubblicata su `main` per misurare Render prima delle modifiche;
  - foto mancanti scaricate una volta nella cartella dati (solo app installata); JSON compatto per i file grandi.
- **19–22/11/2026 — Fase 5** (dettagli in `docs/fase5_piano.md`):
  - prima versione 1.0.0; versione unica in `pyproject.toml`, build = X·10000 + Y·100 + Z;
  - keystore nei segreti di GitHub + originale sul PC + 2 copie fuori dal PC; anche i build locali firmati con la
    chiave vera;
  - Windows: installer Inno Setup per utente (senza amministratore) + zip di riserva; nessuna firma del codice per ora;
  - rilascio da tag `vX.Y.Z` (prove con `vX.Y.Z-rc.N` su `app-nativa`), release in bozza pubblicata a mano, poi
    `app_release` aggiornata dallo SQL Editor;
  - controllo aggiornamenti con RPC dedicata nella connessione anticipata; barra chiudibile a ogni avvio se c'è una
    versione nuova, schermata bloccante sotto `min_version`; webapp esclusa;
  - aggiramento CMake portabile (DLL x64 trovate con vswhere) e controllo dei pacchetti con `controlla_build.py`;
  - istruzioni per gli utenti in `docs/istruzioni_installazione.md`, usate anche come note della release.
- **23/11/2026 — Fase 6** (dettagli in `docs/fase6_piano.md`):
  - nessuna spesa: niente app iPhone (gli iPhone usano la webapp), Render resta sul piano gratuito;
  - registro di chi usa cosa in `client_usage` (piattaforma, versione, primo/ultimo accesso, aperture);
  - barra "C'è l'app" nella webapp aperta da Android o Windows;
  - app Mac gratuita rimandata (serve macOS 11+); nessun rilascio 1.0.1 solo per questa fase.
