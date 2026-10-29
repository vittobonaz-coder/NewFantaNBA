import json
import os
import time
import unicodedata
import re
import pandas as pd
import requests
from datetime import date, datetime, timedelta
from nba_api.stats.endpoints import commonplayerinfo
from nba_api.stats.static import players
from nba_api.stats.endpoints import commonallplayers
from time_manager import NBA_TZ


# Sigle NBA ufficiali (nba_players.nba_team) che su ESPN sono diverse
NBA_TO_ESPN_TEAM = {"GSW": "GS", "NOP": "NO", "NYK": "NY", "SAS": "SA", "UTA": "UTAH", "WAS": "WSH"}
ESPN_TO_NBA_TEAM = {espn: nba for nba, espn in NBA_TO_ESPN_TEAM.items()}


def normalize_name(name):
    """Nome confrontabile tra NBA ed ESPN (es. 'Luka Dončić Jr.' -> 'luka doncic')."""
    # Rimuove accenti e diacritici (es. Dončić -> Doncic)
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
    name = name.lower()
    # Rimuove apostrofi, punti e trattini
    name = name.replace(".", "").replace("'", "").replace("-", " ")
    # Rimuove suffissi comuni
    name = re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', name)
    # Rimuove doppi spazi causati dalle pulizie precedenti
    name = " ".join(name.split())
    return name


class NbaDataManager:

    def __init__(self, player_ids, season="2026-27", s_type="Regular Season"):
        # self.player_ids contiene sempre gli ID UFFICIALI NBA (es. [203999, 1628369])
        self.player_ids = [str(pid) for pid in player_ids]
        self.season = season
        self.s_type = s_type

        self.data_dir = "data"
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

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
        espn_players_list = self.fetch_espn_players()

        # 3. Accoppiamento basato sul Nome Normalizzato (Migliorato)
        espn_dict = {
            normalize_name(p["name"]): p["espn_id"]
            for p in espn_players_list
        }

        nba_to_espn = {}
        espn_to_nba = {}
        unmapped = []

        for nba_p in nba_players_list:
            clean_name = normalize_name(nba_p["full_name"])
            nba_id = str(nba_p["id"])

            if clean_name in espn_dict:
                espn_id = espn_dict[clean_name]
                nba_to_espn[nba_id] = espn_id
                espn_to_nba[espn_id] = nba_id
            else:
                unmapped.append(nba_p["full_name"])

        print("Giocatori non mappati:", unmapped)

        self.save_id_map(nba_to_espn, espn_to_nba)
        print(
            f"Mappa creata: {len(nba_to_espn)} giocatori associati correttamente."
        )
        return nba_to_espn, espn_to_nba

    def save_id_map(self, nba_to_espn, espn_to_nba):
        """Salva le mappe NBA <-> ESPN su file JSON."""
        with open(self.map_file, "w", encoding="utf-8") as f:
            json.dump(
                {"nba_to_espn": nba_to_espn, "espn_to_nba": espn_to_nba},
                f,
                indent=4,
                ensure_ascii=False,
            )

    def fetch_espn_players(self):
        """Scarica i roster attuali delle 30 squadre da ESPN: lista di {"espn_id", "name"}."""
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
        return espn_players_list

    def map_missing_players(self, players_by_id):
        """
        Aggiunge alla mappa i giocatori che mancano (es. rookie assenti dai dati statici di nba_api),
        cercandoli per nome nei roster ESPN attuali.
        :param players_by_id: dizionario {id NBA: nome completo}, es. dalla tabella nba_players
        :return: nomi dei giocatori che non è stato possibile mappare
        """
        missing = {
            str(p_id): name for p_id, name in players_by_id.items()
            if str(p_id) not in self.nba_to_espn_map
        }
        if not missing:
            return []

        print(f"Ricerca su ESPN di {len(missing)} giocatori assenti dalla mappa NBA <-> ESPN...")
        espn_dict = {
            normalize_name(p["name"]): p["espn_id"]
            for p in self.fetch_espn_players()
        }

        not_found = []
        for nba_id, name in missing.items():
            espn_id = espn_dict.get(normalize_name(name))
            if espn_id:
                self.nba_to_espn_map[nba_id] = espn_id
                self.espn_to_nba_map[espn_id] = nba_id
                if nba_id in self.player_ids:
                    self.espn_player_ids.add(espn_id)
                print(f"Mappato: {name} ({nba_id}) -> ESPN {espn_id}")
            else:
                not_found.append(name)

        if len(not_found) < len(missing):
            self.save_id_map(self.nba_to_espn_map, self.espn_to_nba_map)
        return not_found

    # ==========================================
    # SEZIONE 2: METODI ESPN (Dati Giornalieri)
    # ==========================================

    def fetch_boxscores(self, date_string, only_completed=False, include_dnp=False, strict=False):
        """
        Scarica i tabellini via ESPN e riconverte i PLAYER_ID negli ID NBA Ufficiali.
        :param only_completed: se True salta le partite non concluse (in corso, rinviate)
        :param include_dnp: se True include i giocatori a referto non entrati in campo
                            (record con "DNP": True e statistiche vuote -> 0.0 punti)
        :param strict: se True solleva un'eccezione quando ESPN non risponde, invece di restituire []
        """
        try:
            date_param = pd.to_datetime(date_string).strftime("%Y%m%d")
            game_date_iso = pd.to_datetime(date_string).strftime("%Y-%m-%d")

            url_sb = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_param}"
            resp_sb = requests.get(url_sb, timeout=10)
            if resp_sb.status_code != 200:
                if strict:
                    raise RuntimeError(f"ESPN Scoreboard HTTP {resp_sb.status_code}")
                return []

            events = resp_sb.json().get("events", [])
            boxscores = []

            for event in events:
                # Partite in corso o rinviate: il tabellino non è definitivo
                if only_completed and not event.get("status", {}).get("type", {}).get("completed", False):
                    continue

                g_id = str(event.get("id"))
                url_box = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={g_id}"
                resp_box = requests.get(url_box, timeout=10)

                if resp_box.status_code != 200:
                    if strict:
                        raise RuntimeError(f"ESPN Summary HTTP {resp_box.status_code} (partita {g_id})")
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
                    team_abbr = team_entry.get("team", {}).get("abbreviation", "")
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

                            stats = ath.get("stats", [])
                            dnp = ath.get("didNotPlay", False) or not stats
                            if dnp and not include_dnp:
                                continue

                            # Riconversione a ID NBA Ufficiale
                            nba_p_id = self.espn_to_nba_map.get(
                                espn_p_id, espn_p_id
                            )
                            player_id = int(nba_p_id) if nba_p_id.isdigit() else nba_p_id

                            if dnp:
                                # A referto ma non entrato in campo: tabellino vuoto (vale 0.0)
                                boxscores.append({
                                    "PLAYER_ID": player_id,
                                    "GAME_ID": g_id,
                                    "GAME_DATE": game_date_iso,
                                    "MATCHUP": matchup_str,
                                    "TEAM": team_abbr,
                                    "WL": wl_status,
                                    "DNP": True,
                                })
                                continue

                            fg = get_val(stats, "FG").split("-")
                            fg3 = get_val(stats, "3PT").split("-")
                            ft = get_val(stats, "FT").split("-")

                            record = {
                                "PLAYER_ID": player_id,
                                "GAME_ID": g_id,
                                "GAME_DATE": game_date_iso,
                                "MATCHUP": matchup_str,
                                "TEAM": team_abbr,
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
                                "TOV": int(get_val(stats, "TO")),
                                "PF": int(get_val(stats, "PF")),
                                "PTS": int(get_val(stats, "PTS")),
                                "PLUS_MINUS": get_val(stats, "+/-"),
                            }
                            boxscores.append(record)

            print(f"{len(boxscores)} prestazioni trovate.")
            return boxscores

        except Exception as e:
            if strict:
                raise
            print(f"Boxscores Error: {e}")
            return []

    @staticmethod
    def fetch_scoreboard_games(date_param):
        """
        Partite NBA dallo scoreboard ESPN, nel formato della tabella nba_games (senza gameweek).
        :param date_param: un giorno (YYYYMMDD) oppure un mese intero (YYYYMM)
        Le sigle sono quelle NBA ufficiali, i punteggi None finché la partita non inizia.
        Solleva un'eccezione se ESPN non risponde.
        """
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_param}&limit=1000"
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        games = []
        for event in response.json().get("events", []):
            comp = event.get("competitions", [{}])[0]
            sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
            if "home" not in sides or "away" not in sides:
                continue

            status_type = event.get("status", {}).get("type", {})
            name = status_type.get("name", "")
            if name in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED"):
                status = "postponed"
            elif status_type.get("completed"):
                status = "final"
            elif name == "STATUS_SCHEDULED":
                status = "scheduled"
            else:
                status = "in_progress"

            def team(side):
                abbr = sides[side].get("team", {}).get("abbreviation", "")
                return ESPN_TO_NBA_TEAM.get(abbr, abbr)

            def score(side):
                raw = sides[side].get("score")
                return int(raw) if status in ("final", "in_progress") and raw not in (None, "") else None

            # La data NBA è quella USA (fuso di New York) dell'orario di inizio
            start_time = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
            games.append({
                "game_id": str(event.get("id")),
                "nba_date": start_time.astimezone(NBA_TZ).date().isoformat(),
                "start_time": start_time.isoformat(),
                "home_team": team("home"),
                "away_team": team("away"),
                "home_score": score("home"),
                "away_score": score("away"),
                "status": status,
            })
        return games

    @staticmethod
    def fetch_season_games(first_nba_date, last_nba_date):
        """Partite NBA tra due date NBA (YYYY-MM-DD, incluse), scaricate da ESPN un mese alla volta."""
        first = date.fromisoformat(first_nba_date)
        last = date.fromisoformat(last_nba_date)
        games = []
        month = first.replace(day=1)
        while month <= last:
            games += NbaDataManager.fetch_scoreboard_games(month.strftime("%Y%m"))
            month = (month + timedelta(days=32)).replace(day=1)
        return [g for g in games if first_nba_date <= g["nba_date"] <= last_nba_date]

    # ==========================================
    # SEZIONE 3: METODI NBA_API (Dati Statici)
    # ==========================================

    def download_all_players_live(self):
        """Scarica i giocatori attivi interrogando i server NBA in tempo reale."""
        try:
            # is_only_current_season=1 filtra solo chi ha un contratto in questa stagione
            live_data = commonallplayers.CommonAllPlayers(is_only_current_season=1).get_data_frames()[0]
            
            # Filtriamo e rinominiamo le colonne per mantenere la compatibilità col tuo codice
            df_filtered = live_data[["PERSON_ID", "DISPLAY_FIRST_LAST"]].copy()
            df_filtered.rename(
                columns={"PERSON_ID": "PLAYER_ID", "DISPLAY_FIRST_LAST": "PLAYER_NAME"},
                inplace=True,
            )
            
            # Salvataggio
            df_filtered.to_json(
                self.all_players_file, orient="records", indent=4
            )
            
            print(
                f"{len(df_filtered)} giocatori attivi scaricati in tempo reale in"
                f" {self.all_players_file}"
            )
        except Exception as e:
            print(f"Download Live Players Error: {e}")

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
