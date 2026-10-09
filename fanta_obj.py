from dataclasses import dataclass
from itertools import product
from api_nba import NbaDataManager
from datetime import datetime
import os
import json

@dataclass
class Player:
    id: int = 0
    name: str = ""
    team_abbreviation: str = ""
    position: str = ""
    score: float = 0.0

    def __post_init__(self):
        # Ogni volta che l'oggetto viene istanziato, pulisce la posizione
        if self.position:
            self.position = self.get_clean_position()

    def get_avatar_img(self):
        return f"/players/{self.id}.png" if self.id else "avatar_placeholder.png"

    @classmethod
    def from_dict(cls, data: dict):
        """Metodo 'Factory': crea l'oggetto direttamente dal dizionario"""
        obj = cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            team_abbreviation=data.get("team", ""),
            position=data.get("pos", "")
        )
        obj.position = obj.get_clean_position()
        obj.score = data.get("score", 0.0)
        return obj
    
    @classmethod
    def from_json(cls, filename, player_id=None, name=None):
        """Cerca un giocatore nel file JSON tramite ID o Nome e restituisce un'istanza di Player."""
        if not os.path.exists(filename):
            print(f"Errore: Il file {filename} non esiste.")
            return cls() # Restituisce un giocatore vuoto

        with open(filename, "r", encoding="utf-8") as f:
            try:
                data_list = json.load(f)
            except Exception as e:
                print(f"Errore nella lettura del JSON: {e}")
                return cls()

        # Logica di ricerca
        for p_data in data_list:
            # Controllo ID (se fornito) o Nome (se fornito, case-insensitive)
            if (player_id and p_data.get("PLAYER_ID") == player_id) or \
               (name and p_data.get("PLAYER_NAME", "").lower() == name.lower()):
                
                p_obj = cls(
                    id=p_data.get("PLAYER_ID", 0),
                    name=p_data.get("PLAYER_NAME", ""),
                    team_abbreviation=p_data.get("TEAM", ""),
                    position=p_data.get("POSITION", "")
                )
                p_obj.position = p_obj.get_clean_position()
                return p_obj

        print(f"Giocatore non trovato per {'ID: ' + str(player_id) if player_id else 'Nome: ' + name}")
        return cls() # Restituisce un oggetto vuoto se non trovato
    
    def get_clean_position(self) -> str:
        """
        Traduce 'Forward-Guard' in 'A/G', 'Center' in 'C', ecc.
        """
        if not self.position:
            return ""
        
        # Mappa di traduzione
        mapping = {
            "Guard": "G",
            "Forward": "A",
            "Center": "C"
        }

        parts = self.position.replace('-', '/').split('/')
        clean_parts = [mapping.get(p.strip(), p.strip()) for p in parts]
        
        return "/".join(clean_parts)

    calculate_score_from_json_path = os.path.join("data", "historical_boxscores.json")    
    def calculate_score_from_json(self, filename: str = calculate_score_from_json_path, target_date: str = None, average: bool = False) -> float:
        """
        Cerca le prestazioni del giocatore nel file boxscores e calcola il punteggio.
        :param filename: Il percorso del file JSON da cui caricare i boxscore.
        :param target_date: Opzionale. Se fornita (es. 'YYYY-MM-DD'), filtra le partite di quella data.
        :param average: Se True fa la media, altrimenti calcola il totale singolo/giornaliero.
        """
        if not os.path.exists(filename) or self.id == 0:
            self.score = 0.0
            return 0.0

        with open(filename, "r", encoding="utf-8") as f:
            try:
                boxscores = json.load(f)
            except Exception as e:
                print(f"Errore nella lettura dei boxscore da {filename}: {e}")
                self.score = 0.0
                return 0.0
        
        return self.calculate_score(boxscores, target_date=target_date, average=average)
    
    def calculate_score(self, boxscores: list[dict], target_date: str = None, average: bool = False) -> float:
        """
        Riceve una lista di boxscores (dizionari) e calcola il punteggio del giocatore.
        :param boxscores: Lista dei boxscore di gara.
        :param target_date: Opzionale. Se specificata, valuta solo le partite con GAME_DATE corrispondente.
        :param average: Se True calcola la media su tutte le gare trovate.
                        Se False somma i punteggi ottenuti nel target selezionato.
        """
        if not boxscores or self.id == 0:
            self.score = 0.0
            return 0.0
        
        # 1. Filtriamo le partite giocate da QUESTO giocatore
        player_games = [g for g in boxscores if g.get("PLAYER_ID") == self.id]

        # 2. Se è specificata una data target, filtra ulteriormente per la data
        if target_date:
            player_games = [g for g in player_games if g.get("GAME_DATE") == target_date]

        if not player_games:
            self.score = 0.0
            return 0.0

        total_scores = []

        for game in player_games:
            # 1. Punteggio Base (Statistiche grezze)
            pts = game.get("PTS", 0)
            reb = game.get("REB", 0)
            dreb = game.get("DREB", 0)
            oreb = game.get("OREB", 0)
            ast = game.get("AST", 0)
            stl = game.get("STL", 0)
            blk = game.get("BLK", 0)
            tov = game.get("TOV", 0)
            pf = game.get("PF", 0)
            fgm = game.get("FGM", 0)
            fga = game.get("FGA", 0)
            ftm = game.get("FTM", 0)
            fta = game.get("FTA", 0)
            pm = game.get("PLUS_MINUS", 0)
            wl_str = game.get("WL", 0)

            wl = 3 if wl_str == "W" else (-3 if wl_str == "L" else 0)

            # Algoritmo di base
            current_score = float(pts)
            # current_score = (
            #     pts * 1.0 +         
            #     dreb * 1.0 +
            #     oreb * 1.25 +
            #     ast * 1.5 +         
            #     stl * 2.0 +         
            #     blk * 2.0 +         
            #     tov * -1.5 +        
            #     (fgm - fga) * 1.0 + 
            #     (ftm - fta) * 1.0 + 
            #     pm * 0.0 +
            #     wl         
            # )

            # 2. Bonus Multi-Doppia
            stats_to_check = [pts, reb, ast, stl, blk]
            double_digits_count = sum(1 for s in stats_to_check if s >= 10)

            # if double_digits_count == 2:
            #     current_score += 5   # Doppia Doppia
            # elif double_digits_count == 3:
            #     current_score += 10  # Tripla Doppia
            # elif double_digits_count == 4:
            #     current_score += 40  # Quadrupla Doppia (Rarissima)
            # elif double_digits_count == 5:
            #     current_score += 100 # Quintupla Doppia (Leggendaria)

            total_scores.append(current_score)

        # Se richiesto esplicitamente fa la media (es. per historical_boxscores / statistiche generali)
        if average:
            self.score = sum(total_scores) / len(total_scores) if total_scores else 0.0
        else:
            # Per il singolo giorno prende il punteggio della gara
            self.score = float(sum(total_scores)) if total_scores else 0.0
        return self.score
    

class Team:
    """Gestisce il roster, la validazione e l'interfacciamento con i dati API e la UI."""
    
    # Ordine gerarchico per la UI (Court si aspetta prima i titolari, poi la panchina, ecc.)
    ROLE_ORDER = {"STARTER": 0, "SIXTH": 1, "BENCH": 2, "RESERVE": 3}
    
    def __init__(self, name: str):
        self.name = name
        self.players: list[Player] = []
        self.roles_map: dict[int, str] = {}
        self.score: float = 0.0
        self.lineup = "2-2-1"
        self.target_date = ""
        self.filename = os.path.join("data", f"{self.name.replace(' ', '_').lower()}_state.json")
    
    def save_to_json(self):
        """Salva l'intero stato del team, inclusi i dati dei giocatori e il punteggio totale."""
        data = {
            "team_name": self.name,
            "target_date": self.target_date,
            "total_score": self.score,
            "lineup": self.lineup,
            "roster": self.to_ui_format() # Usiamo il formato UI che è già un dizionario pulito
        }
        if not os.path.exists("data"):
            os.makedirs("data")
        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        print(f"Stato del team salvato in {self.filename}")

    def load_from_json(self) -> bool:
        """Carica il team da file. Restituisce True se il caricamento ha successo."""
        if not os.path.exists(self.filename):
            return False
        
        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.name = data["team_name"]
            self.target_date = data.get("target_date", "")
            self.score = data["total_score"]
            self.lineup = data.get("lineup", "2-2-1")
            self.players = []
            self.roles_map = {}
            
            for p_data in data["roster"]:
                # Ricostruiamo l'oggetto Player dai dati salvati
                p = Player.from_dict(p_data)
                self.add_player(p, p_data["role"])
                
            print(f"Dati caricati da {self.filename}. Punteggio: {self.score}")
            return True
        except Exception as e:
            print(f"Errore nel caricamento del file {self.filename}: {e}")
            return False
    
    def calculate_total_score(self, role_configs: dict) -> float:
        """Calcola il punteggio totale del team pesato sui ruoli."""
        total = 0.0
        for p in self.players:
            role = self.roles_map.get(p.id, "RESERVE")
            multiplier = role_configs.get(role, {}).get("mult", 0.0)
            total += p.score * multiplier
        
        self.score = float(total) # Aggiorna il campo della classe
        return self.score
        
    def add_player(self, player: Player, role: str):
        """Aggiunge un giocatore al roster assegnandogli un ruolo."""
        self.players.append(player)
        self.roles_map[player.id] = role

    def is_valid_roster(self) -> bool:
        """Verifica che la squadra sia composta esattamente da 5G, 5A, 3C."""
        if len(self.players) != 13:
            return False
            
        options = [p.position.split('/') for p in self.players]
        return any(
            c.count('G') == 5 and 
            c.count('A') == 5 and 
            c.count('C') == 3 
            for c in product(*options)
        )

    def load_data_from_api(self, api_manager: NbaDataManager, target_date: str, names_list: list[str], roles_dict: dict[str, str]):
        """Scarica i dati tramite l'API Manager e popola il Team."""
        # 1. Recupero ID
        p_ids = api_manager.get_players_ids_by_name(names_list)
        api_manager.player_ids = p_ids
        
        # 2. Scarico Info anagrafiche e Boxscores
        players_raw_info = api_manager.fetch_players_info(p_ids, filename=os.path.join("data", f"{self.name}_info.json"))
        _, daily_boxscores = api_manager.fetch_and_sync(target_date)
        
        # 3. Creazione oggetti Player
        for info in players_raw_info:
            p_obj = Player(
                id=info["PLAYER_ID"],
                name=info["PLAYER_NAME"],
                team_abbreviation=info["TEAM"],
                position=info["POSITION"]
            )
            p_obj.position = p_obj.get_clean_position()
            print(f"{p_obj.name}: {p_obj.position}")
            p_obj.calculate_score(daily_boxscores, target_date=target_date, average=False)
            
            # Recuperiamo il ruolo dal dizionario passato in input usando il nome
            role = roles_dict.get(p_obj.name, "RESERVE")
            self.add_player(p_obj, role)

    def get_ordered_roster(self) -> list[Player]:
        """Restituisce i giocatori ordinati per importanza di ruolo (utile per la UI Court)."""
        if len(self.players) == 13:
            return self.players
        return sorted(self.players, key=lambda p: self.ROLE_ORDER.get(self.roles_map[p.id], 99))

    def to_ui_format(self) -> list[dict]:
        """Esporta il roster nel formato list[dict] atteso dalla classe Court."""
        # ordered_players = self.get_ordered_roster()
        ui_list = []
        for p in self.players:
            ui_list.append({
                "id": p.id,
                "name": p.name,
                "team": p.team_abbreviation,
                "pos": p.position,
                "score": p.score,
                "role": self.roles_map[p.id]
            })
        return ui_list

    def update_team_scores_for_date(self, api_manager: NbaDataManager, target_date: str, names_list: list[str], roles_dict: dict[str, str]):
        """Carica l'anagrafica dai file JSON locali e aggiorna i punteggi. Usa la cache se la data coincide."""
        
        # 0. Controllo Cache State: se il file esiste e ha la stessa target_date, salta il ricalcolo
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    saved_data = json.load(f)
                
                if saved_data.get("target_date") == target_date:
                    print(f"Stato locale aggiornato trovato per {target_date}. Lettura da cache: {self.filename}")
                    self.load_from_json()
                    return  # Termina qui, i punteggi sono stati caricati in memoria
            except Exception as e:
                print(f"Impossibile leggere lo stato locale, procedo con il calcolo: {e}")
        
        # 1. Recupero gli ID dei giocatori
        p_ids = api_manager.get_players_ids_by_name(names_list)
        api_manager.player_ids = p_ids
        
        # 2. Scarica e sincronizza SOLO i boxscores della data target
        _, daily_boxscores = api_manager.fetch_and_sync(target_date)
        
        # 3. Legge l'anagrafica locale già scaricata nel setup statico
        info_path = os.path.join("data", f"{self.name.replace(' ', '_').lower()}_info.json")
        
        if os.path.exists(info_path):
            with open(info_path, "r", encoding="utf-8") as f:
                players_raw_info = json.load(f)
        else:
            # Fallback se il file locale non esiste ancora
            players_raw_info = api_manager.fetch_players_info(p_ids, filename=info_path)
        
        # 4. Ricostruisce la lista giocatori e calcola i punteggi sui boxscores aggiornati
        self.players = []
        for info in players_raw_info:
            p_obj = Player(
                id=info["PLAYER_ID"],
                name=info["PLAYER_NAME"],
                team_abbreviation=info["TEAM"],
                position=info["POSITION"]
            )
            p_obj.calculate_score(daily_boxscores, target_date=target_date, average=False)
            
            role = roles_dict.get(p_obj.name, "RESERVE")
            self.add_player(p_obj, role)

        # 5. Salva il nuovo stato appena calcolato 
        self.target_date = target_date
        self.save_to_json()


# from api_nba import NbaDataManager

# if __name__ == "__main__":
#     manager = NbaDataManager(player_ids=[2544, 1630163])
#     lebron = Player(id=2544, name="LeBron James")
#     lamelo = Player(id=1630163, name="Lamelo Ball")
#     full_boxscores = manager.fetch_boxscores("2026-04-12")

#     print(lebron.calculate_score(boxscores=full_boxscores))
#     print(lamelo.calculate_score(boxscores=full_boxscores))