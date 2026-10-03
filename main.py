import os
import flet as ft
import json
from api_nba import NbaDataManager
from fanta_obj import Team
from ui_court import Court, ROLE_CONFIGS

def init_all_teams():
    api_manager = NbaDataManager(player_ids=[])
    DATA_TARGET = "2026-04-12"
    
    # Carica la configurazione
    with open(os.path.join("data", "fanta_teams.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
        
    teams = []
    for team_name, roles_map in data.items():
        team = Team(name=team_name)
        
        # Carica i dati anagrafici dal file locale e aggiorna solo i punteggi tramite i boxscore
        team.update_team_scores_for_date(
            api_manager=api_manager,
            target_date=DATA_TARGET,
            names_list=list(roles_map.keys()),
            roles_dict=roles_map
        )
        team.calculate_total_score(ROLE_CONFIGS)
        teams.append(team)
    return teams

teams_instances = init_all_teams()
current_team = teams_instances[0] # Bonaz

# 3. Applicazione Flet
def main(page: ft.Page) -> None:
    page.title = 'Fanta NBA - Dashboard'
    # page.scroll = ft.ScrollMode.AUTO
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 358
    page.window.height = 757

    # Verifica validità
    if not current_team.is_valid_roster():
        page.add(ft.Text(f"Errore Roster: {current_team.name}", color="red"))
        return
    
    from ui_court import MainDashboard
    
    # Aggiungiamo la dashboard completa
    page.add(MainDashboard(current_team))

if __name__ == "__main__":
    # Render usa la variabile d'ambiente PORT
    port = int(os.environ.get("PORT", 8080))
    
    ft.run(main=main, 
        port=port, 
        host="0.0.0.0", 
        assets_dir="assets",
    )