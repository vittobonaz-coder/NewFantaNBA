"""
Codice comune dell'app, avviata da test.py (in locale) o da main.py (su Render).
I punteggi li scrive solo il cron (cron_test_script.py). L'accesso è una sola richiesta (RPC login_bundle o
token_bundle): profilo, contesto della lega (giornate e scadenza dei cambi), formazione modificabile della
propria squadra e le sole parti dello snapshot cambiate rispetto alla cache locale (league_cache.py).
"""
import asyncio
import flet as ft
import league_cache
import supabase_rest as rest
from ui_court import MainDashboard, LoginView
from time_manager import TimeManager


LOGIN_TOKEN_KEY = "fantanba.login_token"  # Chiave del token "Ricordami" nello storage del dispositivo/browser


async def main(page: ft.Page) -> None:
    page.title = 'Fanta NBA - Dashboard'
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 358
    page.window.height = 757
    prefs = ft.SharedPreferences()  # Storage del browser (localStorage sul web)

    def show_message(text: str, color: str = "white"):
        page.clean()
        page.add(ft.Text(text, color=color))
        page.update()

    def show_login():
        page.clean()
        page.add(LoginView(page, on_login_success))
        page.update()

    def load_user_data(bundle: dict) -> tuple[dict | None, str | None]:
        """
        Applica il bundle dell'accesso alla cache locale e carica le squadre da mostrare. Nessuna richiesta di rete.
        Gira in un thread, quindi niente UI qui: restituisce (dati, None) oppure (None, errore).
        """
        try:
            team_row = (bundle.get("fanta_teams") or [None])[0]
            if not team_row:
                return None, f"Nessuna squadra associata a {bundle['username']}"

            league_cache.apply_snapshot(bundle)
            league_cache.apply_my_team(bundle.get("my_team"), team_row["name"])
            league = league_cache.parse_context(bundle.get("context") or {})
            TimeManager.sync_with_server(league["now"])
            gameweeks = [gw for gw in (league["current_gw"], league["edit_gw"]) if gw is not None]
            if not gameweeks:
                return None, "Calendario vuoto"
            teams = {gw: league_cache.load_team(team_row["name"], gw) for gw in gameweeks}
        except Exception as e:
            print(f"Errore durante l'aggiornamento dei dati: {e}")
            return None, "Impossibile scaricare i dati, riprova più tardi"

        if any(team is None for team in teams.values()):
            return None, f"Errore Roster: {team_row['name']}"
        return {"team_row": team_row, "league": league, "teams": teams}, None

    async def on_login_success(bundle: dict, remember: bool = False, token: str | None = None):
        """
        bundle: risposta di login_bundle o token_bundle; con username e password contiene anche il token
        di sessione, che serve a tutti i salvataggi (formazione, profilo).
        remember: login con "Ricordami" spuntato, il token si salva sul dispositivo per l'accesso automatico.
        token: accesso automatico con il token già salvato sul dispositivo.
        """
        token = token or bundle.get("token")
        if remember and token:
            try:
                await prefs.set(LOGIN_TOKEN_KEY, token)
            except Exception as e:
                print(f"'Ricordami' non disponibile: {e}")  # Si entra lo stesso, senza accesso automatico

        data, error = await asyncio.to_thread(load_user_data, bundle)
        if error:
            show_message(error, "red")
            return
        team_row, league, teams = data["team_row"], data["league"], data["teams"]

        # Le altre squadre (solo giornata in corso) sono già nella cache: nessuna richiesta all'apertura del tab
        current_gw = league["current_gw"]
        league_loader = (lambda: league_cache.load_other_teams(team_row["id"], current_gw)) \
                        if current_gw is not None else None

        page.clean()
        page.add(MainDashboard(
            user={"id": bundle["id"], "username": bundle["username"], "token": token}, team_row=team_row,
            current_team=teams.get(current_gw) if current_gw != league["edit_gw"] else None, current_gw=current_gw,
            edit_team=teams.get(league["edit_gw"]), edit_gw=league["edit_gw"],
            edit_deadline=league["deadline"],
            league_loader=league_loader,
            on_logout=logout,
        ))
        page.update()
        rest.misura_fine("accesso")

    async def logout(token: str | None):
        """Chiude la sessione (dispositivo e Supabase) e torna al login."""
        try:
            await prefs.remove(LOGIN_TOKEN_KEY)
            if token:
                await asyncio.to_thread(rest.logout, token)
        except Exception as e:
            print(f"Errore durante il logout: {e}")
        show_login()

    async def try_auto_login() -> bool:
        """Accesso con il token salvato nel browser. False = serve la schermata di login."""
        token = await prefs.get(LOGIN_TOKEN_KEY)
        if not token:
            return False
        rest.misura_inizio("accesso")
        page.add(ft.Column([ft.ProgressRing(), ft.Text("Accesso in corso...")],
                           horizontal_alignment=ft.CrossAxisAlignment.CENTER))
        page.update()
        try:
            bundle = await asyncio.to_thread(rest.token_bundle, token, league_cache.local_versions())
        except Exception as e:
            print(f"Accesso automatico non riuscito: {e}")  # Server irraggiungibile: il token resta
            return False
        if not bundle:
            # Scaduto o revocato (logout, cambio password da un altro dispositivo)
            await prefs.remove(LOGIN_TOKEN_KEY)
            return False
        await on_login_success(bundle, token=token)
        return True

    # Avvio: accesso automatico se c'è un token valido, altrimenti schermata di login
    if not await try_auto_login():
        show_login()
