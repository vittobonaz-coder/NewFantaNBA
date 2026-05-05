from api_nba import NbaDataManager
from fanta_obj import Team
from ui_court import Court
import flet as ft
import os

# 1. Configurazione Iniziale
DATA_TARGET = "2026-04-12"
roles_map = {
    "Al Horford": "STARTER", "LeBron James": "STARTER", "Jarred Vanderbilt": "STARTER",
    "James Harden": "STARTER", "Stephen Curry": "STARTER", "Darius Garland": "SIXTH",
    "LaMelo Ball": "BENCH", "Scottie Barnes": "BENCH", "Alperen Sengun": "BENCH",
    "Simone Fontecchio": "BENCH", "Victor Wembanyama": "RESERVE",
    "Paul George": "RESERVE", "Russell Westbrook": "RESERVE"
}
player_names = list(roles_map.keys())

my_team = Team(name="MyTeam")

# 2. Logica di Caricamento Intelligente
if not my_team.load_from_json():
    print("File locale non trovato. Scarico dati dalle API...")
    api_manager = NbaDataManager(player_ids=[])
    my_team.load_data_from_api(
        api_manager=api_manager,
        target_date=DATA_TARGET,
        names_list=player_names,
        roles_dict=roles_map
    )
    # Calcolo iniziale del punteggio
    from ui_court import ROLE_CONFIGS # Importiamo i pesi
    my_team.calculate_total_score(ROLE_CONFIGS)
    # Salviamo subito per il prossimo avvio
    my_team.save_to_json()

# 3. Applicazione Flet
def main(page: ft.Page) -> None:
    page.title = 'Players Cards'
    page.scroll = ft.ScrollMode.AUTO
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 358
    page.window.height = 757

    # Verifica validità del roster direttamente dal metodo della classe Team
    if not my_team.is_valid_roster():
        page.add(ft.Text("Squadra non consentita (Requisito: 5G, 5A, 3C)", color="red"))
        return

    # Passiamo l'output formattato dalla classe Team direttamente al Court
    page.add(Court(my_team))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    ft.run(main=main, 
        port=port, 
        host="0.0.0.0", 
        assets_dir="assets",
    )