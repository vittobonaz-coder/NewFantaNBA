# FantaNBA — istruzioni per Claude Code

App per gestire un campionato privato di fantabasket NBA: una decina di squadre e utenti, codice e commenti in italiano.

## Com'è fatto il progetto

- **Interfaccia:** Flet 0.82.
  - `app.py`: avvio, login, sincronizzazione.
  - `ui_court.py`: interfaccia.
  - `fanta_obj.py`: modelli (Team, Player).
  - `time_manager.py`: giornate e scadenze dei cambi.
- **Versione web:** `main.py` (FastAPI + uvicorn) è il punto d'ingresso su Render, piano Free con 0,1 CPU, che si addormenta dopo 15 minuti. Render pubblica da `main`.
- **Versione desktop locale:** `test.py`, stessa app.
- **Dati:** `supabase_manager.py` (supabase-py, client unico condiviso, `run_parallel` per le richieste in parallelo).
- **Cache locale:** JSON in `data/`. Si riscaricano solo se dopo il download è girato un cron (tabella `cron_runs`). `data/sync_meta.json` e `*_state.json` non sono versionati.
- **Cron:** `cron_test_script.py` gira su GitHub Actions (`.github/workflows/cron-test.yml`), lanciato da pg_cron di Supabase. Scrive punteggi, partite NBA, infortuni e rollover delle giornate.
- **Script di amministrazione locali:** `setup_fanta_championship.py`, `swap_players.py`, `reset_pre_setup.py`, `backfill_lineups.py`, `generate_avg_excel.py`, `download_*`.
- **Database:** schema di riferimento in `sql/schema_riferimento.sql`; migrazioni in `sql/`.

## Lavoro in corso

Migrazione ad **app nativa con `flet build`**. Android e Windows sono entrambe piattaforme obbligatorie: ogni modifica va verificata su tutte e due (dettagli nella sezione "Piattaforme" del piano). Il piano a fasi e lo stato di avanzamento sono in `docs/piano_migrazione_C1.md`: leggilo all'inizio di ogni sessione che riguarda la migrazione.

## Regole di lavoro

- **Branch:** lavora sul branch `app-nativa`, mai direttamente su `main`. Non fare push né merge su `main` senza il mio OK: ogni push su `main` fa ripartire Render.
- **La versione web deve continuare a funzionare** per tutta la migrazione: la usano gli utenti con iPhone e serve come riserva.
- **Un passo alla volta:** procedi una fase del piano alla volta. A fine fase fermati, aggiorna la sezione "Stato di avanzamento" del piano, fai commit e dammi:
  - cosa hai fatto e come l'hai verificato;
  - le misure prima e dopo, se la fase riguarda la velocità;
  - cosa devo fare io, in ordine;
  - rischi e decisioni aperte.
- **Database Supabase:**
  - non eseguire mai SQL da solo e non scrivere sul database da script;
  - scrivi le migrazioni in `sql/` (`AAAA-MM_descrizione.sql`, commenti in italiano, ordine di esecuzione, rollback quando ha senso; lo stile è quello di `sql/2026-11_cron_runs_manual.sql`): le eseguo io nello SQL Editor;
  - ogni migrazione deve restare compatibile con il codice già in produzione (web su Render e cron), oppure dimmi esplicitamente in che ordine pubblicare codice e SQL;
  - dopo una migrazione che cambia tabelle o colonne, aggiorna `sql/schema_riferimento.sql`.
- **Segreti:**
  - la chiave segreta (service role) di Supabase non deve mai finire nel codice dell'app né nella repository: solo variabili d'ambiente, segreti di GitHub o un `.env` locale non versionato;
  - non copiare nelle risposte password o chiavi che trovi nei file (es. `todo.txt`, `data/profiles.json`).
- **File e cronologia:** non cancellare file e non riscrivere la cronologia git senza chiedere. I JSON in `data/` (calendar, standings, injuries) sono una cache che l'app riscrive: non committare le loro modifiche, salvo che io lo chieda.
- **Velocità:** quando dici "più veloce", misura prima e dopo.
- **Ipotesi sbagliate:** se un'ipotesi del piano si rivela sbagliata, fermati e proponi le alternative con pro e contro invece di aggirare il problema.
- **Stile:** commenti e docstring in italiano, sintetici; type hint; nessuna dipendenza nuova senza motivarla. Rispondimi in italiano.
