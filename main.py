import flet as ft
import json
import os
from api_nba import NbaDataManager
from fanta_obj import Team
from ui_court import Court, ROLE_CONFIGS, MainDashboard, LoginView


def main(page: ft.Page) -> None:
    page.title = 'Fanta NBA - Dashboard'
    # page.scroll = ft.ScrollMode.AUTO
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 358
    page.window.height = 757

    def on_login_success(user_data):
        team_name = user_data["username"].replace("_user", "") 
        team = Team(name=team_name)
        
        # PROVA A CARICARE LO STATO SALVATO
        if not team.load_from_json():
            print(f"File di stato non trovato per {team_name}, inizializzo da API...")
            
            # Carichiamo la configurazione dai file JSON
            with open("data/fanta_teams.json", "r", encoding="utf-8") as f:
                all_teams_config = json.load(f)
            
            roles_map = all_teams_config.get(team_name, {})
            names_list = list(roles_map.keys())
            
            # Inizializziamo via API (usando il metodo che avevi già predisposto)
            api_manager = NbaDataManager(player_ids=[])
            team.update_team_scores_for_date(
                api_manager=api_manager,
                target_date="2026-10-03", # Data di riferimento per il setup iniziale
                names_list=names_list,
                roles_dict=roles_map
            )
            # Salviamo per le prossime volte
            team.save_to_json()
        
        if not team.is_valid_roster():
            page.add(ft.Text(f"Errore Roster: {team.name}", color="red"))
            return
        
        page.clean()
        page.add(MainDashboard(team))
        page.update()
    
    # Avvio con schermata di login
    page.add(LoginView(page, on_login_success))

if __name__ == "__main__":
    # Render usa la variabile d'ambiente PORT
    port = int(os.environ.get("PORT", 8080))
    
    ft.run(main=main, 
        port=port, 
        host="0.0.0.0", 
        assets_dir="assets",
    )