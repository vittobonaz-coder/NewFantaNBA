"""
Controllo "da fuori" dei permessi del database dopo la migrazione B della Fase 1
(sql/2026-11_fase1b_rls_revoche.sql): usa SOLO la chiave pubblicabile, come chiunque abbia la repository o l'APK.

  python tools/verifica_permessi.py

Non modifica nessuna riga in nessun caso: l'unico tentativo di scrittura è un UPDATE filtrato su un id
inesistente (se i permessi fossero ancora aperti aggiornerebbe zero righe) e il login ha credenziali inventate.
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from supabase_rest import SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY  # noqa: E402

NO_ROW = "00000000-0000-0000-0000-000000000000"


def main() -> int:
    client = httpx.Client(base_url=f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_PUBLISHABLE_KEY}, timeout=20)
    failures = 0

    def check(label: str, ok: bool, detail: str) -> None:
        nonlocal failures
        failures += not ok
        print(f"{'OK  ' if ok else 'NO  '} {label}  ({detail})")

    # Dati personali: non devono essere leggibili (permesso negato, di solito HTTP 401)
    for table in ("profiles", "login_tokens", "player_stats", "standings_adjustments"):
        r = client.get(f"/{table}", params={"select": "*", "limit": 1})
        check(f"{table} non leggibile", r.status_code >= 400, f"HTTP {r.status_code}")

    r = client.get("/fanta_teams", params={"select": "user_id", "limit": 1})
    check("fanta_teams.user_id non leggibile", r.status_code >= 400, f"HTTP {r.status_code}")

    # Dati di lega: leggibili
    for table, select in (("matchups", "gameweek"), ("lineup_players", "slot"), ("nba_games", "game_id"),
                          ("nba_players", "id"), ("player_injuries", "nba_player_id"), ("cron_runs", "mode"),
                          ("rosters", "nba_player_id"), ("v_standings", "team_name"), ("fanta_teams", "id,name")):
        r = client.get(f"/{table}", params={"select": select, "limit": 1})
        check(f"{table} leggibile", r.status_code == 200, f"HTTP {r.status_code}")

    # Scrittura diretta: negata. L'id non esiste, quindi anche con permessi aperti non cambierebbe nulla
    r = client.patch("/matchups", params={"id": f"eq.{NO_ROW}"}, json={"home_score": 0},
                     headers={"Prefer": "return=minimal"})
    check("scrittura diretta su matchups negata", r.status_code >= 400, f"HTTP {r.status_code}")

    # RPC: login con credenziali inventate -> null
    r = client.post("/rpc/login", json={"p_username": "verifica_inesistente", "p_password": "x"})
    check("rpc login raggiungibile, credenziali errate -> null", r.status_code == 200 and r.json() is None,
          f"HTTP {r.status_code} {r.text[:60]}")

    # RPC solo per la chiave segreta
    r = client.post("/rpc/admin_set_password", json={"p_user_id": NO_ROW, "p_password": "x"})
    check("admin_set_password negata", r.status_code >= 400, f"HTTP {r.status_code}")

    print("\nTutto a posto." if not failures else f"\n{failures} controlli NON superati.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
