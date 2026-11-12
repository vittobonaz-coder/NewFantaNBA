# Fase 0 — Report di ricognizione e fattibilità

Riferimenti: `docs/piano_migrazione_C1.md` (Fase 0). Branch `app-nativa`.

## 1. Flussi attuali

### Login
- **Manuale:** `LoginView._check_login` (ui_court.py:1514) → `SupabaseSync.authenticate` (supabase_manager.py:1046).
  - 1 select su `profiles` con `eq("username")` ed `eq("password")`, cioè password in chiaro confrontata via REST.
  - La squadra arriva nella stessa risposta (`fanta_teams(id, name)`).
- **"Ricordami":** `create_login_token` (supabase_manager.py:1098) fa 1 insert su `login_tokens`. Nel database va solo lo SHA-256 del token.
  - Sul dispositivo il token sta in `ft.SharedPreferences`, chiave `fantanba.login_token` (app.py:21, 100, 151, 199).
  - Funziona già su web (localStorage), desktop e Android.
- **Accesso automatico:** `authenticate_token` (supabase_manager.py:1104) fa 1 select su `login_tokens` con join al profilo. Il token vale 90 giorni.
- **Gestione profilo** (ui_court.py:1160-1203):
  - `check_password` e `update_password` lavorano con la password in chiaro;
  - cambio username: 1 select di tutti gli altri username, poi 1 update;
  - cambio nome squadra: select e update su `fanta_teams`, poi riscarica calendario e classifica.

### Sincronizzazione (`load_user_data`, app.py:112, in un thread)
Tutte le richieste sono **in sequenza**; `run_parallel` non si usa mai in lettura.
1. `get_last_cron_run` (supabase_manager.py:1143) legge `cron_runs` e prende l'ultimo `finished_at` fra **tutte** le modalità.
2. `sync_league_data` (app.py:46) confronta il risultato con `data/sync_meta.json`. Se la cache è vecchia scarica:
   - `matchups` (1 richiesta);
   - `nba_games` (3 richieste per 1206 partite: pagine da 1000 più una pagina vuota finale, supabase_manager.py:696-710);
   - `v_standings` (1);
   - `player_injuries` (1).
3. `sync_team_data` (app.py:71) gira per la giornata in corso e per quella modificabile: per ognuna `lineup_players` e `matchups` (2 richieste).
4. Il tab "Altre squadre" alla prima apertura fa altre 3 richieste in sequenza.

| Scenario | Richieste in sequenza |
|---|---|
| Caso peggiore (dopo un cron, cache vecchia, 2 giornate) | **12**, 13 con "Ricordami" |
| Dati già aggiornati | 2, 3 con "Ricordami" |

### Salvataggio della formazione (`Court._push_lineup`, ui_court.py:494)
**48 richieste HTTP in 5 ondate sequenziali:**
1. 1 select di controllo su `lineup_players`;
2. 15 update su `rosters`;
3. 15 update su `lineup_players` con slot temporanei (+100);
4. 15 update con gli slot e i ruoli finali;
5. 2 update del modulo su `matchups`.

Le ondate 2-5 usano `run_parallel`. Gli update valgono dalla giornata modificabile in poi (`gte("gameweek")`).

### Client Supabase
Si usa **solo PostgREST** tramite `.table()`: nessun `auth`, `storage`, `realtime` né `rpc`. I metodi usati sono:
- filtri e ordinamento: `select`, `eq`, `neq`, `in_`, `order`, `limit`, `range`, `lt`, `lte`, `gte`;
- scritture: `update`, `insert`, `upsert`, `delete`.

Un sostituto con chiamate dirette a REST resterebbe quindi piccolo.

## 2. Cosa non torna con il piano

1. **Richieste al login:** dopo un cron sono **12–13**, non circa 11. La differenza viene dalla pagina vuota finale di `nba_games`.
2. **Qualunque cron fa riscaricare tutto.**
   - Anche il cron degli infortuni (2 volte al giorno) fa riscaricare calendario, partite NBA, classifica e formazioni.
   - Lo stesso vale per un run fallito, perché viene registrato comunque (cron_test_script.py:497-500).
   - Da considerare nella Fase 2 (versione dello snapshot).
3. **La chiave pubblicabile è duplicata:** oltre che in `supabase_manager.py:14` compare in `reset_pre_setup.py:11`. La Fase 1 deve coprire anche quel file.
4. **`.env` non era in `.gitignore`:** l'ho aggiunto in questa fase.
5. **Il workflow del cron** (`.github/workflows/cron-test.yml`) installa `requests pandas nba_api supabase` **senza versioni fissate**. Un aggiornamento di quei pacchetti può rompere il cron in qualunque momento, indipendentemente dalla migrazione.
6. **Percorsi relativi alla cartella di avvio** (`data/...`, `assets`): app.py:17-20, fanta_obj.py:322-347, ui_court.py (19, 259, 877, 981, 1224, 1363), supabase_manager.py, main.py:47.
   - Era già nella Fase 3, ma conferma che l'app vera **non può** girare installata prima di quella fase.
7. **La finestra 358×757** è fissata in `app.main` (app.py:98-99), quindi vale anche per l'app Windows.
8. **`rules.json`** è statico ma sta in `data/`, insieme alla cache che l'app riscrive.
9. **Dipendenze native dell'app:** l'unica è `pydantic_core` (Rust), che arriva con supabase-py.
   - pandas, numpy e nba_api servono solo al cron e agli script.
   - `time_manager.py` usa `zoneinfo`, che su Android richiede `tzdata` (già nei requirements).
10. **Scritture con la chiave anon:** il cron usa la stessa chiave pubblicabile dell'app (nessun segreto nel workflow). Per questo oggi le tabelle devono accettare scritture anonime; per esempio `player_injuries` ha permessi di scrittura per `anon` (sql/2026-11_sostituzioni_infortuni.sql).

11. **⚠️ La repository GitHub è pubblica** (l'API risponde 200 senza autenticazione).
    - **Password del database Postgres:** la versione attuale di `todo.txt` non ne contiene. Era però scritta nel file dal 05/05/2026 (`ff67f99b`) al 31/10/2026 (`4cdfe875`), quindi **è ancora nella cronologia pubblica**.
      - Con quella password e l'indirizzo del progetto (pubblico in `supabase_manager.py`) ci si collega direttamente a Postgres come amministratore, scavalcando qualunque RLS.
      - Esistono bot che cercano credenziali di questo tipo nelle repository pubbliche.
    - **Password degli utenti:** `data/profiles.json` le contiene in chiaro, nella versione attuale e nella cronologia.
    - **Scelta dell'utente:** la repository resta pubblica, per i minuti illimitati di GitHub Actions.
    - **Azioni concordate:**
      - cambiare la password del database: non serve a nessun componente dell'app, del cron o di pg_cron, che usano le chiavi API e il Vault;
      - eliminare `data/profiles.json` e ignorarlo in git;
      - le password degli utenti diventano inutili con l'hash della Fase 1.
    - Riscrivere la cronologia non è necessario: dopo il cambio, la vecchia password del database non vale più.

## 3. Database
Query di ricognizione: `sql/2026-11_ricognizione_schema.sql`, eseguita dall'utente il 12/11/2026. Il risultato è in fondo a `sql/schema_riferimento.sql`.

**Cosa risulta (punto di partenza della Fase 1)**
- **RLS disattivata su tutte le tabelle** tranne `standings_adjustments` (attiva, senza policy). Nessuna policy.
- **`anon` ha tutti i privilegi su tutte le tabelle**, compresi `DELETE` e `TRUNCATE`. La chiave pubblicabile è nella repository pubblica, quindi oggi chiunque può:
  - **leggere tutte le password** da `profiles` via REST: è la stessa cosa che fa il login dell'app, senza filtro;
  - modificare o svuotare qualunque tabella.

  È il rischio principale rimasto dopo il cambio della password del database, e la Fase 1 lo chiude.
- **Nessuna RPC e nessun trigger.** `update_updated_at_column()` esiste ma non è collegata a nessun trigger.
- **`pgcrypto` è già installata** (schema `extensions`): serve per l'hash delle password della Fase 1.
- **Vincolo** `UNIQUE (fanta_team_id, gameweek, slot)`: **non** DEFERRABLE (vedi Fase 2). Ci sono anche diversi `ON DELETE CASCADE` non riportati nelle CREATE TABLE di riferimento.
- **pg_cron**, orari UTC; tutti i job avviano il workflow `cron-test.yml` su `main`, con il token GitHub preso dal Vault:

  | Job | Orario UTC |
  |---|---|
  | daily | 08:00 |
  | rollover | 21:59 e 22:59 |
  | injuries | 21:10 e 22:10 |

  - **Il token GitHub non compare in nessun file.**

## 4. Prova tecnica (`spike_android/`)

Mini-app autonoma (`spike_android/main.py`):
- login con la stessa query di `authenticate`, in sola lettura e senza token;
- lettura di `matchups` come `pull_calendar`;
- interruttore supabase-py / REST diretto (httpx);
- tempi di avvio scritti nella cartella dati dell'app;
- prova di `SharedPreferences`.

URL e chiave stanno in `spike_android/config.py`, non versionato; `config.example.py` è il modello.

### Verifica da PC (Python 3.12, venv dell'app)
- Entrambi i client leggono le stesse **96 righe** di `matchups`.
- Login con utente inesistente: risposta vuota corretta con entrambi.

| Misura (PC, processo nuovo, 3 prove) | ms |
|---|---|
| `import supabase` | 687–739 |
| `import httpx` | 172–187 |
| `import flet` | 687–702 |
| 1ª richiesta supabase-py (connessione + TLS + query) | ~1000 |
| 1ª richiesta REST httpx | ~360 |
| richieste successive, entrambi | 150–230 |

### Build APK: **riuscito**
- `flet build apk` produce `build/apk/fantanba-spike.apk`: **70,6 MB** con 3 architetture, Python incorporato **3.12.9**.
  - Il primo build ha richiesto 32 minuti, compreso il download di NDK, CMake e Gradle.
  - Con `--split-per-abi` si ottiene un APK per architettura, più piccolo (Fase 5).
- **Problema trovato e risolto: pydantic.**
  - Con l'ultima pydantic (2.14.x → pydantic-core 2.50.x) il build fallisce, perché nel repository di Flet (`pypi.flet.dev`) l'ultima ruota Android di pydantic-core è la 2.46.4 (più la 2.47.0, che corrisponde solo a una alpha di pydantic).
  - Soluzione: **`pydantic==2.13.4`**, compatibile con supabase 2.31 (`pydantic>=2.11.7`).
  - La stessa versione andrà fissata nei requirements dell'app (Fase 3), così web e app usano le stesse versioni.
- **Architettura x86 a 32 bit esclusa:** pydantic-core 2.46.4 non ha la ruota per x86 (solo vecchi emulatori), quindi `target_arch = ["arm64-v8a", "armeabi-v7a", "x86_64"]`.
- **Altre dipendenze native di supabase-py:**
  - `cryptography` (tramite `pyjwt[crypto]`) e `yarl` hanno ruote Android su pypi.flet.dev;
  - `multidict`, `propcache` e `websockets` hanno anche una versione in solo Python.
- **Licenze dell'Android SDK:** vanno accettate a mano (`sdkmanager --licenses`) al primo build; `--yes` non basta.

## 5. Avvio a freddo

### Android: Samsung Galaxy A52s 5G (SM-A528B), Android 14, arm64
**Metodo**
- 5 prove per client: `am force-stop`, 4 s di attesa, `am start -W`.
- L'istante del tocco è la riga `START` di ActivityTaskManager in `adb logcat -v epoch`.
- Gli istanti successivi li scrive l'app nella cache esterna, letta con adb.
- **Dati** = login (a vuoto) + lettura di `matchups`, cioè 2 richieste come al login dell'app.
- Script: `misura_android.sh` (nello scratchpad della sessione, non versionato).

| Dal tocco dell'icona a… (ms) | supabase-py: mediana (min–max) | REST httpx: mediana (min–max) |
|---|---|---|
| primo frame Flutter (splash) | 353 (319–384) | 347 (319–357) |
| avvio di Python | 494 (479–760) | 489 (481–550) |
| **prima schermata** | **1750** (1733–2207) | **1777** (1739–1945) |
| **dati letti** | **3768** (3596–4470) | **2714** (2510–2820) |

Dettaglio, mediane in ms:

| | supabase-py | REST httpx |
|---|---|---|
| import del client | 1112 | **0** (httpx è già caricato da Flet) |
| creazione del client | 296 | 341 |
| 1ª richiesta (con connessione e TLS) | 425 | 348 |
| 2ª richiesta | 139 | 146 |

**Osservazioni**
- Tra l'avvio di Python e la prima schermata passano circa 1,2–1,5 s, quasi tutti per `import flet`. È un costo fisso, uguale con entrambi i client.
- **supabase-py aggiunge circa 1,1 s** a ogni avvio a freddo, solo per l'import (pydantic, gotrue, realtime, storage…), senza nessun vantaggio per l'app, che usa solo PostgREST.
- Le richieste in sé hanno tempi equivalenti.
- `SharedPreferences` sopravvive al riavvio e la cartella dati interna (`/data/user/0/<pacchetto>/app_flutter`) è scrivibile.

### Windows 11: PC di sviluppo, app `flet build windows`
**Metodo**
- Avvio con doppio clic da Esplora file, fatto dall'utente.
- L'istante di creazione del processo viene da `GetProcessTimes`; gli istanti successivi li scrive l'app.
- Escluso il primo avvio dopo l'installazione, che estrae il codice Python.
- Prove: 5 con supabase-py, 6 con REST.

| Dall'avvio del processo a… (ms) | supabase-py: mediana (min–max) | REST httpx: mediana (min–max) |
|---|---|---|
| avvio di Python | 325 (265–404) | 294 (290–297) |
| **prima schermata** | **1348** (1242–1462) | **1242** (1236–1248) |
| **dati letti** (login + `matchups`) | **2900** (2627–3001) | **1990** (1950–2152) |

Import del client: supabase-py circa 500 ms, httpx 0 ms. Il resto è equivalente.

**Problemi trovati su Windows**
1. **CMake a 32 bit nelle Build Tools 17.14.**
   - Il plugin serious_python copia `msvcp140.dll`, `vcruntime140.dll` e `vcruntime140_1.dll` da `%WINDIR%\System32`; da un processo a 32 bit Windows lo dirotta su `SysWOW64`.
   - Risultato: DLL a 32 bit in un'app a 64 bit, e `vcruntime140_1.dll` mancante, per cui il build fallisce.
   - **Aggiramento usato per lo spike:** `WINDIR` puntato, solo per il processo di build, a `spike_android/build/winroot`. Lì ci sono le DLL x64 prese da `BuildTools\VC\Redist\MSVC\14.44.35112\x64\Microsoft.VC143.CRT`.
   - **Soluzione definitiva da decidere in Fase 5:** compilare su GitHub Actions (`windows-latest`), oppure installare un CMake a 64 bit, oppure tenere l'aggiramento in uno script di build.
2. **App lanciata dalla sessione di Claude Code:** non estrae il codice Python (`No module named main`).
   - Causa: l'app desktop di Claude è un pacchetto MSIX, i processi figli vedono `%APPDATA%` virtualizzata e la libreria `archive` 4.6.0 scarta i file perché il percorso reale è diverso. Verificato con un programma Dart di prova.
   - **Non riguarda gli utenti:** con doppio clic l'estrazione funziona.
   - Conseguenza pratica: le prove dell'app Windows vanno fatte avviandola da Esplora file.
3. **Cartella dati predefinita = Documenti.**
   - Su Windows `FLET_APP_STORAGE_DATA` punta a `Documenti\flet\<app>`, che qui è **dentro OneDrive**.
   - Per l'app vera (Fase 3) la cache va in `%APPDATA%`, cioè `StoragePaths.get_application_support_directory()`, che la mini-app ha confermato essere `%APPDATA%\FantaNBA\FantaNBA Spike`. `SharedPreferences` sta già lì.
4. **Dimensione:** l'app Windows occupa **99 MB** (cartella non compressa) e non richiede diritti di amministratore.

### Versione web su Render (per confronto)
URL: https://newfantanba.onrender.com (12/11/2026).

| Caso | Misura |
|---|---|
| Server addormentato: prima risposta HTML (`curl`) | **32,6 s** |
| Server sveglio: risposta HTML | 0,20–0,23 s |
| Server sveglio, browser senza cache: download del client Flutter (`main.dart.wasm` 2,7 MB, font, `rive_native.wasm` 0,8 MB) | **~4,5 s**, prima ancora che il server mandi la schermata di login |

**Confronto con l'app nativa**
- Prima schermata in 1,2–1,8 s, con il login già visibile.
- Dati letti in 2,0–2,7 s con REST diretto.
- Mai attese di 30 s per il risveglio del server.

**Limite della misura web:** il tempo esatto fino al login visibile non si è potuto misurare, perché il pannello del browser era nascosto e la pagina non veniva disegnata. I 4,5 s sono un limite inferiore.

### Verifiche manuali su Windows (utente, 12/11/2026)
- Finestra ridimensionabile e massimizzabile: **OK**.
- Invio nel campo password avvia il login: **OK**.

## 6. Ambiente di compilazione

### Stato del PC prima della fase
Non c'erano Flutter, Java, Android SDK, adb né Visual Studio. Spazio libero su C: 59,6 GB.

### Cosa installa da solo `flet build` (0.82, senza diritti di amministratore)

| Strumento | Dove | Note |
|---|---|---|
| Flutter 3.41.4 | `%USERPROFILE%\flutter\3.41.4` | archivio da 1,8 GB |
| JDK Temurin 17.0.13 | `%USERPROFILE%\java\17.0.13+11` | |
| Android SDK | `%USERPROFILE%\Android\sdk` | cmdline-tools 12.0, platform-tools, android-35, build-tools 34; al primo build anche NDK e CMake 3.22.1 |
| Gradle | `%USERPROFILE%\.gradle` | |
| `flet-cli` 0.82 | `spike_android/.venv` | venv separato, non versionato: l'ambiente dell'app non cambia |

### Cosa deve fare l'utente (una volta)
1. **Modalità sviluppatore di Windows**, perché Flutter usa i collegamenti simbolici per i plugin. Fatto.
2. **Licenze dell'Android SDK** con `sdkmanager --licenses`. Fatto.
3. **Solo per `flet build windows`:** Visual Studio 2022 (anche la Community gratuita o le sole Build Tools) con il carico di lavoro **"Sviluppo di applicazioni desktop con C++"**. Richiede i diritti di amministratore e circa 7-10 GB.
4. Per provare sul telefono: debug USB attivo (Opzioni sviluppatore > Debug USB) e cavo, oppure copia manuale dell'APK.

### Locale o GitHub Actions
- La repository è **pubblica**, quindi i minuti di GitHub Actions sono gratuiti e illimitati, anche sui runner Windows.
- Proposta:
  - **in locale** durante lo sviluppo, per avere subito il risultato sul telefono e sul PC;
  - **su GitHub Actions** per le versioni da distribuire (Fase 5): APK su ubuntu, Windows su windows-latest, keystore come segreto GitHub;
  - così il PC non serve per i rilasci e il keystore non resta solo in locale.

## 7. Scelta del client Supabase

**Proposta: REST diretto con `httpx`** (opzione a del piano), con un piccolo modulo che sostituisce le chiamate `.table()` usate dall'app. Resta da approvare.

| | supabase-py | REST diretto (httpx) |
|---|---|---|
| Compila per Android | sì, con `pydantic==2.13.4` | sì, nessun pacchetto nativo in più |
| Dati al primo avvio, Android | 3,77 s | **2,71 s** (−1,1 s) |
| Dati al primo avvio, Windows | 2,90 s | **1,99 s** (−0,9 s) |
| Dipendenze native nell'APK | pydantic-core, cryptography, yarl… | nessuna oltre a Flet |
| Rischio di aggiornamenti | versione di pydantic vincolata dalle ruote di Flet | nessuno |
| Lavoro | nessuno | modulo con le query usate (select/filtri/order/range/insert/update/upsert/delete) |
| Fase 1 (RPC) | `.rpc()` già pronto | `POST /rest/v1/rpc/<nome>`, una riga |

**Perché**
- L'app usa solo PostgREST: supabase-py porta con sé auth, realtime, storage e pydantic senza nessun vantaggio, e costa circa 1 s a ogni avvio.
- Elimina l'unico vincolo di versione critico (pydantic-core per Android).

**Il cron e gli script di amministrazione** (GitHub Actions e PC) possono restare su supabase-py: non finiscono nell'app.
