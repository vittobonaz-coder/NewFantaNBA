"""
Controlli sul pacchetto costruito, prima di distribuirlo (Fase 5, docs/fase5_piano.md). Solo libreria standard.

  python tools/controlla_build.py apk build/apk/bonkest.apk [--cert SHA256 | --debug-ok]
  python tools/controlla_build.py windows build/windows

apk:     firma con il certificato atteso (--cert o variabile ANDROID_CERT_SHA256; flet build firma in silenzio
         con la chiave di debug se mancano le opzioni di firma), nessun segreto né keystore nel contenuto.
windows: exe e DLL a 64 bit (aggiramento CMake, tools/build_windows.ps1), nessun segreto né keystore.
Esce con 1 al primo gruppo di errori.
"""
import argparse
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

FORBIDDEN_BYTES = [b"sb_secret_", b"SUPABASE_SECRET_KEY=", b"ANDROID_KEYSTORE_PASSWORD="]
FORBIDDEN_SUFFIXES = (".jks", ".keystore", ".p12", ".pfx", ".b64")
FORBIDDEN_NAMES = (".env",)
X64_MACHINE = 0x8664
WINDOWS_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")


def scan_bytes(label: str, data: bytes, errors: list[str], depth: int = 0) -> None:
    """Cerca i segreti nel contenuto, entrando negli zip annidati (il codice Python è in app.zip)."""
    errors += [f"{label}: contiene {t.decode()!r}" for t in FORBIDDEN_BYTES if t in data]
    if depth < 3 and data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                scan_zip(zf, label, errors, depth + 1)
        except zipfile.BadZipFile:
            pass


def scan_zip(zf: zipfile.ZipFile, prefix: str, errors: list[str], depth: int = 0) -> None:
    for info in zf.infolist():
        name = f"{prefix}!{info.filename}" if prefix else info.filename
        base = info.filename.rsplit("/", 1)[-1].lower()
        if base.endswith(FORBIDDEN_SUFFIXES) or base.startswith(FORBIDDEN_NAMES):
            errors.append(f"file vietato: {name}")
        if not info.is_dir():
            scan_bytes(name, zf.read(info), errors, depth)


def find_apksigner() -> str | None:
    """apksigner dell'SDK Android (variabili ANDROID_HOME / ANDROID_SDK_ROOT, o ~/Android/sdk come installa flet)."""
    found = shutil.which("apksigner")
    if found:
        return found
    roots = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"), str(Path.home() / "Android" / "sdk")]
    exe = "apksigner.bat" if os.name == "nt" else "apksigner"
    for root in filter(None, roots):
        tools = sorted(Path(root).glob(f"build-tools/*/{exe}"), reverse=True)
        if tools:
            return str(tools[0])
    return None


def apk_certificate(apk: Path) -> tuple[str | None, str]:
    """(SHA-256 del certificato del primo firmatario, testo di apksigner)."""
    tool = find_apksigner()
    if not tool:
        return None, "apksigner non trovato (Android SDK build-tools)"
    env = dict(os.environ)
    if not env.get("JAVA_HOME") and not shutil.which("java"):
        jdks = sorted((Path.home() / "java").glob("*/bin/java*"), reverse=True)  # JDK installato da flet sul PC
        if jdks:
            env["JAVA_HOME"] = str(jdks[0].parent.parent)
    out = subprocess.run([tool, "verify", "--print-certs", str(apk)], capture_output=True, text=True, env=env)
    text = (out.stdout + out.stderr).strip()
    if out.returncode != 0:
        return None, text
    m = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-fA-F:]+)", text)
    return (m[1].replace(":", "").lower() if m else None), text


def check_apk(apk: Path, expected: str | None, debug_ok: bool) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(apk) as zf:
        scan_zip(zf, "", errors)
    digest, text = apk_certificate(apk)
    if digest is None:
        errors.append(f"firma non verificata: {text[-300:]}")
    else:
        debug = "CN=Android Debug" in text
        print(f"Certificato: SHA-256 {digest}{' (chiave di DEBUG)' if debug else ''}")
        if expected:
            if digest != expected.replace(":", "").lower():
                errors.append("l'APK NON è firmato con la chiave attesa (ANDROID_CERT_SHA256)")
        elif not (debug_ok and debug):
            errors.append("impronta attesa mancante: passa --cert o ANDROID_CERT_SHA256 (o --debug-ok per le prove)")
    return errors


def pe_machine(path: Path) -> int | None:
    """Campo Machine dell'intestazione PE (0x8664 = x64)."""
    with open(path, "rb") as f:
        head = f.read(4096)
    if head[:2] != b"MZ":
        return None
    offset = struct.unpack_from("<I", head, 0x3C)[0]
    if head[offset:offset + 4] != b"PE\0\0":
        return None
    return struct.unpack_from("<H", head, offset + 4)[0]


def check_windows(folder: Path) -> list[str]:
    errors: list[str] = []
    for name in WINDOWS_DLLS:
        if not (folder / name).exists():
            errors.append(f"manca {name}")
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() in (".exe", ".dll"):
            machine = pe_machine(path)
            if machine != X64_MACHINE:
                errors.append(f"{path.name}: non è a 64 bit (Machine={machine and hex(machine)})")
    for path in folder.rglob("*"):
        if path.is_file():
            rel = path.relative_to(folder).as_posix()
            if path.name.lower().endswith(FORBIDDEN_SUFFIXES) or path.name.startswith(FORBIDDEN_NAMES):
                errors.append(f"file vietato: {rel}")
            if path.suffix.lower() in (".zip", ".py", ".json", ".txt", ".toml", ".env", ""):
                scan_bytes(rel, path.read_bytes(), errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlli sul pacchetto costruito")
    parser.add_argument("tipo", choices=["apk", "windows"])
    parser.add_argument("percorso", type=Path)
    parser.add_argument("--cert", default=os.environ.get("ANDROID_CERT_SHA256"), help="SHA-256 atteso del certificato")
    parser.add_argument("--debug-ok", action="store_true", help="accetta la chiave di debug (solo build di prova)")
    args = parser.parse_args()
    if not args.percorso.exists():
        print(f"ERRORE: {args.percorso} non esiste")
        return 1
    errors = check_apk(args.percorso, args.cert, args.debug_ok) if args.tipo == "apk" else check_windows(args.percorso)
    if errors:
        print("ERRORE, il pacchetto non va distribuito:\n  " + "\n  ".join(errors[:30]))
        return 1
    print(f"{args.percorso}: controlli superati")
    return 0


if __name__ == "__main__":
    sys.exit(main())
