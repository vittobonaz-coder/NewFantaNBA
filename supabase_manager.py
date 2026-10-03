from supabase import create_client, Client
from fanta_obj import Player, Team

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

# --- ESEMPIO DI UTILIZZO ---
# if __name__ == "__main__":
#     sync_manager = SupabaseSync()

#     # Esempio Scrittura: prendiamo il team esistente dal file locale (caricato in test.py)
#     # my_team = Team(name="MyTeam")
#     # my_team.load_from_json()
#     # my_court = Court(my_team)
#     # sync_manager.push_team(my_team, my_court)

#     # Esempio Lettura:
#     team_remoto = sync_manager.pull_team("MyTeam")
#     if team_remoto:
#         print(f"Team caricato da Cloud: {team_remoto.name}, Score: {team_remoto.score}")
#         for p in team_remoto.get_ordered_roster():
#             print(f" - {p.name} [{team_remoto.roles_map[p.id]}]")