# Fase 3 — App pronta per girare sul dispositivo (piano approvato il 15/11/2026)

Preparato e approvato il 15/11/2026 (branch `app-nativa`, da `9a613dbf`). Decisioni della sezione 10: tutte come proposto; icona preparata da me.
Basato su: `docs/piano_migrazione_C1.md`, `docs/fase0_report.md`, `docs/fase2_piano.md`, `app.py`, `main.py`,
`test.py`, `ui_court.py`, `league_cache.py`, `supabase_rest.py`, `time_manager.py`, `fanta_obj.py`, `.gitignore`,
`requirements*.txt`, `assets/`, `data/`, `spike_android/pyproject.toml`, sorgenti di flet 0.82 e flet-cli 0.82
(`spike_android/.venv`).

## 0. Idea in una riga

Un solo modulo decide dove stanno i file (`app_paths.py`): `data/` per Render, sviluppo, cron e script (nessun
cambiamento per loro); cartella dati dell'app per la versione installata. L'app nativa ha un suo punto
d'ingresso (`nativa.py`) e si costruisce da una **cartella preparata con una lista di file ammessi** (mai `.env`
né `data/`). Interfaccia: area sicura, larghezza massima del contenuto, finestra ridimensionabile, Indietro di
Android, aggiornamento silenzioso al ritorno in primo piano e dati in cache con avviso quando manca la rete.
Nessuna migrazione SQL obbligatoria.

## 1. Cosa ho verificato (ipotesi del piano generale)

| Ipotesi | Esito |
|---|---|
| Flet 0.82 ha gli eventi per ripresa e Indietro | **Sì**: `page.on_app_lifecycle_state_change` (stati `show`, `resume`, `hide`, `inactive`, `pause`…), `View.can_pop` + `View.on_confirm_pop` / `confirm_pop()`, `page.on_view_pop`, `page.on_resize`, `page.media`, `ft.SafeArea`, `page.platform`, `page.web` |
| `flet build` usa `main.py` come ingresso | Per default sì, ma si cambia con `[tool.flet.app] module = "..."` (flet-cli `build_base.py:735`): `main.py` resta a Render |
| `flet build` impacchetta solo il codice dell'app | **No, ipotesi pericolosa.** Impacchetta **tutta** la cartella `tool.flet.app.path` tranne `build` e quello che si elenca in `exclude` (`build_base.py:1766`). Dalla radice della repository finirebbero nell'APK `.env` (con `SUPABASE_SECRET_KEY`), `data/`, `sql/`, `todo.txt`, `spike_android/config.py`… Serve una lista di file ammessi, non di esclusi (sezione 4) |
| Le dipendenze vengono da `pyproject.toml` | Sì: `project.dependencies` ha la precedenza su `requirements.txt`; il permesso INTERNET su Android è aggiunto sempre (`build_base.py:811`), lo scriviamo comunque esplicito |
| `giocatori_nba.json` serve all'app | **No**: lo leggono solo script (`api_nba.py`, `swap_players.py`, cron…). L'app legge solo `rules.json` |
| Cartella dati su Windows | Come in Fase 0: `FLET_APP_STORAGE_DATA` = Documenti (OneDrive), quindi si usa `StoragePaths.get_application_support_directory()` = `%APPDATA%\<company>\<product>` |
| Cron e script leggono `calendar/standings/injuries.json` dalla repository | **No**: il cron non li legge (gira su GitHub dal checkout), `supabase_manager` e `setup_fanta_championship.py` li **scrivono** soltanto. Si possono togliere dal versionamento |

Niente di bloccante: il piano generale regge, con la correzione sull'impacchettamento.

## 2. Punto 1 — Percorsi dei file e cache per dispositivo

### 2.1 Modulo `app_paths.py` (nuovo, solo libreria standard)
```python
DEFAULT_DATA_DIR = "data"            # Render, test.py, cron e script: come oggi
def data_dir() -> Path               # cartella della cache (scrivibile)
def set_data_dir(path: Path) -> None # chiamata solo da nativa.py
def data_file(name: str) -> Path     # data_dir() / name
def resource(name: str) -> Path      # file in sola lettura inclusi nel pacchetto: Path(__file__).parent / name
```
- Default `data` relativo: cron, script e Render restano identici senza toccarli. Solo `nativa.py` chiama
  `set_data_dir` all'avvio, prima di qualunque lettura.
- Cartella sul dispositivo (in `nativa.py`, dentro `main(page)` perché `StoragePaths` è asincrono):
  - Windows: `await ft.StoragePaths().get_application_support_directory()` → `%APPDATA%\FantaNBA\FantaNBA`
    (fuori da OneDrive, senza diritti di amministratore, `SharedPreferences` è già lì);
  - Android: la stessa chiamata (cartella interna privata dell'app); riserva `FLET_APP_STORAGE_DATA`;
  - sottocartella `cache/` (es. `%APPDATA%\FantaNBA\FantaNBA\cache`), così si può svuotare da sola.
- Variabile facoltativa `FANTANBA_DATA_DIR` per provare in sviluppo la cache "da dispositivo" con `test.py`.

### 2.2 Dove si usa (cron e script esclusi)
| File | Oggi | Dopo |
|---|---|---|
| `league_cache.py` | costanti `DATA_DIR`, `CALENDAR_PATH`… calcolate all'import | funzioni (`calendar_path()`…) su `app_paths.data_file`; `write_lineup_state(data_dir=None)` → `app_paths.data_dir()` |
| `fanta_obj.py` (`Team.filename`, `save_to_json`) | `os.path.join("data", ...)` | `app_paths.data_file(...)`; per gli script resta `data/...` |
| `ui_court.py` | `"data"` in 6 punti (righe 22, 262, 875, 979, 1221, 1361) | `league_cache.calendar_path()` ecc.; `rules.json` con `app_paths.resource` |
| `supabase_manager.py` e script | `data/...` | **invariati** (usano `league_cache` con il default) |

Verifica automatica: `grep` di `"data"` nei 6 moduli dell'app = 0 occorrenze fuori da `app_paths.py`.

### 2.3 Cache per dispositivo
La logica "riscarica solo se è cambiato" è già per dispositivo dalla Fase 2: `league_cache.local_versions()` legge
`snapshot_meta.json` **nella cartella dati** e scarta le versioni delle parti i cui file mancano. Cambia solo che
la cartella è quella del dispositivo:
- primo avvio dell'app installata: cartella vuota → `p_versions = {}` → tutte le parti in una risposta
  (20 KB trasferiti, misurato in Fase 2);
- Render: `data/` condivisa fra gli utenti come oggi (le parti sono uguali per tutti; la propria formazione
  arriva sempre nel bundle);
- nessun file di cache nel pacchetto: l'app non parte mai con dati vecchi inclusi nel build.

Nuovo in cache (per la ripresa e il fuori rete, sezioni 6-7): `last_sync` (ora dell'ultimo aggiornamento riuscito)
in `snapshot_meta.json` sotto una chiave che `local_versions()` ignora.

### 2.4 Togliere dal versionamento `calendar.json`, `standings.json`, `injuries.json`
Proposta: **sì**, nel primo commit della fase.
- `.gitignore`: `data/calendar.json`, `data/standings.json`, `data/injuries.json`; poi
  `git rm --cached` dei tre file (restano sul disco del PC).
- Prima verifico che l'app parta senza: `FANTANBA_DATA_DIR` su una cartella vuota con `test.py` e `main.py`
  locale → login → i tre file si creano e le viste li leggono.
- Effetto su Render: dopo il deploy `data/` non li ha; il primo login li scarica tutti (come dopo un cron).
- Risolve anche le modifiche continue che oggi compaiono in `git status`.
- **Non** si tolgono: `all_players.json`, `nba_to_espn_players.json`, `giocatori_nba.json`, `fanta_teams.json`,
  `*_info.json` (dati di partenza degli script) e `rules.json` (si sposta, punto 2).

### Verifiche punto 1
- **Windows (app installata):** dopo il login esiste `%APPDATA%\FantaNBA\FantaNBA\cache\snapshot_meta.json`;
  nulla in Documenti/OneDrive né nella cartella del programma; secondo avvio con 1 richiesta e nessuna parte scaricata.
- **Android:** stesso controllo con `adb shell run-as it.fantanba.fantanba ls files/cache` (APK di debug) o dai
  messaggi in console; riavvio dell'app senza riscaricare.
- **Webapp:** `main.py` locale e poi Render: file in `data/` come oggi; login da cartella vuota.
- **Script:** `swap_players.py --dry-run` e `python -c "import league_cache; print(league_cache.calendar_path())"` → `data\calendar.json`.

## 3. Punto 2 — File nel pacchetto

Misure (15/11/2026):

| File | Dimensione | Chi lo legge | Aggiornamento | Proposta |
|---|---|---|---|---|
| `data/rules.json` | 1,4 KB | solo l'app (Regolamento) | ~1 volta a stagione | **incluso**, spostato in `assets/rules.json` (letto con `app_paths.resource`, sul web servito come file statico: è un'informazione pubblica) |
| `data/giocatori_nba.json` | 73 KB | solo script | — | **escluso** (l'app non lo usa) |
| `assets/players/*.png` | 127 file, 1,96 MB (~15,5 KB l'uno, 260×190) | app | a ogni nuovo giocatore (`swap_players.py` scarica la foto) | **incluse**, con riserva dal CDN NBA per le foto mancanti |
| `assets/avatar_placeholder.png` | **577 KB**, 1024×1536 | app | mai | **inclusa ma rimpicciolita** a ~260×390 (stimati < 40 KB; giova anche al web) |
| `data/*_state.json`, `snapshot_meta.json`, `league_teams.json`, cache | — | — | — | **esclusi**: si creano sul dispositivo |
| `data/profiles.json` | non più presente | — | — | escluso per costruzione (la lista ammessi non include `data/`) |
| `.env`, `todo.txt`, `spike_android/config.py` | — | — | — | **esclusi per costruzione** + controllo automatico (sezione 4.3) |

Foto dei giocatori nuovi: oggi `swap_players.py` le salva in `assets/players/` (quindi serve un deploy per il web e
servirebbe un nuovo build per l'app). In `PlayerCard`: `ft.Image(src=foto locale, error_content=ft.Image(src=
"https://cdn.nba.com/headshots/nba/latest/260x190/<id>.png", error_content=segnaposto))`. Così un giocatore entrato
dopo il build si vede comunque (con rete), senza ricostruire l'APK. Alternativa scartata: tutte le foto dal CDN
(rete a ogni avvio perché Flutter le tiene solo in memoria, niente foto senza rete, dipendenza da un sito esterno).

Impatto sul pacchetto: ~2 MB su ~70 MB dell'APK di prova (Fase 0) e 99 MB dell'app Windows.

### Verifiche punto 2
- Contenuto del pacchetto: elenco dei file dentro `build/.../app.zip` (o equivalente di serious_python) confrontato
  con la lista ammessi; ricerca di `sb_secret_` e `SUPABASE_SECRET_KEY` nel pacchetto = 0.
- Android e Windows: foto visibili per tutta la rosa; un giocatore senza file locale (rinomino un PNG nella copia di
  build) mostra la foto dal CDN, e senza rete il segnaposto. Regolamento visibile.
- Webapp: foto e regolamento come prima.

## 4. Punto 3 — Separazione server/app e `pyproject.toml`

### 4.1 Punti d'ingresso
| File | Uso | Cartella dati |
|---|---|---|
| `main.py` | solo Render (invariato: `assets_dir` resta `assets`) | `data/` |
| `test.py` | sviluppo sul PC (`ft.run(main)`) | `data/` o `FANTANBA_DATA_DIR` |
| **`nativa.py`** (nuovo) | `flet build apk` / `flet build windows` | cartella dati dell'app |

`nativa.py`: imposta la cartella dati con `StoragePaths`, poi chiama `app.main(page)`; `app.main` riceve
l'informazione "nativa" da `app_paths` (per finestra, Indietro, fuori rete).

### 4.2 `pyproject.toml` nella radice (per Flet 0.82)
```toml
[project]
name = "fantanba"
version = "0.3.0"
description = "FantaNBA: fantabasket NBA privato"
requires-python = ">=3.12"
dependencies = ["flet==0.82.0", "tzdata==2025.3"]   # httpx arriva con flet; niente flet-web/fastapi/uvicorn

[tool.flet]
org = "it.fantanba"            # identificativo Android: it.fantanba.fantanba (NON si potrà più cambiare)
product = "FantaNBA"
company = "FantaNBA"
copyright = "FantaNBA"
build_number = 1

[tool.flet.app]
path = "app_src"               # cartella preparata da tools/prepara_build.py (non versionata)
module = "nativa"

[tool.flet.android]
target_arch = ["arm64-v8a", "armeabi-v7a"]   # decisione 4

[tool.flet.android.permission]
"android.permission.INTERNET" = true
```
- **Icona:** `assets/icon.png` (1024×1024, la usa `flet build` per Android, Windows e splash). Oggi non c'è (decisione 5).
- `tzdata` serve: Python incorporato su Android/Windows non ha il database dei fusi per `zoneinfo`.
- `requirements.txt` resta per Render, invariato.
- Render: con build command esplicito (`pip install -r requirements.txt`) un `pyproject.toml` senza
  `[build-system]` e senza `uv.lock`/`poetry.lock` non cambia nulla; lo controllo nel log del primo deploy.

### 4.3 Cartella di build con lista di file ammessi
`tools/prepara_build.py` (nuovo):
1. svuota e ricrea `app_src/`;
2. copia **solo**: `nativa.py`, `app.py`, `app_paths.py`, `ui_court.py`, `fanta_obj.py`, `league_cache.py`,
   `supabase_rest.py`, `time_manager.py`, `assets/` (icona, segnaposto, `players/`, `rules.json`);
3. controlla che gli import dei moduli copiati siano soddisfatti dentro `app_src/` (nessun `supabase_manager`,
   `api_nba`, `requests`, `pandas`);
4. si ferma se in `app_src/` trova `sb_secret_`, `SUPABASE_SECRET_KEY`, `.env` o file `.json` fuori da `assets/`.

Uso: `python tools/prepara_build.py && flet build apk` (e `flet build windows`, con l'aggiramento CMake della
Fase 0 in `tools/build_windows.ps1`; la soluzione definitiva resta in Fase 5). `.gitignore`: `app_src/`, `build/`.

Alternative valutate:
| | Lista ammessi + `app_src/` (proposta) | `path="."` con `exclude` | Codice dell'app in un pacchetto `fantanba/` |
|---|---|---|---|
| Rischio di impacchettare `.env` o dati | nullo (e controllato) | alto: basta dimenticare un file nuovo | basso |
| Modifiche al codice esistente | nessuna | nessuna | grandi: import di `main.py`, script e cron |
| Passo in più | uno script prima del build | nessuno | nessuno |

### Verifiche punto 3
- `flet build apk` e `flet build windows` completati; contenuto del pacchetto come in 3.
- `python -X importtime nativa.py` senza `supabase`, `fastapi`, `uvicorn`.
- Webapp: `main.py` locale invariato; dopo il push, deploy Render con lo stesso comando.

## 5. Punto 4 — Interfaccia

### 5.1 Finestra e layout desktop (Windows)
- `app.py`: via `page.window.width = 358` / `height = 757`. Solo su desktop nativo (non web):
  dimensione iniziale ~1100×800, `min_width = 380`, `min_height = 600`, ridimensionabile e massimizzabile.
- **Larghezza massima del contenuto** (Flet 0.82 non ha `max_width` sui Container): helper `Centrato(content,
  max_width)` che in `page.on_resize` imposta `width = min(page.width, max_width)` e centra.
  - Squadra / Altre squadre: il campo resta largo ~340 (le card hanno misure fisse), centrato; su schermi ≥ 900 px
    titolari a sinistra e panchina + riserve a destra (decisione 6);
  - Calendario e Classifica: fino a ~900 px; Impostazioni e login: ~480 px.
- Barra dei tab: etichette leggibili su desktop (oggi 9,3 / 7,2 pt, pensate per il telefono).
- Tastiera e mouse: Invio nel campo password esegue il login (`on_submit`, oggi manca nell'app vera); rotellina
  sulle liste; **tab scorrevoli** (24 giornate, 8 squadre): su Windows il trascinamento col mouse di una barra
  scorrevole non è garantito → verifico, e se non va aggiungo frecce ‹ › o un menu della giornata.

### 5.2 Telefoni di dimensioni diverse
- `ft.SafeArea` attorno al contenuto: Android 15 con target SDK 35 disegna sotto barra di stato e barra dei gesti.
- Campo largo ~340 dp: entra da 360 dp in su. Sotto (schermi da 320 dp o testo di sistema ingrandito):
  `scale = page.width / 360` applicato al solo campo, calcolato in `on_resize`.
- Prova su emulatore con 3 profili (piccolo 320×640, medio 360×800, grande 412×915) e sul telefono reale;
  dialog (partite del giocatore, profilo) senza tagli.

### 5.3 Tasto Indietro su Android
Con una sola vista Flutter chiude l'app al primo Indietro. Proposta (Flet 0.82):
`page.views[0].can_pop = False` + `on_confirm_pop` che, in ordine:
1. chiude il dialog aperto, se c'è;
2. con modifiche alla formazione non salvate chiede "Uscire senza salvare?";
3. se non si è sul tab Squadra, torna al tab Squadra;
4. altrimenti `confirm_pop(True)` (l'app va in secondo piano/si chiude come le altre app Android).
Rischio: comportamento di `can_pop`/`on_confirm_pop` sulla vista radice da verificare sul telefono (anche con il
gesto "Indietro predittivo" di Android 14+); riserva: `page.on_view_pop` con una seconda vista per i dettagli.
Su Windows e web non cambia nulla (nessun tasto Indietro di sistema; sul web il pulsante del browser resta com'è).

### 5.4 Ripresa dal background con aggiornamento silenzioso
- `page.on_app_lifecycle_state_change`: su `resume`/`show`, se l'ultimo aggiornamento riuscito ha più di
  **5 minuti** (decisione 7), in un thread `rest.token_bundle(token, local_versions())`:
  una richiesta che controlla anche la sessione (revocata → schermata di login) e porta formazione, contesto e
  parti cambiate.
- Se nessuna versione e nessun contesto sono cambiati: nulla a video.
- Se qualcosa è cambiato: si applica la cache e si ricostruisce la dashboard **restando sul tab corrente**
  (decisione 8); se la formazione ha modifiche non salvate, non si tocca nulla e compare una barra
  "Dati aggiornati: tocca per ricaricare".
- Se `edit_gw` è cambiato (passate le 23:59) la ricostruzione avviene comunque, con un avviso, perché i cambi
  della giornata vecchia sono chiusi.
- Su Windows lo stato `resume` arriva anche a ogni ritorno di fuoco della finestra: la soglia dei 5 minuti evita
  richieste a raffica. Sul web l'evento arriva al server quando si torna sulla scheda: stesso comportamento.

### Verifiche punto 4
- **Windows:** ridimensiona, massimizza, finestra minima, schermo 1920×1080; Invio al login; rotellina; tab delle
  giornate raggiungibili col solo mouse; ripresa dopo 5 minuti minimizzata (in console 1 richiesta, nessuna se < 5 min).
- **Android:** 3 profili di emulatore + telefono reale; rotazione (se lasciata attiva: decisione 9); Indietro nei
  4 casi; app in background > 5 min → dati aggiornati senza schermata di caricamento; con un cron passato nel
  frattempo (o `get_snapshot` con versione forzata vecchia) la dashboard si ricostruisce sul tab corrente.
- **Webapp:** browser pane a 375 px e a 1280 px; iPhone dell'utente dopo il deploy (area sicura, tab, dialog).

## 6. Punto 5 — Senza rete

- Dopo ogni accesso riuscito si salvano in `SharedPreferences` (per dispositivo; sul web per browser)
  `fantanba.last_profile` = `{id, username, team_row, context, saved_at}` — nessuna password né token in più
  (il token "Ricordami" c'è già).
- **Avvio senza rete** con token salvato, solo app nativa: se c'è il profilo salvato e la cache ha le formazioni,
  si apre la dashboard dai file locali con una barra in alto "Senza connessione — dati del 15/11 alle 9:12"
  e pulsante "Riprova". Il contesto è quello salvato; se la scadenza salvata è passata, si ricalcola con
  `TimeManager.get_league_context` sul calendario in cache (stessa regola del database, senza deroga).
- **In modalità senza rete:** Salva e le modifiche al profilo mostrano "Serve la connessione"; le modifiche
  alla formazione restano a video (non si perdono). Al "Riprova" riuscito o alla ripresa si torna normali con
  un aggiornamento silenzioso.
- **Login manuale senza rete** o senza profilo salvato: messaggio "Server non raggiungibile, riprova" come oggi.
- **Errore di rete durante l'uso** (salvataggio, aggiornamento silenzioso): messaggio, nessun blocco; distinto da
  `RpcError` (errori veri del database).
- **Web:** la rete che manca è quella del server verso Supabase (raro): resta il comportamento attuale, perché
  `data/` su Render è condivisa e non garantisce i dati di quell'utente (decisione 10).

### Verifiche punto 5
- **Android:** modalità aereo → apri l'app → dati in cache con barra; Salva → messaggio; rete di nuovo → Riprova.
- **Windows:** scheda di rete disattivata (o regola firewall per l'app) → stesso percorso.
- **Webapp:** nessun cambiamento visibile; `test.py` con `SUPABASE_URL` irraggiungibile (variabile solo per test)
  per provare la barra in sviluppo.

## 7. File da cambiare

| File | Modifica |
|---|---|
| `app_paths.py` (nuovo) | cartella dati, file inclusi, modalità nativa |
| `nativa.py` (nuovo) | ingresso dell'app installata |
| `pyproject.toml` (nuovo) | configurazione `flet build` |
| `tools/prepara_build.py`, `tools/build_windows.ps1` (nuovi) | cartella di build con lista ammessi e controlli; aggiramento CMake |
| `app.py` | finestra, SafeArea, Indietro, ripresa, profilo salvato e avvio senza rete |
| `ui_court.py` | percorsi, `rules.json`, larghezze adattive, `on_submit`, foto con riserva, barra "senza connessione", blocco salvataggi offline, modifiche non salvate visibili alla dashboard |
| `league_cache.py` | percorsi come funzioni, `last_sync` |
| `fanta_obj.py` | `Team.filename` con `app_paths` |
| `assets/` | `icon.png`, segnaposto rimpicciolito, `rules.json` (spostato da `data/`) |
| `.gitignore` | `app_src/`, `build/`, i tre JSON di cache |
| `docs/piano_migrazione_C1.md` | stato a fine fase; `docs/fase3_piano.md` = questo piano |

Non cambiano: `main.py` (salvo verifica), `supabase_rest.py` (eventualmente solo la distinzione errore di rete),
`time_manager.py`, cron, script, SQL. **Nessuna migrazione obbligatoria.**

## 8. Misure

La fase non è "di velocità", ma serve la base per la Fase 4: avvio a freddo dell'app vera (tocco/doppio clic →
dashboard), 5 prove, con cache vuota e piena, su Galaxy A52s e PC, stampato con `FANTANBA_MISURE=1` e scritto
in un file nella cartella dati (come lo spike). Più dimensione dell'APK e della cartella Windows.

## 9. Ordine dei lavori e cosa deve fare l'utente

1. **Utente:** approvare il piano e le decisioni della sezione 10.
2. (io) Commit 1: `app_paths`, percorsi, `rules.json` in `assets/`, via dal versionamento i tre JSON
   (verifica a cartella vuota con `test.py` e `main.py` locale).
3. (io) Commit 2: `pyproject.toml`, `nativa.py`, `prepara_build.py`, icona e segnaposto; primi build APK e Windows
   (in background: il primo può durare ~30 min); controllo del contenuto del pacchetto.
4. (io) Commit 3-4: interfaccia (finestra, layout, SafeArea, Indietro, ripresa) e fuori rete; prove su emulatore,
   `test.py`, webapp locale nel browser pane.
5. **Utente — prove sul telefono:** installare l'APK (fonti sconosciute; oppure lo installo io con `adb` se il
   telefono è collegato con il debug USB), poi la lista di prova (sezione 11) e le misure di avvio.
6. **Utente — prove su Windows:** avviare l'app costruita **da Esplora file** (dalla sessione di Claude non estrae il
   codice, Fase 0), lista di prova, misure.
7. **Utente:** OK per portare il codice su `main`. Effetto su Render: layout adattivo e ripresa anche sul web, i tre
   JSON non più nel checkout (primo login dopo il deploy li scarica). Nessun SQL da eseguire prima o dopo.
8. **Utente:** prova della webapp da iPhone (login, Squadra, Calendario, dialog, area sicura) e da PC.
9. (io) Stato del piano, misure, commit.

L'APK/Windows di questa fase sono **di prova** (keystore di debug): la firma vera e la distribuzione sono Fase 5.
Un APK firmato con la chiave di debug non si aggiorna poi con quello firmato in Fase 5: andrà disinstallato
(si perde solo la cache e il "Ricordami").

## 10. Decisioni aperte

1. **Cartella di build con lista ammessi** (proposta) vs `path="."` con `exclude` vs codice in un pacchetto
   (tabella 4.3).
2. **Togliere dal versionamento `calendar/standings/injuries.json` ora** (proposta) vs lasciarli.
3. **Foto incluse con riserva dal CDN NBA** (proposta) vs tutte dal CDN vs solo incluse (un giocatore nuovo
   avrebbe il segnaposto fino al build successivo).
4. **Architetture Android:** `arm64-v8a` + `armeabi-v7a` (proposta; ogni architettura pesa ~20 MB, x86_64 serve
   solo all'emulatore e la aggiungo nei build di prova) vs solo `arm64-v8a` (APK più piccolo, esclude telefoni
   a 32 bit molto vecchi) vs APK separati per architettura (`split_per_abi`, più piccoli ma l'utente deve scegliere quello giusto).
5. **Icona:** me ne dai una tua (PNG quadrato ≥ 1024 px) vs ne preparo io una semplice (pallone arancione su fondo
   scuro, come l'icona del login) con Pillow, già presente nella .venv.
6. **Desktop largo:** campo e panchina affiancati sopra i ~900 px (proposta) vs stessa colonna centrata del telefono
   (più semplice; spreca spazio ma è identica dappertutto).
7. **Soglia per l'aggiornamento al ritorno:** 5 minuti (proposta) vs sempre vs solo dopo l'orario del cron.
8. **Aggiornamento silenzioso = ricostruire la dashboard sul tab corrente** (proposta, semplice e sicuro) vs
   aggiornare solo le viste cambiate (più fluido, è materia della Fase 4).
9. **Rotazione su Android:** solo verticale (proposta, il campo è pensato in verticale) vs libera.
10. **Fuori rete solo sull'app nativa** (proposta) vs anche sul web.
11. **Identificativo e nomi:** `it.fantanba.fantanba`, "FantaNBA", versione `0.3.0` (proposta). L'identificativo
    Android non si cambia più dopo la distribuzione.
12. **Migrazione 2C** (via `login`, `login_with_token` e la SELECT diretta di anon sulle tabelle di lega), rimandata
    dalla Fase 2 "a fine Fase 3": proposta **rimandare a dopo la Fase 5**, quando l'app installata è distribuita e
    lo spike non serve più; nessun codice in produzione le usa, ma toglierle ora non dà vantaggi pratici.

## 11. Lista di prova per l'utente (Android e Windows)

1. Primo avvio: login con "Ricordami", dashboard, tutti i tab.
2. Chiudi e riapri: accesso automatico, nessuna parte riscaricata (in console 1 richiesta).
3. Cambio formazione e salvataggio; modifica non salvata + Indietro (Android) → conferma.
4. Indietro da Calendario → Squadra → esce.
5. App in secondo piano > 5 minuti → al ritorno nessuna schermata di caricamento, dati aggiornati.
6. Modalità aereo / rete disattivata → riapri → dati con barra "Senza connessione"; Salva bloccato; Riprova.
7. Windows: ridimensiona, massimizza, minimo; Invio al login; rotellina; giornate raggiungibili col mouse.
8. Logout e login con un altro utente sullo stesso dispositivo: nessun dato del precedente nella squadra mostrata.
9. Misure di avvio (5 volte, cache piena) annotate.

## 12. Rischi

- **Segreti nel pacchetto:** è il rischio principale se si usasse la radice come cartella dell'app (`.env` con la
  chiave segreta). Mitigato da lista ammessi + controllo automatico + ricerca nel pacchetto finito.
- **Indietro sulla vista radice:** `can_pop`/`on_confirm_pop` da provare sul telefono (Indietro predittivo di
  Android 14+); riserva con una seconda vista.
- **Tab scorrevoli col mouse su Windows:** possibile che la barra delle 24 giornate non si trascini; riserva con
  frecce o menu.
- **Evento di ripresa su Windows** frequente (fuoco della finestra): soglia temporale; e sul web il server riceve
  l'evento solo se la sessione è ancora viva (`SESSION_TIMEOUT` 600 s): dopo, Flet ricarica comunque la pagina.
- **Ricostruzione della dashboard** può perdere lo stato di scorrimento: accettabile ora, migliorabile in Fase 4.
- **Build Windows** con l'aggiramento CMake della Fase 0 e prove solo da Esplora file (limite della sessione di Claude).
- **Più utenti sullo stesso dispositivo:** la cache delle formazioni è per nome squadra, quindi non si mescola;
  il profilo salvato si sovrascrive al login e si cancella al logout.
- **Render:** `pyproject.toml` nella radice: da controllare nel log del primo deploy che il build usi ancora
  `requirements.txt`. Il primo login dopo il deploy scarica i tre JSON (≈20 KB compressi).
- **Dimensione:** Python incorporato domina (~70 MB APK con 3 architetture in Fase 0); le foto aggiungono ~2 MB.

## 13. Cambiato in corso d'opera (15/11/2026)

- **Telefoni sotto 360 dp:** nessuna scala del campo. Le larghezze fisse si restringono da sole fino a 320 dp
  (provato nel browser a 320 px); sotto i 360 dp la barra dei 5 tab scorre, come prima.
- **Indietro con formazione non salvata:** invece di un dialog "Uscire senza salvare?", un avviso e un secondo
  Indietro entro 3 secondi per uscire (verificato nel codice Dart di Flet 0.82: `confirm_pop(True)` sulla vista
  radice chiama `SystemNavigator.pop()`).
- **Frecce per le barre scorrevoli** (giornate del calendario, altre squadre) sempre su PC, anche dal browser:
  Flet 0.82 non abilita il trascinamento col mouse.
- **SnackBar:** con `page.overlay` in Flet 0.82 non compaiono; ora `page.show_dialog` (anche in `Court` e
  `ProfileView`, quindi anche sulla webapp).
- **Tempi di avvio** in `avvii.jsonl` nella cartella dati (`import_flet_ms`, `pagina_ms`, `prima_schermata_ms`
  dall'inizio di Python).
- **16/11: nome Bonkest** (decisione dell'utente dopo le prove): `it.bonkest.bonkest`, prodotto e azienda "Bonkest",
  file `bonkest.apk` / `bonkest.exe`, cartella `%APPDATA%\Bonkest\Bonkest`; titolo e login "Bonkest" anche sul web.
- **16/11: foto in più nel pacchetto:** i giocatori con media FPTS ≥ 18 (probabili acquisti di mercato), 33 foto,
  totale 160 (2,8 MB). Le altre continuano ad arrivare dal CDN NBA.
