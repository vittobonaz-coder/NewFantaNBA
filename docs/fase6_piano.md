# Fase 6 — iOS e dismissione di Render: piano (in attesa di OK)

**A cosa serve questo file:** è il piano della Fase 6 (`docs/piano_migrazione_C1.md`, sezione "Fase 6"). Contiene
le verifiche fatte, le opzioni con costi e conseguenze, e le decisioni aperte. Le decisioni prese andranno in cima.

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
- **Non abbiamo misure di Render:** non so quanto aspetta oggi chi apre la webapp col server addormentato
  (l'ordine di grandezza su Render Free è 30-60 s, ma va misurato).

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

1. B3: misura del risveglio di Render (tu apri la webapp dopo 20 minuti di inattività, io ti do il cronometro
   da seguire; oppure misuro io dal browser integrato).
2. B2: migrazione SQL `sql/2026-11_fase6_piattaforma_login.sql` (parametro facoltativo, compatibile con webapp e
   app 1.0.0 già distribuite) + invio della piattaforma da app e webapp + query per vedere chi usa cosa.
3. B1: barra "C'è l'app" nella webapp per Android/PC (chiudibile, una volta per sessione).
4. Report iOS (questo documento, sezione 2) come conclusione della parte A.
5. Verifiche: webapp da browser PC e da browser Android (barra presente), webapp simulata iOS (barra assente),
   app nativa Android e Windows invariata. Rilascio: B1 e B2 lato web vanno su `main` (Render); lato app
   arrivano con la prossima versione (1.0.1) seguendo `tools/README_release.md`.

## 6. Decisioni aperte

1. **iPhone:** A0 (nessuna app, proposta), A1 TestFlight, A2 Store non in elenco, A3 Ad Hoc? Quanti utenti della
   lega hanno l'iPhone? Sei disposto a spendere 99 €/anno?
2. **Render:** B1 + B2 + B3 (proposta)? Oppure lasciare tutto com'è (fase chiusa col solo report)?
3. **B2, cosa salvare:** solo piattaforma e versione (proposta), oppure anche data dell'ultimo accesso per utente?
4. **B4 (Render a pagamento):** da decidere solo dopo la misura B3.
5. **Ordine con Flet e migrazione 2C:** proposta: Fase 6 (B1-B3) → migrazione 2C → aggiornamento di Flet →
   eventuale app iOS.

## 7. Cosa devi fare tu (dopo l'OK)

- Rispondere alle decisioni sopra.
- Per B2: eseguire la migrazione nello SQL Editor, quando te la preparo.
- Dare l'OK al passaggio su `main` (deploy Render) per B1/B2 lato web.
- Per B3: se vuoi misurare tu dal telefono, aprire la webapp dopo 20 minuti di inattività con un cronometro.

## 8. Rischi

- B2 cambia la firma di `login_bundle`/`token_bundle`: va fatto con un parametro facoltativo, altrimenti le app
  1.0.0 già installate smettono di accedere. Lo verifico su Postgres usa e getta come nelle fasi precedenti.
- Prezzi e regole Apple e Render cambiano: vanno ricontrollati sui siti ufficiali al momento di spendere.
