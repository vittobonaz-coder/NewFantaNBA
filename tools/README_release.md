# Rilascio dell'app installata (Fase 5)

Piano e motivazioni: `docs/fase5_piano.md`. Qui solo i comandi, in ordine. Non incollare mai password o keystore
in file della repository, in chat o in issue.

## Una volta sola: keystore Android

Il keystore è il file con la chiave che firma l'APK. Android installa un aggiornamento solo se è firmato con la
stessa chiave: **se lo perdi, nessuno potrà più aggiornare l'app** (tutti dovrebbero disinstallarla).

1. Crealo (PowerShell). `keytool` chiede la password due volte: sceglila tu e salvala nel gestore di password.
   ```
   New-Item -ItemType Directory -Force "$env:USERPROFILE\.bonkest"
   & "$env:USERPROFILE\java\17.0.13+11\bin\keytool.exe" -genkeypair -v -storetype PKCS12 `
       -keystore "$env:USERPROFILE\.bonkest\bonkest-release.jks" -alias bonkest `
       -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Bonkest"
   ```
2. Copie di riserva **fuori dal PC**: il file `bonkest-release.jks` nel gestore di password (come allegato) e su una
   chiavetta o un cloud personale. La password nel gestore di password.
3. Impronta del certificato (non è segreta), da copiare: la riga `SHA256:` (es. `AB:CD:...`).
   ```
   & "$env:USERPROFILE\java\17.0.13+11\bin\keytool.exe" -list -v -keystore "$env:USERPROFILE\.bonkest\bonkest-release.jks" -alias bonkest
   ```
4. Segreti e variabile su GitHub (dalla cartella della repository; `gh secret set` chiede il valore senza mostrarlo):
   ```
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:USERPROFILE\.bonkest\bonkest-release.jks")) | gh secret set ANDROID_KEYSTORE_BASE64
   gh secret set ANDROID_KEYSTORE_PASSWORD
   gh secret set ANDROID_KEY_ALIAS --body bonkest
   gh variable set ANDROID_CERT_SHA256 --body "AB:CD:..."
   ```
   (In alternativa dal sito: Settings → Secrets and variables → Actions.)
5. Build sul PC firmati con la stessa chiave: nel `.env` (non versionato) le righe `ANDROID_*` di `.env.example`.

## Ogni rilascio

1. Versione in `pyproject.toml`: `version = "X.Y.Z"` e `build_number = X*10000 + Y*100 + Z`
   (es. 1.0.1 → 10001). `python tools/prepara_build.py` controlla la coerenza.
2. Prova (facoltativa ma consigliata): tag `vX.Y.Z-rc.1` sul branch di lavoro e push del tag
   ```
   git tag v1.0.1-rc.1
   git push origin v1.0.1-rc.1
   ```
   GitHub → Actions → "Rilascio app": ~20–30 minuti. Crea una **pre-release in bozza** con i file.
3. Rilascio vero: tag `vX.Y.Z` sul commit di `main`, push del tag, attesa del workflow.
4. GitHub → Releases → la bozza: controlla i file e **Publish release**.
5. SQL Editor: `update public.app_release set latest_version = 'X.Y.Z', updated_at = now();`
   (solo se serve davvero anche `min_version`, vedi `sql/2026-11_fase5_app_release.sql`).
6. Messaggio alla lega con il link https://github.com/vittobonaz-coder/NewFantaNBA/releases/latest

Se il workflow va rifatto sullo stesso tag: cancella la bozza su GitHub, poi Actions → "Rilascio app" → Run
workflow con il tag.

## Build sul PC

- Windows: `powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1 [-Tag vX.Y.Z] [-Installer]`
  (`-Installer` richiede Inno Setup 6).
- Android: `powershell -ExecutionPolicy Bypass -File tools\build_apk.ps1 [-Tag vX.Y.Z]` (firma dal `.env`;
  `-ChiaveDebug` solo per prove).
