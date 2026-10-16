import json
import os
from api_nba import NbaDataManager
from fanta_obj import Player, Team
from supabase_manager import SupabaseSync
from ui_court import ROLE_CONFIGS
from time_manager import TimeManager


def update_all_teams_scores_via_api(target_date: str, role_configs: dict = ROLE_CONFIGS):
    """
    Calcola e aggiorna i punteggi di tutte le squadre per una determinata data
    distinguendo tra data NBA (USA) e data di lega (Italiana).
    
    :param target_date: Data NBA/USA in input (es. "2026-10-03")
    """
    # 0. Gestione della duplice data (NBA vs Italia)
    nba_date = target_date                                              # es. "2026-10-03" (per API NBA)
    italian_date = TimeManager.nba_date_to_italian_date(target_date)    # es. "2026-10-04" (per Supabase / Gameweek)

    api_manager = NbaDataManager(player_ids=[])
    sync = SupabaseSync()

    # Recuperiamo la Gameweek da Supabase usando la DATA ITALIANA
    gameweek = sync.get_gameweek_by_date(italian_date)
    if gameweek is None:
        print(f"Avviso: Nessuna gameweek trovata su Supabase per la data italiana {italian_date}. L'aggiornamento dei matchups verrà saltato.")

    # 1. Recupero i nomi di tutti i team da data/fanta_teams.json
    fanta_teams_path = os.path.join("data", "fanta_teams.json")
    if not os.path.exists(fanta_teams_path):
        print(f"Errore: {fanta_teams_path} non trovato.")
        return []

    with open(fanta_teams_path, "r", encoding="utf-8") as f:
        fanta_teams = json.load(f)

    team_names = list(fanta_teams.keys())

    # 2. Scarico i boxscores dell'API usando la DATA NBA (USA)
    print(f"Scaricamento dati API per la data NBA {nba_date} (corrispondente al {italian_date} in Italia)...")
    _, daily_boxscores = api_manager.fetch_and_sync(nba_date)

    if not daily_boxscores:
        print(f"Nessun boxscore recuperato dall'API per la data {nba_date}.")
        return []

    updated_teams = []

    # 3. Itero su ciascuna squadra
    for team_name in team_names:
        team = Team(team_name)
        team.target_date = italian_date  # Salviamo nello state la data di lega/italiana

        state_file = team.filename  # "data/<nome_team_lower>_state.json"

        if not os.path.exists(state_file):
            print(f"File di stato non trovato: {state_file}. Salto...")
            continue

        with open(state_file, "r", encoding="utf-8") as f:
            state_data = json.load(f)

        team.lineup = state_data.get("lineup", "2-2-1")

        # 4. Ricostruisco il roster e calcolo il punteggio per la data NBA
        for p_data in state_data.get("roster", []):
            player = Player.from_dict(p_data)
            role = p_data.get("role", "RESERVE")

            # I boxscore dell'API contengono GAME_DATE == nba_date ("2026-10-03")
            player.calculate_score(daily_boxscores, target_date=nba_date, average=False)
            team.add_player(player, role)

        # 5. Calcola il totale del team e salva in locale
        team.calculate_total_score(role_configs)
        team.save_to_json()
        updated_teams.append(team)

        print(f"-> {team_name} aggiornato: {team.score} pt totali.")

        # 6. Sincronizzazione con Supabase usando la DATA ITALIANA e la Gameweek trovata
        try:
            team_id = sync.get_team_id_by_name(team_name)
            if team_id:
                if gameweek is not None:
                    sync.update_team_score_for_gameweek(team_id, gameweek, team.score)

                # Aggiorna last_updated_date con la data italiana
                sync.update_team_last_updated_date(team_id, italian_date)
            else:
                print(f"Attenzione: Impossibile trovare l'ID Supabase per il team '{team_name}'.")
        except Exception as e:
            print(f"Errore durante l'aggiornamento su Supabase per {team_name}: {e}")

    return updated_teams


# ==========================================
# Esempio di esecuzione:
# ==========================================
if __name__ == "__main__":
    ROLES_CONFIG = {
        "STARTER": {"mult": 1.0},
        "SIXTH": {"mult": 1.0},
        "BENCH": {"mult": 0.5},
        "RESERVE": {"mult": 0.0}
    }

    DATA_TARGET = "2026-10-03"

    squadre_aggiornate = update_all_teams_scores_via_api(DATA_TARGET, ROLES_CONFIG)