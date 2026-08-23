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

        # 1. Upsert Giocatori
        players_data = []
        for p in team.players:
            players_data.append({
                "id": p.id,
                "name": p.name,
                "team_abbreviation": p.team_abbreviation,
                "position": p.position,
                "score": p.score
            })
        self.supabase.table("players").upsert(players_data).execute()

        # 2. Upsert Team
        # Se court è presente prendiamo la lineup dalla UI, altrimenti default '2-2-1'
        lineup_val = court.lineup if court else team.lineup
        team_row = {
            "name": team.name,
            "total_score": team.score,
            "lineup_type": lineup_val
        }
        team_res = self.supabase.table("fanta_teams").upsert(team_row, on_conflict="name").execute()
        fanta_team_id = team_res.data[0]["id"]

        # 3. Aggiorna il Roster (incluso il nome del giocatore)
        self.supabase.table("roster").delete().eq("fanta_team_id", fanta_team_id).execute()
        
        roster_data = []
        ordered_players = team.get_ordered_roster()
        for idx, p in enumerate(ordered_players):
            roster_data.append({
                "fanta_team_id": fanta_team_id,
                "player_id": p.id,
                "player_name": p.name,  # <--- Nuovo campo salvato
                "role": team.roles_map[p.id],
                "slot_index": idx
            })
        self.supabase.table("roster").insert(roster_data).execute()
        print(f"Sincronizzazione {team.name} completata.")


    def push_all_teams(self, teams_list: list[Team]):
        """Carica tutte le squadre della lista su Supabase"""
        print(f"Inizio sincronizzazione massiva di {len(teams_list)} squadre...")
        for t in teams_list:
            try:
                self.push_team(t)
            except Exception as e:
                print(f"Errore durante l'upload di {t.name}: {e}")
        print("Sincronizzazione globale terminata.")


    def pull_team(self, team_name: str) -> Team:
        """Recupera i dati da Supabase e ricostruisce l'oggetto Team"""
        response = self.supabase.table("fanta_teams") \
            .select("*, roster(*, players(*))") \
            .eq("name", team_name) \
            .single() \
            .execute()

        data = response.data
        if not data:
            return None

        new_team = Team(name=data["name"])
        new_team.score = data["total_score"]

        for item in data["roster"]:
            p_data = item["players"]
            player = Player(
                id=p_data["id"],
                name=p_data["name"],
                team_abbreviation=p_data["team_abbreviation"],
                position=p_data["position"],
                score=p_data["score"]
            )
            new_team.add_player(player, item["role"])
        
        return new_team

# --- ESEMPIO DI UTILIZZO ---
if __name__ == "__main__":
    sync_manager = SupabaseSync()

    # Esempio Scrittura: prendiamo il team esistente dal file locale (caricato in test.py)
    # my_team = Team(name="MyTeam")
    # my_team.load_from_json()
    # my_court = Court(my_team)
    # sync_manager.push_team(my_team, my_court)

    # Esempio Lettura:
    team_remoto = sync_manager.pull_team("MyTeam")
    if team_remoto:
        print(f"Team caricato da Cloud: {team_remoto.name}, Score: {team_remoto.score}")
        for p in team_remoto.get_ordered_roster():
            print(f" - {p.name} [{team_remoto.roles_map[p.id]}]")