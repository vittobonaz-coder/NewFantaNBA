from datetime import datetime, timedelta
import requests
import flet as ft

# 1. Definizione data (YYYYMMDD per l'API ESPN)
data_target = datetime.now() - timedelta(days=1)
data_param = data_target.strftime("%Y%m%d")      # es. "20261006"
data_visualizzazione = data_target.strftime("%Y-%m-%d")

# 2. Endpoint pubblico ESPN (nessun blocco WAF)
url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={data_param}"

print(f"🚀 Richiesta dati a ESPN per la data: {data_visualizzazione}...")

partite_salvate = []

try:
    response = requests.get(url, timeout=10)
    print(f"📊 Status Code: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        events = data.get("events", [])

        for event in events:
            comp = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])

            # Estrazione squadre casa e trasferta
            home = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away = next((c for c in competitors if c.get("homeAway") == "away"), {})

            partite_salvate.append({
                "homeTeam": home.get("team", {}).get("displayName", "Home"),
                "homeScore": home.get("score", "-"),
                "awayTeam": away.get("team", {}).get("displayName", "Away"),
                "awayScore": away.get("score", "-"),
                "status": event.get("status", {}).get("type", {}).get("detail", "N/D")
            })

        print(f"✅ Connessione riuscita! Recuperate {len(partite_salvate)} partite.")
    else:
        print(f"❌ Errore server: {response.status_code}")

except Exception as e:
    print(f"💥 Errore durante il recupero dati: {e}")


def main(page: ft.Page) -> None:
    page.title = "Fanta NBA - Dashboard ESPN"
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
                "Nessun match trovato per questa data.",
                italic=True,
            )
        )
    else:
        for game in partite_salvate:
            match_card = ft.Card(
                content=ft.Container(
                    padding=15,
                    content=ft.Column([
                        ft.Row(
                            [
                                ft.Text(f"{game['homeTeam']}", weight="bold", size=16),
                                ft.Text(f"{game['homeScore']}", size=18, weight="bold", color="blue200"),
                            ],
                            alignment="spaceBetween",
                        ),
                        ft.Row(
                            [
                                ft.Text(f"{game['awayTeam']}", weight="bold", size=16),
                                ft.Text(f"{game['awayScore']}", size=18, weight="bold", color="blue200"),
                            ],
                            alignment="spaceBetween",
                        ),
                        ft.Divider(height=5, color="surfaceVariant"),
                        ft.Text(
                            f"Stato: {game['status']}",
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





# from curl_cffi import requests
# import flet as ft

# HEADERS = {
#     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
#     "Referer": "https://www.nba.com/",
# }

# def get_json(url: str) -> dict:
#     res = requests.get(url, headers=HEADERS, impersonate="chrome", timeout=10)
#     return res.json() if res.status_code == 200 else {}

# def main(page: ft.Page) -> None:
#     page.scroll = "adaptive"

#     # 1. Recupero lo scoreboard del giorno
#     sb = get_json("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json")
#     partite = sb.get("scoreboard", {}).get("games", [])

#     # 2. Ricerca automatica del gameId della sfida Bulls vs Suns
#     game_id = None
#     for g in partite:
#         squadre = [g["homeTeam"]["teamName"].lower(), g["awayTeam"]["teamName"].lower()]
#         if "bulls" in squadre and "suns" in squadre:
#             game_id = g["gameId"]
#             break

#     if not game_id:
#         page.add(ft.Text("⚠️ Partita Chicago Bulls - Phoenix Suns non trovata a calendario oggi."))
#         return

#     # 3. Scarico il tabellino specifico ed emetto le righe di testo
#     box = get_json(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json").get("game", {})

#     for team_key in ["homeTeam", "awayTeam"]:
#         team = box.get(team_key, {})
#         page.add(
#             ft.Text(f"\n🏀 {team.get('teamCity')} {team.get('teamName')} ({team.get('score')} PTS)", weight="bold", size=18)
#         )
        
#         for p in team.get("players", []):
#             st = p.get("statistics", {})
#             if p.get("status") == "ACTIVE" and st.get("points", 0) > 0:
#                 nome = f"{p.get('firstName', '')[0]}. {p.get('familyName')}"
#                 linea = f"{nome}: {st.get('points', 0)} PTS | {st.get('reboundsTotal', 0)} REB | {st.get('assists', 0)} AST"
#                 page.add(ft.Text(linea))

# if __name__ == "__main__":
#     ft.run(main)






# from datetime import datetime, timedelta
# from curl_cffi import requests
# import flet as ft

# # Calcoliamo dinamicamente la data di ieri
# ieri = datetime.now() - timedelta(days=1)
# data_visualizzazione = ieri.strftime("%Y-%m-%d")

# # URL della CDN ufficiale NBA
# url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

# # Header HTTP completi per la CDN
# headers = {
#     "User-Agent": (
#         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
#         " (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
#     ),
#     "Accept": "application/json, text/plain, */*",
#     "Origin": "https://www.nba.com",
#     "Referer": "https://www.nba.com/",
# }

# print(f"🚀 Invio della richiesta alla CDN Ufficiale NBA per la data: {data_visualizzazione}...")
# print(f"🔗 URL INTERROGATO: {url}")

# partite_salvate = []

# try:
#     response = requests.get(url, headers=headers, impersonate="chrome", timeout=10)
#     print(f"📊 Status Code ricevuto dal server: {response.status_code}")

#     if response.status_code == 200:
#         data = response.json()
#         partite_salvate = data.get("scoreboard", {}).get("games", [])
#         print(f"✅ Connessione riuscita! Recuperate {len(partite_salvate)} partite.")
#     elif response.status_code == 404:
#         print(f"⚠️ Nessuna partita trovata a calendario per il giorno {data_visualizzazione} (404).")
#     else:
#         print(f"❌ Errore imprevisto dalla CDN (Status: {response.status_code})")

# except Exception as e:
#     print(f"💥 Errore durante il recupero dati: {e}")


# def main(page: ft.Page) -> None:
#     page.title = "Fanta NBA - Dashboard CDN"
#     page.vertical_alignment = "center"
#     page.theme_mode = "dark"
#     page.window.width = 400
#     page.window.height = 750
#     page.padding = 20

#     header = ft.Text(
#         f"Partite del {data_visualizzazione}",
#         size=22,
#         weight="bold",
#         color="amber",
#     )

#     lista_partite = ft.ListView(expand=True, spacing=15)

#     if not partite_salvate:
#         lista_partite.controls.append(
#             ft.Text(
#                 "Nessun match trovato per questa data nella CDN NBA.",
#                 italic=True,
#             )
#         )
#     else:
#         for game in partite_salvate:
#             home_team = game.get("homeTeam", {}).get("teamName", "Home")
#             away_team = game.get("awayTeam", {}).get("teamName", "Away")

#             score_home = game.get("homeTeam", {}).get("score", "-")
#             score_away = game.get("awayTeam", {}).get("score", "-")

#             status = game.get("gameStatusText", "Unknown")

#             match_card = ft.Card(
#                 content=ft.Container(
#                     padding=15,
#                     content=ft.Column([
#                         ft.Row(
#                             [
#                                 ft.Text(
#                                     f"{home_team}",
#                                     weight="bold",
#                                     size=16,
#                                 ),
#                                 ft.Text(
#                                     f"{str(score_home)}",
#                                     size=18,
#                                     weight="bold",
#                                     color="blue200",
#                                 ),
#                             ],
#                             alignment="spaceBetween",
#                         ),
#                         ft.Row(
#                             [
#                                 ft.Text(
#                                     f"{away_team}",
#                                     weight="bold",
#                                     size=16,
#                                 ),
#                                 ft.Text(
#                                     f"{str(score_away)}",
#                                     size=18,
#                                     weight="bold",
#                                     color="blue200",
#                                 ),
#                             ],
#                             alignment="spaceBetween",
#                         ),
#                         ft.Divider(
#                             height=5, color="surfaceVariant"
#                         ),
#                         ft.Text(
#                             f"Stato: {status}",
#                             size=12,
#                             color="grey400",
#                             italic=True,
#                         ),
#                     ]),
#                 )
#             )
#             lista_partite.controls.append(match_card)

#     page.add(header, ft.Divider(height=10), lista_partite)


# if __name__ == "__main__":
#     ft.run(main)