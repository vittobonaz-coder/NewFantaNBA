# Build dell'APK sul PC (Fase 5, docs/fase5_piano.md, sez. 2), firmato con la chiave vera come quelli di GitHub:
# così APK locali e delle release si installano uno sopra l'altro senza disinstallare.
# Legge dal .env (non versionato) ANDROID_KEYSTORE_PATH, ANDROID_KEYSTORE_PASSWORD, ANDROID_KEY_ALIAS e
# ANDROID_CERT_SHA256; senza queste variabili si ferma, salvo -ChiaveDebug (solo per prove: un APK con la chiave
# di debug non si installa sopra quelli veri, va prima disinstallata l'app).
# Un APK firmato qui è "ufficiale" a tutti gli effetti: non distribuirlo per sbaglio.
#
#   powershell -ExecutionPolicy Bypass -File tools\build_apk.ps1 [-Tag v1.0.0] [-ChiaveDebug] [altri argomenti di flet build]
param(
    [string]$Tag = "",
    [switch]$ChiaveDebug,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$FletArgs = @()
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$flet = $env:FLET_EXE
if (-not $flet) {
    $venv = Join-Path $root "spike_android\.venv\Scripts\flet.exe"
    $flet = if (Test-Path $venv) { $venv } else { (Get-Command flet -ErrorAction Stop).Source }
}

# Variabili dal .env (righe NOME=valore, senza esportarle oltre questo processo)
$cfg = @{}
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*(ANDROID_[A-Z0-9_]+)\s*=\s*(.*?)\s*$') { $cfg[$Matches[1]] = $Matches[2] }
    }
}

$signing = $cfg["ANDROID_KEYSTORE_PATH"] -and $cfg["ANDROID_KEYSTORE_PASSWORD"] -and $cfg["ANDROID_KEY_ALIAS"]
if (-not $signing -and -not $ChiaveDebug) {
    throw "Firma non configurata nel .env (vedi .env.example). Per una prova con la chiave di debug: -ChiaveDebug"
}
if ($signing -and -not (Test-Path $cfg["ANDROID_KEYSTORE_PATH"])) {
    throw "Keystore non trovato: $($cfg['ANDROID_KEYSTORE_PATH'])"
}

$prepara = @("tools\prepara_build.py")
if ($Tag) { $prepara += @("--tag", $Tag) }
python @prepara
if ($LASTEXITCODE -ne 0) { throw "prepara_build fallito" }

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$names = "FLET_ANDROID_SIGNING_KEY_STORE", "FLET_ANDROID_SIGNING_KEY_STORE_PASSWORD",
         "FLET_ANDROID_SIGNING_KEY_PASSWORD", "FLET_ANDROID_SIGNING_KEY_ALIAS"
try {
    if ($signing) {
        # Con PKCS12 la password della chiave è quella del keystore
        $env:FLET_ANDROID_SIGNING_KEY_STORE = $cfg["ANDROID_KEYSTORE_PATH"]
        $env:FLET_ANDROID_SIGNING_KEY_STORE_PASSWORD = $cfg["ANDROID_KEYSTORE_PASSWORD"]
        $env:FLET_ANDROID_SIGNING_KEY_PASSWORD = $cfg["ANDROID_KEYSTORE_PASSWORD"]
        $env:FLET_ANDROID_SIGNING_KEY_ALIAS = $cfg["ANDROID_KEY_ALIAS"]
    }
    & $flet build apk --no-rich-output --yes @FletArgs
    if ($LASTEXITCODE -ne 0) { throw "flet build apk fallito ($LASTEXITCODE)" }
} finally {
    foreach ($n in $names) { Remove-Item "Env:$n" -ErrorAction SilentlyContinue }
}

$check = @("tools\controlla_build.py", "apk", "build\apk\bonkest.apk")
if ($signing) { $check += @("--cert", $cfg["ANDROID_CERT_SHA256"]) } else { $check += "--debug-ok" }
python @check
if ($LASTEXITCODE -ne 0) { throw "controllo dell'APK fallito" }
exit 0
