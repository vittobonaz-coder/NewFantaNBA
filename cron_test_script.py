from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from api_nba import NbaDataManager

# --- Parametri del test ---
PLAYER_NAME = "Andrew Wiggins"
TEAMS = {"MIA", "ORL"}  # Heat vs Magic
# ESPN usa la data USA: la partita di "stanotte" (notte italiana tra il 16 e il 17 ottobre)
# per ESPN e' del 16 ottobre 2026.
GAME_DATE = "2026-10-16"


def print_timestamp():
    now_utc = datetime.now(timezone.utc)
    now_italy = now_utc.astimezone(ZoneInfo("Europe/Rome"))
    print("🚀 Script Python avviato!")
    print(f"📅 Timestamp UTC:    {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🇮🇹 Timestamp Italia: {now_italy.strftime('%Y-%m-%d %H:%M:%S')} ({now_italy.tzname()})")


def main():
    print_timestamp()

    # 1. Ricava l'ID NBA del giocatore da data/all_players.json
    manager = NbaDataManager(player_ids=[])
    player_ids = manager.get_players_ids_by_name([PLAYER_NAME])
    if not player_ids:
        raise SystemExit(f"❌ Giocatore '{PLAYER_NAME}' non trovato.")
    player_id = player_ids[0]

    # 2. Ricrea il manager filtrando solo su quel giocatore
    manager = NbaDataManager(player_ids=[player_id])

    # 3. Trova la partita Heat vs Magic nella data indicata
    games = manager.fetch_matchups(GAME_DATE)
    game = next(
        (g for g in games if set(g["MATCHUP"].split(" @ ")) == TEAMS),
        None,
    )
    if game is None:
        raise SystemExit(f"❌ Nessuna partita {' vs '.join(sorted(TEAMS))} il {GAME_DATE}.")
    print(f"🏀 Partita: {game['MATCHUP']}  |  Risultato: {game['SCORE']}  |  GAME_ID: {game['GAME_ID']}")

    # 4. Scarica i tabellini e tieni solo quello del giocatore in quella partita
    boxscores = manager.fetch_boxscores(GAME_DATE)
    box = next(
        (b for b in boxscores
         if str(b["GAME_ID"]) == game["GAME_ID"] and str(b["PLAYER_ID"]) == str(player_id)),
        None,
    )
    if box is None:
        raise SystemExit(f"❌ Nessun tabellino per {PLAYER_NAME} (non ha giocato?).")

    # 5. Stampa il tabellino
    print(f"\n📊 Tabellino di {PLAYER_NAME} ({box['MATCHUP']}, {box['WL']})")
    print(f"   MIN {box['MIN']} | PTS {box['PTS']} | REB {box['REB']} (OREB {box['OREB']}, DREB {box['DREB']}) | AST {box['AST']}")
    print(f"   FG {box['FGM']}/{box['FGA']} | 3PT {box['FG3M']}/{box['FG3A']} | FT {box['FTM']}/{box['FTA']}")
    print(f"   STL {box['STL']} | BLK {box['BLK']} | TOV {box['TOV']} | PF {box['PF']} | +/- {box['PLUS_MINUS']}")


if __name__ == "__main__":
    main()
