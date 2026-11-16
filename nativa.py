"""
Punto d'ingresso dell'app installata (flet build apk / windows, pyproject.toml). Render usa main.py,
lo sviluppo sul PC test.py: entrambi tengono la cache in data/.
Qui la cache va nella cartella dati dell'utente: %APPDATA%\\Bonkest\\Bonkest\\cache su Windows (fuori da
Documenti/OneDrive e dalla cartella del programma), la cartella interna privata dell'app su Android.
Ogni avvio aggiunge una riga ad avvii.jsonl (nella stessa cartella) con i tempi, per le misure della Fase 4.
"""
import time

T_MODULE = time.perf_counter()  # Primo istante in cui gira codice Python dell'app

import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import flet as ft  # noqa: E402

import app_paths  # noqa: E402
import misure  # noqa: E402

T_FLET = time.perf_counter()  # Dopo import flet (il costo fisso maggiore, Fase 0)
STARTUP_LOG = misure.AVVII_FILE
misure.imposta_inizio(T_MODULE)  # Tappe dell'avvio dall'inizio di Python (solo con le misure accese)


async def resolve_data_dir() -> Path:
    """Cartella dati dell'app: StoragePaths (application support), riserva FLET_APP_STORAGE_DATA."""
    try:
        base = await ft.StoragePaths().get_application_support_directory()
        if base:
            return Path(base) / "cache"
    except Exception as e:
        print(f"StoragePaths non disponibile: {e}")
    env = os.getenv("FLET_APP_STORAGE_DATA")
    return Path(env) / "cache" if env else Path(app_paths.DEFAULT_DATA_DIR)


def log_startup(page: ft.Page, t_page: float, cache_vuota: bool) -> None:
    """Tempi dell'avvio (ms dall'inizio di Python) in avvii.jsonl: niente dati personali."""
    now = time.perf_counter()
    row = {
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "piattaforma": str(page.platform.value if page.platform else ""),
        "cache_vuota": cache_vuota,
        "import_flet_ms": round((T_FLET - T_MODULE) * 1000),
        "pagina_ms": round((t_page - T_MODULE) * 1000),
        "prima_schermata_ms": round((now - T_MODULE) * 1000),
    }
    try:
        with open(app_paths.data_file(STARTUP_LOG), "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError as e:
        print(f"Tempi di avvio non salvati: {e}")


async def native_main(page: ft.Page) -> None:
    t_page = time.perf_counter()
    misure.tappa(page, "pagina")
    app_paths.set_data_dir(await resolve_data_dir(), native=True)
    misure.tappa(page, "data_dir")
    cache_vuota = not app_paths.data_file("snapshot_meta.json").exists()
    from app import main  # Dopo set_data_dir: nessun modulo deve leggere la cache prima
    misure.tappa(page, "import_app")
    await main(page)  # Torna dopo la prima schermata (dashboard o login)
    log_startup(page, t_page, cache_vuota)


if __name__ == "__main__":
    ft.run(main=native_main)
