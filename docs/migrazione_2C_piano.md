# Migrazione 2C — chiusura delle vecchie strade d'accesso al database: piano (in attesa di OK)

**A cosa serve questo file:** è il piano della "migrazione 2C", rimandata dalla Fase 2 (`docs/fase2_piano.md`,
parte C) a dopo la Fase 5 (`docs/piano_migrazione_C1.md`, "Decisioni prese"). Contiene cosa si toglie, chi lo usa
ancora, cosa si guadagna davvero e le decisioni aperte.

## 1. Cosa toglie

Oggi la chiave pubblica (`sb_publishable_…`, scritta in `supabase_rest.py` e quindi dentro l'APK e la repository)
apre tre "porte" che l'app non usa più:

1. **Lettura diretta delle tabelle di lega:** con la chiave pubblica si può chiedere a Supabase, per esempio,
   `GET /rest/v1/rosters?select=*` e avere tutte le rose. Riguarda `matchups`, `lineup_players`, `nba_games`,
   `nba_players`, `player_injuries`, `cron_runs`, `rosters`, `v_standings` e `fanta_teams` (solo id e nome).
   È stata aperta nella Fase 1 (`sql/2026-11_fase1b_rls_revoche.sql`, sezione 2) quando l'app leggeva così.
2. **RPC `login_with_token`:** accesso con il token della Fase 1, sostituita da `token_bundle` nella Fase 2.
3. **RPC `login`:** login della Fase 1, sostituita da `login_bundle`. **Non si può cancellare:** `login_bundle` la
   usa al suo interno. Si può solo togliere il permesso di chiamarla da fuori.

*RPC* = funzione che sta nel database e che l'app chiama per nome (es. `POST /rest/v1/rpc/login_bundle`).

## 2. Chi le usa ancora (ricognizione fatta nel codice)

| Chi | Cosa usa | Effetto della migrazione |
|---|---|---|
| App installata 1.0.0 e pre-release `rc` | solo RPC (`login_bundle`, `token_bundle`, `get_snapshot`, `save_lineup`, …) | nessuno |
| Webapp su Render (`main`) | le stesse RPC | nessuno |
| Cron e script di amministrazione (`supabase_manager.py`, `swap_players.py`, `reset_pre_setup.py`, `setup_fanta_championship.py`, `generate_avg_excel.py`, `backfill_lineups.py`) | chiave **segreta** (`admin=True`): scavalca permessi e RLS | nessuno |
| `tools/verifica_permessi.py` | controlla che le tabelle di lega **siano** leggibili e che `login` risponda | va aggiornato: dopo la migrazione deve controllare il contrario |
| `spike_android/main.py` (mini-app della Fase 0) | `login` e lettura diretta di `matchups` | smette di funzionare; non serve più. La cartella resta: il suo ambiente Python (`spike_android/.venv`) è quello che usiamo per `flet build` |
| Strumenti **fuori da questa repository** (un foglio Google, un'altra app, un bot…) che leggono il database con la chiave pubblica | non li vedo dal codice | **smetterebbero di funzionare**: vedi decisione 1 |

Le RPC che restano (`get_snapshot`, `login_bundle`…) leggono le tabelle "con i permessi del proprietario"
(SECURITY DEFINER): non hanno bisogno che la chiave pubblica possa leggerle.

## 3. Cosa si guadagna davvero (onestamente)

- **Poco sulla riservatezza:** `get_snapshot` restituisce a chiunque abbia la chiave pubblica calendario,
  classifica, formazioni della giornata e infortuni. Sono dati di lega, non personali; restano visibili così.
- **Superficie più piccola:** oggi chi ha la chiave può fare query libere su 9 tabelle (filtri, ordinamenti, tutte
  le righe di `nba_games` e `nba_players`, tutte le rose di tutte le giornate). Dopo, può fare solo quello che le
  RPC prevedono. Meno porte = meno cose da tenere d'occhio.
- **Meno codice morto nel database:** `login_with_token` sparisce; `login` resta solo come pezzo interno.
- **Coerenza con il piano originale:** la Fase 1 diceva "lettura con la chiave anon solo dei dati che servono
  all'app"; ora all'app non serve nessuna lettura diretta.

In pratica: è una pulizia di sicurezza, non risolve un problema visibile. Se preferisci, si può anche non fare
(vedi decisione 3).

## 4. Proposta

Una migrazione `sql/2026-11_2C_chiusura_letture.sql`, stile delle precedenti (commenti, verifiche, rollback):

1. toglie a `anon` e `authenticated` (*ruoli* = "identità" con cui Supabase esegue le richieste: `anon` è chi usa
   la chiave pubblica senza login Supabase) la lettura delle 9 tabelle/viste e cancella le policy
   "lettura dati di lega" (una *policy* è la regola RLS che dice quali righe si vedono);
2. cancella `login_with_token`;
3. toglie il permesso di chiamare `login` da fuori (resta usabile da `login_bundle`);
4. in fondo: query di verifica e rollback che riapre tutto com'era.

Più, nel codice:
- `tools/verifica_permessi.py`: le tabelle di lega devono risultare **non** leggibili, `login` e
  `login_with_token` non chiamabili; restano i controlli su `get_snapshot`, `login_bundle`, `token_bundle`;
- una nota in cima a `spike_android/main.py` ("non funziona più dopo la migrazione 2C");
- `sql/schema_riferimento.sql` aggiornato.

**Ordine rispetto al codice: indifferente.** Nessun codice in produzione usa le porte che si chiudono, quindi non
serve né un deploy su Render né un rilascio dell'app.

**Prima di eseguirla** ti do una query di sola lettura per controllare sul database vero l'elenco delle funzioni
pubbliche e dei permessi di `anon`: se ci fosse qualcosa che non conosco (es. una funzione creata a mano in
passato), mi fermo e ne parliamo.

## 5. Verifiche previste

- migrazione su Postgres usa e getta: eseguibile due volte; `anon` non legge le tabelle; `login_bundle` funziona
  ancora (chiama `login` dall'interno); `login` e `login_with_token` non chiamabili da `anon`; rollback eseguibile;
- dopo l'esecuzione (tu): `python tools/verifica_permessi.py` aggiornato, tutto OK; webapp: accesso, cambio
  formazione e salvataggio; app sul telefono e sul PC: accesso; il cron del giorno dopo verde.

## 5-bis. Funzioni future (domanda del 23/11)

- **Storico dei tabellini** (tutte le partite e i fantapunteggi di tutte le giornate): non è bloccato. Si farà con
  una RPC nuova (es. lo storico di una giornata o di una squadra in una richiesta), come tutto il resto dell'app
  dalla Fase 2. Leggere le tabelle direttamente sarebbe comunque contro l'impostazione attuale (più richieste,
  dati non filtrati).
- **Backup completo del campionato:** non è toccato. Un backup vero deve includere anche `profiles` (password
  cifrate), `login_tokens`, `player_stats`, `standings_adjustments`, che la chiave pubblica non legge già dalla
  Fase 1: serve in ogni caso la chiave segreta o la connessione diretta al database (es. `pg_dump`), da uno script
  locale o da GitHub Actions con un segreto. Attenzione per allora: la repository è pubblica, quindi un backup non
  va mai salvato in chiaro tra i file o gli artifact di GitHub.

## 6. Decisioni aperte

1. **Strumenti esterni:** usi (o usa qualcuno della lega) qualcosa fuori da questa repository che legge il
   database con la chiave pubblica? Esempi: un foglio Google con IMPORTDATA/IMPORTJSON, un bot Telegram,
   un'altra app. Se sì, smetterebbero di funzionare.
2. **`login`:** togliere solo il permesso da fuori (proposta: una riga, si annulla con una riga) oppure spostarla
   tra le funzioni private (`private.login`, più pulito ma bisogna riscrivere anche `login_bundle`).
3. **Farla o no:** procedere (proposta, è piccola e reversibile) oppure lasciare tutto com'è.
