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


def _version_key(tool: Path) -> tuple:
    """Ordina le cartelle build-tools per versione numerica (37.0.0 > 34.0.0 > 9.0.0)."""
    return tuple(int(x) if x.isdigit() else -1 for x in re.split(r"[.-]", tool.parent.name))


def find_apksigners() -> list[str]:
    """
    apksigner disponibili, dal più recente: SDK Android (ANDROID_HOME / ANDROID_SDK_ROOT, o ~/Android/sdk come
    installa flet), poi PATH. Se uno non funziona (es. vuole un'altra versione di Java) si prova il successivo.
    """
    found: list[str] = []
    roots = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"), str(Path.home() / "Android" / "sdk")]
    exe = "apksigner.bat" if os.name == "nt" else "apksigner"
    for root in filter(None, roots):
        for tool in sorted(Path(root).glob(f"build-tools/*/{exe}"), key=_version_key, reverse=True):
            if str(tool) not in found:
                found.append(str(tool))
    on_path = shutil.which("apksigner")
    if on_path and on_path not in found:
        found.append(on_path)
    return found


def _meaningful(text: str) -> str:
    """Testo di apksigner senza gli avvisi di Java (righe WARNING), che nasconderebbero l'errore vero."""
    return "\n".join(ln for ln in text.splitlines() if ln.strip() and not ln.startswith("WARNING:"))


def apk_certificate(apk: Path) -> tuple[str | None, str]:
    """(SHA-256 del certificato del primo firmatario, testo di apksigner o errori di tutti i tentativi)."""
    tools = find_apksigners()
    if not tools:
        return None, "apksigner non trovato (Android SDK build-tools)"
    env = dict(os.environ)
    if not env.get("JAVA_HOME") and not shutil.which("java"):
        jdks = sorted((Path.home() / "java").glob("*/bin/java*"), reverse=True)  # JDK installato da flet sul PC
        if jdks:
            env["JAVA_HOME"] = str(jdks[0].parent.parent)
    failures = []
    for tool in tools:
        out = subprocess.run([tool, "verify", "--print-certs", str(apk)], capture_output=True, text=True, env=env)
        text = _meaningful(out.stdout + "\n" + out.stderr)
        m = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-fA-F:]+)", text)
        if out.returncode == 0 and m:
            print(f"apksigner usato: {tool}")
            return m[1].replace(":", "").lower(), text
        failures.append(f"{tool} (codice {out.returncode}): {text[:800] or '(nessun messaggio)'}")
    return None, "\n    ".join(failures)


def normalize_digest(value: str) -> str:
    """
    Impronta scritta come la stampa keytool ("SHA256: AB:CD:...") o apksigner ("abcd..."): solo le cifre
    esadecimali, minuscole. Toglie l'eventuale prefisso "SHA256:" / "SHA-256", spazi e due punti.
    """
    value = re.sub(r"(?i)^\s*sha-?256\s*:?", "", value or "")
    return re.sub(r"[^0-9a-fA-F]", "", value).lower()


def check_apk(apk: Path, expected: str | None, debug_ok: bool) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(apk) as zf:
        scan_zip(zf, "", errors)
    digest, text = apk_certificate(apk)
    if digest is None:
        errors.append(f"firma non verificata:\n    {text}")
    else:
        debug = "CN=Android Debug" in text
        print(f"Certificato: SHA-256 {digest}{' (chiave di DEBUG)' if debug else ''}")
        if expected:
            wanted = normalize_digest(expected)
            if digest != wanted:
                # Entrambe le impronte nel messaggio (non sono segrete): si capisce subito se è la chiave di debug,
                # una chiave diversa o un'impronta copiata male (es. SHA1 invece di SHA256)
                errors.append(f"l'APK NON è firmato con la chiave attesa (ANDROID_CERT_SHA256)."
                              f" Impronta dell'APK: {digest}{' (chiave di DEBUG)' if debug else ''}."
                              f" Impronta attesa: {wanted or '(vuota)'} ({len(wanted)} caratteri, ne servono 64)")
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
        if os.environ.get("GITHUB_ACTIONS"):
            # Annotazioni: compaiono nel riepilogo dell'esecuzione, leggibili anche senza accesso ai log
            for err in errors[:10]:
                print("::error::" + err.replace("%", "%25").replace("\r", "").replace("\n", "%0A"))
        return 1
    print(f"{args.percorso}: controlli superati")
    return 0


if __name__ == "__main__":
    sys.exit(main())
