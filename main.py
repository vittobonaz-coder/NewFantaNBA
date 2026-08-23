import os
import flet as ft
import json
from api_nba import NbaDataManager
from fanta_obj import Team
from ui_court import Court, ROLE_CONFIGS

def load_fanta_teams(filepath="fanta_teams.json"):
    # Verifica che il file esista per evitare crash all'avvio
    if not os.path.exists(filepath):
        print(f"ERRORE: {filepath} non trovato!")
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

# Caricamento configurazioni (veloce)
ALL_TEAMS_DATA = load_fanta_teams()
DATA_TARGET = "2026-04-12"
api_manager = NbaDataManager(player_ids=[])

def main(page: ft.Page) -> None:
    page.title = 'Fanta NBA - Dashboard'
    page.theme_mode = ft.ThemeMode.DARK
    
    # Mostriamo un caricamento mentre inizializziamo i dati
    loading_text = ft.Text("Inizializzazione dati NBA in corso... attendere.", size=20)
    progress_ring = ft.ProgressRing()
    loading_container = ft.Column([loading_text, progress_ring], horizontal_alignment="center")
    page.add(loading_container)
    
    # 2. Inizializzazione Squadre (Spostata dentro main così il server è già attivo)
    teams_instances = []
    for team_name, roles_map in ALL_TEAMS_DATA.items():
        team = Team(name=team_name)
        if not team.load_from_json():
            # Questo scaricamento avverrà mentre la pagina è già "viva" su Render
            team.load_data_from_api(
                api_manager=api_manager,
                target_date=DATA_TARGET,
                names_list=list(roles_map.keys()),
                roles_dict=roles_map
            )
            team.calculate_total_score(ROLE_CONFIGS)
            team.save_to_json()
        teams_instances.append(team)

    # Una volta pronti, puliamo la pagina e carichiamo la UI reale
    page.clean()
    
    if not teams_instances:
        page.add(ft.Text("Nessuna squadra caricata. Controlla fanta_teams.json"))
        return

    current_team = teams_instances[0] # Mostra la prima squadra

    page.add(ft.Text(f"SQUADRA: {current_team.name}", size=25, weight="bold"))
    page.add(Court(current_team))
    page.update()

if __name__ == "__main__":
    # Render usa la variabile d'ambiente PORT
    port = int(os.environ.get("PORT", 8080))
    
    ft.run(main=main, 
        port=port, 
        host="0.0.0.0", 
        assets_dir="assets",
    )