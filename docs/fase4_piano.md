# Fase 4 — Fluidità dell'interfaccia (proposta del 16/11/2026, decisioni discusse, in attesa del "procedi")

**Decisioni dell'utente (16/11):** 1 correzione su Flet 0.82 ora, aggiornamento di Flet a fine migrazione
(sezione 13); 2 menu aggiornati sul posto (B); 3 schermata dei tempi **solo temporanea, per il debug della
fase**, nascosta agli utenti e tolta a fine fase (sezione 3.2); 4 connessione anticipata + profilo in
background, dashboard dalla cache solo se l'avvio sul telefono resta > 2 s; 5 strumentazione su `main` per i
numeri "prima" di Render, con lo stesso vincolo del punto 3; 6 foto offline sì; 7 JSON compatto per i file
grandi, indentati i piccoli.

Branch `app-nativa` (da `12511e56`). Nessun file del repository modificato in questo passo.
Basato su: `CLAUDE.md`, `docs/piano_migrazione_C1.md`, `docs/fase3_piano.md`, `app.py`, `nativa.py`,
`app_paths.py`, `ui_court.py`, `league_cache.py`, `supabase_rest.py`, `fanta_obj.py`, `main.py`, sorgenti di
flet 0.82.0 (`.venv`) e del client Dart `flet-0.82.0` (cache pub), sorgenti di flet 0.82.2 / 0.83+ su GitHub.
Misure fatte da me sul PC con script nella mia cartella temporanea (sola lettura della repo, copia di `data/`,
nessuna chiamata al database).

## 0. Idea in una riga

Il costo principale **non** sono i ~150 menu: è un difetto di Flet 0.82 che rende ogni `update()` lentissimo
(~450 ms sul PC per il solo campo, ~930 ms per tutta la pagina, anche senza modifiche). Si corregge con poche
righe, poi si tolgono gli `update()` doppi, si aggiornano le card "sul posto", si anticipa la connessione a
Supabase all'avvio e si aggiunge una schermata "Informazioni e tempi" per leggere le misure sul telefono.

## 1. Cosa ho verificato (ipotesi del piano generale)

| Ipotesi | Esito |
|---|---|
| Il costo dello scambio sono i ~150 `PopupMenuItem` ricreati | **Solo in parte (ipotesi da correggere).** Costruirli costa 3,6 ms (Python, PC). Il costo vero è il calcolo della patch nell'`update()`: in `flet/controls/object_patch.py` (0.82.0, righe 667 e 971) `_compare_lists` e `_compare_dataclasses` chiamano `logger.debug(f"... {src} {dst}")`: la f-string si valuta **sempre**, anche col debug spento, e fa il `repr` di tutto il sottoalbero a ogni lista e a ogni controllo visitato (costo quadratico con la profondità) |
| `update_data` ricostruisce la card | Sì: 21 controlli nuovi per card; dopo la correzione costa poco, ma si può fare meglio (sezione 4) |
| Doppio `update()` negli scambi | Sì: `toggle_buttons(True)` fa `self.update()` e poi `handle_swap` ne fa un altro. Idem `change_lineup` e `restore_saved_state` |
| SnackBar mai tolte da `page.overlay` | **Già risolto in Fase 3**: `page.show_dialog` (flet `base_page.py:371-410`) le toglie da `page._dialogs` quando si chiudono. Da confermare con un conteggio nella prova (sezione 6) |
| Il difetto è corretto nelle versioni successive | Sì: da **0.83.0** il messaggio usa `%s` (valutato solo col debug acceso). 0.82.2 ha ancora la f-string |
| `ft.Image` mostra un file locale | Sì su Android e Windows: il client (`images_io.dart:53`) usa `FileImage` se la stringa è un percorso che esiste sul dispositivo. **No sul web** (`images_web.dart`: il browser non vede i file del server) |

### Misure sul PC (Python 3.12, Flet 0.82.0, cache reale, squadra Minghie GW 4 + GW 5)

| Operazione | Oggi | Con la correzione del `repr` |
|---|---|---|
| Patch di un `update()` del campo **senza modifiche** | **455–470 ms** | 9 ms |
| Patch di uno scambio (campo) | **450–660 ms** ×2 (doppio update) | 14 ms |
| Scambio senza rigenerare i menu | 455 ms | 9 ms (6 KB invece di 16,6 KB, 58 controlli rimontati invece di 308) |
| `update()` della pagina intera (es. `select_tab`, `apply_width`) | **~930 ms** | 19 ms |
| `TeamView.show_court` (pulsanti "Giornata 4" / "Formazione G5": aggiorna i due campi) | ~900 ms | ~20 ms |
| Costruzione della dashboard (885 controlli) | 6–19 ms | uguale |
| Primo invio della dashboard (diff + msgpack, 88 KB) | 27–47 ms | 17–40 ms |
| `refresh_menus` (solo Python) | 3,6 ms | uguale |
| Calendario Lega / giornata NBA / campo di un'altra squadra (costruzione + patch) | 7 / 31 / 23 ms | uguale (sono "montaggi", il difetto pesa poco) |
| `json.dump` del calendario: indent=4 / compatto | 8 ms, 382 KB / 6 ms, 166 KB | — |
| `import app` (dopo flet) | 52 ms | — |
| Creazione `httpx.Client` (contesto SSL + certifi) | 170–270 ms | — |
| Prima richiesta HTTPS a Supabase (DNS+TCP+TLS, senza toccare il DB) / seconda | 170–330 ms / 55–67 ms | — |

Stima (da verificare con le misure vere): il Galaxy A52s è ~3–4 volte più lento del PC in Python, Render
(0,1 CPU) anche 10 volte. Uno scambio oggi costa quindi **~3 s sul telefono** e potenzialmente **diversi secondi
sulla webapp**; dopo la correzione qualche decina di ms (più il disegno del client).

Correzione proposta (`flet_fix.py`, nuovo, ~25 righe): solo se `flet.__version__ == "0.82.0"` (o `0.82.*`),
sostituisce il `__repr__` generato dalle dataclass in tutte le sottoclassi di `BaseControl` con uno breve
(`<Container>`). Il `repr` non serve a Flet per funzionare (nessun uso fuori dai log, verificato con grep);
le nostre classi (`PlayerCard`, `Court`…) lo ereditano. Si applica in cima ad `app.py` (quindi per `main.py`,
`test.py`, `nativa.py`). Alternative nella decisione 1.

## 2. Dove vanno i ~1,9 s tra "pagina pronta" e "dashboard" (Windows)

Percorso di `nativa.native_main` → `app.main` con "Ricordami" e cache piena:

| Passo | Costo misurato/stimato sul PC |
|---|---|
| `StoragePaths().get_application_support_directory()` (andata e ritorno col client Flutter) | non misurato |
| `from app import main` (ui_court, league_cache, supabase_rest, time_manager) | ~50 ms |
| `prefs.get(token)` (andata e ritorno) + `show(spinner)` | non misurato |
| **`httpx.Client` alla prima chiamata** (SSL + certifi) | **170–270 ms** |
| **`token_bundle`**: DNS+TCP+TLS + richiesta | **~250–450 ms** |
| `load_user_data`: scrittura cache (nulla di cambiato: `snapshot_meta.json` + la propria formazione) | < 10 ms |
| `build_dashboard` + `show()` (diff + msgpack 88 KB) | ~50–70 ms |
| `save_last_profile` → `prefs.set` (andata e ritorno, **prima** del tempo registrato) | non misurato |

Conto noto ≈ 0,6–0,9 s; restano ~1 s da attribuire, probabilmente alle 3–4 andate e ritorno col client
Flutter, al Python incorporato (import da pacchetto, certifi) e al disegno. Per questo il primo passo è
strumentare (sezione 3): niente ottimizzazioni dell'avvio "alla cieca". Due interventi sono comunque sicuri:
1. **Connessione anticipata:** in `nativa.py`, appena parte `native_main`, un thread crea il client httpx e apre
   la connessione TLS con una richiesta che non tocca il database (`GET /rest/v1/` senza chiave → 401, come ho
   fatto io), in parallelo con `StoragePaths`, `import app` e `prefs.get`. Guadagno atteso 0,3–0,5 s.
2. **`save_last_profile` fuori dal percorso critico** (`page.run_task` dopo la dashboard).

Opzione più grande (decisione 4): **dashboard subito dalla cache** con "Ricordami" (come l'avvio senza rete),
scambi disabilitati e una piccola scritta "Aggiornamento…" finché `token_bundle` non risponde; poi si
abilitano gli scambi, o si ricostruisce la dashboard se è cambiato qualcosa (stessa firma di `refresh`).
Guadagno atteso: tutta la parte di rete (0,5–0,8 s). Rischio: per un attimo dati vecchi (dopo un cron) e un
ricarico visibile.

## 3. Punto 1 — Misure

### 3.1 Strumentazione (`misure.py`, nuovo, solo libreria standard)
```python
def segna(nome: str) -> None                 # tappa dell'avvio: ms dall'inizio di Python
def durata(nome: str, ms: float, **extra)   # interazione: scambio, modulo, tab, salvataggio…
def ultime(n: int = 50) -> list[dict]        # per la schermata Informazioni
```
- App installata: righe in `misure.jsonl` nella cartella dati (tiene le ultime ~300 righe); `avvii.jsonl`
  resta com'è e si arricchisce con le tappe dell'avvio: `data_dir`, `import_app`, `token_letto`,
  `client_http`, `rete` (ms, byte), `cache_scritta`, `dashboard_costruita`, `inviata`, `profilo_salvato`.
- Webapp e sviluppo: in memoria per sessione e, con `FANTANBA_MISURE=1`, stampate (come oggi `[MISURE]` di
  `supabase_rest.py`, che resta).
- **Interazioni misurate** (ms Python dall'evento alla fine dell'`update()`): scambio, cambio modulo, Annulla,
  apertura di ogni tab (prima volta e successive), cambio giornata/squadra nelle barre, passaggio
  "Giornata/Formazione", dettaglio partite, salvataggio (rete separata).
- **Tempo fino al client** (solo con "misure dettagliate" attive): dopo l'`update()` una chiamata leggera al
  client (es. `SharedPreferences.contains_key`) attende la risposta; i messaggi viaggiano in ordine, quindi
  misura invio + applicazione della patch sul dispositivo (non il disegno del fotogramma).
- Niente dati personali nelle righe (solo nomi delle operazioni, ms, byte, piattaforma, versione).

### 3.2 Come l'utente legge le misure del telefono (decisione: temporaneo, solo per il debug)
Un tab **"Tempi"** nelle Impostazioni, **visibile solo con le misure accese**; nessun utente della lega lo vede:
- **app installata:** acceso solo nei build di prova di questa fase (`python tools/prepara_build.py --misure`
  aggiunge in `app_src/` il file `misure_attive`); i build normali non lo contengono;
- **webapp:** acceso solo se su Render c'è la variabile `FANTANBA_MISURE=1` (la metti per le prove e la togli
  dopo); con la variabile accesa il tab lo vedrebbe chiunque apra le Impostazioni in quel periodo (dati innocui:
  solo tempi);
- contenuto: "Avvio: mediana degli ultimi 5" con le tappe, ultime 20 operazioni, "Misure dettagliate",
  **"Copia negli appunti"** (`ft.Clipboard().set`), "Azzera".
- **A fine fase** (ultimo commit, prima del passaggio finale su `main`) tolgo il tab e le chiamate di misura
  dell'interfaccia; resta solo la stampa `[MISURE]` con `FANTANBA_MISURE=1` come oggi e la riga di
  `avvii.jsonl` già esistente.

### 3.3 Cosa misurare, prima e dopo (5 ripetizioni, mediana e intervallo)
| Misura | Android (A52s, APK) | Windows (app installata) | Webapp |
|---|---|---|---|
| Accesso automatico: dashboard da tocco/doppio clic (`avvii.jsonl` + cronometro la prima volta) | ✓ | ✓ | Render: dal login alla dashboard |
| Login manuale (pulsante → dashboard) | ✓ | ✓ | ✓ |
| Apertura tab: Altre squadre, Calendario, Calendario NBA, Campionato, Impostazioni (1ª e 2ª volta) | ✓ | ✓ | ✓ |
| Scambio di giocatori, cambio modulo, Annulla, Giornata↔Formazione | ✓ | ✓ | ✓ |
| Salvataggio (totale e rete) | ✓ | ✓ | ✓ |

"Prima": build della strumentazione **senza** altre modifiche (commit 1). "Dopo": build finale.
Webapp: `main.py` in locale (PC) prima/dopo; su Render i numeri veri del server da 0,1 CPU si hanno solo
pubblicando la strumentazione (decisione 5).

### Verifiche
- PC: `test.py` e `nativa.py` con `FANTANBA_MISURE=1`; `misure.jsonl` scritto, schermata Info e copia.
- Android/Windows: tab Info, copia negli appunti, incolla in un messaggio.
- Webapp: tab Info con le misure della sessione; nessun file scritto in `data/` dalle misure.

## 4. Punto 2 — Menu di scambio

### 4.1 Confronto
| | A. "Tocca A, poi tocca B" | B. Menu attuale, aggiornando solo ciò che cambia (proposta) |
|---|---|---|
| Interazione | nuova: tocco sulla card la seleziona, le card compatibili si illuminano, secondo tocco scambia; serve annullare (tocco fuori, Indietro) | invariata, già nota agli utenti |
| Conflitto | il tocco sulla card **oggi apre il dettaglio delle partite**: andrebbe spostato su pressione lunga o su un'icona "i" (pressione lunga non esiste col mouse) | nessuno |
| Telefono | buono (bersagli grandi) | buono |
| Mouse (Windows) | buono | buono |
| Webapp / iPhone | **peggio**: ogni tocco è un'andata e ritorno col server da 0,1 CPU, anche solo per evidenziare le card | **meglio**: il menu si apre nel client senza server; una sola andata e ritorno alla scelta |
| Controlli in meno | ~140 (`PopupMenuItem`) | 0, ma non si ricreano più |
| Lavoro | medio-alto (stato di selezione, evidenziazione, nuovo gesto per i dettagli) | basso |

Con la correzione del `repr` lo scambio passa da ~900 ms (due update) a ~15 ms sul PC anche con i menu:
il vantaggio residuo di A è piccolo, mentre peggiora la webapp e cambia abitudini. **Proposta: B.**

### 4.2 Cosa cambia (B)
1. `PlayerCard.update_data`: modifica i controlli esistenti (src della foto, nome, squadra/posizione,
   pallini delle partite, punteggio, badge infortunio) invece di `setup_ui()`; la struttura si ricrea solo se
   cambia il ruolo (titolare ↔ panchina: dimensioni diverse) o compare/sparisce il badge. Patch attesa: poche
   centinaia di byte per card invece di 21 controlli nuovi.
2. `refresh_menus`: per ogni card un dizionario {slot di destinazione: `PopupMenuItem`} riusato; si aggiungono
   o tolgono voci solo se cambia l'insieme degli scambi validi e si cambia solo il testo delle voci il cui
   giocatore è cambiato.
3. Un solo `update()` per interazione: `toggle_buttons` non chiama più `update()` quando lo chiama già il
   chiamante (`handle_swap`, `change_lineup`, `restore_saved_state`).
4. `update_starters_layout`: riusa le 3 `Row` dei titolari cambiando i loro `controls`, invece di crearne di
   nuove a ogni cambio modulo (oggi rimonta 382 controlli). Da misurare: Flet confronta le liste per identità
   degli oggetti e dovrebbe spostare le card senza rimontarle.
5. `handle_card_click`, `TeamView.switch_court`, `handle_cancel`: niente velo (sezione 5).
6. `MainDashboard.select_tab`, `apply_width`, `RoundTabs.handle_arrow`: `update()` mirato al controllo
   cambiato (barra dei tab / campi) invece della dashboard intera dove possibile.

### Verifiche
- Automatiche sul PC (script di prova in `tools/`, senza rete): per 200 scambi casuali e tutti i cambi modulo,
  stato delle card identico a quello del codice di prima (giocatori, ruoli, punteggio totale, voci dei menu);
  patch per scambio < 3 KB; tempo patch < 20 ms.
- Android/Windows: scambi a raffica, modulo, Annulla, Salva, Indietro con modifiche non salvate; menu con le
  voci giuste dopo ogni scambio; misure prima/dopo dalla tab Info.
- Webapp: stesso giro nel browser integrato a 375 e 1280 px e da iPhone dopo il deploy.

## 5. Punto 3 — Problemi minori

| Problema | Proposta | File |
|---|---|---|
| `LoadingOverlay` sulle operazioni senza rete (+50 ms di attesa fissa e due update ciascuna) | tolto da dettaglio partite, Annulla, Giornata↔Formazione; resta su Salva, profilo, logout, caricamento Altre squadre e **prima** costruzione di una giornata NBA/squadra nelle barre (`RoundTabs`) | `ui_court.py` |
| Doppio `update()` negli scambi (e in modulo/Annulla) | sezione 4.2 punto 3 | `ui_court.py` |
| `json.dump` con indent sui file grandi | `write_json` compatto di default (`separators=(",", ":")`, senza indent): calendario 382 → ~160 KB, −2 ms sul PC (×3–4 sul telefono a ogni cron); `snapshot_meta.json` e `*_state.json` restano leggibili con indent (piccoli) | `league_cache.py` |
| `Team.save_to_json` non atomico (dopo Salva) | usa `league_cache.write_json` (scrittura atomica) — piccolo, opportuno ora | `fanta_obj.py` |
| SnackBar che si accumulano | **già risolto** (Fase 3, `page.show_dialog`): verifico solo che dopo 10 messaggi `page._dialogs.controls` sia vuoto | — |

Effetto sugli script: `supabase_manager.py` usa `league_cache.write_json`: i file in `data/` diventano compatti
(non versionati dalla Fase 3, nessun diff in git). Nessun script legge quei file "a occhio".

## 6. Punto 4 — Foto offline

Oggi: 160 foto incluse (2,4 MB, ~15 KB l'una, 260×190), **tutti i 120 giocatori in rosa hanno la foto inclusa**
(verificato). La riserva dal CDN NBA serve solo ai giocatori arrivati dopo il build (mercato, `swap_players.py`),
e Flutter tiene le immagini di rete solo in memoria: senza rete o a ogni riavvio → segnaposto/riscaricamento.

Proposta (solo app installata):
- dopo la dashboard, in un thread, per i giocatori delle rose in cache (proprie e altrui) **senza** foto inclusa
  né già scaricata: download da `NBA_HEADSHOT_URL` in `<cartella dati>/players/<id>.png` (scrittura atomica,
  timeout breve, al massimo ~20 per volta; un 404 si ricorda per un giorno in `players/_mancanti.json`);
- `PlayerCard.build_avatar` decide in Python **una sola sorgente**: foto inclusa se il file esiste
  (`app_paths.resource`), altrimenti (solo nativa) percorso assoluto del file scaricato, altrimenti URL del CDN
  con il segnaposto come `error_content`. Oggi ogni card ha 3 `Image` annidate (inclusa → CDN → segnaposto):
  si scende a 1–2, cioè ~60 controlli in meno nella dashboard, anche sul web.
- Dimensioni: realisticamente 0–30 foto a stagione, < 0,5 MB. Pulizia: le foto scaricate che finiscono nel
  pacchetto al build successivo si cancellano all'avvio (si controlla l'esistenza nel pacchetto).
- **Web:** invariato (foto da `assets/` di Render e riserva dal CDN); un percorso di file non avrebbe senso nel
  browser, e mandare le foto come byte nel websocket costerebbe troppo con 0,1 CPU.

Pro: foto sempre visibili senza rete; meno controlli. Contro: ~60 righe e un accesso a un sito esterno in
background (lo stesso che oggi fa Flutter). Decisione 6.

### Verifiche
- PC (`nativa.py`) e Windows: rinomino una foto nella copia di build → dopo l'avvio compare in
  `%APPDATA%\Bonkest\Bonkest\cache\players\`; rete disattivata → riavvio → foto visibile.
- Android: modalità aereo dopo il primo avvio → foto visibile.
- Webapp: foto come prima; nessuna cartella `players` in `data/`.

## 7. Punto 5 — La versione web non deve peggiorare

- Tutte le modifiche sono nel codice comune: la correzione del `repr` e gli update singoli **migliorano** la
  webapp più dell'app (lì ogni `update()` gira sul server da 0,1 CPU).
- Solo-nativa: connessione anticipata (in `nativa.py`), foto offline, eventuale dashboard dalla cache.
- `flet_fix.py` controlla la versione di Flet: con un aggiornamento futuro si disattiva da solo.
- Verifica: `main.py` in locale (misure prima/dopo nella tab Info e con `FANTANBA_MISURE=1`), browser
  integrato a 375/1280 px; dopo il deploy, prova da iPhone e da PC con i tempi nella tab Info.

## 8. File da cambiare

| File | Modifica |
|---|---|
| `flet_fix.py` (nuovo) | `repr` brevi per Flet 0.82 |
| `misure.py` (nuovo) | tappe e durate, `misure.jsonl`, memoria per sessione |
| `app.py` | applica `flet_fix`; tappe dell'avvio; `save_last_profile` in background; (decisione 4) dashboard dalla cache |
| `nativa.py` | connessione anticipata; tappe in `avvii.jsonl`; avvio download foto |
| `ui_court.py` | `update_data` sul posto, menu riusati, update singoli, velo solo dove serve, tab Info, sorgente unica delle foto, durate delle interazioni |
| `league_cache.py` | `write_json` compatto per i file grandi |
| `fanta_obj.py` | `save_to_json` atomico |
| `supabase_rest.py` | `warm_up()` (client + connessione, nessuna chiamata al DB) |
| `tools/prepara_build.py` | aggiunge `flet_fix.py`, `misure.py` alla lista dei file ammessi |
| `tools/prova_scambi.py` (nuovo) | confronto automatico vecchio/nuovo e tempi delle patch |
| `docs/fase4_piano.md`, `docs/piano_migrazione_C1.md` | piano e stato |

Non cambiano: cron, script, SQL. **Nessuna migrazione.** Nessuna dipendenza nuova.

## 9. Ordine dei lavori, cosa fa l'utente, pubblicazione su `main`

1. **Utente:** "procedi".
2. (io) **Commit 1 — misure:** `misure.py`, tappe, tab "Tempi" nascosto (sezione 3.2). Build APK e Windows
   "prima" con `--misure`.
3. **Utente:** installare i build "prima"; su telefono e Windows: 5 avvii con "Ricordami", 5 scambi, 3 cambi
   modulo, apertura di ogni tab, 1 salvataggio; "Copia negli appunti" dal tab Tempi e incollarmi il testo.
4. **Utente:** OK a pubblicare il solo commit 1 su `main` (un deploy di Render, il tab resta invisibile);
   impostare su Render `FANTANBA_MISURE=1`, stesse prove dalla webapp (iPhone e PC), copia dei tempi, poi
   togliere la variabile.
5. (io) **Commit 2 — correzione Flet + update singoli;** **commit 3 — card e menu sul posto, modulo;**
   **commit 4 — problemi minori;** **commit 5 — avvio** (connessione anticipata, profilo in background,
   eventuale dashboard dalla cache); **commit 6 — foto offline.** Dopo ogni commit misure sul PC e prova
   nel browser integrato; script `tools/prova_scambi.py`.
6. (io) Build "dopo" APK e Windows.
7. **Utente:** stesse prove e misure del punto 3, più la lista di prova (sezione 11); copia dei tempi.
8. **Utente:** OK per portare il codice su `main` (avanzamento diretto da `app-nativa`). Nessun SQL prima o
   dopo. Effetto su Render: scambi e tab molto più rapidi.
9. **Utente:** con `FANTANBA_MISURE=1` su Render, prova della webapp da iPhone e PC e copia dei tempi; poi via
   la variabile.
10. (io) **Commit finale:** via il tab Tempi e le misure dell'interfaccia (sezione 3.2); stato e misure
    prima/dopo in `docs/piano_migrazione_C1.md`; build normali (senza `--misure`).
11. **Utente:** OK per portare su `main` il commit finale (un ultimo deploy di Render, nessun cambiamento visibile).

## 10. Decisioni (prese il 16/11: vedi in cima; qui le alternative valutate)

1. **Correzione del difetto di Flet:** `flet_fix.py` con `repr` brevi su 0.82 (proposta: nessun cambio di
   versione, 25 righe, effetto misurato ×30–50) vs **aggiornare Flet a 0.83+** (corretto a monte, ma cambia
   flet-cli, client Flutter, build Android/Windows e `flet-web` su Render: da fare con calma, magari in Fase 5,
   con una prova completa) vs entrambe (prima la correzione, l'aggiornamento dopo).
2. **Menu di scambio:** B, menu aggiornati sul posto (proposta) vs A, "tocca A poi tocca B".
3. **Dove leggere le misure:** tab "Info" visibile nelle Impostazioni con "Copia negli appunti" (proposta) vs
   schermata nascosta (es. 5 tocchi sulla versione) vs solo file (`adb pull`, scomodo e richiede debug USB).
4. **Avvio:** solo connessione anticipata + profilo in background (proposta per il primo giro) vs anche
   **dashboard subito dalla cache** con aggiornamento in background (più veloce di 0,5–0,8 s, ma dati vecchi per
   un attimo e possibile ricarico): la decido con le misure "dopo" se l'avvio sul telefono resta > 2 s.
5. **Numeri "prima" di Render:** pubblicare su `main` il solo commit di strumentazione (proposta; un deploy in
   più, rischio basso) vs misurare la webapp solo in locale e su Render solo "dopo".
6. **Foto offline:** sì, come in sezione 6 (proposta) vs rimandare (oggi tutte le foto in rosa sono incluse).
7. **`json` compatto** per calendario, infortuni, classifica e `league_teams` (proposta) vs lasciare indent.

## 11. Lista di prova per l'utente (Android e Windows)

1. Accesso automatico ×5 (tempi dalla tab Info); un login manuale.
2. Squadra: 5 scambi di fila (titolare↔panchina, panchina↔riserva), 3 cambi modulo, Annulla, Salva; le voci dei
   menu sono quelle giuste dopo ogni scambio; il totale torna.
3. Giornata↔Formazione ×3; dettaglio partite di 3 giocatori.
4. Altre squadre (scorri 3 squadre, frecce su Windows), Calendario Lega e NBA (3 giornate), Campionato,
   Impostazioni → Info: "Copia negli appunti" e incolla.
5. Senza rete dopo il primo avvio: foto visibili, dati in cache come in Fase 3.
6. Indietro (Android) con modifiche non salvate: avviso come prima.
7. Windows: ridimensiona sopra/sotto 760 px (campo affiancato) con modifiche non salvate: restano.

## 12. Rischi

- **`flet_fix` su una versione diversa di Flet:** controllato con la versione; se Flet cambiasse uso del `repr`
  (oggi nessuno) lo vedrebbero i test. I messaggi di debug di Flet diventano meno dettagliati (non li usiamo).
- **Aggiornamento sul posto delle card:** rischio di disallineare dati e controlli (giocatore giusto, foto
  sbagliata): coperto dal confronto automatico su 200 scambi e dal controllo visivo.
- **Riuso delle `Row` nel cambio modulo:** se Flet rimontasse comunque le card, nessun danno (solo meno guadagno).
- **Connessione anticipata:** una richiesta in più (401, nessun accesso al DB) per avvio; se fallisce non cambia
  nulla (la richiesta vera si rifà).
- **Misure:** il "tempo fino al client" aggiunge un'andata e ritorno: solo con "misure dettagliate".
- **Foto scaricate:** sito esterno (CDN NBA) e spazio nella cartella dati, limitati e puliti al build successivo.
- **Stime telefono/Render:** sono estrapolate dal PC; i numeri veri arrivano dal commit 1.

## 13. Da fare in futuro (deciso il 16/11/2026)

- **Aggiornare Flet** (0.83 o l'ultima, oggi 1.1.2) **alla fine della migrazione**, dopo l'ultima fase: corregge a
  monte il difetto delle patch (da 0.83.0) e può portare altri miglioramenti. Va fatto con una prova separata
  (build Android e Windows, `flet-web` su Render, client Flutter della webapp, eventuali comandi cambiati, la
  1.x è un cambio di versione principale). Con l'aggiornamento `flet_fix.py` si disattiva da solo (controlla la
  versione) e poi si toglie. Da registrare in `docs/piano_migrazione_C1.md` (Decisioni prese / Fase 6).

## 14. Cambiato in corso d'opera

- **16/11, commit 1 — aggiornamento automatico di Flet:** dopo **ogni** evento (tocco, cambio tab, voce di menu,
  ridimensionamento) Flet 0.82 chiama da sé `update()` sul primo antenato "isolato", cioè la **pagina intera**
  (`Session.after_event`, `messaging/session.py:438`), oltre agli `update()` che fa già il nostro codice. Con il
  difetto del `repr` è un'altra patch da ~1 s sul PC a ogni evento. Le misure (`misure.installa_misura_eventi`,
  che avvolge `Session.dispatch_event`) comprendono quindi gestore + aggiornamento automatico. Nel commit 2 si
  valuta, misurando, se spegnerlo nei nostri gestori (`ft.context.disable_auto_update()`), dato che ognuno
  aggiorna già quello che cambia.
- **16/11, commit 1 — prime misure sul banco di prova** (webapp locale sul PC, login e salvataggio simulati,
  nessuna rete): `show()` della dashboard dopo il login **~960 ms** (spiega buona parte del secondo di avvio non
  attribuito su Windows), Giornata↔Formazione 1,8 s, scambio 0,93 s, Annulla 1,8 s, apertura di Calendario,
  Campionato e Impostazioni 0,9–1 s ciascuna. Sono numeri "prima" del solo PC.
- **Copia negli appunti:** nel browser può essere rifiutata (permesso o clic "troppo lontano" dalla chiamata, che
  passa dal server); in quel caso un messaggio invita a selezionare il testo (selezionabile). Sull'app installata
  gli appunti non hanno questo limite.
- **18/11, misure "prima" sui dispositivi** (build `5b492cd7` con le misure, mediane in ms):
  | | Telefono (A52s) | Windows |
  |---|---|---|
  | Avvio → dashboard | 5.432 | 2.658 |
  | di cui import di flet / client httpx / rete | 1.212 / ~190 / 270–560 | 575 / ~240 / 260–480 |
  | di cui **`show()` della dashboard** | **~3.300** | **~1.030** |
  | Scambio | 3.237 | 907 |
  | Cambio modulo | 6.466 | — |
  | Annulla | 6.970 | 1.922 |
  | Giornata↔Formazione | 6.656 | 1.833 |
  | Apertura dei tab (prima volta) | 4.900–5.500 | 1.150–1.420 |
  | Giornate del calendario | 5.100–5.700 | 1.300–1.450 |
  | Salvataggio (di cui rete) | 5.860 (549) | 2.048 (544) |
- **18/11, commit 2 — `flet_fix.py`:** oltre ai `repr` brevi spegne l'aggiornamento automatico per tutta l'app
  (`UpdateBehavior._auto_update_enabled = False`, valore predefinito copiato nel contesto di ogni evento; stesso
  effetto di `ft.context.disable_auto_update()` ma per tutte le sessioni). Controllati tutti i gestori: ognuno
  aggiorna già quello che cambia (`show_dialog`/`pop_dialog` aggiornano da soli). Un solo `update()` per scambio,
  cambio modulo, Annulla e chiusura dei cambi (`toggle_buttons(update=False)`).
  Banco di prova (webapp locale sul PC, stesse operazioni, ms "py"): login → dashboard 1.145 → **270**
  (`show()` 958 → 70), scambio 933 → **42**, Annulla 1.832 → **127**, Giornata↔Formazione 1.799 → **80**,
  apertura Calendario 899 → **9**, Campionato 933 → **16**, Impostazioni 982 → **26**, Altre squadre **61**.
- **18/11, commit 3 — card, menu e righe sul posto:** `PlayerCard` si costruisce una volta e `update_data` cambia
  solo i valori (testi, foto, badge e freccia sempre presenti, nascosti quando non servono; pallini rifatti solo
  se cambiano le partite); voci dei menu riusate per (card, destinazione); tre `Row` dei titolari riusate nel cambio
  modulo. `tools/prova_scambi.py`: 34 formazioni in cache, 3.400 operazioni casuali, nessun errore (card uguali a
  card nuove, menu giusti, totale giusto). Patch mediane, commit 2 → commit 3: scambio 19,6 → **9,2 ms** e
  15,5 → **3,2 KB**; cambio modulo 22,3 → 10,6 ms e 22,7 → 7,4 KB; Annulla 27,1 → 13,1 ms e 37,8 → 14,3 KB.
