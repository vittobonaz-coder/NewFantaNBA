from datetime import datetime
import json
import os
import time
from nba_api.stats.endpoints import commonplayerinfo
from nba_api.stats.static import players
import pandas as pd
import requests


class NbaDataManager:

    def __init__(self, player_ids, season="2026-27", s_type="Pre Season"):
        # self.player_ids contiene sempre gli ID UFFICIALI NBA (es. [203999, 1628369])
        self.player_ids = [str(pid) for pid in player_ids]
        self.season = season
        self.s_type = s_type

        self.data_dir = "data"
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        self.games_file = os.path.join(self.data_dir, "historical_games.json")
        self.boxscores_file = os.path.join(
            self.data_dir, "historical_boxscores.json"
        )
        self.all_players_file = os.path.join(self.data_dir, "all_players.json")
        self.map_file = os.path.join(
            self.data_dir, "nba_to_espn_players.json"
        )

        # Carica o genera le mappe di traduzione NBA <-> ESPN
        self.nba_to_espn_map, self.espn_to_nba_map = self.load_or_build_id_map()

        # Insieme degli ID ESPN per un filtraggio rapido durante la scarico dei boxscore
        self.espn_player_ids = {
            self.nba_to_espn_map[nba_id]
            for nba_id in self.player_ids
            if nba_id in self.nba_to_espn_map
        }

    # ==========================================
    # SEZIONE 1: GESTIONE MAPPA ID (NBA <-> ESPN)
    # ==========================================

    def load_or_build_id_map(self, force_rebuild=False):
        """Carica le mappe da file JSON o le costruisce da zero combinando NBA API ed ESPN API."""
        if not force_rebuild and os.path.exists(self.map_file):
            try:
                with open(self.map_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("nba_to_espn", {}), data.get(
                        "espn_to_nba", {}
                    )
            except Exception as e:
                print(f"Errore nel caricamento della mappa ID: {e}")

        print("Generazione della mappa di conversione ID NBA <-> ESPN...")

        # 1. Ottieni giocatori attivi NBA Ufficiali
        nba_players_list = players.get_active_players()

        # 2. Ottieni giocatori attivi da ESPN
        espn_players_list = []
        try:
            url_teams = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams?limit=30"
            resp = requests.get(url_teams, timeout=10).json()
            teams = resp["sports"][0]["leagues"][0]["teams"]

            for t in teams:
                t_id = t["team"]["id"]
                r_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{t_id}/roster"
                r_data = requests.get(r_url, timeout=10).json()
                for ath in r_data.get("athletes", []):
                    espn_players_list.append({
                        "espn_id": str(ath["id"]),
                        "name": ath.get("fullName", ""),
                    })
                time.sleep(0.05)
        except Exception as e:
            print(f"Errore durante il recupero dei giocatori ESPN: {e}")

        # 3. Accoppiamento basato sul Nome Normalizzato
        espn_dict = {
            p["name"].lower().replace(".", ""): p["espn_id"]
            for p in espn_players_list
        }

        nba_to_espn = {}
        espn_to_nba = {}

        for nba_p in nba_players_list:
            clean_name = nba_p["full_name"].lower().replace(".", "")
            nba_id = str(nba_p["id"])

            if clean_name in espn_dict:
                espn_id = espn_dict[clean_name]
                nba_to_espn[nba_id] = espn_id
                espn_to_nba[espn_id] = nba_id

        # Salva mappa su file
        with open(self.map_file, "w", encoding="utf-8") as f:
            json.dump(
                {"nba_to_espn": nba_to_espn, "espn_to_nba": espn_to_nba},
                f,
                indent=4,
                ensure_ascii=False,
            )

        print(
            f"Mappa creata: {len(nba_to_espn)} giocatori associati correttamente."
        )
        return nba_to_espn, espn_to_nba

    # ==========================================
    # SEZIONE 2: METODI ESPN (Dati Giornalieri)
    # ==========================================

    def fetch_and_sync(self, date_string):
        """Scarica risultati e boxscore della data in input e li aggiunge ai json"""
        raw_games = self.fetch_matchups(date_string)
        if not raw_games:
            return [], []

        raw_boxscores = self.fetch_boxscores(date_string)

        full_history_games = self.sync_file(raw_games, self.games_file)
        full_history_boxscores = self.sync_file(
            raw_boxscores, self.boxscores_file
        )

        return full_history_games, full_history_boxscores

    def sync_file(self, new_data, filename):
        """Gestisce l'archiviazione dei dati evitando duplicati"""
        if not new_data:
            return []

        data = []
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)

        def get_uid(item):
            return (str(item.get("GAME_ID")), str(item.get("PLAYER_ID")))

        existing_uids = {get_uid(item) for item in data}

        added_count = 0
        for item in new_data:
            if get_uid(item) not in existing_uids:
                data.append(item)
                added_count += 1

        if added_count > 0:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            print(
                f"Sincronizzato {filename}: aggiunti {added_count} nuovi"
                " record."
            )

        return data

    def fetch_matchups(self, date_string):
        """Scarica risultati per il giorno in input via API ESPN Scoreboard"""
        try:
            date_param = pd.to_datetime(date_string).strftime("%Y%m%d")
            game_date_iso = pd.to_datetime(date_string).strftime("%Y-%m-%d")

            url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_param}"
            response = requests.get(url, timeout=10)

            if response.status_code != 200:
                print(f"Errore ESPN Scoreboard HTTP {response.status_code}")
                return []

            events = response.json().get("events", [])
            result = []

            for event in events:
                g_id = str(event.get("id"))
                comp = event.get("competitions", [{}])[0]
                competitors = comp.get("competitors", [])

                home_team = next(
                    (c for c in competitors if c.get("homeAway") == "home"), {}
                )
                away_team = next(
                    (c for c in competitors if c.get("homeAway") == "away"), {}
                )

                home_abbr = home_team.get("team", {}).get(
                    "abbreviation", "HOME"
                )
                away_abbr = away_team.get("team", {}).get(
                    "abbreviation", "AWAY"
                )

                home_score = home_team.get("score", "0")
                away_score = away_team.get("score", "0")

                result.append({
                    "GAME_ID": g_id,
                    "GAME_DATE": game_date_iso,
                    "MATCHUP": f"{away_abbr} @ {home_abbr}",
                    "SCORE": f"{away_score} - {home_score}",
                })

            print(f"{len(result)} games found.")
            return result

        except Exception as e:
            print(f"Games Error: {e}")
            return []

    def fetch_boxscores(self, date_string):
        """Scarica i tabellini via ESPN e riconverte i PLAYER_ID negli ID NBA Ufficiali"""
        try:
            date_param = pd.to_datetime(date_string).strftime("%Y%m%d")
            game_date_iso = pd.to_datetime(date_string).strftime("%Y-%m-%d")

            url_sb = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_param}"
            resp_sb = requests.get(url_sb, timeout=10)
            if resp_sb.status_code != 200:
                return []

            events = resp_sb.json().get("events", [])
            boxscores = []

            for event in events:
                g_id = str(event.get("id"))
                url_box = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={g_id}"
                resp_box = requests.get(url_box, timeout=10)

                if resp_box.status_code != 200:
                    continue

                data_box = resp_box.json()
                teams_players = (
                    data_box.get("boxscore", {}).get("players", [])
                )

                competitors = (
                    data_box.get("header", {})
                    .get("competitions", [{}])[0]
                    .get("competitors", [])
                )
                winners_team_ids = [
                    str(c.get("id")) for c in competitors if c.get("winner")
                ]

                home_c = next(
                    (c for c in competitors if c.get("homeAway") == "home"), {}
                )
                away_c = next(
                    (c for c in competitors if c.get("homeAway") == "away"), {}
                )
                matchup_str = f"{away_c.get('team', {}).get('abbreviation', 'AWAY')} @ {home_c.get('team', {}).get('abbreviation', 'HOME')}"

                for team_entry in teams_players:
                    t_id = str(team_entry.get("team", {}).get("id"))
                    wl_status = "W" if t_id in winners_team_ids else "L"

                    for stat_group in team_entry.get("statistics", []):
                        labels = stat_group.get("names", [])

                        def get_val(stats_arr, name):
                            if name in labels:
                                idx = labels.index(name)
                                val = stats_arr[idx]
                                return val if val != "" else "0"
                            return "0"

                        for ath in stat_group.get("athletes", []):
                            espn_p_id = str(ath.get("athlete", {}).get("id"))

                            # Filtra usando gli ID di ESPN
                            if (
                                self.espn_player_ids
                                and espn_p_id not in self.espn_player_ids
                            ):
                                continue

                            if ath.get("didNotPlay", False):
                                continue

                            stats = ath.get("stats", [])
                            if not stats:
                                continue

                            # Riconversione a ID NBA Ufficiale
                            nba_p_id = self.espn_to_nba_map.get(
                                espn_p_id, espn_p_id
                            )

                            fg = get_val(stats, "FG").split("-")
                            fg3 = get_val(stats, "3PT").split("-")
                            ft = get_val(stats, "FT").split("-")

                            record = {
                                "PLAYER_ID": int(nba_p_id)
                                if nba_p_id.isdigit()
                                else nba_p_id,
                                "GAME_ID": g_id,
                                "GAME_DATE": game_date_iso,
                                "MATCHUP": matchup_str,
                                "WL": wl_status,
                                "MIN": get_val(stats, "MIN"),
                                "FGM": int(fg[0]) if len(fg) > 0 else 0,
                                "FGA": int(fg[1]) if len(fg) > 1 else 0,
                                "FG3M": int(fg3[0]) if len(fg3) > 0 else 0,
                                "FG3A": int(fg3[1]) if len(fg3) > 1 else 0,
                                "FTM": int(ft[0]) if len(ft) > 0 else 0,
                                "FTA": int(ft[1]) if len(ft) > 1 else 0,
                                "OREB": int(get_val(stats, "OREB")),
                                "DREB": int(get_val(stats, "DREB")),
                                "REB": int(get_val(stats, "REB")),
                                "AST": int(get_val(stats, "AST")),
                                "STL": int(get_val(stats, "STL")),
                                "BLK": int(get_val(stats, "BLK")),
                                "TOV": int(get_val(stats, "TOV")),
                                "PF": int(get_val(stats, "PF")),
                                "PTS": int(get_val(stats, "PTS")),
                                "PLUS_MINUS": get_val(stats, "+/-"),
                            }
                            boxscores.append(record)

            print(f"{len(boxscores)} prestazioni trovate.")
            return boxscores

        except Exception as e:
            print(f"Boxscores Error: {e}")
            return []

    # ==========================================
    # SEZIONE 3: METODI NBA_API (Dati Statici)
    # ==========================================

    def download_all_players(self):
        """Usa NBA API ufficiale per salvare tutti i giocatori attivi nel file all_players.json"""
        try:
            active_players = players.get_active_players()
            df = pd.DataFrame(active_players)
            df_filtered = df[["id", "full_name"]].copy()
            df_filtered.rename(
                columns={"id": "PLAYER_ID", "full_name": "PLAYER_NAME"},
                inplace=True,
            )
            df_filtered.to_json(
                self.all_players_file, orient="records", indent=4
            )
            print(
                f"{len(df_filtered)} active players found in"
                f" {self.all_players_file}"
            )
        except Exception as e:
            print(f"Download All Players Error: {e}")

    def download_all_players_espn(self):
            """Scarica i roster di tutte le 30 squadre NBA da ESPN salvandoli in all_players.json"""
            try:
                url_teams = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams?limit=30"
                resp = requests.get(url_teams, timeout=10)
                if resp.status_code != 200:
                    print("Errore nel recupero dei team ESPN.")
                    return
    
                teams_data = (
                    resp.json()
                    .get("sports", [{}])[0]
                    .get("leagues", [{}])[0]
                    .get("teams", [])
                )
                all_players = []
    
                for team_item in teams_data:
                    t_id = team_item.get("team", {}).get("id")
                    url_roster = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{t_id}/roster"
                    resp_roster = requests.get(url_roster, timeout=10)
    
                    if resp_roster.status_code == 200:
                        athletes = resp_roster.json().get("athletes", [])
                        for ath in athletes:
                            all_players.append({
                                "PLAYER_ID": str(ath.get("id")),
                                "PLAYER_NAME": ath.get("fullName"),
                            })
    
                    time.sleep(0.1)  # Pausa leggera anti-rate limit
    
                with open(self.all_players_file, "w", encoding="utf-8") as f:
                    json.dump(all_players, f, indent=4, ensure_ascii=False)
    
                print(
                    f"{len(all_players)} active players found in"
                    f" {self.all_players_file}"
                )
    
            except Exception as e:
                print(f"Download Players Error: {e}")

    def fetch_players_info(self, player_ids, filename=None):
        """Usa NBA API (CommonPlayerInfo) per scaricare dettagli statici (Nome, Team, Ruolo)"""
        if filename is None:
            filename = os.path.join(self.data_dir, "giocatori_nba.json")

        players_list = []

        for p_id in player_ids:
            try:
                player_data = commonplayerinfo.CommonPlayerInfo(
                    player_id=p_id
                ).get_dict()
                data_row = player_data["resultSets"][0]["rowSet"][0]
                headers = player_data["resultSets"][0]["headers"]
                p_info = dict(zip(headers, data_row))

                player = {
                    "PLAYER_ID": p_id,
                    "PLAYER_NAME": p_info.get("DISPLAY_FIRST_LAST"),
                    "TEAM": p_info.get("TEAM_ABBREVIATION"),
                    "POSITION": p_info.get("POSITION"),
                }
                players_list.append(player)
                time.sleep(0.6)  # Pausa precauzionale per NBA API

            except Exception as e:
                print(f"Errore con l'ID NBA {p_id}: {e}")
                time.sleep(1.5)

        if not filename.endswith(".json"):
            filename += ".json"

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(players_list, f, indent=4, ensure_ascii=False)

        print(f"\nDownload completato! Dati salvati in: {filename}")
        return players_list

    def get_players_ids_by_name(self, player_names_list):
        """Restituisce la lista degli ID UFFICIALI NBA cercandoli per nome in all_players.json"""
        if not os.path.exists(self.all_players_file):
            print(
                f"Errore: il file {self.all_players_file} non esiste. Esegui"
                " prima download_all_players()."
            )
            return []

        try:
            df_all = pd.read_json(self.all_players_file)
        except Exception as e:
            print(f"Errore nella lettura del file JSON: {e}")
            return []

        found_ids = []

        for name in player_names_list:
            match = df_all[
                df_all["PLAYER_NAME"].str.lower() == name.lower()
            ]
            if not match.empty:
                p_id = int(match.iloc[0]["PLAYER_ID"])
                found_ids.append(p_id)
                print(f"Trovato: {name} -> {p_id}")
            else:
                print(
                    f"Attenzione: Giocatore '{name}' non trovato nel database."
                )

        return found_ids








# from datetime import datetime
# import json
# import os
# import time
# import pandas as pd
# import requests


# class NbaDataManager:

#     def __init__(self, player_ids, season="2026-27", s_type="Pre Season"):
#         # Notare che gli ID di ESPN sono stringhe/interi propri di ESPN.
#         # Se utilizzi player_ids già memorizzati con gli ID di ESPN, il filtro funzionerà direttamente.
#         self.player_ids = [str(pid) for pid in player_ids]
#         self.season = season
#         self.s_type = s_type
#         self.stats_to_save = [
#             "PLAYER_ID",
#             "GAME_ID",
#             "GAME_DATE",
#             "MATCHUP",
#             "WL",
#             "MIN",
#             "FGM",
#             "FGA",
#             "FG3M",
#             "FG3A",
#             "FTM",
#             "FTA",
#             "OREB",
#             "DREB",
#             "REB",
#             "AST",
#             "STL",
#             "BLK",
#             "TOV",
#             "PF",
#             "PTS",
#             "PLUS_MINUS",
#         ]
#         self.data_dir = "data"
#         if not os.path.exists(self.data_dir):
#             os.makedirs(self.data_dir)
#         self.games_file = os.path.join(self.data_dir, "historical_games.json")
#         self.boxscores_file = os.path.join(
#             self.data_dir, "historical_boxscores.json"
#         )
#         self.all_players_file = os.path.join(self.data_dir, "all_players.json")

#     def fetch_and_sync(self, date_string):
#         """Scarica risultati e boxscore della data in input e li aggiunge ai json"""
#         raw_games = self.fetch_matchups(date_string)

#         if not raw_games:
#             return [], []

#         raw_boxscores = self.fetch_boxscores(date_string)

#         full_history_games = self.sync_file(raw_games, self.games_file)
#         full_history_boxscores = self.sync_file(
#             raw_boxscores, self.boxscores_file
#         )

#         return full_history_games, full_history_boxscores

#     def sync_file(self, new_data, filename):
#         """Gestisce l'archiviazione dei dati evitando duplicati"""
#         if not new_data:
#             return []

#         data = []
#         if os.path.exists(filename):
#             with open(filename, "r", encoding="utf-8") as f:
#                 data = json.load(f)

#         def get_uid(item):
#             return (str(item.get("GAME_ID")), str(item.get("PLAYER_ID")))

#         existing_uids = {get_uid(item) for item in data}

#         added_count = 0
#         for item in new_data:
#             if get_uid(item) not in existing_uids:
#                 data.append(item)
#                 added_count += 1

#         if added_count > 0:
#             with open(filename, "w", encoding="utf-8") as f:
#                 json.dump(data, f, indent=4, ensure_ascii=False)
#             print(
#                 f"Sincronizzato {filename}: aggiunti {added_count} nuovi"
#                 " record."
#             )

#         return data

#     def fetch_matchups(self, date_string):
#         """Scarica i matchup e i risultati per la data in input via ESPN Scoreboard API"""
#         try:
#             # ESPN accetta la data nel formato YYYYMMDD
#             date_param = pd.to_datetime(date_string).strftime("%Y%m%d")
#             game_date_iso = pd.to_datetime(date_string).strftime("%Y-%m-%d")

#             url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_param}"
#             response = requests.get(url, timeout=10)

#             if response.status_code != 200:
#                 print(f"Errore ESPN Scoreboard HTTP {response.status_code}")
#                 return []

#             data = response.json()
#             events = data.get("events", [])

#             result = []
#             for event in events:
#                 g_id = str(event.get("id"))
#                 comp = event.get("competitions", [{}])[0]
#                 competitors = comp.get("competitors", [])

#                 home_team = next(
#                     (c for c in competitors if c.get("homeAway") == "home"), {}
#                 )
#                 away_team = next(
#                     (c for c in competitors if c.get("homeAway") == "away"), {}
#                 )

#                 home_abbr = home_team.get("team", {}).get(
#                     "abbreviation", "HOME"
#                 )
#                 away_abbr = away_team.get("team", {}).get(
#                     "abbreviation", "AWAY"
#                 )

#                 home_score = home_team.get("score", "0")
#                 away_score = away_team.get("score", "0")

#                 result.append({
#                     "GAME_ID": g_id,
#                     "GAME_DATE": game_date_iso,
#                     "MATCHUP": f"{away_abbr} @ {home_abbr}",
#                     "SCORE": f"{away_score} - {home_score}",
#                 })

#             print(f"{len(result)} games found.")
#             return result

#         except Exception as e:
#             print(f"Games Error: {e}")
#             return []

#     def fetch_boxscores(self, date_string):
#         """Scarica i tabellini per la data e li filtra per player_ids"""
#         try:
#             date_param = pd.to_datetime(date_string).strftime("%Y%m%d")
#             game_date_iso = pd.to_datetime(date_string).strftime("%Y-%m-%d")

#             # 1. Recupero gli ID di tutti i match della giornata
#             url_sb = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_param}"
#             resp_sb = requests.get(url_sb, timeout=10)
#             if resp_sb.status_code != 200:
#                 return []

#             events = resp_sb.json().get("events", [])
#             boxscores = []

#             # 2. Per ciascun match recupero il boxscore dettagliato
#             for event in events:
#                 g_id = str(event.get("id"))
#                 url_box = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={g_id}"
#                 resp_box = requests.get(url_box, timeout=10)

#                 if resp_box.status_code != 200:
#                     continue

#                 data_box = resp_box.json()
#                 teams_players = (
#                     data_box.get("boxscore", {}).get("players", [])
#                 )

#                 # Trova chi ha vinto / perso per compilare WL
#                 competitors = (
#                     data_box.get("header", {})
#                     .get("competitions", [{}])[0]
#                     .get("competitors", [])
#                 )
#                 winners_team_ids = [
#                     str(c.get("id")) for c in competitors if c.get("winner")
#                 ]

#                 # Determino le abbreviazioni per il matchup
#                 home_c = next(
#                     (c for c in competitors if c.get("homeAway") == "home"), {}
#                 )
#                 away_c = next(
#                     (c for c in competitors if c.get("homeAway") == "away"), {}
#                 )
#                 matchup_str = f"{away_c.get('team', {}).get('abbreviation', 'AWAY')} @ {home_c.get('team', {}).get('abbreviation', 'HOME')}"

#                 for team_entry in teams_players:
#                     t_id = str(team_entry.get("team", {}).get("id"))
#                     is_winner = t_id in winners_team_ids
#                     wl_status = "W" if is_winner else "L"

#                     for stat_group in team_entry.get("statistics", []):
#                         labels = stat_group.get("names", [])

#                         # Mappatura indici delle statistiche ESPN
#                         def get_val(stats_arr, name):
#                             if name in labels:
#                                 idx = labels.index(name)
#                                 val = stats_arr[idx]
#                                 return val if val != "" else "0"
#                             return "0"

#                         for ath in stat_group.get("athletes", []):
#                             p_id = str(ath.get("athlete", {}).get("id"))

#                             # Filtro sugli ID richiesti nel fantateam
#                             if self.player_ids and p_id not in self.player_ids:
#                                 continue

#                             if ath.get("didNotPlay", False):
#                                 continue

#                             stats = ath.get("stats", [])
#                             if not stats:
#                                 continue

#                             # Parsing FGM-FGA, FG3M-FG3A, FTM-FTA
#                             fg = get_val(stats, "FG").split("-")
#                             fg3 = get_val(stats, "3PT").split("-")
#                             ft = get_val(stats, "FT").split("-")

#                             fgm = int(fg[0]) if len(fg) > 0 else 0
#                             fga = int(fg[1]) if len(fg) > 1 else 0
#                             fg3m = int(fg3[0]) if len(fg3) > 0 else 0
#                             fg3a = int(fg3[1]) if len(fg3) > 1 else 0
#                             ftm = int(ft[0]) if len(ft) > 0 else 0
#                             fta = int(ft[1]) if len(ft) > 1 else 0

#                             record = {
#                                 "PLAYER_ID": p_id,
#                                 "GAME_ID": g_id,
#                                 "GAME_DATE": game_date_iso,
#                                 "MATCHUP": matchup_str,
#                                 "WL": wl_status,
#                                 "MIN": get_val(stats, "MIN"),
#                                 "FGM": fgm,
#                                 "FGA": fga,
#                                 "FG3M": fg3m,
#                                 "FG3A": fg3a,
#                                 "FTM": ftm,
#                                 "FTA": fta,
#                                 "OREB": int(get_val(stats, "OREB")),
#                                 "DREB": int(get_val(stats, "DREB")),
#                                 "REB": int(get_val(stats, "REB")),
#                                 "AST": int(get_val(stats, "AST")),
#                                 "STL": int(get_val(stats, "STL")),
#                                 "BLK": int(get_val(stats, "BLK")),
#                                 "TOV": int(get_val(stats, "TOV")),
#                                 "PF": int(get_val(stats, "PF")),
#                                 "PTS": int(get_val(stats, "PTS")),
#                                 "PLUS_MINUS": get_val(stats, "+/-"),
#                             }
#                             boxscores.append(record)

#             print(f"{len(boxscores)} prestazioni trovate.")
#             return boxscores

#         except Exception as e:
#             print(f"Boxscores Error: {e}")
#             return []

#     def download_all_players(self):
#         """Scarica i roster di tutte le 30 squadre NBA da ESPN salvandoli in all_players.json"""
#         try:
#             url_teams = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams?limit=30"
#             resp = requests.get(url_teams, timeout=10)
#             if resp.status_code != 200:
#                 print("Errore nel recupero dei team ESPN.")
#                 return

#             teams_data = (
#                 resp.json()
#                 .get("sports", [{}])[0]
#                 .get("leagues", [{}])[0]
#                 .get("teams", [])
#             )
#             all_players = []

#             for team_item in teams_data:
#                 t_id = team_item.get("team", {}).get("id")
#                 url_roster = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{t_id}/roster"
#                 resp_roster = requests.get(url_roster, timeout=10)

#                 if resp_roster.status_code == 200:
#                     athletes = resp_roster.json().get("athletes", [])
#                     for ath in athletes:
#                         all_players.append({
#                             "PLAYER_ID": str(ath.get("id")),
#                             "PLAYER_NAME": ath.get("fullName"),
#                         })

#                 time.sleep(0.1)  # Pausa leggera anti-rate limit

#             with open(self.all_players_file, "w", encoding="utf-8") as f:
#                 json.dump(all_players, f, indent=4, ensure_ascii=False)

#             print(
#                 f"{len(all_players)} active players found in"
#                 f" {self.all_players_file}"
#             )

#         except Exception as e:
#             print(f"Download Players Error: {e}")

#     def fetch_players_info(self, player_ids, filename=None):
#         """Scarica dettagli (Nome, Squadra, Posizione) per gli ID passati via API ESPN Athlete"""
#         if filename is None:
#             filename = os.path.join("data", "giocatori_nba.json")

#         players_list = []

#         for p_id in player_ids:
#             try:
#                 url = f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/athletes/{p_id}"
#                 resp = requests.get(url, timeout=10)

#                 if resp.status_code == 200:
#                     data = resp.json()
#                     player = {
#                         "PLAYER_ID": str(p_id),
#                         "PLAYER_NAME": data.get("fullName"),
#                         "TEAM": data.get("team", {})
#                         .get("$ref", "")
#                         .split("/")[-1],  # ID Team o Abbreviazione
#                         "POSITION": data.get("position", {}).get(
#                             "abbreviation"
#                         ),
#                     }
#                     players_list.append(player)
#                 time.sleep(0.1)

#             except Exception as e:
#                 print(f"Errore con l'ID {p_id}: {e}")

#         if not filename.endswith(".json"):
#             filename += ".json"

#         with open(filename, "w", encoding="utf-8") as f:
#             json.dump(players_list, f, indent=4, ensure_ascii=False)

#         print(f"\nDownload completato! Dati salvati in: {filename}")
#         return players_list

#     def get_players_ids_by_name(self, player_names_list):
#         """Restituisce la lista degli ID leggendo dal file all_players.json generato da ESPN"""
#         filename = self.all_players_file

#         if not os.path.exists(filename):
#             print(
#                 f"Errore: il file {filename} non esiste. Esegui prima"
#                 " download_all_players()."
#             )
#             return []

#         try:
#             df_all = pd.read_json(filename)
#         except Exception as e:
#             print(f"Errore nella lettura del file JSON: {e}")
#             return []

#         found_ids = []

#         for name in player_names_list:
#             match = df_all[
#                 df_all["PLAYER_NAME"].str.lower() == name.lower()
#             ]
#             if not match.empty:
#                 p_id = str(match.iloc[0]["PLAYER_ID"])
#                 found_ids.append(p_id)
#                 print(f"Trovato: {name} -> {p_id}")
#             else:
#                 print(
#                     f"Attenzione: Giocatore '{name}' non trovato nel database."
#                 )

#         return found_ids