"""
Prepara app_src/, la sola cartella che `flet build` impacchetta (pyproject.toml, tool.flet.app.path).

flet build include TUTTO quello che trova nella cartella dell'app, tranne build/: dalla radice della
repository finirebbero nell'APK anche .env (chiave segreta), data/, sql/... Qui si copia invece una
lista di file AMMESSI, poi si controlla che non sia entrato nulla di segreto.

  python tools/prepara_build.py [--misure]
  flet build apk          (o: powershell -File tools/build_windows.ps1 [-Misure])

--misure (Fase 4, solo build di prova): aggiunge il file misure_attive, che accende misure.py e il tab
"Tempi" nelle Impostazioni. I build per gli utenti si fanno senza.
"""
import ast
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "app_src"

# Moduli dell'app nativa (nativa.py e tutto ciò che importa) e asset (icona, foto, regolamento)
APP_MODULES = ["nativa.py", "app.py", "app_paths.py", "ui_court.py", "fanta_obj.py", "league_cache.py",
               "supabase_rest.py", "time_manager.py", "misure.py", "flet_fix.py", "foto.py"]
FLAG_MISURE = "misure_attive"  # Stesso nome di misure.FLAG_FILE
ASSET_FILES = ["icon.png", "avatar_placeholder.png", "rules.json"]
ASSET_DIRS = ["players"]

# Import ammessi oltre ai moduli dell'app: libreria standard + dipendenze di pyproject.toml
THIRD_PARTY = {"flet", "httpx"}
FORBIDDEN_TEXT = ["sb_secret_", "SUPABASE_SECRET_KEY=", "service_role\":"]


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
        if path.name.startswith(".env"):
            errors.append(f"file vietato: {rel}")
        if path.suffix == ".json" and not rel.startswith("assets/"):
            errors.append(f"JSON fuori da assets/: {rel}")
        if path.suffix in {".py", ".json", ".txt", ".toml"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            errors += [f"{rel}: contiene '{t}'" for t in FORBIDDEN_TEXT if t in text]
    return errors


def main() -> int:
    copy_files()
    if "--misure" in sys.argv[1:]:
        (DEST / FLAG_MISURE).write_text("Build di prova con le misure accese (Fase 4)\n", encoding="utf-8")
    errors = check_imports() + check_content()
    if errors:
        print("ERRORE, app_src/ non va impacchettata:\n  " + "\n  ".join(errors))
        shutil.rmtree(DEST)
        return 1
    files = [p for p in DEST.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    misure_on = (DEST / FLAG_MISURE).exists()
    print(f"app_src/ pronta: {len(files)} file, {size / 1024:.0f} KB, misure {'ACCESE' if misure_on else 'spente'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
