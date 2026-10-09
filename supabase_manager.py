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


if __name__ == "__main__":
    SupabaseSync().update_team_last_updated_date(team_id="1bca61f0-aea0-41fe-9c55-39b9e9fa825e")