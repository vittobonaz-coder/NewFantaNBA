import os
import requests
import flet as ft
import json
import os
from datetime import datetime, timedelta


# Per eliminare qualsiasi problema con il terminale di Windows,
# INCOLLA LA TUA CHIAVE DIRETTAMENTE QUI SOTTO tra le virgolette:
api_key = "78008e43b200285bc518fb31ce23ef20"

# Calcola dinamicamente la data di ieri nel formato YYYY-MM-DD
ieri = datetime.now()
# ieri = datetime.now() - timedelta(days=1)
data_ricerca = ieri.strftime("%Y-%m-%d")

# 1. URL CORRETTO PER PASSARE DA RAPIDAPI (Evita il blocco Cloudflare)
url = "https://v1.basketball.api-sports.io/games"

# Parametri richiesti dall'endpoint games di RapidAPI
# Parametri per filtrare per data e Pre Season
params = {
    "date": data_ricerca,  # Sostituisci con la data desiderata (YYYY-MM-DD)
    "league": "nba",
    "season": 2026,
    "stage": "preseason"  # Specifica Pre Season
}

# 2. HEADERS SPECIFICI CON L'HOST CORRETTO
headers = {
    "x-apisports-key": api_key
}


try:
    response = requests.get(url, headers=headers, params=params, timeout=10)
    print(f"📊 Status Code: {response.status_code}")
    print("📄 Risposta:")
    print(response.json())
except requests.exceptions.RequestException as e:
    print(f"💥 Errore: {e}")

# print(f"🚀 Invio della richiesta ad API-NBA per la data: {data_ricerca}...")

# # Definiamo la variabile a livello globale per evitare in ogni caso il NameError
# partite_salvate = []

# try:
#     response = requests.get(url, headers=headers, params=params, timeout=10)
    
#     print(f"📊 Status Code ricevuto dal server: {response.status_code}")
    
#     if response.status_code == 200:
#         data = response.json()
#         # Estraiamo la lista dei match restituiti dall'API
#         partite_salvate = data.get("response", [])
#         print(f"✅ Recuperate {len(partite_salvate)} partite.")
#     else:
#         print(f"❌ Errore dall'API ({response.status_code}): {response.text}")
    
# except requests.exceptions.RequestException as e:
#     print(f"💥 Errore di rete: {e}")



# def main(page: ft.Page) -> None:
#     page.title = 'Fanta NBA - Dashboard'
#     page.vertical_alignment = ft.MainAxisAlignment.CENTER
#     page.theme_mode = ft.ThemeMode.DARK
#     page.window.width = 358
#     page.window.height = 757


#     # Titolo dell'applicazione
#     header = ft.Text(
#         f"Partite del {data_ricerca}", 
#         size=22, 
#         weight=ft.FontWeight.BOLD, 
#         color=ft.Colors.AMBER
#     )

#     lista_partite = ft.ListView(expand=1, spacing=15)

#     if not partite_salvate:
#         lista_partite.controls.append(
#             ft.Text("Nessuna partita in programma o giocata per questa data.", italic=True)
#         )
#     else:
#         for match in partite_salvate:
#             # Estrazione dei dati in modo sicuro dai dizionari annidati
#             home_team = match.get("teams", {}).get("home", {}).get("name", "Home")
#             away_team = match.get("teams", {}).get("away", {}).get("name", "Away")
            
#             # Punteggi (se la partita non è iniziata potrebbero essere None)
#             score_home = match.get("scores", {}).get("home", {}).get("total", "-")
#             score_away = match.get("scores", {}).get("away", {}).get("total", "-")
            
#             # Stato attuale della partita (es. "Finished", "Not Started")
#             status = match.get("status", {}).get("long", "Unknown")

#             # Creazione di una card grafica per ogni partita
#             match_card = ft.Card(
#                 content=ft.Container(
#                     padding=15,
#                     content=ft.Column([
#                         ft.Row([
#                             ft.Text(f"{home_team}", weight=ft.FontWeight.BOLD, size=16),
#                             ft.Text(f"{score_home}", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_200)
#                         ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        
#                         ft.Row([
#                             ft.Text(f"{away_team}", weight=ft.FontWeight.BOLD, size=16),
#                             ft.Text(f"{score_away}", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_200)
#                         ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        
#                         ft.Divider(height=5, color=ft.Colors.SURFACE_VARIANT),
#                         ft.Text(f"Stato: {status}", size=12, color=ft.Colors.GREY_400, italic=True)
#                     ])
#                 )
#             )
#             lista_partite.controls.append(match_card)

#     # Aggiunge i componenti alla schermata
#     page.add(header, ft.Divider(height=10), lista_partite)

# if __name__ == "__main__":
#     ft.run(main=main)








# import flet as ft
# import json
# import os
# from api_nba import NbaDataManager
# from fanta_obj import Team
# from ui_court import Court, ROLE_CONFIGS, MainDashboard, LoginView


# def main(page: ft.Page) -> None:
#     page.title = 'Fanta NBA - Dashboard'
#     page.vertical_alignment = ft.MainAxisAlignment.CENTER
#     page.theme_mode = ft.ThemeMode.DARK
#     page.window.width = 358
#     page.window.height = 757

#     def on_login_success(user_data):
#         team_name = user_data["username"].replace("_user", "") 
#         team = Team(name=team_name)
        
#         # PROVA A CARICARE LO STATO SALVATO
#         if not team.load_from_json():
#             print(f"File di stato non trovato per {team_name}, inizializzo da API...")
            
#             # Carichiamo la configurazione dai file JSON
#             with open("data/fanta_teams.json", "r", encoding="utf-8") as f:
#                 all_teams_config = json.load(f)
            
#             roles_map = all_teams_config.get(team_name, {})
#             names_list = list(roles_map.keys())
            
#             # Inizializziamo via API (usando il metodo che avevi già predisposto)
#             api_manager = NbaDataManager(player_ids=[])
#             team.update_team_scores_for_date(
#                 api_manager=api_manager,
#                 target_date="2026-10-03", # Data di riferimento per il setup iniziale
#                 names_list=names_list,
#                 roles_dict=roles_map
#             )
#             # Salviamo per le prossime volte
#             team.save_to_json()
        
#         if not team.is_valid_roster():
#             page.add(ft.Text(f"Errore Roster: {team.name}", color="red"))
#             return
        
#         page.clean()
#         page.add(MainDashboard(team))
#         page.update()
    
#     # Avvio con schermata di login
#     page.add(LoginView(page, on_login_success))

# if __name__ == "__main__":
#     ft.run(main=main)