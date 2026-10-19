"""
Codice comune dell'app, avviata da test.py (in locale) o da main.py (su Render).
I punteggi li scrive solo il cron (cron_test_script.py): l'app li scarica da Supabase
quando è girato un cron dopo l'ultimo download e li salva nei file locali.
"""
import os
import json
import flet as ft
from datetime import datetime
from fanta_obj import Team
from ui_court import MainDashboard, LoginView
from time_manager import TimeManager
from supabase_manager import SupabaseSync


CALENDAR_PATH = os.path.join("data", "calendar.json")
STANDINGS_PATH = os.path.join("data", "standings.json")
SYNC_META_PATH = os.path.join("data", "sync_meta.json")  # Da non committare (.gitignore)


def parse_timestamp(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None

def is_stale(data_as_of: str | None, last_update: datetime) -> bool:
    """True se dopo il download dei dati locali è girato un cron (o non si sa quando sono stati scaricati)."""
    local = parse_timestamp(data_as_of)
    return local is None or local < last_update

def get_last_update(sync: SupabaseSync) -> datetime:
    """Fine dell'ultimo cron che ha scritto su Supabase (se non tracciato: ultimo orario programmato + margine)."""
    return sync.get_last_cron_run() or TimeManager.last_scheduled_cron()

def sync_league_data(sync: SupabaseSync, last_update: datetime) -> list[dict]:
    """Calendario (con i punteggi di tutte le squadre) e classifica: riscaricati solo se è girato un cron."""
    meta = {}
    if os.path.exists(SYNC_META_PATH):
        try:
            with open(SYNC_META_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            meta = {}

    files_exist = os.path.exists(CALENDAR_PATH) and os.path.exists(STANDINGS_PATH)
    if files_exist and not is_stale(meta.get("league_data_as_of"), last_update):
        print("Calendario e classifica locali già aggiornati")
        with open(CALENDAR_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    calendar = sync.pull_calendar()
    sync.sync_standings()
    with open(SYNC_META_PATH, "w", encoding="utf-8") as f:
        json.dump({"league_data_as_of": last_update.isoformat()}, f, indent=4)
    return calendar

def sync_team_data(sync: SupabaseSync, team_name: str, team_id: str, gameweek: int, last_update: datetime) -> Team | None:
    """Formazione e punteggi della squadra per la giornata indicata: riscaricati se mancano o sono vecchi."""
    team = Team(team_name, gameweek=gameweek)
    if team.load_from_json() and not is_stale(team.data_as_of, last_update):
        print(f"Stato locale di {team_name} già aggiornato (GW {gameweek})")
        return team

    sync.pull_lineup_for_team(team_name, gameweek, team_id=team_id, data_as_of=last_update)
    return team if team.load_from_json() else None


def main(page: ft.Page) -> None:
    page.title = 'Fanta NBA - Dashboard'
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 358
    page.window.height = 757

    def show_message(text: str, color: str = "white"):
        page.clean()
        page.add(ft.Text(text, color=color))
        page.update()

    def on_login_success(user_data):
        page.clean()
        page.add(ft.Column(
            [ft.ProgressRing(), ft.Text("Aggiornamento dati...")],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER
        ))
        page.update()

        try:
            sync = SupabaseSync()
            team_row = sync.get_team_by_user_id(user_data["id"])
            if not team_row:
                show_message(f"Nessuna squadra associata a {user_data['username']}", "red")
                return

            # 1. Calendario e classifica (riscaricati solo dopo un nuovo run del cron)
            last_update = get_last_update(sync)
            calendar = sync_league_data(sync, last_update)

            # 2. Giornata in corso, giornata modificabile e scadenza dei cambi
            league = TimeManager.get_league_context(calendar)
            gameweeks = [gw for gw in (league["current_gw"], league["edit_gw"]) if gw is not None]
            if not gameweeks:
                show_message("Calendario vuoto", "red")
                return

            # 3. Formazione e punteggi della squadra per ciascuna giornata da mostrare
            teams = {gw: sync_team_data(sync, team_row["name"], team_row["id"], gw, last_update) for gw in gameweeks}
        except Exception as e:
            print(f"Errore durante l'aggiornamento dei dati: {e}")
            show_message("Impossibile scaricare i dati, riprova più tardi", "red")
            return

        if any(team is None or not team.is_valid_roster() for team in teams.values()):
            show_message(f"Errore Roster: {team_row['name']}", "red")
            return

        page.clean()
        page.add(MainDashboard(
            current_team=teams.get(league["current_gw"]), current_gw=league["current_gw"],
            edit_team=teams.get(league["edit_gw"]), edit_gw=league["edit_gw"],
            edit_deadline=league["deadline"]
        ))
        page.update()

    # Avvio con schermata di login
    page.add(LoginView(page, on_login_success))
