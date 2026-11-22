# Rilascio dell'app installata (Fase 5) — guida spiegata

Questa guida spiega **cosa fare** e **perché**, passo per passo. Il piano tecnico con le decisioni è in
`docs/fase5_piano.md`. Regola d'oro: password e keystore non vanno mai nella repository, in chat, in un'issue o in
un messaggio.

---

## 1. Il quadro generale in 30 secondi

```
 tu: tag v1.0.0  ──►  GitHub Actions compila  ──►  release in BOZZA  ──►  tu: "Publish"  ──►  tu: SQL app_release
                       (APK firmato + Setup.exe      (invisibile agli        (visibile a         (le app degli utenti
                        + zip)                        altri)                  tutti)              vedono "Disponibile…")
```

- **Tu decidi quando** esce una versione (mettendo il tag) e **quando gli utenti lo sanno** (aggiornando la riga
  sul database). In mezzo c'è sempre un momento in cui puoi provare i file senza che nessuno se ne accorga.
- Render (la webapp) non c'entra: non riparte con un tag, ma solo quando cambia `main`.

### Parole che incontrerai

| Parola | Cosa vuol dire qui |
|---|---|
| **Firma / keystore** | Il keystore è un file che contiene una chiave segreta. Con quella chiave si mette un "sigillo" sull'APK. Android installa un aggiornamento **solo se ha lo stesso sigillo** dell'app già installata: così nessun altro può spacciare un suo APK per un aggiornamento di Bonkest. |
| **Alias** | Il nome della chiave dentro il keystore (un keystore può contenerne più di una). Il nostro è `bonkest`. Non è segreto. |
| **Impronta (SHA-256)** | Un "codice fiscale" del certificato: una lunga stringa calcolata dalla chiave pubblica. Non è segreta e serve a controllare che l'APK sia firmato con la chiave giusta. |
| **Tag** | Un'etichetta con un nome (es. `v1.0.0`) attaccata a un commit preciso. "Questa è la versione 1.0.0" = "questo esatto stato del codice". |
| **GitHub Actions / workflow** | Computer di GitHub che eseguono, gratis, una lista di istruzioni scritta in un file (`.github/workflows/release.yml`). Ogni computer usato si chiama *runner* e viene cancellato alla fine. |
| **Segreto (GitHub)** | Un valore che GitHub conserva cifrato e passa al workflow, senza mai mostrarlo (neanche a te dopo averlo salvato) e senza scriverlo nei log. |
| **Variabile (GitHub)** | Come un segreto, ma visibile: per valori non riservati (l'impronta). |
| **Base64** | Un modo di trasformare un file qualsiasi in testo, perché i segreti di GitHub accettano solo testo. Il workflow lo ritrasforma nel file originale. |
| **Release** | Una pagina di GitHub con i file da scaricare di una versione. **Bozza** = visibile solo a te finché non premi "Publish". **Pre-release** = versione di prova: non è mai considerata "l'ultima" dai link di download. |
| **rc** | *Release candidate*, "candidata": `v1.0.0-rc.1` è la prima prova della 1.0.0. |
| **RPC / RLS** | Una RPC è una funzione del database che l'app può chiamare; le RLS sono le regole che impediscono all'app di leggere le tabelle direttamente. Per gli aggiornamenti l'app chiama la RPC `app_release` e non vede altro. |

---

## 2. Una volta sola: il keystore Android

### 2.1 Creare il keystore

Apri PowerShell (non serve essere nella cartella della repository) e incolla:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.bonkest"
& "$env:USERPROFILE\java\17.0.13+11\bin\keytool.exe" -genkeypair -v -storetype PKCS12 `
    -keystore "$env:USERPROFILE\.bonkest\bonkest-release.jks" -alias bonkest `
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Bonkest"
```

**Cosa fa, pezzo per pezzo:**
- `New-Item ... .bonkest`: crea la cartella `C:\Users\<tu>\.bonkest`, fuori dalla repository, così il file non può
  finire per sbaglio in un commit.
- `keytool.exe`: il programma di Java che crea chiavi. È quello installato da Flet durante la Fase 0.
- `-genkeypair`: genera una coppia di chiavi (una segreta per firmare, una pubblica che finisce nel certificato).
- `-storetype PKCS12`: il formato standard del file. Con questo formato la password del file e quella della chiave
  sono **la stessa**: una sola password da ricordare.
- `-keystore ...bonkest-release.jks`: dove salvare il file.
- `-alias bonkest`: il nome della chiave dentro il file.
- `-keyalg RSA -keysize 2048`: il tipo e la robustezza della chiave (lo standard per Android).
- `-validity 10000`: validità in giorni (circa 27 anni). Android vuole che duri a lungo: non si può "rinnovare".
- `-dname "CN=Bonkest"`: il nome scritto nel certificato. È solo un'etichetta.
- Il carattere `` ` `` a fine riga dice a PowerShell che il comando continua sulla riga dopo.

**Cosa vedrai:** chiede due volte una password (mentre scrivi non compare nulla: è normale). Sceglila lunga,
**salvala subito nel gestore di password**, poi compare un messaggio del tipo "Generazione in corso… ".

**Se va storto:**
- "keytool.exe non riconosciuto" o "percorso non trovato": la versione di Java ha un altro nome. Guarda in
  `C:\Users\<tu>\java\` e correggi il numero nel percorso.
- "il keystore esiste già": **fermati**. Esiste già una chiave: non sovrascriverla, potrebbe essere quella in uso.

### 2.2 Copie di riserva (fondamentale)

- **Perché:** senza questo file nessun utente potrà più aggiornare l'app: dovrebbero tutti disinstallarla (perdendo
  il "Ricordami") e installare una versione firmata con una chiave nuova. Non esiste un modo di recuperarlo.
- **Cosa fare:**
  1. nel gestore di password: una voce "Bonkest keystore" con la password e il file `bonkest-release.jks` allegato;
  2. una seconda copia del file su una chiavetta USB o su un cloud personale.
- I segreti di GitHub **non** sono una copia di riserva: GitHub non permette di riscaricarli.

### 2.3 Leggere l'impronta del certificato

```powershell
& "$env:USERPROFILE\java\17.0.13+11\bin\keytool.exe" -list -v -keystore "$env:USERPROFILE\.bonkest\bonkest-release.jks" -alias bonkest
```

- `-list -v`: mostra il contenuto del keystore in modo dettagliato (*verbose*).
- **Cosa vedrai:** chiede la password, poi tra le righe una che inizia con `SHA256:` seguita da coppie di caratteri
  separate da due punti (es. `AB:CD:12:…`). Copia **tutta** quella sequenza: serve al punto 2.4 e nel `.env`.
- Non è un segreto: è ciò che permette al workflow di accorgersi se un APK è stato firmato con la chiave sbagliata.

### 2.4 Segreti e variabile su GitHub (dal sito)

**Perché:** il workflow gira sui computer di GitHub, che non vedono il tuo PC. Per firmare l'APK lì sopra devono
avere il keystore e la password: glieli dai come segreti, che restano cifrati e non compaiono mai nei log.

1. Copia il keystore negli appunti, già trasformato in testo (base64):
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:USERPROFILE\.bonkest\bonkest-release.jks")) | Set-Clipboard
   ```
   - `ReadAllBytes`: legge il file così com'è; `ToBase64String`: lo trasforma in testo; `Set-Clipboard`: lo mette
     negli appunti senza mostrarlo a schermo né salvarlo in un file.
2. Sul sito: repository **NewFantaNBA → Settings → Secrets and variables → Actions**.
3. Scheda **Secrets → New repository secret**, tre volte:
   | Nome | Valore |
   |---|---|
   | `ANDROID_KEYSTORE_BASE64` | incolla (Ctrl+V) il testo copiato al punto 1: è lunghissimo, è normale |
   | `ANDROID_KEYSTORE_PASSWORD` | la password scelta al punto 2.1 |
   | `ANDROID_KEY_ALIAS` | `bonkest` |
4. Scheda **Variables → New repository variable**: nome `ANDROID_CERT_SHA256`, valore l'impronta del punto 2.3.
5. Svuota gli appunti copiando qualcos'altro (il keystore in base64 non deve restare lì).

**Se va storto:** se sbagli un valore, nella stessa pagina c'è "Update" per sostituirlo. Se il workflow fallisce con
"Segreto ANDROID_KEYSTORE_BASE64 mancante" o "NON è firmato con la chiave attesa", ricontrolla nomi e valori.

### 2.5 Build sul PC firmati con la chiave vera (facoltativo)

Nel file `.env` della repository (non è versionato: non finisce mai su GitHub) aggiungi:

```
ANDROID_KEYSTORE_PATH=C:\Users\<tu>\.bonkest\bonkest-release.jks
ANDROID_KEYSTORE_PASSWORD=<la password>
ANDROID_KEY_ALIAS=bonkest
ANDROID_CERT_SHA256=<l'impronta>
```

- **Perché:** così un APK compilato sul PC ha lo stesso sigillo di quelli di GitHub, e puoi installarli uno sopra
  l'altro senza disinstallare.
- **Attenzione:** un APK firmato così è "ufficiale" a tutti gli effetti: non mandarlo in giro per sbaglio.

---

## 3. Ogni rilascio

### 3.1 Scegliere il numero di versione

In `pyproject.toml`:
```
version = "1.0.1"
build_number = 10001
```
- **Regola:** `X.Y.Z` → `build_number = X*10000 + Y*100 + Z` (1.0.0 → 10000, 1.0.1 → 10001, 1.2.0 → 10200).
- **Perché due numeri:** `version` è quello che vedono le persone; `build_number` è quello che usa Android per
  capire se un APK è più nuovo. Android **rifiuta** un aggiornamento con un numero più basso di quello installato.
  La formula garantisce che cresca sempre insieme alla versione.
- Come scegliere: Z (1.0.**1**) per correzioni, Y (1.**1**.0) per novità, X per cambiamenti grossi.
- **Verifica:** `python tools/prepara_build.py` stampa "versione X.Y.Z (build N)" oppure un ERRORE che dice cosa
  non torna.

### 3.2 Prova: tag `-rc` sul branch di lavoro

**Il numero del tag deve essere identico a `version` di `pyproject.toml`** (più `-rc.N`). Esempio con
`version = "1.0.0"` (la prima versione):

```
git tag v1.0.0-rc.1
git push origin v1.0.0-rc.1
```
Se i numeri non coincidono il workflow si ferma subito con "il tag … non corrisponde alla versione …": è il
controllo che evita di pubblicare un'app con il numero sbagliato. In quel caso cancella il tag sbagliato (vedi
"Cancellare un tag sbagliato" in fondo alla sezione 3) e rifallo con il numero giusto.

- `git tag`: attacca l'etichetta all'ultimo commit del branch su cui sei.
- `git push origin <tag>`: manda **solo l'etichetta** su GitHub (e il commit a cui punta). Questo fa partire il
  workflow "Rilascio app". `main` e Render non vengono toccati.
- **Cosa vedrai:** su GitHub → **Actions** compare un'esecuzione "Rilascio app" con tre blocchi: `android` e
  `windows` lavorano in parallelo (20–30 minuti la prima volta, meno dopo grazie alla cache), poi `release`.
  Alla fine in **Releases** trovi una bozza contrassegnata "Pre-release" con `bonkest.apk`, `Bonkest-Setup.exe`,
  `bonkest-windows.zip` e `SHA256SUMS.txt`.
- **Se va storto:** clicca sul blocco rosso e poi sul passaggio fallito per leggere l'errore (o passami il testo).
  Corretto il problema si fa una nuova prova con `rc.2`.

### 3.2-bis Provare la pre-release sui propri dispositivi

**Perché:** prima che la versione arrivi alla lega, la provi tu dove la useranno gli altri. Finché la release è in
bozza nessuno la vede, quindi puoi provare e rifare (`rc.N+1`) quante volte serve.

1. **Scaricare i file.** GitHub → **Releases** (colonna destra della pagina della repository, o
   `…/NewFantaNBA/releases`). La bozza compare **solo se hai fatto l'accesso** con il tuo account: apri la bozza e
   in fondo, sotto **Assets**, ci sono i file.
   - Telefono: il modo più semplice è aprire la pagina dal browser del telefono con l'accesso a GitHub e toccare
     `bonkest.apk`. In alternativa scaricalo sul PC e passalo al telefono (cavo USB, o mandalo a te stesso via
     email/Drive).
   - PC: scarica `Bonkest-Setup.exe` (e, se vuoi provarlo, `bonkest-windows.zip`).
2. **Solo la prima volta:** disinstalla dal telefono la vecchia app di prova (firmata con la chiave di debug),
   altrimenti Android rifiuta l'installazione ("conflitto con un pacchetto esistente"). Su Windows non serve:
   l'installer non tocca la vecchia cartella `build\windows`, che puoi cancellare quando vuoi.
3. **Installa** seguendo `docs/istruzioni_installazione.md`, come farebbe un utente della lega (è anche il modo per
   controllare che le istruzioni siano chiare).
4. **Lista di prova** (sezione 12 di `docs/fase5_piano.md`):
   - accesso, versione in fondo a Impostazioni → Gestione Profilo ("Bonkest 1.0.0 (rc.N)");
   - Windows: installazione senza diritti di amministratore, avvio dal menu Start, "Ricordami";
   - **barra "nuova versione"**: nello SQL Editor
     `update public.app_release set latest_version = '1.0.1' where platform = 'android';` → riapri l'app: compare
     "Disponibile la versione 1.0.1"; "Scarica" apre il link (darà "non trovato" finché la release non è
     pubblicata: è normale); "×" la chiude. Stessa cosa con `platform = 'windows'`.
   - **blocco**: `update public.app_release set min_version = '9.0.0' where platform = 'android';` → riapri:
     schermata "Aggiornamento necessario", nessun accesso.
   - **rimetti i valori di partenza** (importante!):
     `update public.app_release set latest_version = '0.0.0', min_version = '0.0.0', updated_at = now();`
   - modalità aereo: l'app si apre dalla cache, senza blocchi;
   - aggiornamento: alla prossima `rc` installala **sopra** questa, senza disinstallare: accesso e dati restano.
   - Richiede la migrazione `sql/2026-11_fase5_app_release.sql` già eseguita.

**Se qualcosa non va:** annota cosa hai fatto e cosa vedi (uno screenshot aiuta); si corregge e si prova con la
`rc` successiva.

### 3.3 Rilascio vero

Dopo che il codice è su `main` (con il tuo OK):
```
git checkout main
git pull
git tag v1.0.1
git push origin v1.0.1
```
- `checkout` + `pull`: ti metti su `main` aggiornato, così il tag punta al codice che è davvero in produzione.
- Il resto come al punto 3.2; la release è in bozza ma **non** pre-release.

### 3.4 Pubblicare la bozza

GitHub → **Releases** → la bozza → **Edit** → controlla i file → **Publish release**.
- Da questo momento il link `…/releases/latest/download/bonkest.apk` porta alla nuova versione.
- Prima di pubblicare puoi scaricare e installare i file sui tuoi dispositivi: nessun altro li vede.

### 3.5 Avvisare le app

Nello SQL Editor di Supabase:
```sql
update public.app_release set latest_version = '1.0.1', updated_at = now();
```
- **Cosa fa:** scrive "l'ultima versione è la 1.0.1" per Android e Windows. Al prossimo avvio le app più vecchie
  mostrano la barra "Disponibile la versione 1.0.1".
- **Perché a mano:** decidi tu quando gli utenti lo vengono a sapere, dopo aver provato.
- **Versione minima** (`min_version`): alzala solo quando le versioni vecchie *non devono* più funzionare (es. dopo
  un cambio del database che le romperebbe). Un valore sbagliato blocca tutti gli utenti dell'app; si rimedia
  rieseguendo l'`update` con il valore giusto, e intanto la webapp funziona sempre.

### 3.6 Avvisare la lega

Messaggio con il link https://github.com/vittobonaz-coder/NewFantaNBA/releases/latest — la pagina contiene già le
istruzioni di installazione (`docs/istruzioni_installazione.md`).

### Cancellare un tag sbagliato

```
git tag -d v1.0.1-rc.1
git push origin --delete v1.0.1-rc.1
```
- `git tag -d`: toglie l'etichetta dal tuo PC; `git push origin --delete`: la toglie da GitHub. Il codice non
  cambia: sparisce solo l'etichetta.
- Se il workflow aveva già creato una bozza per quel tag, cancellala da Releases.

### Rifare un rilascio sullo stesso tag

Se il workflow fallisce a metà o va ripetuto: cancella l'eventuale bozza su GitHub (Releases → bozza → Delete), poi
Actions → "Rilascio app" → **Run workflow** e scrivi il tag. (Questo pulsante compare solo quando il workflow è su
`main`; prima, si fa una nuova `rc`.)

---

## 4. Build sul PC

- **Windows:** `powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1 [-Tag vX.Y.Z] [-Installer]`
  - `-ExecutionPolicy Bypass`: permette a PowerShell di eseguire lo script (Windows di base lo impedisce);
  - `-Tag`: controlla che il tag corrisponda alla versione;
  - `-Installer`: crea anche `Bonkest-Setup.exe` e lo zip in `build\dist` (serve Inno Setup 6 installato).
  - Risultato: la cartella `build\windows` con `bonkest.exe`.
- **Android:** `powershell -ExecutionPolicy Bypass -File tools\build_apk.ps1 [-Tag vX.Y.Z] [-ChiaveDebug]`
  - firma con la chiave del `.env` (punto 2.5); senza, si ferma e lo dice;
  - `-ChiaveDebug`: firma con la chiave di prova del PC. Quell'APK **non** si installa sopra le versioni vere:
    serve prima disinstallare l'app.
  - Risultato: `build\apk\bonkest.apk`.

---

## 5. I file della Fase 5, spiegati

Come si collegano:
```
pyproject.toml ──(versione)──► tools/prepara_build.py ──► app_src/ (con versione.py) ──► flet build
                                                                                          │
                       tools/build_apk.ps1 / tools/build_windows.ps1 ◄────────────────────┘ (lo lanciano)
                                       │
                                       ▼
                         tools/controlla_build.py  (firma giusta? niente segreti? 64 bit?)
                                       │
                 .github/workflows/release.yml (fa tutto questo su GitHub e crea la bozza)

All'avvio dell'app installata:  nativa.py ──► supabase_rest.warm_up ──► RPC app_release (database)
                                app.py ──► aggiornamenti.esito ──► schermata bloccante / barra / niente
```

| File | A cosa serve | Quando lo tocchi |
|---|---|---|
| `pyproject.toml` | Nome, versione e numero di build dell'app installata: Flet li legge durante il build | A ogni rilascio (punto 3.1) |
| `versione.py` | Dice all'app che versione è. Nella repository vale "nessuna versione" (webapp e sviluppo: nessun controllo aggiornamenti); nel build viene riscritto con i valori veri | Mai a mano |
| `tools/prepara_build.py` | Prepara la cartella `app_src/` con **solo** i file ammessi (mai `.env`, dati o chiavi), controlla versione e tag, scrive `versione.py` | Se aggiungi un modulo all'app (lista `APP_MODULES`) |
| `tools/build_windows.ps1` | Build Windows uguale sul PC e su GitHub. Contiene l'aggiramento del problema di CMake: fornisce a serious_python i tre file di sistema a 64 bit giusti | Raramente |
| `tools/build_apk.ps1` | Build Android sul PC, firmato con la chiave del `.env` | Mai, lo lanci soltanto |
| `tools/controlla_build.py` | Il "controllore" prima della distribuzione: firma dell'APK confrontata con l'impronta, nessuna password o chiave dentro i pacchetti (anche negli zip annidati), exe e DLL Windows a 64 bit | Se cambia cosa va controllato |
| `tools/installer_windows.iss` | Ricetta per Inno Setup (programma gratuito che crea i `Setup.exe`): installa per il solo utente in `%LOCALAPPDATA%\Programs\Bonkest`, crea il collegamento nel menu Start, sostituisce la versione precedente. Il valore `AppId` non va mai cambiato: è ciò con cui Windows riconosce l'installazione precedente | Quasi mai |
| `.github/workflows/release.yml` | Le istruzioni per GitHub Actions: tre lavori (android, windows, release). Il keystore viene ricostruito dal segreto solo per la durata del lavoro e poi cancellato | Se cambia il processo di rilascio |
| `aggiornamenti.py` | Confronta la versione installata con quella del database: "ok", "nuova" o "obbligatoria". Nel dubbio (dati mancanti o strani) risponde "ok": meglio non bloccare nessuno per errore | Raramente |
| `supabase_rest.py` (`warm_up`, `release_info`) | All'avvio, mentre Flet si carica, apre la connessione con Supabase e intanto chiede `app_release`: il controllo non aggiunge attese | Raramente |
| `app.py` (`check_updates` e dintorni) | Mostra la schermata "Aggiornamento necessario" o la barra "Disponibile la versione …" | Se vuoi cambiare testi o comportamento |
| `sql/2026-11_fase5_app_release.sql` | Crea la tabella `app_release` (una riga per Android, una per Windows) e la funzione che l'app chiama. In fondo: verifiche, comandi da usare a ogni rilascio, rollback | Una volta (esecuzione), poi solo gli snippet in fondo |
| `docs/istruzioni_installazione.md` | Il testo per la lega; diventa anche la descrizione di ogni release su GitHub | Se cambiano le istruzioni |
| `.gitignore` | Impedisce a git di includere file `.jks`, `.keystore`, `.b64`… anche per sbaglio | Mai |
