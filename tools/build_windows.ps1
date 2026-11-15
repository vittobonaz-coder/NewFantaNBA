# Build dell'app Windows (flet build windows) con l'aggiramento della Fase 0 (docs/fase0_report.md, sez. 5):
# le Build Tools 17.14 hanno un CMake a 32 bit, e serious_python copierebbe le DLL di runtime da SysWOW64 (32 bit).
# Qui WINDIR punta, solo per questo processo, a build\winroot con le DLL x64 delle Build Tools.
# Soluzione definitiva da decidere in Fase 5 (GitHub Actions o CMake a 64 bit).
#
#   powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1
# L'app costruita va avviata con doppio clic da Esplora file (dalla sessione di Claude Code non si avvia).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$flet = Join-Path $root "spike_android\.venv\Scripts\flet.exe"   # flet-cli 0.82 (venv separato, non versionato)
$crt = Get-ChildItem "C:\Program Files (x86)\Microsoft Visual Studio\*\BuildTools\VC\Redist\MSVC\*\x64\Microsoft.VC143.CRT" -Directory |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $crt) { throw "DLL x64 di Visual C++ non trovate nelle Build Tools" }

$winroot = Join-Path $root "build\winroot\System32"
New-Item -ItemType Directory -Force $winroot | Out-Null
foreach ($dll in "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll") {
    Copy-Item (Join-Path $crt.FullName $dll) $winroot -Force
}

python tools\prepara_build.py
if ($LASTEXITCODE -ne 0) { throw "prepara_build fallito" }

$env:WINDIR = Join-Path $root "build\winroot"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
& $flet build windows --no-rich-output --yes
exit $LASTEXITCODE
