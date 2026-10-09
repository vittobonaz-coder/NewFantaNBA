import json
import os
from api_nba import NbaDataManager
from fanta_obj import Team, Player
from supabase_manager import SupabaseSync
from datetime import datetime, timedelta

sync = SupabaseSync()
api_manager = NbaDataManager(player_ids=[])

fanta_teams_path = os.path.join("data", "fanta_teams.json")
if os.path.exists(fanta_teams_path):
    with open(fanta_teams_path, "r", encoding="utf-8") as f:
        teams_data = json.load(f)
else:
    teams_data = {}


def ensure_history_files():
    """Crea i file storici se non esistono."""
    data_dir = "data"
    files = ["historical_boxscores.json", "historical_games.json"]
    
    for filename in files:
        filepath = os.path.join(data_dir, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump([], f)
            print(f"File {filename} creato.")
        else:
            print(f"File {filename} già presente.")


def run_teams_setup():
    # --- SETUP DELLE SQUADRE E DEI ROSTER ---
    ensure_history_files()
    
    for team_name, roles_map in teams_data.items():
        team = Team(name=team_name)
        # Scarica anagrafiche NBA
        p_ids = api_manager.get_players_ids_by_name(list(roles_map.keys()))
        info_path = os.path.join("data", f"{team_name.replace(' ', '_').lower()}_info.json")
        api_manager.fetch_players_info(p_ids, filename=info_path)
        
        with open(info_path, "r", encoding="utf-8") as f:
            players_info = json.load(f)
            
        for p_info in players_info:
            player = Player(
                id=p_info["PLAYER_ID"],
                name=p_info["PLAYER_NAME"],
                team_abbreviation=p_info["TEAM"],
                position=p_info["POSITION"]
            )
            team.add_player(player, roles_map.get(p_info["PLAYER_NAME"], "RISERVA"))

        # Push struttura squadra
        sync.push_team(team)   
        
    print("Setup statico completato (fanta_teams, nba_players, rosters).")


def generate_calendar(team_names: list[str], start_date_str: str, end_date_str: str) -> list[dict]:
    """
    Genera il calendario delle giornate e i relativi matchup tramite algoritmo Round-Robin Berger.
    
    :param team_names: Lista con i nomi delle squadre.
    :param start_date_str: Data inizio campionato in formato 'YYYY-MM-DD'.
    :param end_date_str: Data fine campionato in formato 'YYYY-MM-DD'.
    :return: Lista di dizionari rappresenta le giornate.
    """
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()

    # 1. Calcola gli intervalli di date per ciascuna giornata (7 giorni ciascuna, l'ultima prende i restanti)
    periods = []
    curr_start = start_date
    while curr_start <= end_date:
        curr_end = curr_start + timedelta(days=6)
        if curr_end > end_date:
            curr_end = end_date
        
        periods.append({
            "start_date": curr_start.strftime("%Y-%m-%d"),
            "end_date": curr_end.strftime("%Y-%m-%d")
        })
        curr_start = curr_end + timedelta(days=1)

    # 2. Algoritmo Round-Robin (Berger) per generare le giornate di scontro
    teams = list(team_names)
    # Se il numero di squadre è dispari, aggiungiamo un 'BYE' (riposo)
    if len(teams) % 2 != 0:
        teams.append("BYE")
        
    num_teams = len(teams)
    rounds_per_cycle = num_teams - 1
    half = num_teams // 2
    
    # Genera un ciclo completo di gironi (Round-Robin)
    unique_rounds = []
    for r in range(rounds_per_cycle):
        matchups = []
        for i in range(half):
            t1 = teams[i]
            t2 = teams[num_teams - 1 - i]
            if t1 != "BYE" and t2 != "BYE":
                # Alterna casa/trasferta in base al turno
                if r % 2 == 0:
                    matchups.append({"home_team": t1, "away_team": t2})
                else:
                    matchups.append({"home_team": t2, "away_team": t1})
        unique_rounds.append(matchups)
        # Ruota l'array delle squadre tenendo la prima fissa
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]

    # 3. Assegna i gironi ripetuti alle giornate (periodi)
    calendar = []
    for idx, period in enumerate(periods):
        round_matchups = unique_rounds[idx % rounds_per_cycle]
        
        formatted_matchups = []
        for m in round_matchups:
            formatted_matchups.append({
                "home_team": m["home_team"],
                "away_team": m["away_team"],
                "home_score": 0.00,
                "away_score": 0.00,
                "was_played": False,
                "home_lineup": "2-2-1",
                "away_lineup": "2-2-1"
            })

        calendar.append({
            "round_number": idx + 1,
            "start_date": period["start_date"],
            "end_date": period["end_date"],
            "matchups": formatted_matchups
        })

    return calendar


def run_calendar_setup(start_date: str, end_date: str):
    print(f"Generazione calendario dal {start_date} al {end_date}...")
    team_names = list(teams_data.keys())
    calendar = generate_calendar(team_names, start_date, end_date)
    
    # Salvataggio in locale
    calendar_path = os.path.join("data", "calendar.json")
    with open(calendar_path, "w", encoding="utf-8") as f:
        json.dump(calendar, f, indent=4, ensure_ascii=False)
        
    # Push del calendario su Supabase (se implementato in SupabaseSync)
    sync.push_calendar(calendar)

    print(f"Calendario di {len(calendar)} giornate generato e salvato con successo!")


if __name__ == "__main__":
    run_teams_setup()
    run_calendar_setup(start_date="2026-10-04", end_date="2026-10-16")
    SupabaseSync().sync_standings()