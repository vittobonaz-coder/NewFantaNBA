# Build dell'app Windows (flet build windows), uguale sul PC e su GitHub Actions (Fase 5, docs/fase5_piano.md).
#
# Aggiramento CMake (Fase 0, docs/fase0_report.md sez. 5), tenuto come soluzione definitiva e reso portabile:
# serious_python copia msvcp140/vcruntime140/vcruntime140_1.dll da $ENV{WINDIR}/System32; da un CMake a 32 bit
# Windows dirotta su SysWOW64 (DLL a 32 bit in un'app a 64 bit). Qui WINDIR punta, solo per questo processo, a
# build\winroot con le DLL x64 di Visual C++ trovate con vswhere (Build Tools sul PC, Enterprise su GitHub).
# Funziona con CMake a 32 o 64 bit; dopo il build tools\controlla_build.py verifica che le DLL siano x64.
#
#   powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1 [-Tag v1.0.0] [-Installer] [altri argomenti di flet build]
#   -Tag        tag del rilascio, controllato con la versione di pyproject.toml (prepara_build.py)
#   -Installer  dopo il build crea build\dist\Bonkest-Setup.exe (Inno Setup 6) e build\dist\bonkest-windows.zip
#   flet-cli: $env:FLET_EXE, altrimenti spike_android\.venv (PC), altrimenti flet nel PATH (GitHub)
#   (dopo un cambio di nome dell'app serve --clear-cache: la cache di CMake ricorda il nome vecchio)
# L'app costruita va avviata con doppio clic da Esplora file (dalla sessione di Claude Code non si avvia).
param(
    [string]$Tag = "",
    [switch]$Installer,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$FletArgs = @()
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# flet-cli 0.82
$flet = $env:FLET_EXE
if (-not $flet) {
    $venv = Join-Path $root "spike_android\.venv\Scripts\flet.exe"   # venv separato, non versionato
    $flet = if (Test-Path $venv) { $venv } else { (Get-Command flet -ErrorAction Stop).Source }
}

# DLL x64 di Visual C++ dall'installazione di Visual Studio (qualunque edizione) trovata con vswhere
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) { throw "vswhere non trovato: Visual Studio o Build Tools non installati" }
$vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsPath) { throw "Visual Studio con gli strumenti C++ x64 non trovato" }
$crt = Get-ChildItem (Join-Path $vsPath "VC\Redist\MSVC\*\x64\Microsoft.VC14*.CRT") -Directory |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $crt) { throw "DLL x64 di Visual C++ non trovate in $vsPath\VC\Redist" }
Write-Host "DLL di Visual C++: $($crt.FullName)"

$winroot = Join-Path $root "build\winroot\System32"
New-Item -ItemType Directory -Force $winroot | Out-Null
foreach ($dll in "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll") {
    Copy-Item (Join-Path $crt.FullName $dll) $winroot -Force
}

$prepara = @("tools\prepara_build.py")
if ($Tag) { $prepara += @("--tag", $Tag) }
python @prepara
if ($LASTEXITCODE -ne 0) { throw "prepara_build fallito" }

$oldWindir = $env:WINDIR
$env:WINDIR = Join-Path $root "build\winroot"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try {
    & $flet build windows --no-rich-output --yes @FletArgs
    if ($LASTEXITCODE -ne 0) { throw "flet build windows fallito ($LASTEXITCODE)" }
} finally {
    $env:WINDIR = $oldWindir
}

python tools\controlla_build.py windows build\windows
if ($LASTEXITCODE -ne 0) { throw "controllo del build Windows fallito" }

if ($Installer) {
    $dist = Join-Path $root "build\dist"
    New-Item -ItemType Directory -Force $dist | Out-Null
    $zip = Join-Path $dist "bonkest-windows.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $root "build\windows\*") -DestinationPath $zip

    $iscc = @((Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
              (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
              (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")) |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) { throw "Inno Setup 6 non installato (serve solo per -Installer)" }
    $version = python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
    & $iscc /Qp "/DAppVersion=$version" "/DSourceDir=$root\build\windows" "/DOutputDir=$dist" tools\installer_windows.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallito ($LASTEXITCODE)" }
    Get-ChildItem $dist | ForEach-Object { Write-Host ("{0}  {1:N1} MB" -f $_.Name, ($_.Length / 1MB)) }
}
exit 0
