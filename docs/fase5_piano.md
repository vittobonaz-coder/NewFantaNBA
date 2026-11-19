# Fase 5 — Build, firma, distribuzione e aggiornamenti (piano approvato il 19/11/2026)

**Decisioni dell'utente (19/11):** 1 prima versione distribuita **1.0.0**; 2 keystore nei segreti GitHub + originale
sul PC + 2 copie di riserva fuori dal PC; 3 build locali firmate con la chiave vera (se ci sono le variabili);
4 **installer Inno Setup + zip** di riserva; 5 release in **bozza**, pubblicata dall'utente, poi `app_release`
aggiornata a mano dallo SQL Editor; 6 configurazione degli aggiornamenti con una **RPC dedicata** chiamata nella
connessione anticipata; 7 barra "nuova versione" a ogni avvio (solo se c'è una versione più nuova), chiudibile;
8 **nessuna firma del codice** su Windows per ora; 9 aggiramento CMake **portabile** (PC e GitHub) con controllo
delle DLL; 10 prova del workflow con un tag **`v1.0.0-rc.N` su `app-nativa`** prima di `main`; 11 istruzioni in
`docs/istruzioni_installazione.md`, usate anche come note della release, più un messaggio breve per WhatsApp.

Branch `app-nativa`. Basato su: `CLAUDE.md`, `docs/piano_migrazione_C1.md`, `docs/fase0_report.md`,
`docs/fase3_piano.md`, `docs/fase4_piano.md`, `pyproject.toml`, `tools/prepara_build.py`,
`tools/build_windows.ps1`, `nativa.py`, `app.py`, `app_paths.py`, `supabase_rest.py`, `.github/workflows/`,
sorgenti di flet-cli 0.82.0 (`spike_android/.venv`), template Flutter di build (`build/flutter`),
`serious_python_windows-0.9.12/windows/CMakeLists.txt`.

## 0. Idea in una riga

Un tag `vX.Y.Z` fa compilare a GitHub l'APK firmato con la chiave vera e l'app Windows (installer + zip) e li mette
in una release in bozza; l'utente la pubblica e aggiorna una riga su Supabase; le app installate leggono quella riga
all'avvio, senza attese in più, e propongono o impongono l'aggiornamento. La webapp non cambia.

## 1. Cosa ho verificato (ipotesi del piano generale)

| Ipotesi | Esito |
|---|---|
| `flet build` firma l'APK con una chiave nostra | **Sì**: `--android-signing-key-store`, `--android-signing-key-store-password`, `--android-signing-key-password`, `--android-signing-key-alias` o le variabili `FLET_ANDROID_SIGNING_*`. **Senza, firma in silenzio con la chiave di debug**: serve un controllo dopo il build |
| Compilare su GitHub Actions | Android sì: `flet build --yes` installa da solo Flutter 3.41.4, JDK 17 e SDK Android. **Windows da provare**: serious_python copia `msvcp140.dll`, `vcruntime140.dll`, `vcruntime140_1.dll` da `$ENV{WINDIR}/System32`; se il CMake di Visual Studio sul runner è a 32 bit il problema della Fase 0 si ripete. Coperto dall'aggiramento portabile (sezione 7) |
| L'app conosce la sua versione | **No**: il template passa a Python solo `FLET_PLATFORM`, `FLET_APP_STORAGE_*`, `FLET_ASSETS_DIR`. La versione va scritta nel pacchetto (`versione.py` generato). Versione e numero di build del pacchetto li prende flet da `project.version` e `tool.flet.build_number` di `pyproject.toml` |
| Numero di build | Oggi fisso a 1. Android rifiuta un aggiornamento con numero più basso: regola fissa X·10000 + Y·100 + Z, controllata da `prepara_build.py` |
| APK da fonti sconosciute | Oggi sì in Italia. **Rischio futuro**: verifica obbligatoria degli sviluppatori annunciata da Google anche fuori dal Play Store (alcuni Paesi dal 2026, globale dal 2027; da ricontrollare) |
| SmartScreen | Senza firma del codice: "PC protetto da Windows" → "Ulteriori informazioni" → "Esegui comunque". **Rischio**: con Smart App Control attivo (Windows 11) le app non firmate sono bloccate senza scelta |

## 2. Keystore Android (lo crea l'utente)

Il keystore è il file con la chiave che "sigilla" l'APK; Android installa un aggiornamento solo se ha lo stesso
sigillo dell'app già installata. **Se si perde, nessun utente può più aggiornare: tutti dovrebbero disinstallare.**

1. Creazione (PowerShell, password scelta e scritta dall'utente; con PKCS12 password del keystore = della chiave):
   ```
   New-Item -ItemType Directory -Force "$env:USERPROFILE\.bonkest"
   & "$env:USERPROFILE\java\17.0.13+11\bin\keytool.exe" -genkeypair -v -storetype PKCS12 `
       -keystore "$env:USERPROFILE\.bonkest\bonkest-release.jks" -alias bonkest `
       -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Bonkest"
   ```
2. Copie: l'originale in `%USERPROFILE%\.bonkest\` (mai nella repository: `.gitignore` e `prepara_build.py` rifiutano
   `*.jks`, `*.keystore`), **due copie di riserva fuori dal PC** (gestore di password con la password, chiavetta o
   cloud personale). I segreti GitHub non si possono rileggere: non sono una copia di riserva.
3. Segreti e variabile GitHub (comandi esatti in `tools/README_release.md`): `ANDROID_KEYSTORE_BASE64` (il file in
   testo), `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`; variabile **non segreta** `ANDROID_CERT_SHA256`
   (impronta del certificato) per il controllo della firma.
4. Build locali (decisione 3): `tools/build_apk.ps1` firma con la chiave vera se nel `.env` ci sono
   `ANDROID_KEYSTORE_PATH`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_CERT_SHA256`; senza, si ferma (con
   `-ChiaveDebug` compila con la chiave di debug, solo per prove). Un APK locale firmato è "ufficiale": non va distribuito
   per sbaglio.

## 3. Versione unica

- Fonte: `pyproject.toml` (`project.version`, `tool.flet.build_number`), letti da flet al build.
- `tools/prepara_build.py`: controlla `build_number == X·10000+Y·100+Z`; con `--tag vX.Y.Z[-rc.N]` controlla che
  il tag coincida con la versione; scrive `app_src/versione.py` (versione, build, commit, tag).
- `versione.py` nella repository: valori "non di build" (webapp, `test.py`, `nativa.py` in sviluppo: nessun
  controllo aggiornamenti).
- Impostazioni → Gestione Profilo, in fondo: "Bonkest 1.0.0" nell'app installata, "Bonkest — versione web" sulla webapp.

## 4. Workflow `.github/workflows/release.yml`

- Parte con un tag `v*` (e a mano dalle Actions, solo dopo che il file è su `main`). Concorrenza: un rilascio alla volta.
- **android** (ubuntu-latest): Python 3.12, `flet-cli==0.82.0` (+ `flet==0.82.0`), keystore dal segreto in
  `$RUNNER_TEMP` (cancellato a fine job), `prepara_build.py --tag`, `flet build apk`, `tools/controlla_build.py apk`
  (impronta = `ANDROID_CERT_SHA256`, nessun segreto nel contenuto) → artefatto `bonkest.apk`.
- **windows** (windows-latest): stessi pacchetti, `tools/build_windows.ps1 -Tag`, `controlla_build.py windows`
  (DLL a 64 bit, nessun segreto), installer Inno Setup (`tools/installer_windows.iss`) e zip → artefatti
  `Bonkest-Setup.exe`, `bonkest-windows.zip`.
- **release**: scarica gli artefatti, `SHA256SUMS.txt`, `gh release create` **in bozza** (pre-release se il tag ha
  `-rc`), note = `docs/istruzioni_installazione.md`. Nomi fissi: link stabile
  `https://github.com/<repo>/releases/latest/download/bonkest.apk` (le pre-release non contano come "latest").
- Permessi: `contents: read` in generale, `contents: write` solo nel job release; nessuna azione di terzi oltre a
  quelle ufficiali `actions/*`. Il workflow del cron non cambia; un tag non fa ripartire Render.

## 5. Controllo aggiornamenti

**SQL** `sql/2026-11_fase5_app_release.sql` (solo aggiunte): tabella `app_release` (`platform` android/windows,
`latest_version`, `min_version`, `url`, `note`, `updated_at`), RLS attiva e chiusa ad anon; RPC
`app_release(p_platform text) returns jsonb` (SECURITY DEFINER, `search_path = ''`, EXECUTE ad anon). Snippet per
aggiornare dopo una release; rollback.

**App installata:**
- `nativa.py`: il thread della connessione anticipata chiama `supabase_rest.warm_up(piattaforma)`, che invece della
  HEAD con risposta 401 chiama la RPC `app_release` (stessa connessione, in parallelo con `import flet`).
- `aggiornamenti.py` (nuovo): confronto delle versioni → `"ok" | "nuova" | "obbligatoria"`.
- `app.py`: prima dell'accesso aspetta l'esito (al massimo 2 s, di solito già pronto). **Obbligatoria**: schermata
  "Aggiornamento necessario" con "Scarica" (apre il link nel browser) e nessun accesso. **Nuova**: barra
  "Disponibile la versione X" con "Scarica" e "×" sopra la dashboard, a ogni avvio. Senza rete, RPC assente, errore
  o build di sviluppo: nessun controllo.
- **Webapp:** nessun controllo (`app_paths.is_native()` falso), nessuna chiamata in più.

Compatibilità: la migrazione aggiunge soltanto; il codice funziona anche prima della migrazione (RPC assente → nessun
controllo). Rende sicura, dopo, la migrazione 2C (si potrà alzare `min_version`).

## 6. Windows: installer + zip

- `tools/installer_windows.iss` (Inno Setup 6, gratuito, solo per il build): `PrivilegesRequired=lowest` (niente
  amministratore), cartella `%LOCALAPPDATA%\Programs\Bonkest`, collegamento nel menu Start (e sul desktop a
  scelta), disinstallazione, `AppId` fisso: un nuovo `Bonkest-Setup.exe` aggiorna sopra la versione precedente
  (chiude l'app). I dati in `%APPDATA%\Bonkest` restano.
- Zip di riserva: la cartella dell'app (`bonkest.exe` e file accanto), da estrarre e avviare con doppio clic.
- In locale l'installer si fa solo se Inno Setup è installato (`build_windows.ps1 -Installer`).

## 7. Aggiramento CMake definitivo (portabile)

`tools/build_windows.ps1`: trova le DLL x64 di Visual C++ con `vswhere` (Build Tools sul PC, Enterprise su GitHub)
invece del percorso fisso; flet-cli da `$env:FLET_EXE`, poi `spike_android\.venv`, poi PATH; `WINDIR` puntato a
`build\winroot` solo per il processo di build come oggi. Dopo il build `controlla_build.py windows` verifica
nell'intestazione PE che le DLL siano x64. Funziona con CMake a 32 o 64 bit.

## 8. Dagli APK di debug alla chiave vera

Solo i dispositivi dell'utente hanno build di prova. Android: **disinstallare** l'APK di debug prima del primo APK
firmato (si perdono "Ricordami" e cache: un login). Windows: nessuna firma; cancellare la vecchia cartella
`build\windows` usata per le prove e installare con `Bonkest-Setup.exe`.

## 9. File

| File | Modifica |
|---|---|
| `versione.py` (nuovo) | versione "non di build"; riscritto in `app_src/` |
| `aggiornamenti.py` (nuovo) | confronto versioni ed esito del controllo |
| `supabase_rest.py` | `app_release()`, `warm_up(piattaforma)`, `release_info()` |
| `nativa.py` | piattaforma nel thread della connessione anticipata |
| `app.py` | schermata "Aggiornamento necessario", barra "nuova versione" |
| `ui_court.py` | versione in fondo a Gestione Profilo |
| `pyproject.toml` | 1.0.0, build 10000 |
| `tools/prepara_build.py` | `versione.py`, controlli di versione e tag, rifiuta keystore |
| `tools/build_windows.ps1` | DLL con vswhere, flet-cli configurabile, `-Tag`, `-Installer` |
| `tools/build_apk.ps1` (nuovo) | build APK locale firmato dal `.env` |
| `tools/controlla_build.py` (nuovo) | firma APK, DLL x64, nessun segreto |
| `tools/installer_windows.iss` (nuovo) | installer Inno Setup |
| `tools/README_release.md` (nuovo) | keystore, segreti, rilascio passo per passo |
| `.github/workflows/release.yml` (nuovo) | build e release in bozza |
| `sql/2026-11_fase5_app_release.sql` (nuovo), `sql/schema_riferimento.sql` | `app_release` |
| `docs/istruzioni_installazione.md` (nuovo) | istruzioni per la lega |
| `.gitignore`, `.env.example` | keystore, variabili di firma locale |

Non cambiano: cron, script di amministrazione, `main.py`. Nessuna dipendenza nuova nell'app.

## 10. Ordine dei lavori, cosa fa l'utente, pubblicazione su `main`

1. (io) Codice, SQL, workflow, istruzioni; prove locali (sezione 11). Commit su `app-nativa`.
2. **Utente:** keystore e copie (sezione 2); segreti e variabile GitHub; migrazione SQL e query di verifica.
3. **Utente:** OK per il push di `app-nativa` e del tag `v1.0.0-rc.1` (non tocca `main` né Render).
4. **Utente:** disinstalla l'APK di debug, installa APK e `Bonkest-Setup.exe` della pre-release; lista di prova
   (sezione 12). Correzioni con `rc.2`, `rc.3`…
5. **Utente:** OK per portare il codice su `main` (un deploy di Render: la webapp mostra solo la versione nelle
   Impostazioni). SQL già eseguito, nessun ordine critico.
6. Tag `v1.0.0` su `main` → bozza → **utente** la pubblica → aggiorna `app_release` (snippet) → manda le istruzioni.
7. (io) Stato della fase in `docs/piano_migrazione_C1.md`, commit.

## 11. Verifiche (mie, in locale)

- `prepara_build.py`: versione/build/tag coerenti e incoerenti; `versione.py` generato; keystore rifiutato.
- `aggiornamenti.py`: confronti (1.0.0 < 1.0.10, rc, valori assenti o malformati).
- Banco di prova con server finto: RPC assente (404), `nuova`, `obbligatoria`, rete assente.
- Webapp locale nel browser integrato: login, Impostazioni con "versione web", nessuna chiamata `app_release`.
- `nativa.py` sul PC: avvio normale (build di sviluppo: nessun controllo).
- Build Windows locale con lo script nuovo e `controlla_build.py`; APK locale con la chiave di debug (`-ChiaveDebug`) per
  provare il controllo della firma (senza impronta attesa deve fallire).

## 12. Lista di prova per l'utente (pre-release)

1. Android: installazione dell'APK della pre-release (fonti sconosciute, Play Protect); accesso; versione nelle
   Impostazioni.
2. Windows: `Bonkest-Setup.exe` senza amministratore (SmartScreen), avvio dal menu Start, dati e "Ricordami".
3. Con `app_release` a `latest_version` più alta: barra "Disponibile…", "Scarica" apre il link, "×" la chiude.
4. Con `min_version` più alta: schermata bloccante; poi rimettere i valori giusti.
5. Modalità aereo: avvio dalla cache senza blocchi.
6. Aggiornamento: installare `rc.2` sopra `rc.1` (Android senza disinstallare, Windows con il nuovo setup).

## 13. Rischi

- **Perdita del keystore**: nessun aggiornamento possibile (copie di riserva, sezione 2).
- **Firma sbagliata in silenzio** (segreto mancante): bloccata da `controlla_build.py`.
- **Windows su GitHub** non ancora provato: aggiramento portabile; se fallisse, build Windows dal PC e caricamento a mano.
- **Smart App Control / Play Protect** sui dispositivi degli utenti: istruzioni; firma del codice solo se serve.
- **Verifica sviluppatori Android (2027)**: da ricontrollare prima della prossima stagione.
- **Blocco per versione minima**: un valore sbagliato blocca tutti gli utenti dell'app; si corregge dallo SQL Editor
  e la webapp resta sempre usabile.
