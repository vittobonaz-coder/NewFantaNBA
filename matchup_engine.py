from supabase import Client
from fanta_obj import Team, Player
import json

class MatchupManager:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def get_current_gameweek(self, current_date: str) -> int:
        # Rimuovi .single() e prendi il primo risultato se esiste
        res = self.supabase.table("matchups").select("gameweek")\
            .lte("start_date", current_date)\
            .gte("end_date", current_date).execute()
        
        if res.data:
            return res.data[0].get("gameweek")
        return None

    def update_matchup_scores(self, gameweek: int):
        print(f"DEBUG: Inizio update per GW {gameweek}")
        # 1. Recupera l'intervallo di date della GW (prendiamo il primo risultato)
        res = self.supabase.table("matchups").select("start_date, end_date")\
            .eq("gameweek", gameweek).execute()
        
        if not res.data:
            print(f"Nessun matchup trovato per GW {gameweek}")
            return
            
        matchup_info = res.data[0] # Prendi il primo, dato che le date sono uguali per la GW
        start = matchup_info["start_date"]
        end = matchup_info["end_date"]
        print(f"DEBUG: Periodo GW {start} -> {end}")

        # 2. Recupera le lineup per la GW
        lineups = self.supabase.table("lineup_players").select("*").eq("gameweek", gameweek).execute().data
        print(f"DEBUG: Lineup trovate: {len(lineups)}")
        
        # 3. Recupera SOLO le stats nell'intervallo temporale della GW
        stats_res = self.supabase.table("player_stats").select("*")\
            .gte("game_date", start)\
            .lte("game_date", end).execute().data
        print(f"DEBUG: Stats trovate nel DB: {len(stats_res)}")

        if not stats_res:
            print("DEBUG: Nessuna statistica trovata! Il calcolo si fermerà qui.")
            return
        
        # 4. Raggruppa per team e calcola (usando la logica esistente nel tuo Team)
        team_scores = {}
        for lp in lineups:
            t_id = lp["fanta_team_id"]
            if t_id not in team_scores: team_scores[t_id] = 0.0
            
            # Qui riutilizzi la logica del Player per calcolare il punteggio
            # (Puoi istanziare un Player ed usare il tuo metodo calculate_score esistente)
            p = Player(id=lp["nba_player_id"])
            p.calculate_score(stats_res) # Questo metodo usa il tuo algoritmo originale
            
            score = p.score * lp["multiplier"]
            team_scores[t_id] += score
            
            # Aggiorna il singolo giocatore su Supabase
            self.supabase.table("lineup_players").update({"final_score": score}).eq("id", lp["id"]).execute()

        # 5. Aggiorna i totali nei Matchup
        for t_id, total in team_scores.items():
            self.supabase.table("matchups").update({"home_score": total}).eq("home_team_id", t_id).eq("gameweek", gameweek).execute()
            self.supabase.table("matchups").update({"away_score": total}).eq("away_team_id", t_id).eq("gameweek", gameweek).execute()

    def sync_team_to_matchup(self, gameweek: int, team: Team):
        """
        1. Prende i giocatori dal team.
        2. Scrive i punteggi singoli in lineup_players.
        3. Aggiorna il totale in matchups.
        """
        # 1. Recupera fanta_team_id
        team_id = self.supabase.table("fanta_teams").select("id").eq("name", team.name).single().execute().data["id"]

        # 2. Per ogni giocatore nel team, aggiorniamo/inseriamo in lineup_players
        for p in team.players:
            # Calcolo del punteggio per il giocatore (usa la tua logica esistente)
            # Nota: qui potresti aver bisogno di passare le stats del DB se vuoi
            # il punteggio reale, oppure usare p.score se è già calcolato.
            final_p_score = p.score * team.roles_map.get(p.id, "RESERVE") # semplificato

            self.supabase.table("lineup_players").upsert({
                "fanta_team_id": team_id,
                "gameweek": gameweek,
                "nba_player_id": p.id,
                "slot": team.roles_map.get(p.id, "RESERVE"),
                "final_score": final_p_score
            }).execute()

        # 3. Aggiorna il punteggio totale in matchups
        # Recupera il matchup corrente per il team
        matchup = self.supabase.table("matchups").select("*").eq("gameweek", gameweek)\
            .or_(f"home_team_id.eq.{team_id},away_team_id.eq.{team_id}").single().execute().data
        
        # Calcola totale dalla tabella lineup_players aggiornata
        total_score = self.supabase.table("lineup_players").select("final_score")\
            .eq("fanta_team_id", team_id).eq("gameweek", gameweek).execute().data
        total = sum(item["final_score"] for item in total_score)

        if matchup["home_team_id"] == team_id:
            self.supabase.table("matchups").update({"home_score": total}).eq("id", matchup["id"]).execute()
        else:
            self.supabase.table("matchups").update({"away_score": total}).eq("id", matchup["id"]).execute()
    
    def get_standings(self):
        # TODO: Dovrebbe anche aggiornare il file standings.json in locale da cui leggerà l'HMI
        """Legge direttamente dalla vista v_standings."""
        return self.supabase.table("v_standings").select("*").execute().data