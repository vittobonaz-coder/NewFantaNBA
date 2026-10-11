import os
import json
import flet as ft
from typing import Dict, Optional, Union
from datetime import datetime, date
from fanta_obj import Player, Team
from api_nba import NbaDataManager
from ui_court import ROLE_CONFIGS, MainDashboard, LoginView
from time_manager import TimeManager
from supabase_manager import SupabaseSync

def get_user_date(team_name: str, teams_dict: Optional[Dict[str, str]] = None, as_date_object: bool = False, output_format: Optional[str] = None) -> Union[str, date, None]:
    """
    Restituisce la data associata a un username presente nel dizionario.
    Args:
        username (str): L'username da cercare (es. 'Mazen').
        user_dict (dict, optional): Il dizionario con gli username e le date. 
                                    Se None, usa USERS_DATES.
        as_date_object (bool): Se True, restituisce un oggetto datetime.date anziché str.
        output_format (str, optional): Formato di output per la stringa (es. "%d/%m/%Y").
    Returns:
        Union[str, date, None]: La data trovata o None se l'utente non esiste.
    """
    if teams_dict is None:
        print("Errore: il dict Username: date è vuoto")

    # Ricerca dell'username nel dizionario
    date_str = teams_dict.get(team_name)

    if not date_str:
        print(f"Attenzione: Username '{team_name}' non trovato nel dizionario.")
        return None

    try:
        # Conversione della stringa ISO ("YYYY-MM-DD") in oggetto date
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        if as_date_object:
            return parsed_date
        
        if output_format:
            return parsed_date.strftime(output_format)

        return date_str

    except ValueError:
        print(f"Errore: Il formato della data per '{team_name}' non è valido (%Y-%m-%d).")
        return None

def update_all_teams_scores_via_api(target_date: str, role_configs: dict = ROLE_CONFIGS):
    """
    Calcola e aggiorna i punteggi di tutte le squadre e dei giocatori in lineup_players per una determinata data.
    :param target_date: Data NBA/USA in input (es. "2026-10-03")
    """
    # 0. Gestione della duplice data (NBA vs Italia)
    nba_date = target_date                                              # es. "2026-10-03" (per API NBA)
    italian_date = TimeManager.nba_date_to_italian_date(target_date)    # es. "2026-10-04" (per Supabase / Gameweek)

    api_manager = NbaDataManager(player_ids=[])
    sync = SupabaseSync()

    # Recuperiamo la Gameweek da Supabase usando la DATA ITALIANA
    gameweek = sync.get_gameweek_by_date(italian_date)
    if gameweek is None:
        print(f"Avviso: Nessuna gameweek trovata su Supabase per la data italiana {italian_date}. L'aggiornamento dei matchups verrà saltato.")

    # 1. Recupero i nomi di tutti i team da data/fanta_teams.json
    fanta_teams_path = os.path.join("data", "fanta_teams.json")
    if not os.path.exists(fanta_teams_path):
        print(f"Errore: {fanta_teams_path} non trovato.")
        return []

    with open(fanta_teams_path, "r", encoding="utf-8") as f:
        fanta_teams = json.load(f)

    team_names = list(fanta_teams.keys())

    # 2. Scarico i boxscores dell'API usando la DATA NBA (USA)
    print(f"Scaricamento dati API per la data NBA {nba_date} (corrispondente al {italian_date} in Italia)...")
    _, daily_boxscores = api_manager.fetch_and_sync(nba_date)

    if not daily_boxscores:
        print(f"Nessun boxscore recuperato dall'API per la data {nba_date}.")
        return []

    updated_teams = []

    # 3. Itero su ciascuna squadra
    for team_name in team_names:
        team = Team(team_name)
        team.target_date = italian_date  # Salviamo nello state la data di lega/italiana

        state_file = team.filename  # "data/<nome_team_lower>_state.json"

        if not os.path.exists(state_file):
            print(f"File di stato non trovato: {state_file}. Salto...")
            continue

        with open(state_file, "r", encoding="utf-8") as f:
            state_data = json.load(f)

        team.lineup = state_data.get("lineup", "2-2-1")

        # 4. Ricostruisco il roster e calcolo il punteggio per la data NBA
        for p_data in state_data.get("roster", []):
            player = Player.from_dict(p_data)
            role = p_data.get("role", "RESERVE")

            # I boxscore dell'API contengono GAME_DATE == nba_date ("2026-10-03")
            player.calculate_score(daily_boxscores, target_date=nba_date, average=False)
            team.add_player(player, role)

            # Aggiorna lo score del singolo giocatore anche nella tabella lineup_players
            if gameweek is not None:
                sync.update_lineup_player_score(
                    gameweek=gameweek,
                    score=player.score,
                    nba_player_id=player.id
                )

        # 5. Calcola il totale del team e salva in locale
        team.calculate_total_score(role_configs)
        team.save_to_json() # Salva stato team su <nome_team>_state.json
        updated_teams.append(team)

        print(f"-> {team_name} aggiornato: {team.score} pt totali.")

        # 6. Sincronizzazione con Supabase usando la DATA ITALIANA e la Gameweek trovata
        try:
            team_id = sync.get_team_id_by_name(team_name)
            if team_id:
                if gameweek is not None:
                    sync.update_team_score_for_gameweek(team_id, gameweek, team.score)

                # Aggiorna last_updated_date con la data italiana
                # sync.update_team_last_updated_date(team_id, italian_date)
            else:
                print(f"Attenzione: Impossibile trovare l'ID Supabase per il team '{team_name}'.")
        except Exception as e:
            print(f"Errore durante l'aggiornamento su Supabase per {team_name}: {e}")

    return updated_teams

def daily_update_needed(team_name: str) -> bool:
    if TimeManager.is_past_eight_am():
        print(f"Sono passate le 8, controllo l'ultimo update per {team_name}")
        user_update_dict = SupabaseSync().get_last_updated_dates()
        last_updated_date = get_user_date(team_name=team_name, teams_dict=user_update_dict)
        print(f"La data dell'ultimo update è {last_updated_date}")
        if TimeManager().is_date_before_today(last_updated_date):
            print(f"L'ultimo update risale a prima di oggi --> Update necessario")
            return True
    else:
        print("Update non necessario")
        return False

def run_daily_update(team_id: str, new_date: date | str):
    # Formatta la data nel formato ISO "YYYY-MM-DD"
    if isinstance(new_date, date):
        date_str = new_date.isoformat()
    else:
        date_str = str(new_date)
    ita_date = TimeManager().nba_date_to_italian_date(nba_date_str=date_str)
    gw = SupabaseSync().get_gameweek_by_date(target_date=ita_date)

    # 1. Aggiorno last_updated_dates in fanta_teams (supabase)
    SupabaseSync().update_team_last_updated_date(team_id=team_id, new_date=ita_date)
    # 2. Controllo se il database è già stato aggiornato da un altro utente
    last_updated_dates = SupabaseSync().get_last_updated_dates()
    today_str = datetime.now().strftime("%Y-%m-%d")
    if today_str in last_updated_dates.values():
        # Leggo il punteggio della squadra direttamente da matchups (supabase)
        # team_score = SupabaseSync().get_team_score_for_gameweek(team_id=team_id, gameweek=gw)
        pass # matchups e v-standings sono già aggiornate
    else:
        SupabaseSync().sync_team_positions_to_json(team_id=team_id)
        SupabaseSync().sync_all_teams_state_to_json()
        update_all_teams_scores_via_api(target_date=date_str)

    # Pull e salvo classifica in locale da Supabase
    SupabaseSync().sync_standings()
    # Pull e salvo lo stato in locale
    team_name = SupabaseSync().get_team_name_by_id(team_id=team_id)
    SupabaseSync().pull_lineup_for_team(team_name=team_name, gameweek=gw)
    # Pull e salvo calendario in locale
    SupabaseSync().pull_calendar()


def main(page: ft.Page) -> None:
    page.title = 'Fanta NBA - Dashboard'
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 358
    page.window.height = 757

    def on_login_success(user_data):
        target_date = TimeManager().get_nba_target_date()
        # TODO: la riga seguente va sostituita con un metodo
        team_name = user_data["username"].replace("_user", "") 
        team = Team(name=team_name)

        sync = SupabaseSync()
        team_id = sync.get_team_id_by_name(team_name=team_name)
        # username = user_data["username"] 
        if daily_update_needed(team_name=team_name):
            run_daily_update(team_id=team_id, new_date=target_date)

        # 1. Prova a caricare lo stato dal file locale
        loaded_local = team.load_from_json()

        # 2. Se il file locale non esiste o è vuoto, scarica da Supabase
        if not loaded_local or not team.players:
            roles_map, names_list = sync.get_team_roster_data(team_id=team_id)
        else:
            # leggendo il ruolo dalla mappa interna di team (che usa p.id come chiave)
            roles_map = {p.name: team.roles_map.get(p.id, "RESERVE") for p in team.players}
            names_list = [p.name for p in team.players]

        # 3. Aggiorna i punteggi per la data di riferimento
        api_manager = NbaDataManager(player_ids=[])
        team.update_team_scores_for_date(
            api_manager=api_manager,
            target_date=target_date, # Data di riferimento per il setup iniziale
            names_list=names_list,
            roles_dict=roles_map,
            role_configs=ROLE_CONFIGS
        )
        
        
        if not team.is_valid_roster():
            page.add(ft.Text(f"Errore Roster: {team.name}", color="red"))
            return
        
        page.clean()
        page.add(MainDashboard(team))
        page.update()
    
    # Avvio con schermata di login
    page.add(LoginView(page, on_login_success))


if __name__ == "__main__":
    # Render usa la variabile d'ambiente PORT
    port = int(os.environ.get("PORT", 8080))
    
    ft.run(main=main, 
        port=port, 
        host="0.0.0.0", 
        assets_dir="assets",
    )