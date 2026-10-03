import flet as ft
import json
from api_nba import NbaDataManager
from fanta_obj import Team
from ui_court import Court, ROLE_CONFIGS
import os

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
    ft.run(main=main)







# import flet as ft
# from fanta_obj import Team
# from ui_court import MainDashboard

# # 1. Caricamento squadre dai file JSON (che sono stati generati dal setup)
# # Sostituiamo il caricamento complesso con un semplice load_from_json
# def get_all_teams():
#     import glob
#     teams = []
#     # Leggiamo tutti i file *_state.json creati dallo script di setup
#     for filepath in glob.glob("*_state.json"):
#         team_name = filepath.replace("_state.json", "").replace("_", " ").title()
#         team = Team(name=team_name)
#         if team.load_from_json():
#             teams.append(team)
#     return teams

# teams_instances = get_all_teams()

# # 2. Selezione della squadra (logica che evolverà in login utente)
# if not teams_instances:
#     print("Nessun file di stato trovato! Esegui prima setup_fanta_teams.py")
#     exit()

# current_team = teams_instances[0] 

# def main(page: ft.Page) -> None:
#     page.title = 'Fanta NBA - Dashboard'
#     page.vertical_alignment = ft.MainAxisAlignment.CENTER
#     page.theme_mode = ft.ThemeMode.DARK
#     page.window.width = 358
#     page.window.height = 757

#     if not current_team.is_valid_roster():
#         page.add(ft.Text(f"Errore Roster: {current_team.name}", color="red"))
#         return
    
#     page.add(MainDashboard(current_team))

# if __name__ == "__main__":
#     ft.run(main=main)