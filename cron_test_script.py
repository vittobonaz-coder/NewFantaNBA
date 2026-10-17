import contextlib
import io

from api_nba import NbaDataManager
from fanta_obj import Player

# --- Parametri del test ---
PLAYER_NAME = "Andrew Wiggins"
TEAMS = {"MIA", "ORL"}  # Heat vs Magic
# ESPN usa la data USA: la partita della notte italiana tra il 16 e il 17 ottobre
# per ESPN e' del 16 ottobre 2026.
GAME_DATE = "2026-10-16"


def main():
    # I metodi di api_nba stampano messaggi di servizio: li nascondiamo
    # per mostrare solo il fanta-punteggio.
    with contextlib.redirect_stdout(io.StringIO()):
        # 1. ID NBA del giocatore (da data/all_players.json)
        player_ids = NbaDataManager(player_ids=[]).get_players_ids_by_name([PLAYER_NAME])
        if not player_ids:
            raise SystemExit(f"Giocatore '{PLAYER_NAME}' non trovato.")
        player_id = player_ids[0]

        # 2. Tabellini della data, filtrati sul giocatore
        manager = NbaDataManager(player_ids=[player_id])
        boxscores = manager.fetch_boxscores(GAME_DATE)

    # 3. Tieni solo il tabellino della partita Heat vs Magic
    boxscores = [b for b in boxscores if set(b["MATCHUP"].split(" @ ")) == TEAMS]
    if not boxscores:
        raise SystemExit(f"Nessun tabellino di {PLAYER_NAME} per MIA vs ORL il {GAME_DATE}.")

    # 4. Calcolo del fanta-punteggio con il metodo di fanta_obj.Player
    player = Player(id=player_id, name=PLAYER_NAME)
    score = player.calculate_score(boxscores, target_date=GAME_DATE)

    print(f"Fanta-punteggio {PLAYER_NAME}: {score:.2f}")


if __name__ == "__main__":
    main()