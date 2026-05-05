from nba_api.stats.endpoints import commonplayerinfo
from nba_api.stats.static import players
from nba_api.stats.endpoints import leaguegamelog
import pandas as pd
import json
import os
import time

class NbaDataManager:

    def __init__(self, player_ids, season='2025-26', s_type='Regular Season'):
        self.player_ids = player_ids
        self.season = season
        self.s_type = s_type
        self.games_file = "historical_games.json"
        self.boxscores_file = "historical_boxscores.json"
        self.stats_to_save = [
            "PLAYER_ID", "GAME_ID", "GAME_DATE", "MATCHUP", "WL", "MIN", 
            "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", 
            "REB", "AST", "STL", "BLK", "TOV", "PF", "PTS", "PLUS_MINUS"
        ]
    

    def fetch_and_sync(self, date_string):
        """Scarica risultati e boxscore della data in input e li aggiunge ai json"""
        # 1. Scarica i dati
        raw_games = self.fetch_matchups(date_string)

        # Se non trovo partite, è inutile cercare i tabellini
        if not raw_games:
            return [], []
        
        raw_boxscores = self.fetch_boxscores(date_string)

        # 2. Sincronizza cache e memorizza in RAM
        full_history_games = self.sync_file(raw_games, self.games_file)
        full_history_boxscores = self.sync_file(raw_boxscores, self.boxscores_file)

        return full_history_games, full_history_boxscores
    

    def sync_file(self, new_data, filename):
        """Gestisce l'archiviazione dei dati evitando che lo stesso risultato o lo stesso tabellino venga salvato due volte"""
        if not new_data: return []
        
        if not filename.endswith(".json"):
            filename += ".json"

        data = []
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f: 
                data = json.load(f)
        
        # Creiamo un set di identificatori univoci (tuple)
        # Per le partite sarà (GAME_ID, None), per i boxscores sarà (GAME_ID, PLAYER_ID)
        def get_uid(item): 
            return (item.get("GAME_ID"), item.get("PLAYER_ID"))
            
        existing_uids = {get_uid(item) for item in data}
        
        added_count = 0
        for item in new_data:
            if get_uid(item) not in existing_uids:
                data.append(item)
                added_count += 1
        
        if added_count > 0:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            print(f"Sincronizzato {filename}: aggiunti {added_count} nuovi record.")
        
        return data
    

    def fetch_matchups(self, date_string):
        """Scarica i matchup (no partite future) e i risultati per il giorno in input"""
        try:
            date_nba = pd.to_datetime(date_string).strftime('%m/%d/%Y') # Conversione nel formato MM/DD/YYYY
            
            # Chiamata in modalità 'T' (Team)
            log = leaguegamelog.LeagueGameLog(
                season=self.season,
                season_type_all_star=self.s_type,
                date_from_nullable=date_nba,
                date_to_nullable=date_nba,
                player_or_team_abbreviation='T'
            )
            df = log.get_data_frames()[0]

            if df.empty:
                print("No data found.")
                return []

            games_dict = {}

            for _, row in df.iterrows():
                g_id = row['GAME_ID']
                
                if g_id not in games_dict:
                    games_dict[g_id] = {
                        "GAME_ID": g_id,
                        "GAME_DATE": row['GAME_DATE'], # Salvata correttamente qui
                        "home_score": 0,
                        "away_score": 0,
                        "home_team": "",
                        "away_team": ""
                    }

                team_abbr = row['TEAM_ABBREVIATION']
                matchup = row['MATCHUP']
                pts = int(row['PTS'])

                # Logica per assegnare Home e Away
                if "@" in matchup:
                    if matchup.split(" @ ")[0] == team_abbr:
                        games_dict[g_id]["away_score"] = pts
                        games_dict[g_id]["away_team"] = team_abbr
                        games_dict[g_id]["home_team"] = matchup.split(" @ ")[1]
                    else:
                        games_dict[g_id]["home_score"] = pts
                        games_dict[g_id]["home_team"] = team_abbr
                        games_dict[g_id]["away_team"] = matchup.split(" @ ")[0]
                elif "vs." in matchup:
                    if matchup.split(" vs. ")[0] == team_abbr:
                        games_dict[g_id]["home_score"] = pts
                        games_dict[g_id]["home_team"] = team_abbr
                        games_dict[g_id]["away_team"] = matchup.split(" vs. ")[1]
                    else:
                        games_dict[g_id]["away_score"] = pts
                        games_dict[g_id]["away_team"] = team_abbr
                        games_dict[g_id]["home_team"] = matchup.split(" vs. ")[0]

            # Formattazione finale
            result = []
            for g_id, info in games_dict.items():
                result.append({
                    "GAME_ID": g_id,
                    "GAME_DATE": info["GAME_DATE"],
                    "MATCHUP": f"{info['away_team']} @ {info['home_team']}",
                    "SCORE": f"{info.get('away_score', 0)} - {info.get('home_score', 0)}"
                })

            print(f"{len(result)} games found.")
            return result

        except Exception as e:
            print(f"Games Error: {e}")
            return []
    

    def fetch_boxscores(self, date_string):
        """Scarica i boxscores per il giorno in input e i giocatori in player_ids"""
        try:
            date_nba = pd.to_datetime(date_string).strftime('%m/%d/%Y') # Conversione nel formato MM/DD/YYYY
            
            # Una sola chiamata per TUTTI i giocatori della lega, 'P'
            log = leaguegamelog.LeagueGameLog(
                season=self.season,
                season_type_all_star=self.s_type,
                date_from_nullable=date_nba,
                date_to_nullable=date_nba,
                player_or_team_abbreviation='P'
            )
            df_all = log.get_data_frames()[0]
            df_team = df_all[df_all['PLAYER_ID'].isin(self.player_ids)] # Filtra sul fanta-team
            df_final = df_team[self.stats_to_save].copy()
            boxscores = df_final.to_dict(orient='records')  

            print(f"{len(boxscores)} prestazioni trovate.")
            return boxscores
        
        except Exception as e:
            print(f"Boxscores Error: {e}")


    def download_all_players(self):
        """Questa funzione restituisce tutti i giocatori (ID + Nome) che hanno un contratto attivo"""
        active_players = players.get_active_players()
        df = pd.DataFrame(active_players)
        df_filtered = df[['id', 'full_name']].copy()
        df_filtered.rename(columns={'id': 'PLAYER_ID', 'full_name': 'PLAYER_NAME'}, inplace=True)
        df_filtered.to_json("all_players.json", orient="records", indent=4)
        print(f"{len(df_filtered)} active players found.")
    

    def fetch_players_info(self, player_ids, filename="giocatori_nba.json"):
        """Scarica info dettagliate per una lista di ID e salva su un file specificato"""
        players_list = []
        
        for p_id in player_ids:
            try:
                # Richiesta all'endpoint ufficiale
                player_data = commonplayerinfo.CommonPlayerInfo(player_id=p_id).get_dict()
                
                # Mapping dei dati
                data_row = player_data['resultSets'][0]['rowSet'][0]
                headers = player_data['resultSets'][0]['headers']
                p_info = dict(zip(headers, data_row))
                
                # Creazione dizionario pulito
                player = {
                    "PLAYER_ID": p_id,
                    "PLAYER_NAME": p_info.get("DISPLAY_FIRST_LAST"),
                    "TEAM": p_info.get("TEAM_ABBREVIATION"),
                    "POSITION": p_info.get("POSITION")
                }
                
                players_list.append(player)
                
                # Breve pausa per non essere bloccati dai server
                time.sleep(0.6) 
                
            except Exception as e:
                print(f"Errore con l'ID {p_id}: {e}")
                time.sleep(2)

        if not filename.endswith(".json"):
            filename += ".json"

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(players_list, f, indent=4, ensure_ascii=False)
        
        print(f"\nDownload completato! Dati salvati in: {filename}")
        return players_list
    

    def get_players_ids_by_name(self, player_names_list):
        """Riceve una lista di nomi (stringhe) e restituisce una lista di ID (interi) leggendo dal file all_players.json."""
        filename = "all_players.json"

        if not os.path.exists(filename):
            print(f"Errore: il file {filename} non esiste. Esegui prima download_all_players().")
            return []

        try:
            df_all = pd.read_json(filename)
        except Exception as e:
            print(f"Errore nella lettura del file JSON: {e}")
            return []

        found_ids = []
        
        # Cerco ogni nome della lista fornita
        for name in player_names_list:
            match = df_all[df_all['PLAYER_NAME'].str.lower() == name.lower()]
            if not match.empty:
                p_id = int(match.iloc[0]['PLAYER_ID'])
                found_ids.append(p_id)
                print(f"Trovato: {name} -> {p_id}")
            else:
                print(f"Attenzione: Giocatore '{name}' non trovato nel database.")

        return found_ids



# if __name__ == "__main__":
#     # 1. Inizializzazione
#     print("--- TEST 1: Inizializzazione ---")
#     DATA_TARGET = "2026-04-12"
#     MIEI_NOMI = ["LeBron James", "LaMelo Ball", "Victor Wembanyama"]
#     nba = NbaDataManager(player_ids=[])
#     print("Manager creato con successo.\n")

#     # 2. Test download_all_players
#     print("--- TEST 2: Download database globale giocatori ---")
#     nba.download_all_players()
#     if os.path.exists("all_players.json"):
#         print("File all_players.json creato correttamente.\n")

#     # 3. Test get_players_ids_by_name
#     print("--- TEST 3: Ricerca ID tramite nomi ---")
#     ids_trovati = nba.get_players_ids_by_name(MIEI_NOMI)
#     nba.player_ids = ids_trovati
#     print(f"ID impostati nel manager: {nba.player_ids}\n")

#     # 4. Test fetch_players_info
#     print("--- TEST 4: Download info anagrafiche dettagliate ---")
#     # Testiamo il salvataggio con un nome file personalizzato
#     info_file = "test_info_giocatori.json"
#     nba.fetch_players_info(nba.player_ids, filename=info_file)
#     if os.path.exists(info_file):
#         print(f"Dettagli salvati correttamente in {info_file}.\n")

#     # 5. Test fetch_and_sync (Il cuore del sistema)
#     print(f"--- TEST 5: Sync partite e boxscores per la data {DATA_TARGET} ---")
#     # Eseguiamo il sync due volte per verificare che non ci siano duplicati
#     print("Primo tentativo di sincronizzazione...")
#     games_1, box_1 = nba.fetch_and_sync(DATA_TARGET)
    
#     print("\nSecondo tentativo di sincronizzazione (dovrebbe aggiungere 0 record)...")
#     games_2, box_2 = nba.fetch_and_sync(DATA_TARGET)

#     # Verifica finale dei dati in memoria
#     print("\n--- RESOCONTO FINALE ---")
#     print(f"Partite totali in archivio: {len(games_2)}")
#     print(f"Prestazioni individuali in archivio: {len(box_2)}")
    
#     if len(games_1) == len(games_2) and len(box_1) == len(box_2):
#         print("Successo: La logica anti-duplicazione dei file funziona correttamente.")
#     else:
#         print("Errore: Sono stati creati duplicati nei file JSON.")