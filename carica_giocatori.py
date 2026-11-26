"""
Carica in nba_players tutti i giocatori NBA (non solo quelli nei roster), per il mercato.

  python carica_giocatori.py [--dry-run]

Da lanciare dopo la parte 1 di sql/2026-11_mercato.sql, e di nuovo quando si aggiornano
data/giocatori_nba.json o data/nba_to_espn_players.json (es. nuovi giocatori a metà stagione).

Per ogni giocatore scrive:
- espn_id: dalla mappa NBA->ESPN; senza, il mercato rifiuta le offerte su quel giocatore
  (il cron non saprebbe dargli un punteggio);
- search_name: nome normalizzato (nomi.normalize_name), con cui il mercato trova il nome incollato dall'Excel.
I giocatori già presenti tengono squadra NBA e posizione del database (le aggiorna il cron);
quelli nuovi le prendono da data/giocatori_nba.json.
Lo script è ripetibile: rilanciarlo non crea doppioni.
"""
import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from nomi import normalize_name
from supabase_manager import SupabaseSync

DATA_DIR = Path("data")
PLAYERS_INFO_PATH = DATA_DIR / "giocatori_nba.json"
ESPN_MAP_PATH = DATA_DIR / "nba_to_espn_players.json"
BATCH_SIZE = 500


@dataclass(frozen=True)
class NbaPlayerRow:
    """Riga di public.nba_players come la scrive questo script."""
    id: int
    full_name: str
    nba_team: str
    position: str
    espn_id: str | None
    search_name: str


def build_rows(info: list[dict], existing: list[dict], espn_map: dict[str, str]) -> list[NbaPlayerRow]:
    """
    Righe da scrivere: i giocatori del file più quelli già nel database che il file non ha
    (es. giocatori ceduti, che restano per lo storico). Per i già presenti valgono squadra e posizione
    del database.
    """
    by_id = {int(p["PLAYER_ID"]): p for p in info}
    in_db = {int(r["id"]): r for r in existing}
    rows = []
    for p_id in sorted(by_id.keys() | in_db.keys()):
        db_row, file_row = in_db.get(p_id), by_id.get(p_id)
        name = db_row["full_name"] if db_row else file_row["PLAYER_NAME"]
        rows.append(NbaPlayerRow(
            id=p_id,
            full_name=name,
            nba_team=db_row["nba_team"] if db_row else (file_row.get("TEAM") or ""),
            position=db_row["position"] if db_row else (file_row.get("POSITION") or ""),
            espn_id=espn_map.get(str(p_id)),
            search_name=normalize_name(name),
        ))
    return rows


def duplicate_names(rows: list[NbaPlayerRow]) -> dict[str, list[int]]:
    """Nomi normalizzati condivisi da più giocatori: nel mercato darebbero 'nome ambiguo'."""
    seen: dict[str, list[int]] = {}
    for row in rows:
        seen.setdefault(row.search_name, []).append(row.id)
    return {name: ids for name, ids in seen.items() if len(ids) > 1}


def main() -> None:
    parser = argparse.ArgumentParser(description="Tutti i giocatori NBA in nba_players, per il mercato")
    parser.add_argument("--dry-run", action="store_true", help="controlla e stampa senza scrivere")
    args = parser.parse_args()

    info = json.loads(PLAYERS_INFO_PATH.read_text(encoding="utf-8"))
    espn_map = json.loads(ESPN_MAP_PATH.read_text(encoding="utf-8")).get("nba_to_espn", {})

    db = SupabaseSync(admin=True).supabase
    existing = db.table("nba_players").select("id, full_name, nba_team, position").execute().data or []
    rows = build_rows(info, existing, espn_map)

    without_espn = [r for r in rows if r.espn_id is None]
    print(f"Giocatori: {len(rows)} ({len(existing)} già nel database, {len(rows) - len(existing)} nuovi)")
    print(f"Senza ID ESPN (offerte rifiutate): {len(without_espn)}")
    for r in without_espn:
        print(f"  - {r.full_name} ({r.id})")
    for name, ids in duplicate_names(rows).items():
        print(f"ATTENZIONE: nome '{name}' condiviso da {ids}: nel mercato risulterà ambiguo")

    if args.dry_run:
        print("Dry-run: nessuna modifica.")
        return
    payload = [asdict(r) for r in rows]
    for start in range(0, len(payload), BATCH_SIZE):
        db.table("nba_players").upsert(payload[start:start + BATCH_SIZE]).execute()
    print(f"Scritti {len(payload)} giocatori in nba_players.")


if __name__ == "__main__":
    main()
