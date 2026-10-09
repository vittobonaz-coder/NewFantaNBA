import os
import json
from supabase import create_client, Client
from fanta_obj import Player, Team
from pathlib import Path
from datetime import date

SUPABASE_URL = "https://ifqiarpfsbcrfpmabdus.supabase.co"
SUPABASE_KEY = "sb_publishable_KNhdTSkcs0XuzDwKqNbIOA_XpiJlqFZ"

class SupabaseSync:
    def __init__(self):
        self.supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    def push_team(self, team: Team, court=None):
        """Salva l'intero stato del team su Supabase"""
        print(f"Sincronizzazione team {team.name} su Supabase...")

        # 1. Upsert Giocatori (nba_players)
        players_data = []
        for p in team.players:
            players_data.append({
                "id": p.id,
                "full_name": p.name,       # <--- Adattato al nuovo DB
                "nba_team": p.team_abbreviation,
                "position": p.position
            })
        self.supabase.table("nba_players").upsert(players_data).execute()

        # 2. Gestione Fanta-Team (Sostituito upsert con logica manuale)
        existing_team = self.supabase.table("fanta_teams").select("id").eq("name", team.name).execute()
        
        if existing_team.data:
            fanta_team_id = existing_team.data[0]["id"]
        else:
            team_res = self.supabase.table("fanta_teams").insert({"name": team.name}).execute()
            fanta_team_id = team_res.data[0]["id"]

        # 3. Aggiorna il Roster (Tabella rosters)
        self.supabase.table("rosters").delete().eq("fanta_team_id", fanta_team_id).execute()
        
        roster_data = []
        for p in team.players:
            roster_data.append({
                "fanta_team_id": fanta_team_id,
                "nba_player_id": p.id,
                "assigned_position": team.roles_map[p.id],
                "player_name": p.name
            })
        self.supabase.table("rosters").insert(roster_data).execute()
        print(f"Sincronizzazione {team.name} completata.")

    def pull_team(self, team_name: str) -> Team:
        """Recupera i dati da Supabase"""
        # Join tra fanta_teams, rosters e nba_players
        response = self.supabase.table("fanta_teams") \
            .select("name, rosters(nba_players(*))") \
            .eq("name", team_name) \
            .single() \
            .execute()

        data = response.data
        if not data: return None

        new_team = Team(name=data["name"])
        
        for item in data["rosters"]:
            p_data = item["nba_players"]
            player = Player(
                id=p_data["id"],
                name=p_data["full_name"], # <--- Adattato al nuovo DB
                team_abbreviation=p_data["nba_team"],
                position=p_data["position"]
            )
            # Nota: nel pull attuale mancano i punteggi salvati se non li aggiungi alla tabella
            new_team.add_player(player, "RISERVA") 
        
        return new_team

    def push_calendar(self, calendar: list[dict]):
        """
        Popola la tabella matchups su Supabase partendo dal calendario generato.
        """
        print("Sincronizzazione del calendario su Supabase...")

        # 1. Recupera la mappa nome_team -> uuid da fanta_teams
        teams_res = self.supabase.table("fanta_teams").select("id, name").execute()
        if not teams_res.data:
            print("Errore: Nessun fanta_team trovato su Supabase. Esegui prima push_team.")
            return

        team_map = {t["name"]: t["id"] for t in teams_res.data}

        # 2. Prepara le righe da inserire nella tabella matchups
        matchups_data = []
        for round_data in calendar:
            gameweek = round_data["round_number"]
            start_date = round_data["start_date"]
            end_date = round_data["end_date"]

            for matchup in round_data["matchups"]:
                home_name = matchup["home_team"]
                away_name = matchup["away_team"]

                home_id = team_map.get(home_name)
                away_id = team_map.get(away_name)

                if home_id and away_id:
                    matchups_data.append({
                        "gameweek": gameweek,
                        "start_date": start_date,
                        "end_date": end_date,
                        "home_team_id": home_id,
                        "away_team_id": away_id,
                        "home_score": 0.00,
                        "away_score": 0.00,
                        "was_played": False,
                        "home_lineup": "NULL",
                        "away_lineup": "NULL"
                    })
                else:
                    print(f"Attenzione: ID non trovato per {home_name} o {away_name}")

        # 4. Inserimento batch in Supabase
        if matchups_data:
            self.supabase.table("matchups").insert(matchups_data).execute()
            print(f"Calendario caricato con successo: {len(matchups_data)} matchup inseriti su Supabase.")

    def sync_standings(self, filepath: str = os.path.join("data", "standings.json")) -> list[dict]:
        """
        Sincronizza la classifica locale leggendo la vista 'v_standings' da Supabase 
        e salvando i dati nella cartella 'data/standings.json'.
        """
        print("Sincronizzazione classifica da Supabase in corso...")
        
        try:
            # 1. Fetch dei dati dalla vista 'v_standings'
            response = self.supabase.table("v_standings").select("*").execute()
            standings_data = response.data

            if standings_data is None:
                print("Avviso: Nessun dato restituito dalla vista 'v_standings'.")
                standings_data = []

            # 2. Scrittura del file JSON nella cartella 'data' (creata se non esiste)
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(standings_data, f, ensure_ascii=False, indent=4)

            print(f"Classifica aggiornata con successo in '{filepath}' ({len(standings_data)} squadre).")
            return standings_data

        except Exception as e:
            print(f"Errore durante la sincronizzazione della classifica: {e}")
            raise e

    def get_last_updated_dates(self) -> dict[str, str]:
        """
        Recupera le date di ultimo aggiornamento per ogni fanta-team.
        Restituisce un dizionario con struttura: {"Nome Team": "YYYY-MM-DD"}
        """
        try:
            response = (
                self.supabase.table("fanta_teams")
                .select("name, last_updated_date")
                .execute()
            )
            
            data = response.data or []
            return {item["name"]: item["last_updated_date"] for item in data}

        except Exception as e:
            print(f"Errore durante il recupero delle date di aggiornamento: {e}")
            return {}

    def update_team_last_updated_date(self, team_id: str, new_date: date | str = None) -> bool:
        """
        Aggiorna la colonna last_updated_date per la squadra specificata da team_id.
        Se new_date non viene passato, imposta la data di oggi (YYYY-MM-DD).
        """
        # Se non viene fornita una data specifica, usa la data odierna nel formato ISO (YYYY-MM-DD)
        if new_date is None:
            formatted_date = date.today().isoformat()
        elif isinstance(new_date, date):
            formatted_date = new_date.isoformat()
        else:
            formatted_date = str(new_date)

        print(f"Aggiornamento last_updated_date per la squadra {team_id} alla data {formatted_date}...")

        try:
            response = (
                self.supabase.table("fanta_teams")
                .update({"last_updated_date": formatted_date})
                .eq("id", team_id)
                .execute()
            )

            if response.data:
                print(f"Data aggiornata con successo per il team ID: {team_id}")
                return True
            else:
                print(f"Attenzione: Nessuna squadra trovata con ID: {team_id}")
                return False

        except Exception as e:
            print(f"Errore durante l'aggiornamento di last_updated_date: {e}")
            raise e

    def get_team_score_for_gameweek(self, team_id: str, gameweek: int) -> float | None:
        """
        Restituisce il punteggio ottenuto dalla squadra (home_score o away_score) 
        nella tabella 'matchups' per una determinata gameweek.
        
        Ritorna None se la partita non esiste.
        """
        try:
            # 1. Cerca se la squadra ha giocato in casa nella gameweek
            home_res = (
                self.supabase.table("matchups")
                .select("home_score")
                .eq("gameweek", gameweek)
                .eq("home_team_id", team_id)
                .execute()
            )

            if home_res.data:
                score_raw = home_res.data[0]["home_score"]
                return float(score_raw) if score_raw is not None else 0.0

            # 2. Se non era in casa, cerca se ha giocato in trasferta
            away_res = (
                self.supabase.table("matchups")
                .select("away_score")
                .eq("gameweek", gameweek)
                .eq("away_team_id", team_id)
                .execute()
            )

            if away_res.data:
                score_raw = away_res.data[0]["away_score"]
                return float(score_raw) if score_raw is not None else 0.0

            print(f"Nessun matchup trovato per team_id={team_id} nella gameweek {gameweek}.")
            return None

        except Exception as e:
            print(f"Errore durante il recupero del punteggio per team_id={team_id}, gameweek={gameweek}: {e}")
            raise e

    def update_team_score_for_gameweek(self, team_id: str, gameweek: int, score: float) -> bool:
        """
        Aggiorna il punteggio di una squadra nella tabella 'matchups' per una determinata gameweek.
        Riconosce autonomamente se la squadra ha giocato in casa (home_score) o in trasferta (away_score).
        """
        print(f"Aggiornamento punteggio ({score}) per il team {team_id} nella gameweek {gameweek}...")
        try:
            # 1. Controlla se il team gioca in casa per questa gameweek
            home_check = (
                self.supabase.table("matchups")
                .select("id")
                .eq("gameweek", gameweek)
                .eq("home_team_id", team_id)
                .execute()
            )

            if home_check.data:
                matchup_id = home_check.data[0]["id"]
                self.supabase.table("matchups").update({"home_score": score}).eq("id", matchup_id).execute()
                print(f"Aggiornato home_score = {score} per la partita {matchup_id}.")
                return True

            # 2. Se non gioca in casa, controlla se gioca in trasferta
            away_check = (
                self.supabase.table("matchups")
                .select("id")
                .eq("gameweek", gameweek)
                .eq("away_team_id", team_id)
                .execute()
            )

            if away_check.data:
                matchup_id = away_check.data[0]["id"]
                self.supabase.table("matchups").update({"away_score": score}).eq("id", matchup_id).execute()
                print(f"Aggiornato away_score = {score} per la partita {matchup_id}.")
                return True

            print(f"Attenzione: Nessuna partita trovata per team_id={team_id} nella gameweek {gameweek}.")
            return False

        except Exception as e:
            print(f"Errore durante l'aggiornamento del punteggio: {e}")
            raise e

    def sync_team_positions_to_json(self, team_id: str, filepath: str = os.path.join("data", "fanta_teams.json")) -> bool:
        """
        Legge la colonna 'assigned_position' dei giocatori per un determinato team_id
        dalla tabella 'rosters' e aggiorna le posizioni corrispondenti nel file JSON fanta_teams.json.
        """
        print(f"Sincronizzazione posizioni per il team ID: {team_id}...")
        try:
            # 1. Recupera il nome del fanta-team da fanta_teams
            team_res = self.supabase.table("fanta_teams").select("name").eq("id", team_id).execute()
            if not team_res.data:
                print(f"Errore: Nessun fanta-team trovato con ID {team_id}.")
                return False

            team_name = team_res.data[0]["name"]

            # 2. Recupera i giocatori e le loro posizioni assegnate dalla tabella rosters
            roster_res = (
                self.supabase.table("rosters")
                .select("player_name, assigned_position")
                .eq("fanta_team_id", team_id)
                .execute()
            )

            if not roster_res.data:
                print(f"Attenzione: Nessun giocatore trovato nel roster per il team {team_name} ({team_id}).")
                return False

            # Crea la mappa localmente { "Nome Giocatore": "STARTER" / "BENCH" / ... }
            db_positions = {row["player_name"]: row["assigned_position"] for row in roster_res.data}

            # 3. Legge e aggiorna il file fanta_teams.json
            json_path = Path(filepath)
            if not json_path.exists():
                print(f"Errore: Il file '{filepath}' non esiste.")
                return False

            with open(json_path, "r", encoding="utf-8") as f:
                teams_data = json.load(f)

            if team_name not in teams_data:
                teams_data[team_name] = {}

            # Sovrascrive/aggiorna le posizioni dei giocatori per questa squadra
            for player_name, assigned_pos in db_positions.items():
                teams_data[team_name][player_name] = assigned_pos

            # 4. Salva il file JSON aggiornato
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(teams_data, f, ensure_ascii=False, indent=4)

            print(f"Posizioni per '{team_name}' aggiornate con successo nel file '{filepath}'.")
            return True

        except Exception as e:
            print(f"Errore durante l'aggiornamento del file JSON per il team ID {team_id}: {e}")
            raise e
        

if __name__ == "__main__":
    sync = SupabaseSync()
    
    # Esempio con l'ID di un team (es. "Bonaz" o "Mazen")
    team_uuid = "a4ddff3f-33cd-4ba2-b7e0-f50eb5efe9b8"
    sync.sync_team_positions_to_json(team_id=team_uuid)