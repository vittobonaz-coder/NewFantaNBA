import os
import json
from supabase import create_client, Client
from fanta_obj import Player, Team, NOT_PLAYED_SCORE
from pathlib import Path
from datetime import date
from time_manager import TimeManager

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

    def sync_team_positions_to_json(self, team_id: str, data_dir: str = "data") -> bool:
        """
        Legge la colonna 'assigned_position' dei giocatori per un determinato team_id
        dalla tabella 'rosters' e aggiorna il campo 'role' nel file JSON '<nome_team>_state.json'.
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
                .select("nba_player_id, player_name, assigned_position")
                .eq("fanta_team_id", team_id)
                .execute()
            )

            if not roster_res.data:
                print(f"Attenzione: Nessun giocatore trovato nel roster per il team {team_name} ({team_id}).")
                return False

            # Crea le mappe di confronto sia per Nome che per ID NBA (per massima affidabilità)
            db_positions_by_name = {row["player_name"]: row["assigned_position"] for row in roster_res.data}
            db_positions_by_id = {row["nba_player_id"]: row["assigned_position"] for row in roster_res.data}

            # 3. Costruisce il percorso del file <nome_team>_state.json
            filename = f"{team_name.lower()}_state.json"
            json_path = Path(data_dir) / filename

            if not json_path.exists():
                print(f"Errore: Il file '{json_path}' non esiste.")
                return False

            with open(json_path, "r", encoding="utf-8") as f:
                state_data = json.load(f)

            # Convertiamo sia ID che nomi in stringhe per evitare fallimenti di lookup
            db_positions_by_name = {str(row["player_name"]).lower().strip(): row["assigned_position"] for row in roster_res.data if row.get("player_name")}
            db_positions_by_id = {str(row["nba_player_id"]): row["assigned_position"] for row in roster_res.data if row.get("nba_player_id")}

            # 4. Aggiorna il campo 'role' di ogni giocatore presente nella lista 'roster'
            updated_count = 0
            if "roster" in state_data and isinstance(state_data["roster"], list):
                for player in state_data["roster"]:
                    p_id = str(player.get("id")) if player.get("id") is not None else ""
                    p_name = str(player.get("name")).lower().strip() if player.get("name") else ""

                    # Trova il nuovo ruolo controllando prima l'ID, poi il Nome
                    new_role = db_positions_by_id.get(p_id) or db_positions_by_name.get(p_name)
                    
                    if new_role:
                        player["role"] = new_role
                        updated_count += 1

            # 5. Salva il file JSON aggiornato
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(state_data, f, ensure_ascii=False, indent=4)

            print(f"Posizioni per '{team_name}' aggiornate con successo in '{json_path}' ({updated_count} giocatori).")
            return True

        except Exception as e:
            print(f"Errore durante l'aggiornamento del file state JSON per il team ID {team_id}: {e}")
            raise e

    def get_team_roster_data(self, team_id: str) -> tuple[dict[str, str], list[str]]:
        """
        Legge la tabella 'rosters' per un determinato team_id e restituisce una tupla contenente:
        - roles_map: dict {player_name: assigned_position}
        - names_list: list [player_name, ...]
        """
        try:
            response = (
                self.supabase.table("rosters")
                .select("player_name, assigned_position")
                .eq("fanta_team_id", team_id)
                .execute()
            )

            data = response.data or []

            if not data:
                print(f"Attenzione: Nessun giocatore trovato nella tabella rosters per il team_id {team_id}.")
                return {}, []

            roles_map = {row["player_name"]: row["assigned_position"] for row in data if row.get("player_name")}
            names_list = [row["player_name"] for row in data if row.get("player_name")]

            return roles_map, names_list

        except Exception as e:
            print(f"Errore durante il recupero dei dati del roster per team_id {team_id}: {e}")
            raise e

    def get_team_id_by_name(self, team_name: str) -> str | None:
        """
        Restituisce il team_id (UUID) di una fanta-squadra a partire dal suo nome.
        Ritorna None se la squadra non viene trovata.
        """
        try:
            response = (
                self.supabase.table("fanta_teams")
                .select("id")
                .eq("name", team_name)
                .execute()
            )

            data = response.data
            if data and len(data) > 0:
                return data[0]["id"]

            print(f"Attenzione: Nessuna squadra trovata con nome '{team_name}'.")
            return None

        except Exception as e:
            print(f"Errore durante il recupero dell'ID per la squadra '{team_name}': {e}")
            raise e

    def get_gameweek_by_date(self, target_date: date | str) -> int | None:
        """
        Restituisce la gameweek corrispondente a una determinata data
        verificando l'intervallo start_date <= target_date <= end_date nella tabella 'matchups'.
        Ritorna None se la data non rientra in alcuna gameweek.
        """
        # Formatta la data nel formato ISO "YYYY-MM-DD"
        if isinstance(target_date, date):
            date_str = target_date.isoformat()
        else:
            date_str = str(target_date)

        try:
            # Filtra i matchups dove start_date <= date_str e end_date >= date_str
            response = (
                self.supabase.table("matchups")
                .select("gameweek")
                .lte("start_date", date_str)
                .gte("end_date", date_str)
                .limit(1)
                .execute()
            )

            data = response.data

            if data and len(data) > 0:
                return int(data[0]["gameweek"])

            print(f"Nessuna gameweek trovata per la data {date_str}.")
            return None

        except Exception as e:
            print(f"Errore durante il recupero della gameweek per la data {date_str}: {e}")
            raise e

    def sync_all_teams_state_to_json(self, data_dir: str = "data") -> None:
        """
        Allinea i file '<nome_team>_state.json' locali con il database Supabase per TUTTE le squadre.
        Se il file esiste, aggiorna il roster preservando score e lineup. 
        Se non esiste, lo crea da zero.
        """
        print("Inizio sincronizzazione di tutti i file di stato dei team (state.json)...")
        
        try:
            # 1. Recupera tutte le tabelle necessarie in sole 3 query (ottimizzazione)
            teams_res = self.supabase.table("fanta_teams").select("*").execute()
            rosters_res = self.supabase.table("rosters").select("*").execute()
            players_res = self.supabase.table("nba_players").select("*").execute()

            teams_data = teams_res.data or []
            rosters_data = rosters_res.data or []
            players_data = players_res.data or []

            # 2. Crea dizionari di supporto per incrociare i dati velocemente in memoria
            players_dict = {p["id"]: p for p in players_data}
            
            rosters_by_team = {}
            for r in rosters_data:
                t_id = r["fanta_team_id"]
                if t_id not in rosters_by_team:
                    rosters_by_team[t_id] = []
                rosters_by_team[t_id].append(r)

            # 3. Assicurati che la cartella 'data' esista
            dir_path = Path(data_dir)
            dir_path.mkdir(parents=True, exist_ok=True)

            # 4. Itera su ogni fanta-squadra per creare/aggiornare il JSON
            for team in teams_data:
                team_id = team["id"]
                team_name = team["name"]
                
                filename = f"{team_name.lower()}_state.json"
                json_path = dir_path / filename

                # Dati base se il file non esiste
                state_data = {
                    "team_name": team_name,
                    "target_date": date.today().isoformat(),
                    "total_score": 0.0,
                    "lineup": "2-2-1",
                    "roster": []
                }

                # Dizionario per mantenere i punteggi attuali (score) se il file esiste
                existing_scores = {}

                if json_path.exists():
                    with open(json_path, "r", encoding="utf-8") as f:
                        try:
                            existing_data = json.load(f)
                            # Preserva campi vitali dal file preesistente
                            state_data["target_date"] = existing_data.get("target_date", state_data["target_date"])
                            state_data["total_score"] = existing_data.get("total_score", 0.0)
                            state_data["lineup"] = existing_data.get("lineup", "2-2-1")
                            
                            # Salva gli score attuali dei giocatori mappati per ID
                            for p in existing_data.get("roster", []):
                                if "id" in p:
                                    existing_scores[p["id"]] = p.get("score", NOT_PLAYED_SCORE)
                        except json.JSONDecodeError:
                            print(f"Avviso: Il file {filename} era corrotto. Verrà ricreato.")

                # 5. Costruisci il nuovo roster allineato al DB
                new_roster = []
                for r_entry in rosters_by_team.get(team_id, []):
                    nba_id = r_entry["nba_player_id"]
                    player_info = players_dict.get(nba_id, {})
                    
                    new_roster.append({
                        "id": nba_id,
                        "name": player_info.get("full_name", r_entry.get("player_name", "Sconosciuto")),
                        "team": player_info.get("nba_team", ""),
                        "pos": player_info.get("position", ""),
                        "score": existing_scores.get(nba_id, NOT_PLAYED_SCORE),
                        "role": r_entry.get("assigned_position", "RESERVE")
                    })
                
                state_data["roster"] = new_roster

                # 6. Salva il file su disco
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, ensure_ascii=False, indent=4)
                
            print(f"Sincronizzazione completata con successo! Aggiornati/Creati {len(teams_data)} file JSON.")

        except Exception as e:
            print(f"Errore critico durante la sincronizzazione massiva dei team state: {e}")
            raise e

    def update_lineup_player_score(self, gameweek: int, score: float | None, nba_player_id: int = None, player_name: str = None) -> bool:
        """
        Aggiorna il campo 'score' nella tabella lineup_players per un giocatore in una determinata gameweek.
        Utilizza nba_player_id (consigliato) o player_name per identificare il giocatore.
        """
        if nba_player_id is None and player_name is None:
            print("Errore: Devi fornire nba_player_id o player_name per aggiornare lo score.")
            return False
            
        try:
            # Prepariamo l'update di base con la gameweek
            query = self.supabase.table("lineup_players").update({"score": score}).eq("gameweek", gameweek)
            
            # Aggiungiamo il filtro per il giocatore
            if nba_player_id is not None:
                query = query.eq("nba_player_id", nba_player_id)
            else:
                query = query.eq("player_name", player_name)
                
            response = query.execute()
            
            # Se response.data è valorizzato, l'update è andato a buon fine (il giocatore era schierato)
            if response.data:
                # print(f"Score ({score}) aggiornato in lineup_players per id={nba_player_id} / gw={gameweek}.")
                return True
            else:
                # Il giocatore potrebbe non essere stato inserito nella lineup di questa gameweek, ignoriamo silenziosamente o logghiamo
                return False
                
        except Exception as e:
            print(f"Errore durante l'aggiornamento del punteggio in lineup_players per {nba_player_id or player_name} (GW: {gameweek}): {e}")
            return False

    def get_lineup_player_score(self, gameweek: int, fanta_team_id: str, nba_player_id: int) -> float | None:
        """
        Recupera lo score attuale di un giocatore dalla tabella lineup_players su Supabase.
        Restituisce None se la squadra NBA del giocatore non ha ancora giocato (score NULL).
        """
        try:
            response = self.supabase.table('lineup_players') \
                .select('score') \
                .eq('gameweek', gameweek) \
                .eq('fanta_team_id', fanta_team_id) \
                .eq('nba_player_id', nba_player_id) \
                .execute()
            
            if response.data and len(response.data) > 0:
                raw_score = response.data[0].get('score')
                return float(raw_score) if raw_score is not None else NOT_PLAYED_SCORE
        except Exception as e:
            print(f"Errore recupero score per player {nba_player_id} da supabase: {e}")
            
        return 0.0

    def push_lineup_for_team(self, team_name: str, data_dir: str = "data") -> bool:
        """
        Legge il file state.json di una singola squadra e compila la tabella lineup_players 
        per la gameweek corrente, calcolata dalla target_date.
        """
        filename = f"{team_name.lower()}_state.json"
        json_path = Path(data_dir) / filename

        if not json_path.exists():
            print(f"Errore: File {json_path} non trovato per il team {team_name}.")
            return False

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                state_data = json.load(f)

            target_date_nba = state_data.get("target_date")
            if not target_date_nba:
                print(f"Errore: target_date mancante nel file {filename}.")
                return False

            # 1. Calcola la data italiana (Lega) per recuperare la gameweek corretta
            # (Assicurati di aver importato TimeManager nel tuo file)
            italian_date = TimeManager.nba_date_to_italian_date(target_date_nba)
            
            gameweek = self.get_gameweek_by_date(italian_date)
            if gameweek is None:
                print(f"Errore: Nessuna gameweek trovata su Supabase per la data {italian_date}.")
                return False

            # 2. Ottieni il fanta_team_id
            fanta_team_id = self.get_team_id_by_name(team_name)
            if not fanta_team_id:
                print(f"Errore: Impossibile recuperare l'ID per il team {team_name}.")
                return False

            # 3. Elimina l'eventuale lineup già presente per evitare giocatori duplicati
            self.supabase.table("lineup_players").delete() \
                .eq("fanta_team_id", fanta_team_id) \
                .eq("gameweek", gameweek) \
                .execute()

            # 4. Prepara i dati da inserire iterando sul roster
            roster = state_data.get("roster", [])
            lineup_data = []

            for index, player in enumerate(roster):
                # Lo slot è la posizione nell'array (partendo da 1)
                slot_number = index + 1 
                
                lineup_data.append({
                    "fanta_team_id": fanta_team_id,
                    "gameweek": gameweek,
                    "nba_player_id": player.get("id"),
                    "slot": slot_number,
                    "score": player.get("score", NOT_PLAYED_SCORE),
                    "player_name": player.get("name"),
                    "role": player.get("role"),
                    "target_date": target_date_nba
                })

            # 5. Inserisci in batch la nuova lineup su Supabase
            if lineup_data:
                self.supabase.table("lineup_players").insert(lineup_data).execute()
                print(f"Lineup di '{team_name}' caricata (GW {gameweek}, {len(lineup_data)} giocatori).")
            else:
                print(f"Avviso: Roster vuoto per {team_name}, nessun dato inserito.")

            return True

        except Exception as e:
            print(f"Errore durante l'aggiornamento della lineup per {team_name}: {e}")
            return False


    def push_lineup_for_all_teams(self, data_dir: str = "data") -> None:
        """
        Itera su tutti i fanta_teams salvati su Supabase e compila le rispettive 
        tabelle lineup_players leggendo i file state.json locali.
        """
        print("Inizio esportazione delle lineup verso Supabase per TUTTE le squadre...")
        try:
            # 1. Recupera la lista di tutti i team dal DB
            teams_res = self.supabase.table("fanta_teams").select("name").execute()
            if not teams_res.data:
                print("Nessuna squadra trovata nel database Supabase.")
                return

            success_count = 0
            # 2. Itera ed esegue il caricamento per ogni squadra
            for team in teams_res.data:
                team_name = team["name"]
                if self.push_lineup_for_team(team_name=team_name, data_dir=data_dir):
                    success_count += 1
            
            print(f"Esportazione completata: {success_count}/{len(teams_res.data)} squadre aggiornate su DB.")

        except Exception as e:
            print(f"Errore critico durante l'esportazione massiva delle lineup: {e}")

    def push_season_lineups(self, calendar: list[dict]) -> None:
        """
        Inserisce in lineup_players le righe di TUTTE le giornate della stagione per tutte le squadre,
        partendo dai file <nome_team>_state.json locali. Gli score sono NULL (nessuna partita giocata).
        Pensato per il setup iniziale: presuppone la tabella vuota (reset_pre_setup.py).
        """
        print("Inserimento delle lineup di tutte le giornate su Supabase...")
        teams_res = self.supabase.table("fanta_teams").select("id, name").execute()
        if not teams_res.data:
            print("Nessuna squadra trovata nel database Supabase.")
            return

        for t in teams_res.data:
            state_path = Team(t["name"]).filename
            if not os.path.exists(state_path):
                print(f"Errore: File {state_path} non trovato per il team {t['name']}.")
                continue
            with open(state_path, "r", encoding="utf-8") as f:
                roster = json.load(f).get("roster", [])

            lineup_data = []
            for round_data in calendar:
                # Le date del calendario sono italiane, target_date in lineup_players è la data NBA
                target_date = TimeManager.italian_date_to_nba_date(round_data["start_date"])
                for index, player in enumerate(roster):
                    lineup_data.append({
                        "fanta_team_id": t["id"],
                        "gameweek": round_data["round_number"],
                        "nba_player_id": player.get("id"),
                        "slot": index + 1,
                        "score": NOT_PLAYED_SCORE,
                        "player_name": player.get("name"),
                        "role": player.get("role"),
                        "target_date": target_date
                    })

            if lineup_data:
                self.supabase.table("lineup_players").insert(lineup_data).execute()
                print(f"Lineup di '{t['name']}' caricate: {len(calendar)} giornate, {len(lineup_data)} righe.")

    def pull_lineup_for_team(self, team_name: str, gameweek: int, data_dir: str = "data") -> bool:
        """
        Scarica i dati dalla tabella lineup_players per una specifica gameweek e aggiorna 
        (o crea) il file locale <nome_team>_state.json.
        """
        print(f"Recupero della lineup per '{team_name}' (GW {gameweek}) da Supabase...")
        try:
            # 1. Recupera l'ID del fanta team
            team_id = self.get_team_id_by_name(team_name)
            if not team_id:
                print(f"Errore: Team '{team_name}' non trovato su Supabase.")
                return False

            # 2. Interroga lineup_players unendo i dati di nba_players (per avere team NBA e posizione)
            response = (
                self.supabase.table("lineup_players")
                .select("*, nba_players(nba_team, position)")
                .eq("fanta_team_id", team_id)
                .eq("gameweek", gameweek)
                .order("slot")
                .execute()
            )

            data = response.data
            if not data:
                print(f"Attenzione: Nessuna lineup trovata per '{team_name}' nella gameweek {gameweek}.")
                return False

            # 3. Costruisci il nuovo roster formattato per il JSON
            new_roster = []
            target_date = str(date.today().isoformat())  # Fallback

            for row in data:
                # Estrae target_date (basta prenderla dalla prima riga valida)
                if row.get("target_date"):
                    target_date = row["target_date"]

                # Dati dalla join con la tabella nba_players
                nba_info = row.get("nba_players") or {}

                new_roster.append({
                    "id": row.get("nba_player_id"),
                    "name": row.get("player_name"),
                    "team": nba_info.get("nba_team", ""),
                    "pos": nba_info.get("position", ""),
                    "score": float(row["score"]) if row.get("score") is not None else NOT_PLAYED_SCORE,
                    "role": row.get("role", "RESERVE")
                })

            # 4. Leggi il file esistente per preservare total_score e lineup (modulo)
            filename = f"{team_name.lower()}_state.json"
            json_path = Path(data_dir) / filename

            state_data = {
                "team_name": team_name,
                "target_date": target_date,
                "total_score": 0.0,
                "lineup": "2-2-1",
                "roster": new_roster
            }

            if json_path.exists():
                with open(json_path, "r", encoding="utf-8") as f:
                    try:
                        existing_data = json.load(f)
                        # Preserva modulo e score totale attuali
                        state_data["total_score"] = existing_data.get("total_score", 0.0)
                        state_data["lineup"] = existing_data.get("lineup", "2-2-1")
                    except json.JSONDecodeError:
                        pass

            # 5. Salva (o sovrascrivi) il file locale
            json_path.parent.mkdir(parents=True, exist_ok=True)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(state_data, f, ensure_ascii=False, indent=4)

            print(f"File '{filename}' aggiornato con successo ({len(new_roster)} giocatori).")
            return True

        except Exception as e:
            print(f"Errore durante il pull della lineup per {team_name}: {e}")
            return False


    def pull_lineup_for_all_teams(self, gameweek: int, data_dir: str = "data") -> None:
        """
        Scarica le lineup di TUTTE le squadre da Supabase per una determinata gameweek
        e aggiorna i rispettivi file <nome_team>_state.json locali.
        """
        print(f"Inizio importazione delle lineup da Supabase (GW {gameweek}) per TUTTE le squadre...")
        try:
            # 1. Recupera la lista dei team
            teams_res = self.supabase.table("fanta_teams").select("name").execute()
            if not teams_res.data:
                print("Nessuna squadra trovata nel database Supabase.")
                return

            success_count = 0
            
            # 2. Itera ed esegue il pull per ogni squadra
            for team in teams_res.data:
                team_name = team["name"]
                if self.pull_lineup_for_team(team_name=team_name, gameweek=gameweek, data_dir=data_dir):
                    success_count += 1
            
            print(f"Importazione completata: {success_count}/{len(teams_res.data)} file di stato aggiornati.")

        except Exception as e:
            print(f"Errore critico durante l'importazione massiva delle lineup: {e}")

    def get_team_name_by_id(self, team_id: str) -> str | None:
        """
        Restituisce il nome di una fanta-squadra (team_name) a partire dal suo team_id (UUID)
        interrogando la tabella 'fanta_teams'.
        
        Ritorna None se l'ID non viene trovato.
        """
        try:
            response = (
                self.supabase.table("fanta_teams")
                .select("name")
                .eq("id", team_id)
                .execute()
            )

            data = response.data
            if data and len(data) > 0:
                return data[0]["name"]

            print(f"Attenzione: Nessuna squadra trovata con ID '{team_id}'.")
            return None

        except Exception as e:
            print(f"Errore durante il recupero del nome per il team ID '{team_id}': {e}")
            raise e

    def pull_calendar(self, filepath: str = os.path.join("data", "calendar.json")) -> list[dict]:
        """
        Scarica il calendario dalla tabella 'matchups' di Supabase, risolve i nomi delle squadre
        e salva la struttura formattata in 'data/calendar.json'.
        """
        print("Sincronizzazione del calendario da Supabase in corso...")
        try:
            # Query con join per ottenere i nomi di home_team e away_team
            response = (
                self.supabase.table("matchups")
                .select(
                    "gameweek, start_date, end_date, home_score, away_score, was_played, "
                    "home_lineup, away_lineup, "
                    "home_team:fanta_teams!home_team_id(name), "
                    "away_team:fanta_teams!away_team_id(name)"
                )
                .order("gameweek")
                .execute()
            )

            data = response.data or []
            if not data:
                print("Avviso: Nessun matchup trovato su Supabase.")
                return []

            # Raggruppa i matchup per gameweek
            rounds_dict = {}
            for row in data:
                gw = row["gameweek"]
                if gw not in rounds_dict:
                    rounds_dict[gw] = {
                        "round_number": gw,
                        "start_date": str(row["start_date"]),
                        "end_date": str(row["end_date"]),
                        "matchups": []
                    }

                home_name = row["home_team"]["name"] if row.get("home_team") else "Unknown"
                away_name = row["away_team"]["name"] if row.get("away_team") else "Unknown"

                rounds_dict[gw]["matchups"].append({
                    "home_team": home_name,
                    "away_team": away_name,
                    "home_score": float(row["home_score"] or 0.0),
                    "away_score": float(row["away_score"] or 0.0),
                    "was_played": bool(row["was_played"]),
                    "home_lineup": row["home_lineup"] or "2-2-1",
                    "away_lineup": row["away_lineup"] or "2-2-1"
                })

            calendar_data = list(rounds_dict.values())

            # Scrittura su file JSON
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(calendar_data, f, ensure_ascii=False, indent=4)

            print(f"Calendario salvato con successo in '{filepath}' ({len(calendar_data)} giornate).")
            return calendar_data

        except Exception as e:
            print(f"Errore durante il pull del calendario da Supabase: {e}")
            raise e

    def is_first_day_of_gameweek(self, check_date: date | str, gameweek: int) -> bool:
        """
        Verifica se la data fornita (check_date) corrisponde al primo giorno (start_date)
        della gameweek indicata, consultando la tabella 'matchups'.
        
        Ritorna True se la data corrisponde a start_date, False altrimenti.
        """
        # Normalizza la data nel formato ISO "YYYY-MM-DD"
        if isinstance(check_date, date):
            date_str = check_date.isoformat()
        else:
            date_str = str(check_date)

        try:
            # Recupera la start_date per la gameweek indicata
            response = (
                self.supabase.table("matchups")
                .select("start_date")
                .eq("gameweek", gameweek)
                .limit(1)
                .execute()
            )

            data = response.data
            if data and len(data) > 0:
                gw_start_date = str(data[0]["start_date"])
                return gw_start_date == date_str

            print(f"Attenzione: Nessun matchup trovato per la gameweek {gameweek}.")
            return False

        except Exception as e:
            print(f"Errore durante la verifica del primo giorno per la GW {gameweek} e data {date_str}: {e}")
            raise e

    def reset_lineup_scores_for_gameweek(self, gameweek: int) -> bool:
        """
        Resetta il campo 'score' a NULL (= squadra NBA non ancora scesa in campo)
        per tutti i giocatori schierati nella tabella lineup_players per la gameweek specificata.
        """
        print(f"Resettaggio punteggi nella tabella lineup_players per la gameweek {gameweek}...")
        try:
            response = (
                self.supabase.table("lineup_players")
                .update({"score": NOT_PLAYED_SCORE})
                .eq("gameweek", gameweek)
                .execute()
            )

            updated_rows = len(response.data) if response.data else 0
            
            if updated_rows > 0:
                print(f"Reset completato con successo: score impostato a NULL per {updated_rows} righe (GW {gameweek}).")
                return True
            else:
                print(f"Attenzione: Nessuna riga trovata nella tabella lineup_players per la gameweek {gameweek}.")
                return False

        except Exception as e:
            print(f"Errore durante il reset degli score in lineup_players per la gameweek {gameweek}: {e}")
            raise e

    def push_fanta_teams_from_json(self, filepath: str = os.path.join("data", "fanta_teams.json")) -> bool:
        """
        1. Legge le chiavi (nomi delle squadre) dal file fanta_teams.json e 
        le inserisce nella tabella 'fanta_teams' su Supabase se non esistono già.
        """
        print(f"Lettura delle squadre dal file {filepath}...")
        try:
            if not os.path.exists(filepath):
                print(f"Errore: Il file {filepath} non esiste.")
                return False

            with open(filepath, "r", encoding="utf-8") as f:
                teams_data = json.load(f)

            # Le chiavi del JSON sono i nomi delle squadre
            team_names = list(teams_data.keys())
            
            # Recupera le squadre già presenti su DB per evitare duplicati
            existing_res = self.supabase.table("fanta_teams").select("name").execute()
            existing_names = [row["name"] for row in existing_res.data] if existing_res.data else []

            # Prepara i record solo per le squadre mancanti
            new_teams = [{"name": name} for name in team_names if name not in existing_names]

            if new_teams:
                self.supabase.table("fanta_teams").insert(new_teams).execute()
                print(f"Inserite {len(new_teams)} nuove squadre in 'fanta_teams'.")
            else:
                print("Tutte le squadre del JSON sono già presenti su Supabase.")

            return True

        except Exception as e:
            print(f"Errore durante il push delle fanta_teams: {e}")
            return False


    def push_profiles_from_teams(self) -> bool:
        """
        2. Legge la tabella 'fanta_teams', crea un profilo in 'profiles' per ogni 
        squadra (username: <nome_team>_user, password: 1) e collega l'id del profilo 
        al campo user_id della squadra.
        """
        print("Generazione dei profili a partire dalla tabella fanta_teams...")
        try:
            # Recupera le squadre dal database (con eventuale user_id già assegnato)
            teams_res = self.supabase.table("fanta_teams").select("id, name, user_id").execute()
            teams = teams_res.data or []

            # Recupera i profili esistenti per evitare di creare username duplicati
            profiles_res = self.supabase.table("profiles").select("id, username").execute()
            existing_profiles = {p["username"]: p["id"] for p in profiles_res.data} if profiles_res.data else {}

            created_count = 0
            linked_count = 0

            for team in teams:
                # Genera l'username desiderato
                target_username = f"{team['name']}_user"
                
                profile_id = existing_profiles.get(target_username)

                # Se il profilo non esiste, crealo
                if not profile_id:
                    new_profile = {
                        "username": target_username,
                        "password": "1"  # Come da richiesta, password impostata a "1"
                    }
                    insert_res = self.supabase.table("profiles").insert(new_profile).execute()
                    
                    if insert_res.data:
                        profile_id = insert_res.data[0]["id"]
                        existing_profiles[target_username] = profile_id
                        created_count += 1

                # Se la squadra non ha ancora il profilo collegato (FK user_id), aggiornala
                if profile_id and team.get("user_id") != profile_id:
                    self.supabase.table("fanta_teams").update({"user_id": profile_id}).eq("id", team["id"]).execute()
                    linked_count += 1

            print(f"Profili: {created_count} creati. Collegamenti FK aggiornati: {linked_count}.")
            return True

        except Exception as e:
            print(f"Errore durante la creazione dei profili: {e}")
            return False


    def pull_profiles(self, filepath: str = os.path.join("data", "profiles.json")) -> list[dict]:
        """
        3. Scarica la tabella 'profiles' da Supabase e la salva nel file 
        'profiles.json', includendo id, username e password.
        """
        print("Scaricamento dei profili da Supabase in corso...")
        try:
            # Recupera i dati richiesti
            response = self.supabase.table("profiles").select("id, username, password").execute()
            profiles_data = response.data or []

            # Salva nel file JSON
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(profiles_data, f, ensure_ascii=False, indent=4)

            print(f"Scaricati con successo {len(profiles_data)} profili in '{filepath}'.")
            return profiles_data

        except Exception as e:
            print(f"Errore durante il pull della tabella profiles: {e}")
            raise e

    def get_nba_player_ids(self, player_names: list[str] = None) -> list[int]:
        """
        Restituisce gli ID NBA ufficiali presenti nella tabella 'nba_players'.
        Se player_names è None restituisce tutti gli ID, altrimenti solo quelli
        dei giocatori il cui full_name corrisponde esattamente ai nomi forniti.
        """
        try:
            query = self.supabase.table("nba_players").select("id, full_name")

            if player_names is not None:
                if not player_names:
                    return []
                query = query.in_("full_name", player_names)

            data = query.execute().data or []

            if player_names is not None:
                found_names = {row["full_name"] for row in data}
                for name in player_names:
                    if name not in found_names:
                        print(f"Attenzione: Giocatore '{name}' non trovato in nba_players.")

            return [int(row["id"]) for row in data]

        except Exception as e:
            print(f"Errore durante il recupero degli ID da nba_players: {e}")
            raise e


if __name__ == "__main__":
    sync = SupabaseSync()
    
    # Esempio con l'ID di un team (es. "Bonaz" o "Mazen")
    team_uuid = "a4ddff3f-33cd-4ba2-b7e0-f50eb5efe9b8"

    # sync.sync_all_teams_state_to_json()

    # Aggiorna un singolo team...
    # sync.push_lineup_for_team("Pit")
    # ...oppure aggiorna tutto in blocco (ideale prima o dopo aver calcolato le API)
    # sync.push_lineup_for_all_teams()

    # team_name = sync.get_team_name_by_id(team_uuid)
    # print(f"Il nome della squadra con ID {team_uuid} è: {team_name}")
    print(len(sync.get_nba_player_ids()))