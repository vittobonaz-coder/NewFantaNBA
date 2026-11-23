# Fase 6 — iOS e dismissione di Render: piano (conclusa il 23/11/2026; app Mac aggiunta dopo)

**A cosa serve questo file:** è il piano della Fase 6 (`docs/piano_migrazione_C1.md`, sezione "Fase 6"). Contiene
le verifiche fatte, le opzioni con costi e conseguenze, e le decisioni aperte. Le decisioni prese andranno in cima.

## Decisioni prese

- **23/11/2026 — nessuna spesa**, né per Apple né per Render: escluse A1, A2, A3 (tutte richiedono l'account
  sviluppatore Apple) e B4. Niente app per iPhone: chi ha l'iPhone usa la webapp (A0).
- Nella lega gli utenti con l'iPhone sono 2, **entrambi hanno anche un PC**: uno Windows (può già usare l'app
  Windows), uno Mac (vedi A5).
- **23/11/2026 — approvate B1, B2, B3.** B2 salva anche ultimo accesso e numero di aperture (costa niente).
  **App Mac (A5) per ora no:** si può aggiungere più tardi senza toccare il resto (un job in più nel workflow),
  dopo aver saputo che versione di macOS ha l'utente col Mac (serve almeno 11 Big Sur).

La fase è **facoltativa** e il piano originale la descrive così:
- **iOS:** solo un report su cosa servirebbe (Mac, account Apple, TestFlight), **nessuna implementazione**;
- **Render:** quando gli utenti Android/PC sono passati all'app, ridurre il carico della webapp **senza toglierla**
  a chi ha l'iPhone.

## 1. Cosa ho verificato

- **Il pacchetto iPhone si costruisce solo su macOS.** In flet-cli 0.82 (`flet_cli/commands/build_base.py`) i
  formati `ipa` (app per iPhone) e `ios-simulator` hanno `can_be_run_on: ["Darwin"]`, cioè solo Mac. Da questo PC
  Windows non si può. Si può però usare una macchina macOS di **GitHub Actions** (gratuita per le repository
  pubbliche, come la nostra), come facciamo già per Windows e Android.
- **Firma iOS in flet:** servono `--ios-team-id` (codice del tuo account sviluppatore), un *provisioning profile*
  (file di Apple che dice "questa app, firmata da questo sviluppatore, può girare su questi iPhone / essere
  distribuita così") e un *certificato di firma* (l'equivalente Apple del nostro keystore Android). Senza
  provisioning profile flet produce solo un archivio Xcode, non un'app installabile.
- **Il nostro codice è quasi pronto per iOS:** stesso Python, `httpx` funziona anche lì. Andrebbero adattati:
  `aggiornamenti.piattaforma()` (oggi riconosce solo "android" e "windows"), il vincolo della tabella
  `app_release` (stesso limite), `app_paths` (cartella dati su iOS) e i margini dello schermo (notch). Nessuna di
  queste è difficile; non le tocco senza decisione.
- **La webapp sa da che sistema la apri:** in Flet web `page.platform` è il sistema del browser (Android, iOS,
  Windows…), e `page.web` è vero. Quindi la webapp può riconoscere chi la apre da Android o da PC e suggerirgli
  l'app.
- **"Webapp senza server" (Python nel browser, `flet build web`) oggi non funzionerebbe col nostro codice:**
  in quella modalità Python gira nel browser con *Pyodide* (Python compilato per il browser), dove non ci sono
  thread né connessioni di rete "normali". Noi usiamo `httpx.Client` sincrono con thread (`asyncio.to_thread`,
  `run_parallel`): andrebbe riscritto lo strato di rete. Ipotesi da verificare con una prova, non una certezza.
- **Misura di Render (B3, 23/11):** prima risposta della pagina con il server addormentato **22,9 s**; da sveglio
  0,24-0,32 s (`curl` dal PC, solo la pagina HTML: poi il browser scarica il client Flutter, già in cache dalla
  seconda volta, e fa l'accesso). Chi apre la webapp dopo 15 minuti di inattività aspetta quindi ~25 s in più.

## 2. Parte A — iPhone

### Cosa servirebbe in ogni caso per un'app iOS vera

1. **Apple Developer Program:** 99 €/anno (circa). Senza, un'app installata da te scade dopo 7 giorni e va
   reinstallata col cavo da un Mac: inutilizzabile per la lega.
2. **Un iPhone per le prove** (il tuo o di un amico della lega). Il simulatore iPhone esiste solo su Mac.
3. **Build su GitHub Actions (macOS)** con certificato e provisioning profile nei segreti, come il keystore.
   Il certificato si può creare anche da Windows (richiesta generata con `openssl`, caricata sul sito Apple).
4. **Un modo di distribuirla** (vedi opzioni sotto). Su iPhone non esiste l'equivalente dell'APK: non si può
   mandare un file da installare.

### Opzioni

| | Cosa vuol dire in pratica | Costo | Pro | Contro |
|---|---|---|---|---|
| **A0. Nessuna app iOS** (proposta per ora) | Chi ha l'iPhone usa la webapp; consiglio "Aggiungi alla schermata Home" da Safari | 0 | Niente da mantenere | Resta l'attesa di Render e la lentezza del web |
| **A1. TestFlight** | App "Apple per le beta": gli amici installano TestFlight, tu mandi un link | 99 €/anno | Fino a 10.000 persone, niente UDID, aggiornamenti comodi | **Ogni build scade dopo 90 giorni**: almeno un rilascio ogni 3 mesi; prima pubblicazione revisionata da Apple (in genere 1 giorno) |
| **A2. App Store "non in elenco"** | App vera sullo Store, trovabile solo col link | 99 €/anno | Nessuna scadenza | Revisione completa: account di prova per Apple, privacy policy, rischio di rifiuto per "app per pochi"; più lavoro a ogni versione |
| **A3. Ad Hoc** | App firmata per una lista di iPhone precisi | 99 €/anno | Niente revisione | Serve l'identificativo (UDID) di ogni iPhone; nuovo telefono = nuovo build; installazione scomoda |

Esempio concreto per A1: rilasci la 1.1.0 a dicembre; se non esce nulla di nuovo fino a marzo, a inizio marzo
devi rifare un build (stesso codice, numero nuovo) e caricarlo, altrimenti agli iPhone l'app smette di aprirsi.

**A5. App per Mac, gratuita (aggiunta il 23/11):** `flet build macos` gira su una macchina macOS di GitHub
Actions, gratis. Senza account a pagamento l'app non è "notarizzata" (controllata da Apple): al primo avvio macOS
la blocca e va sbloccata una volta da Impostazioni di Sistema → Privacy e sicurezza → "Apri comunque" (come
"Esegui comunque" di SmartScreen su Windows). Contro: non posso provarla io (serve un Mac), le prove le farebbe
l'utente col Mac; un job in più nel workflow (~10 min) e un file in più in ogni release; Mac non è piattaforma
obbligatoria. Da verificare: che il build funzioni sui Mac Apple Silicon e Intel.
**Versione minima: macOS 11 Big Sur** (il modello di progetto di flet 0.82 fissa `MACOSX_DEPLOYMENT_TARGET = 11.0`,
visto in `build/flutter/macos/`). Big Sur gira sui Mac dal 2013-2014 in poi (MacBook Air/Pro fine 2013, iMac e
Mac mini 2014). Sotto Big Sur l'app non si apre: resta la webapp. Un futuro aggiornamento di Flet potrebbe alzare
il minimo.

**Proposta:** A0 adesso. Se la lentezza della webapp pesa davvero agli utenti iPhone, A1 come fase a sé, con un
amico con iPhone disponibile per le prove.

## 3. Parte B — Render e webapp

Oggi: Render Free, 0,1 CPU, si addormenta dopo 15 minuti, costo 0. Chi ha l'iPhone (e chiunque come riserva) la
usa dal browser.

| | Cosa vuol dire | Costo | Pro | Contro |
|---|---|---|---|---|
| **B1. Invito all'app nella webapp** (proposta) | Chi apre la webapp da Android o PC vede una barra "C'è l'app Bonkest" con il link alle Release | 0 | Sposta gli utenti verso l'app: meno carico su Render | Piccola modifica a `app.py`, va su `main` |
| **B2. Sapere chi usa cosa** (proposta) | Al login l'app manda piattaforma e versione ("web/ios", "android 1.0.0"…), salvate col token | 0 | Sai quando tutti sono passati all'app, chi ha versioni vecchie prima di alzare `min_version` | Migrazione SQL (nuovo parametro facoltativo, compatibile) |
| **B3. Misura del risveglio** (proposta) | Cronometro l'apertura della webapp col server addormentato e sveglio | 0 | Decidi su numeri veri | — |
| B4. Render a pagamento | Piano che non si addormenta | ~7 $/mese (da ricontrollare) | Niente attesa | Costo fisso |
| B5. Webapp statica (Python nel browser) | `flet build web` su GitHub Pages, niente server | 0 | Render eliminabile | Riscrittura dello strato di rete, primo caricamento pesante, rischio alto: solo dopo una prova |

"Ridurre il carico" con B1+B2: Render resta identico, ma lo usano solo gli iPhone e chi è fuori casa. Il server
si addormenta di più ma costa zero; il problema vero per gli iPhone resta l'attesa del risveglio (B3 la misura).

## 4. Cose rimandate "a dopo la migrazione" (non sono Fase 6, ma vanno messe in fila)

- **Migrazione 2C** (togliere `login`, `login_with_token` e la lettura diretta delle tabelle con la chiave
  pubblica). B2 aiuta: prima di farla sai se qualcuno usa ancora versioni vecchie.
- **Aggiornamento di Flet** (0.83 o l'ultima) con prova separata, poi via `flet_fix.py`. Utile farlo **prima**
  di un'eventuale app iOS (A1), per non costruirla su una versione da cambiare subito dopo.

## 5. Proposta di lavoro (se approvi)

1. B3: misura del risveglio di Render (fatta da me con `curl`, vedi sezione 1).
2. B2: migrazione SQL `sql/2026-11_fase6_client_usage.sql` (parametro facoltativo, compatibile con webapp e
   app 1.0.0 già distribuite) + invio della piattaforma da app e webapp + query per vedere chi usa cosa.
3. B1: barra "C'è l'app" nella webapp per Android/PC (chiudibile, una volta per sessione).
4. Report iOS (questo documento, sezione 2) come conclusione della parte A.
5. Verifiche: webapp da browser PC e da browser Android (barra presente), webapp simulata iOS (barra assente),
   app nativa Android e Windows invariata. Rilascio: B1 e B2 lato web vanno su `main` (Render); lato app
   arrivano con la prossima versione (1.0.1) seguendo `tools/README_release.md`.

## 6. Decisioni aperte

1. ~~iPhone~~: deciso A0 (nessuna spesa). **Mac (A5):** rimandata, in attesa della versione di macOS dell'utente.
2. ~~Render~~: approvate B1 + B2 + B3.
3. ~~B2, cosa salvare~~: piattaforma, versione, primo e ultimo accesso, numero di aperture.
4. ~~B4 (Render a pagamento)~~: escluso (nessuna spesa). B3 resta utile per sapere quanto aspettano gli iPhone.
5. **Ordine con Flet e migrazione 2C:** proposta: Fase 6 (B1-B3) → migrazione 2C → aggiornamento di Flet →
   eventuale app iOS.

## 7. Fatto e verificato (23/11)

**File nuovi o cambiati e come si collegano:**
- `sql/2026-11_fase6_client_usage.sql` (nuovo): tabella `client_usage` e nuove firme di `login_bundle` /
  `token_bundle` con `p_client`; in fondo le query "chi usa cosa" da lanciare nello SQL Editor e il rollback.
- `aggiornamenti.py`: `client_info()` decide il nome del client (`web-ios`, `android`…) da `page.web`,
  `page.platform` e `versione.VERSIONE`.
- `supabase_rest.py`: `login_bundle` / `token_bundle` accettano `client`; `_bundle_rpc` lo manda come `p_client`
  e, se il database non ha ancora la migrazione (risposta 404 PGRST202), ripete senza e smette di mandarlo
  finché il processo non riparte. Così l'ordine tra deploy e SQL non conta.
- `app.py`: calcola `client` una volta per pagina e lo passa a login e accesso automatico (non agli aggiornamenti
  silenziosi: `accessi` conta le aperture); barra "Bonkest c'è anche come app per Android/Windows" con "Scopri"
  (link alla pagina delle Release, con le istruzioni) e ×, solo nella webapp aperta da Android o Windows.
  La barra degli aggiornamenti (Fase 5) e la nuova usano lo stesso `closable_bar`.
- `ui_court.py`: `LoginView` riceve `client` e lo passa a `login_bundle`.
- `sql/schema_riferimento.sql` (sezione FASE 6), `tools/misura_login.py` (nota: ora conta un accesso).

**Verifiche:**
- migrazione su Postgres usa e getta (funzioni della Fase 2 simulate): eseguita 2 volte; una sola funzione per
  nome; chiamata senza `p_client` (app 1.0.0) funziona e registra `non-indicato`; con `p_client` registra client e
  versione e aggiorna la riga; credenziali errate o token falso: nulla registrato; client/versione non validi non
  bloccano l'accesso (`non-valido`); anon non legge la tabella né chiama `private.record_client`; query "versioni
  vecchie" corretta; rollback eseguibile;
- `_bundle_rpc` contro un server finto: database senza `p_client` → una sola chiamata fallita poi senza; con
  `p_client` → mandato; un errore 500 non viene nascosto;
- webapp in locale (banco come Render, accesso simulato): browser Windows → barra "per Windows" e client
  `web-windows`, la × la chiude; Android simulato → barra "per Android", `web-android`; iPhone simulato → nessuna
  barra, `web-ios`;
- **non verificato sui dispositivi:** l'app installata manda `android`/`windows` con la versione solo dalla
  prossima release (1.0.1); va controllato allora, con la query della migrazione, dopo averla aperta su telefono e PC.

## 8. Cosa devi fare tu, in ordine

1. **Eseguire la migrazione** `sql/2026-11_fase6_client_usage.sql` nello SQL Editor (tutto il file; le parti
   commentate in fondo no). Poi la verifica 1 in fondo al file: devono uscire 2 righe con `p_client` nella firma.
2. **OK per portare `app-nativa` su `main`** (deploy Render): la webapp manda il client e mostra la barra.
3. Dopo il deploy: aprire la webapp dal PC (barra "per Windows"), poi nello SQL Editor la query "Per utente"
   della migrazione: deve comparire una riga `web-windows` per te.
4. Quando vuoi (non urgente): rilascio 1.0.1 con `tools/README_release.md` (sezione 3), così anche le app
   installate mandano piattaforma e versione.

## 9. Rischi

- Se la migrazione si esegue **dopo** il deploy, la webapp si accorge che `p_client` manca e smette di mandarlo
  fino al riavvio del processo su Render (succede da solo quando il server si addormenta, dopo 15 minuti).
- Le statistiche sono indicative: `accessi` conta le aperture, non il tempo d'uso; chi resta sempre con la stessa
  pagina aperta conta una volta.
- Prezzi e regole Apple e Render cambiano: vanno ricontrollati sui siti ufficiali se un giorno si volesse spendere.

## 10. App per Mac (A5), aggiunta il 23/11

**Decisione:** l'utente col Mac ha macOS 12 Monterey (12.7.6): sopra il minimo (11 Big Sur), quindi si fa.
L'aggiornamento di Flet resta rimandato (da ricordare).

**Cosa ho fatto:**
- `.github/workflows/release.yml`: job `macos` su una macchina macOS di GitHub (`macos-15`): `prepara_build.py`,
  `flet build macos`, controllo, zip con `ditto` (strumento di macOS che conserva link e permessi dentro la
  `.app`), file `Bonkest-macOS.zip` nella release. **Facoltativo:** se fallisce, la release esce lo stesso con
  Android e Windows (con un avviso), perché il Mac non è una piattaforma obbligatoria.
- `tools/controlla_build.py macos`: legge l'intestazione di ogni eseguibile e libreria Mac (formato *Mach-O*) e
  controlla che sia "universale", cioè contenga sia la versione Intel (x86_64) sia quella Apple Silicon (arm64):
  non sappiamo che processore ha il Mac dell'amico, e Monterey gira su entrambi. Più il solito controllo dei segreti.
- `aggiornamenti.py`: piattaforma `macos` per il controllo aggiornamenti; `sql/2026-11_fase6_app_release_macos.sql`
  aggiunge la riga `macos` ad `app_release` (vincolo allargato, solo aggiunte).
- `app.py`: la barra "C'è l'app" compare anche nella webapp aperta da Mac ("per Mac").
- `docs/istruzioni_installazione.md`: sezione Mac (trascinare in Applicazioni, primo avvio con clic destro → Apri,
  rimedio per "app danneggiata"); `tools/README_release.md`: quattro blocchi, zip da passare all'amico.

**Verifiche:** migrazione su Postgres usa e getta (riga macos, `ios` rifiutata, rollback); controllo Mach-O con
file di prova (trova una libreria solo arm64 e un segreto, passa con file universali); YAML del workflow letto
correttamente. Il build vero: prova `v1.0.0-rc.5` su GitHub (esito sotto). L'avvio sul Mac lo può provare solo
l'amico.

**Prove su GitHub (23-24/11):**
- `rc.5`: la macchina `macos-14` non esiste più su GitHub → `macos-15`. La release è uscita lo stesso senza il file
  Mac (verificato che il Mac è davvero facoltativo).
- `rc.6`-`rc.9`: build fallito senza messaggio leggibile (log visibili solo con l'accesso). Aggiunto
  `tools/esegui_con_log.py`: esegue i comandi e, se uno fallisce, mette le righe utili in un'annotazione e nel
  riepilogo. `rc.10`: l'annotazione mostra la causa: `connectivity_plus` 7.3.1 (componente di flet per lo stato
  della connessione) usa un'API di macOS 26 (`NWPath.isUltraConstrained`) che con Xcode 16.4, predefinito sulla
  macchina, non compila.
- **`rc.11`: tutto verde.** Il workflow sceglie l'Xcode più recente installato (passo "Scelta di Xcode", si ferma
  se è più vecchio della 26). `controlla_build.py macos` superato: tutti gli eseguibili e le librerie sono
  universali (Intel + Apple Silicon). L'app resta per macOS 11+: l'API nuova si usa solo se c'è macOS 26.

**Da fare da parte tua, in ordine:**
1. Eseguire `sql/2026-11_fase6_app_release_macos.sql` nello SQL Editor (aggiunge la riga `macos`).
2. Releases → bozza `v1.0.0-rc.11` → scaricare `Bonkest-macOS.zip` e mandarlo all'amico col Mac con la sezione
   "Mac" di `docs/istruzioni_installazione.md`. Prove sue: si apre (clic destro → Apri), accesso con "Ricordami",
   in Impostazioni "Bonkest 1.0.0 (rc.11)", cambio formazione e salvataggio, chiusura e riapertura (entra da
   solo), finestra ridimensionabile.
3. Cancellare le bozze `rc.5`-`rc.10` (e poi la `rc.11`).
4. Se le prove vanno bene: rilascio vero `1.0.1` (`tools/README_release.md`, sezione 3) con le tre app, poi OK
   per `main` (la webapp mostra la barra "per Mac" solo dopo, quando il file Mac è nella release pubblicata).
