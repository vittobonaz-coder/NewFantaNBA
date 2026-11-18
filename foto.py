"""
Foto dei giocatori (Fase 4, docs/fase4_piano.md sezione 6).

Ordine delle sorgenti per una card:
1. foto inclusa nel pacchetto / in assets/ di Render (`assets/players/<id>.png`);
2. solo app installata: foto scaricata una volta nella cartella dati (`<cartella dati>/players/<id>.png`),
   così resta visibile anche senza rete (Flutter tiene le immagini di rete solo in memoria);
3. CDN NBA (con rete), con il segnaposto se manca anche lì.
Sul web il punto 2 non esiste: il browser non vede i file del server.
"""
import json
import os
import tempfile
import time
from datetime import date
from pathlib import Path

import app_paths

NBA_HEADSHOT_URL = "https://cdn.nba.com/headshots/nba/latest/260x190/{id}.png"
PLAYERS_DIR = "players"
MISSING_FILE = "_mancanti.json"  # {id: "AAAA-MM-GG"}: foto assente anche sul CDN, si riprova il giorno dopo
MAX_DOWNLOADS = 20               # Per avvio
TIMEOUT = 8.0

_included: dict[int, bool] = {}


def included(player_id: int) -> bool:
    """True se la foto è nel pacchetto (o in assets/ sul server)."""
    if player_id not in _included:
        _included[player_id] = app_paths.resource(f"assets/{PLAYERS_DIR}/{player_id}.png").exists()
    return _included[player_id]


def downloaded_path(player_id: int) -> Path:
    return app_paths.data_file(PLAYERS_DIR) / f"{player_id}.png"


def source(player_id: int) -> str:
    """Sorgente della foto per ft.Image (vedi l'ordine in cima al modulo); il segnaposto lo mette la card."""
    if not player_id:
        return "avatar_placeholder.png"
    if included(player_id):
        return f"/{PLAYERS_DIR}/{player_id}.png"
    if app_paths.is_native():
        local = downloaded_path(player_id)
        if local.exists():
            return str(local.resolve())  # Percorso assoluto: il client Flutter lo apre come file
    return NBA_HEADSHOT_URL.format(id=player_id)


def roster_ids() -> set[int]:
    """ID dei giocatori di tutte le formazioni in cache (propria squadra e altre)."""
    ids: set[int] = set()
    for path in app_paths.data_dir().glob("*_state.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ids.update(int(p["id"]) for p in data.get("roster", []) if p.get("id"))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return ids


def sync_missing() -> int:
    """
    Solo app installata, in un thread: scarica le foto mancanti dei giocatori in cache e cancella quelle
    scaricate che ora sono nel pacchetto. Restituisce quante foto ha scaricato. Mai eccezioni.
    """
    if not app_paths.is_native():
        return 0
    folder = app_paths.data_file(PLAYERS_DIR)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for path in folder.glob("*.png"):  # Arrivate col nuovo build: la copia scaricata non serve più
            if path.stem.isdigit() and included(int(path.stem)):
                path.unlink(missing_ok=True)
        missing_path = folder / MISSING_FILE
        try:
            missing = json.loads(missing_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            missing = {}
        today = date.today().isoformat()
        todo = [i for i in sorted(roster_ids())
                if not included(i) and not downloaded_path(i).exists() and missing.get(str(i)) != today]
    except OSError as e:
        print(f"Foto offline: cartella non disponibile ({e})")
        return 0
    if not todo:
        return 0

    import httpx
    count = 0
    t = time.perf_counter()
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            for player_id in todo[:MAX_DOWNLOADS]:
                try:
                    response = client.get(NBA_HEADSHOT_URL.format(id=player_id))
                except httpx.HTTPError as e:
                    print(f"Foto offline: rete non disponibile ({e})")
                    break
                if response.status_code != 200 or not response.content.startswith(b"\x89PNG"):
                    missing[str(player_id)] = today
                    continue
                fd, tmp = tempfile.mkstemp(dir=folder, prefix=".foto.", suffix=".tmp")
                with os.fdopen(fd, "wb") as f:
                    f.write(response.content)
                os.replace(tmp, downloaded_path(player_id))
                count += 1
        (folder / MISSING_FILE).write_text(json.dumps(missing), encoding="utf-8")
    except OSError as e:
        print(f"Foto offline: scrittura non riuscita ({e})")
    print(f"Foto offline: {count} scaricate su {len(todo)} mancanti in {(time.perf_counter() - t) * 1000:.0f} ms")
    return count
