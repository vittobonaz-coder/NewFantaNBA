"""
Prepara app_src/, la sola cartella che `flet build` impacchetta (pyproject.toml, tool.flet.app.path).

flet build include TUTTO quello che trova nella cartella dell'app, tranne build/: dalla radice della
repository finirebbero nell'APK anche .env (chiave segreta), data/, sql/... Qui si copia invece una
lista di file AMMESSI, poi si controlla che non sia entrato nulla di segreto.

Fase 5: scrive app_src/versione.py con la versione di pyproject.toml e controlla che il numero di build
segua la regola X*10000 + Y*100 + Z e che l'eventuale tag del rilascio (--tag vX.Y.Z[-rc.N]) coincida.

  python tools/prepara_build.py [--tag v1.0.0]
  flet build apk          (o: tools/build_apk.ps1, tools/build_windows.ps1)
"""
import argparse
import ast
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "app_src"

# Moduli dell'app nativa (nativa.py e tutto ciò che importa) e asset (icona, foto, regolamento)
APP_MODULES = ["nativa.py", "app.py", "app_paths.py", "ui_court.py", "fanta_obj.py", "league_cache.py",
               "supabase_rest.py", "time_manager.py", "flet_fix.py", "foto.py", "aggiornamenti.py",
               "versione.py"]
ASSET_FILES = ["icon.png", "avatar_placeholder.png", "rules.json"]
ASSET_DIRS = ["players"]

# Import ammessi oltre ai moduli dell'app: libreria standard + dipendenze di pyproject.toml
THIRD_PARTY = {"flet", "httpx"}
FORBIDDEN_TEXT = ["sb_secret_", "SUPABASE_SECRET_KEY=", "service_role\":", "ANDROID_KEYSTORE_PASSWORD="]
FORBIDDEN_SUFFIXES = {".jks", ".keystore", ".p12", ".pfx", ".b64"}  # Chiavi di firma: mai nel pacchetto
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)(-rc\.\d+)?$")


def build_number(version: str) -> int:
    """Numero di build dalla versione: X*10000 + Y*100 + Z (Y e Z fino a 99)."""
    m = VERSION_RE.match(version)
    if not m or int(m[2]) > 99 or int(m[3]) > 99:
        raise ValueError(f"versione non valida: {version!r} (atteso X.Y.Z, Y e Z fino a 99)")
    return int(m[1]) * 10000 + int(m[2]) * 100 + int(m[3])


def read_version(tag: str | None) -> tuple[str, int, list[str]]:
    """Versione e numero di build da pyproject.toml, con i controlli di coerenza (anche col tag)."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = data["project"]["version"]
    number = data["tool"]["flet"].get("build_number")
    errors = []
    try:
        expected = build_number(version)
        if number != expected:
            errors.append(f"pyproject.toml: build_number {number}, atteso {expected} per la versione {version}")
    except ValueError as e:
        errors.append(f"pyproject.toml: {e}")
    if tag:
        m = TAG_RE.match(tag)
        if not m:
            errors.append(f"tag non valido: {tag!r} (atteso vX.Y.Z o vX.Y.Z-rc.N)")
        elif m[1] != version:
            errors.append(f"il tag {tag} non corrisponde alla versione {version} di pyproject.toml")
    return version, number, errors


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else ""
    except OSError:
        return ""


def write_version(version: str, number: int, tag: str | None) -> None:
    """app_src/versione.py: stessa interfaccia di versione.py, con i valori del build."""
    text = (ROOT / "versione.py").read_text(encoding="utf-8")
    values = {"VERSIONE": f'"{version}"', "BUILD": str(number), "TAG": f'"{tag or ""}"', "COMMIT": f'"{git_commit()}"'}
    for name, value in values.items():
        # "NOME: tipo = valore   # commento" -> stesso tipo e commento, valore del build
        text, n = re.subn(rf"^({name}:[^=]*= ).*?(\s+#)", lambda m: m[1] + value + m[2], text, count=1, flags=re.M)
        if n != 1:
            raise RuntimeError(f"versione.py: riga {name} non trovata")
    (DEST / "versione.py").write_text(text, encoding="utf-8")


def copy_files() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    (DEST / "assets").mkdir(parents=True)
    for name in APP_MODULES:
        shutil.copy2(ROOT / name, DEST / name)
    for name in ASSET_FILES:
        shutil.copy2(ROOT / "assets" / name, DEST / "assets" / name)
    for name in ASSET_DIRS:
        shutil.copytree(ROOT / "assets" / name, DEST / "assets" / name)


def check_imports() -> list[str]:
    """Ogni import dei moduli copiati deve essere un modulo copiato, della libreria standard o ammesso."""
    local = {Path(m).stem for m in APP_MODULES}
    errors = []
    for name in APP_MODULES:
        tree = ast.parse((DEST / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module.split(".")[0]]
            else:
                continue
            for mod in mods:
                if mod not in local and mod not in THIRD_PARTY and mod not in sys.stdlib_module_names:
                    errors.append(f"{name}: import non ammesso '{mod}'")
    return errors


def check_content() -> list[str]:
    """Nessun segreto, nessun .env, nessun JSON fuori da assets/."""
    errors = []
    for path in DEST.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(DEST).as_posix()
        if path.name.startswith(".env") or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"file vietato: {rel}")
        if path.suffix == ".json" and not rel.startswith("assets/"):
            errors.append(f"JSON fuori da assets/: {rel}")
        if path.suffix in {".py", ".json", ".txt", ".toml"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            errors += [f"{rel}: contiene '{t}'" for t in FORBIDDEN_TEXT if t in text]
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepara app_src/ per flet build")
    parser.add_argument("--tag", help="tag del rilascio (vX.Y.Z o vX.Y.Z-rc.N): deve coincidere con pyproject.toml")
    args = parser.parse_args()
    version, number, errors = read_version(args.tag)
    if errors:
        print("ERRORE di versione:\n  " + "\n  ".join(errors))
        return 1
    copy_files()
    write_version(version, number, args.tag)
    errors = check_imports() + check_content()
    if errors:
        print("ERRORE, app_src/ non va impacchettata:\n  " + "\n  ".join(errors))
        shutil.rmtree(DEST)
        return 1
    files = [p for p in DEST.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    print(f"app_src/ pronta: {len(files)} file, {size / 1024:.0f} KB, versione {version} (build {number})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
