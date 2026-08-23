import os
import flet as ft
import json
from api_nba import NbaDataManager
from fanta_obj import Team
from ui_court import Court, ROLE_CONFIGS

# 1. Caricamento squadre dal File JSON
def load_fanta_teams(filepath="fanta_teams.json"):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

# Carichiamo il dizionario con tutte le squadre
ALL_TEAMS_DATA = load_fanta_teams()
DATA_TARGET = "2026-04-12"

# Lista che conterrà le istanze della classe Team
teams_instances = []
api_manager = NbaDataManager(player_ids=[])

# 2. Inizializzazione Automatica di tutte le squadre
for team_name, roles_map in ALL_TEAMS_DATA.items():
    team = Team(name=team_name)
    
    # Se non esiste il file locale, scarica i dati
    if not team.load_from_json():
        print(f"Dati locali per {team_name} non trovati. Scarico da API...")
        team.load_data_from_api(
            api_manager=api_manager,
            target_date=DATA_TARGET,
            names_list=list(roles_map.keys()),
            roles_dict=roles_map
        )
        team.calculate_total_score(ROLE_CONFIGS)
        team.save_to_json()
    
    teams_instances.append(team)

# Per la UI, scegliamo quale squadra visualizzare (es. la prima)
current_team = teams_instances[1]
# current_team = teams_instances[1]

# 3. Applicazione Flet
def main(page: ft.Page) -> None:
    page.title = 'Fanta NBA - Dashboard'
    page.scroll = ft.ScrollMode.AUTO
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 358
    page.window.height = 757

    # Verifica validità
    if not current_team.is_valid_roster():
        page.add(ft.Text(f"Errore Roster: {current_team.name}", color="red"))
        return

    # Aggiungiamo un titolo per capire quale squadra stiamo guardando
    page.add(ft.Text(f"SQUADRA: {current_team.name}", size=25, weight="bold"))
    
    # Creiamo l'interfaccia Court passandogli l'istanza del team
    court_ui = Court(current_team)
    page.add(court_ui)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    ft.run(main=main, 
        port=port, 
        host="0.0.0.0", 
        assets_dir="assets",
    )