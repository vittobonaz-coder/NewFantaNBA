import json
from api_nba import NbaDataManager
from fanta_obj import Team, Player
from supabase_manager import SupabaseSync
import os

def run_setup():
    sync = SupabaseSync()
    api_manager = NbaDataManager(player_ids=[])
    
    with open(os.path.join("data", "fanta_teams.json"), "r", encoding="utf-8") as f:
        teams_data = json.load(f)
    
    for team_name, roles_map in teams_data.items():
        team = Team(name=team_name)
        # Scarica anagrafiche NBA
        p_ids = api_manager.get_players_ids_by_name(list(roles_map.keys()))
        info_path = os.path.join("data", f"{team_name.replace(' ', '_').lower()}_info.json")
        api_manager.fetch_players_info(p_ids, filename=info_path)
        
        # --- AGGIUNTA: Popola il team con i dati appena scaricati ---
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

if __name__ == "__main__":
    run_setup()