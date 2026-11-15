"""
Percorsi dei file dell'app, in un posto solo (Fase 3, docs/fase3_piano.md).

- Cache dei dati (scrivibile): `data/` per Render, sviluppo (test.py), cron e script, che non toccano
  nulla qui; nell'app installata (nativa.py) la cartella dati dell'utente, impostata con set_data_dir
  prima di qualunque lettura. FANTANBA_DATA_DIR permette di provare in sviluppo una cartella diversa.
- File in sola lettura inclusi nel pacchetto (es. assets/rules.json): accanto al codice.
"""
import os
from pathlib import Path

DEFAULT_DATA_DIR = "data"
APP_DIR = Path(__file__).resolve().parent

_data_dir: Path = Path(os.environ.get("FANTANBA_DATA_DIR") or DEFAULT_DATA_DIR)
_native = False


def data_dir() -> Path:
    """Cartella della cache locale."""
    return _data_dir


def set_data_dir(path: str | Path, native: bool = True) -> None:
    """Imposta la cartella della cache (la crea se manca). La chiama solo il punto d'ingresso dell'app installata."""
    global _data_dir, _native
    _data_dir = Path(path)
    _data_dir.mkdir(parents=True, exist_ok=True)
    _native = native


def data_file(name: str) -> Path:
    """File della cache locale."""
    return _data_dir / name


def resource(name: str) -> Path:
    """File in sola lettura incluso nel pacchetto, relativo alla cartella del codice (es. 'assets/rules.json')."""
    return APP_DIR / name


def is_native() -> bool:
    """True nell'app installata (flet build), False su Render e in sviluppo."""
    return _native
