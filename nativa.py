"""
Punto d'ingresso dell'app installata (flet build apk / windows, pyproject.toml). Render usa main.py,
lo sviluppo sul PC test.py: entrambi tengono la cache in data/.
Qui la cache va nella cartella dati dell'utente: %APPDATA%\\FantaNBA\\FantaNBA\\cache su Windows (fuori da
Documenti/OneDrive e dalla cartella del programma), la cartella interna privata dell'app su Android.
"""
import os
from pathlib import Path

import flet as ft

import app_paths


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


async def native_main(page: ft.Page) -> None:
    app_paths.set_data_dir(await resolve_data_dir(), native=True)
    from app import main  # Dopo set_data_dir: nessun modulo deve leggere la cache prima
    await main(page)


if __name__ == "__main__":
    ft.run(main=native_main)
