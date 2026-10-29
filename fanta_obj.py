from dataclasses import dataclass
import os
import json


# Score di un giocatore la cui squadra non ha ancora giocato nella data target
NOT_PLAYED_SCORE = None

# Numero di giocatori di ogni rosa: 5 titolari + 1 sesto uomo + 4 panchina + 5 riserve
ROSTER_SIZE = 15

# Moltiplicatori del punteggio per ruolo (unica fonte: usati dalla UI e dal cron job)
ROLE_MULTIPLIERS = {"STARTER": 1.0, "SIXTH": 1.0, "BENCH": 0.75, "RESERVE": 0.0}

def has_played(score) -> bool:
    """True se lo score rappresenta una partita già giocata (anche con 0 punti o DNP)."""
    return score is not None



@dataclass
class Player:
    id: int = 0
    name: str = ""
    team_abbreviation: str = ""
    position: str = ""
    score: float | None = 0.0

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

    def calculate_score(self, boxscores: list[dict], target_date: str = None, average: bool = False) -> float | None:
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

        # Giocatore assente dai boxscores: la sua squadra non ha (ancora) giocato
        # TODO: anche i DNP finiscono qui (fetch_boxscores li scarta), ma dovrebbero valere 0.0
        if not player_games:
            self.score = NOT_PLAYED_SCORE
            return self.score

        total_scores = []

        for game in player_games:
            try:
                # Funzione interna di supporto per convertire in modo sicuro qualsiasi statistica in numero
                def get_num(key, default=0, is_float=False):
                    val = game.get(key, default)
                    if val is None or val == "":
                        return float(default) if is_float else int(default)
                    try:
                        return float(val) if is_float else int(float(val))
                    except (ValueError, TypeError):
                        return float(default) if is_float else int(default)

                # 1. Punteggio Base (Statistiche grezze estratte in sicurezza)
                pts = get_num("PTS", 0)
                reb = get_num("REB", 0)
                dreb = get_num("DREB", 0)
                oreb = get_num("OREB", 0)
                ast = get_num("AST", 0)
                stl = get_num("STL", 0)
                blk = get_num("BLK", 0)
                tov = get_num("TOV", 0)
                pf = get_num("PF", 0)
                fgm = get_num("FGM", 0)
                fga = get_num("FGA", 0)
                fg3m = get_num("FG3M", 0)
                ftm = get_num("FTM", 0)
                fta = get_num("FTA", 0)
                pm = get_num("PLUS_MINUS", 0.0, is_float=True)
                wl_str = game.get("WL", "L")

                # Algoritmo di base
                current_score = (
                    pts * 1.0 +                     # Punto realizzato (+1)
                    dreb * 1.0 +                    # Rimbalzo difensivo (+1)
                    oreb * 1.25 +                   # Rimbalzo offensivo (+1.25)
                    ast * 1.5 +                     # Assist (+1.5)
                    stl * 2.5 +                     # Steal (+2.5)
                    blk * 2.5 +                     # Stoppata (+2.5)
                    tov * -1.5 +                    # Palla persa (-1.5)
                    (fgm - fga) * 1.0 +             # Tiro sbagliato (-1 per ogni errore)
                    (ftm - fta) * 1.0 +             # Tiro libero sbagliato (-1 per ogni errore)
                    (pm / 5.0)                      # Plus/Minus (PM/5) - ora protetto da TypeError
                )

                # 3. Bonus scalare Triple segnate (da 3 in poi)
                if fg3m >= 3:
                    current_score += fg3m

                # 4. Bonus scalare Punti segnati (da 30 in poi)
                if pts >= 30:
                    current_score += (pts // 10)

                # 5. Bonus soglia Rimbalzi e Assist (20+)
                if reb >= 20:
                    current_score += 5
                if ast >= 20:
                    current_score += 5

                # 6. Bonus Multi-Doppia
                stats_to_check = [pts, reb, ast, stl, blk]
                double_digits_count = sum(1 for s in stats_to_check if s >= 10)

                if double_digits_count == 2:
                    current_score += 5    # Doppia Doppia
                elif double_digits_count == 3:
                    current_score += 10   # Tripla Doppia
                elif double_digits_count == 4:
                    current_score += 40   # Quadrupla Doppia
                elif double_digits_count >= 5:
                    current_score += 100  # Quintupla Doppia

                # 7. Vittoria squadra (+5%)
                if wl_str == "W":
                    current_score *= 1.05

                # 8. Malus espulsione per 6 falli (-6, fuori dal +5% vittoria)
                if pf >= 6:
                    current_score -= 5

                total_scores.append(current_score)
            except Exception:
                # Salta eventuali partite corrotte senza bloccare l'esecuzione globale
                continue

        # Se richiesto esplicitamente fa la media (es. per historical_boxscores / statistiche generali)
        if average:
            self.score = sum(total_scores) / len(total_scores) if total_scores else 0.0
        else:
            # Per il singolo giorno prende il punteggio della gara
            self.score = float(sum(total_scores)) if total_scores else 0.0
        return self.score

    @classmethod
    def calculate_scores(cls, player_ids: list[int], boxscores: list[dict], target_date: str = None, average: bool = False) -> dict[int, float]:
        """
        Calcola il fanta-punteggio di una lista di giocatori a partire dagli stessi boxscores.
        Restituisce un dizionario {player_id: score}.
        I giocatori senza partite nei boxscores (o nella target_date) hanno score None (NOT_PLAYED_SCORE).
        """
        scores = {}
        for p_id in player_ids:
            player = cls(id=int(p_id))
            scores[int(p_id)] = player.calculate_score(boxscores, target_date=target_date, average=average)
        return scores


# Modulo di partenza (e di ripiego quando non ce n'è uno salvato)
DEFAULT_LINEUP = "2-2-1"

# Posizioni richieste dagli slot titolari (0-4) per ogni modulo
LINEUP_ROLES = {
    "2-2-1": ['C', 'A', 'A', 'G', 'G'],
    "2-1-2": ['C', 'C', 'A', 'G', 'G'],
    "1-2-2": ['C', 'C', 'A', 'A', 'G'],
    "3-1-1": ['C', 'A', 'G', 'G', 'G'],
    "1-3-1": ['C', 'A', 'A', 'A', 'G'],
}

def find_starter_assignment(roles: list[str], players: list[Player]) -> list[int] | None:
    """
    Cerca giocatori distinti che coprano le posizioni richieste dagli slot titolari.
    Restituisce, per ogni slot, l'indice del giocatore scelto; None se il modulo è impossibile.
    Per fare meno scambi possibili preferisce chi è già nello slot, poi gli altri titolari,
    poi sesto uomo, panchina e riserve.
    """
    n_starters = len(roles)

    def candidates(k):
        return [k] + [i for i in range(n_starters) if i != k] + list(range(n_starters, len(players)))

    def assign(k, used):
        if k == n_starters:
            return []
        for idx in candidates(k):
            if idx not in used and roles[k] in players[idx].position.split('/'):
                rest = assign(k + 1, used | {idx})
                if rest is not None:
                    return [idx] + rest
        return None

    return assign(0, frozenset())

def infer_lineup(players: list[Player], preferred: str) -> str | None:
    """
    Restituisce il modulo che i primi 5 giocatori (titolari) rispettano già, senza scambi.
    Se ne vanno bene più di uno (giocatori con doppia posizione) preferisce preferred.
    """
    for lineup in [preferred] + [l for l in LINEUP_ROLES if l != preferred]:
        roles = LINEUP_ROLES.get(lineup)
        if roles and len(players) >= len(roles) and all(r in p.position.split('/') for r, p in zip(roles, players)):
            return lineup
    return None


class Team:
    """Gestisce il roster, la validazione e l'interfacciamento con i dati API e la UI."""
    
    def __init__(self, name: str, gameweek: int | None = None):
        self.name = name
        self.players: list[Player] = []
        self.roles_map: dict[int, str] = {}
        self.score: float = 0.0
        self.lineup = "2-2-1"
        self.target_date = ""
        self.gameweek = gameweek  # Giornata a cui si riferiscono formazione e punteggi
        self.data_as_of = ""      # Fine dell'ultimo cron (ISO, UTC) quando i dati sono stati scaricati
        # Con la giornata, un file per giornata (l'app ne usa due nella finestra dei cambi)
        suffix = f"_gw{gameweek}" if gameweek is not None else ""
        self.filename = os.path.join("data", f"{self.name.replace(' ', '_').lower()}{suffix}_state.json")
    
    def save_to_json(self):
        """Salva l'intero stato del team, inclusi i dati dei giocatori e il punteggio totale."""
        data = {
            "team_name": self.name,
            "target_date": self.target_date,
            "gameweek": self.gameweek,
            "data_as_of": self.data_as_of,
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
            self.gameweek = data.get("gameweek", self.gameweek)
            self.data_as_of = data.get("data_as_of", "")
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
        """Calcola il punteggio totale del team pesato sui ruoli.
        I giocatori la cui squadra non ha ancora giocato non vengono conteggiati."""
        total = 0.0
        for p in self.players:
            if not has_played(p.score):
                continue
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
        """Verifica che la squadra sia composta esattamente da ROSTER_SIZE giocatori."""
        return len(self.players) == ROSTER_SIZE

    def to_ui_format(self) -> list[dict]:
        """Esporta il roster nel formato list[dict] atteso dalla classe Court."""
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
