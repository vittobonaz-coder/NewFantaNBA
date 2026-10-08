from datetime import datetime, timedelta
from curl_cffi import requests
import flet as ft

# Calcoliamo dinamicamente la data di ieri
ieri = datetime.now() - timedelta(days=1)
data_visualizzazione = ieri.strftime("%Y-%m-%d")

# URL della CDN ufficiale NBA
url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

# Header HTTP completi per la CDN
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
}

print(f"🚀 Invio della richiesta alla CDN Ufficiale NBA per la data: {data_visualizzazione}...")
print(f"🔗 URL INTERROGATO: {url}")

partite_salvate = []

try:
    response = requests.get(url, headers=headers, impersonate="chrome", timeout=10)
    print(f"📊 Status Code ricevuto dal server: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        partite_salvate = data.get("scoreboard", {}).get("games", [])
        print(f"✅ Connessione riuscita! Recuperate {len(partite_salvate)} partite.")
    elif response.status_code == 404:
        print(f"⚠️ Nessuna partita trovata a calendario per il giorno {data_visualizzazione} (404).")
    else:
        print(f"❌ Errore imprevisto dalla CDN (Status: {response.status_code})")

except Exception as e:
    print(f"💥 Errore durante il recupero dati: {e}")


def main(page: ft.Page) -> None:
    page.title = "Fanta NBA - Dashboard CDN"
    page.vertical_alignment = "center"
    page.theme_mode = "dark"
    page.window.width = 400
    page.window.height = 750
    page.padding = 20

    header = ft.Text(
        f"Partite del {data_visualizzazione}",
        size=22,
        weight="bold",
        color="amber",
    )

    lista_partite = ft.ListView(expand=True, spacing=15)

    if not partite_salvate:
        lista_partite.controls.append(
            ft.Text(
                "Nessun match trovato per questa data nella CDN NBA.",
                italic=True,
            )
        )
    else:
        for game in partite_salvate:
            home_team = game.get("homeTeam", {}).get("teamName", "Home")
            away_team = game.get("awayTeam", {}).get("teamName", "Away")

            score_home = game.get("homeTeam", {}).get("score", "-")
            score_away = game.get("awayTeam", {}).get("score", "-")

            status = game.get("gameStatusText", "Unknown")

            match_card = ft.Card(
                content=ft.Container(
                    padding=15,
                    content=ft.Column([
                        ft.Row(
                            [
                                ft.Text(
                                    f"{home_team}",
                                    weight="bold",
                                    size=16,
                                ),
                                ft.Text(
                                    f"{str(score_home)}",
                                    size=18,
                                    weight="bold",
                                    color="blue200",
                                ),
                            ],
                            alignment="spaceBetween",
                        ),
                        ft.Row(
                            [
                                ft.Text(
                                    f"{away_team}",
                                    weight="bold",
                                    size=16,
                                ),
                                ft.Text(
                                    f"{str(score_away)}",
                                    size=18,
                                    weight="bold",
                                    color="blue200",
                                ),
                            ],
                            alignment="spaceBetween",
                        ),
                        ft.Divider(
                            height=5, color="surfaceVariant"
                        ),
                        ft.Text(
                            f"Stato: {status}",
                            size=12,
                            color="grey400",
                            italic=True,
                        ),
                    ]),
                )
            )
            lista_partite.controls.append(match_card)

    page.add(header, ft.Divider(height=10), lista_partite)


if __name__ == "__main__":
    ft.run(main)





















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
