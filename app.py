"""
Codice comune dell'app, avviata da test.py (in locale), main.py (su Render) o nativa.py (app installata).
I punteggi li scrive solo il cron (cron_test_script.py). L'accesso è una sola richiesta (RPC login_bundle o
token_bundle): profilo, contesto della lega (giornate e scadenza dei cambi), formazione modificabile della
propria squadra e le sole parti dello snapshot cambiate rispetto alla cache locale (league_cache.py).

Fase 3 (docs/fase3_piano.md): area sicura dei telefoni, finestra ridimensionabile sul PC, tasto Indietro su
Android, aggiornamento silenzioso al ritorno in primo piano e, nell'app installata, dati in cache senza rete.

Fase 5 (docs/fase5_piano.md): nell'app installata, controllo degli aggiornamenti letto all'avvio (app_release):
sotto la versione minima l'app non si usa, con una versione più nuova compare una barra chiudibile.

Fase 6 (docs/fase6_piano.md): all'accesso si manda chi accede (client_usage); la webapp aperta da Android, Windows o
Mac mostra una barra chiudibile che invita a installare l'app.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import flet as ft

import aggiornamenti
import app_paths
import flet_fix
import foto
import league_cache
import supabase_rest as rest
import versione
from ui_court import MainDashboard, LoginView
from time_manager import TimeManager, ITA_TZ


LOGIN_TOKEN_KEY = "fantanba.login_token"    # Token "Ricordami" nello storage del dispositivo/browser
LAST_PROFILE_KEY = "fantanba.last_profile"  # Ultimo accesso riuscito (solo app installata): per l'avvio senza rete
REFRESH_AFTER = timedelta(minutes=5)        # Al ritorno in primo piano si aggiorna se i dati sono più vecchi
BACK_EXIT_WINDOW = 3.0                      # Secondi per il secondo Indietro con modifiche non salvate
DESKTOP_PLATFORMS = (ft.PagePlatform.WINDOWS, ft.PagePlatform.MACOS, ft.PagePlatform.LINUX)
# Sistemi con l'app pubblicata. Mac (ft.PagePlatform.MACOS: "Mac") da aggiungere quando esce il rilascio con
# l'app per Mac: prima l'invito porterebbe a una release senza il file per Mac.
APP_PLATFORMS = {ft.PagePlatform.ANDROID: "Android", ft.PagePlatform.WINDOWS: "Windows"}
RELEASES_URL = "https://github.com/vittobonaz-coder/NewFantaNBA/releases/latest"  # Download e istruzioni

if not flet_fix.applica():  # Patch veloci e niente aggiornamento automatico (solo Flet 0.82)
    print(f"flet_fix non applicato: Flet {ft.__version__}")


def _bundle_signature(bundle: dict) -> str:
    """Ciò che cambia la dashboard: parti scaricate, contesto (senza l'ora), propria formazione."""
    context = {k: v for k, v in (bundle.get("context") or {}).items() if k != "now"}
    return json.dumps([sorted(bundle.get("parts") or {}), context, bundle.get("my_team")], sort_keys=True, default=str)


async def main(page: ft.Page) -> None:
    page.title = 'Bonkest'
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0
    native = app_paths.is_native()
    if not page.web and page.platform in DESKTOP_PLATFORMS:
        # Finestra libera (non più 358×757): il contenuto si adatta in larghezza
        page.window.width, page.window.height = 1100, 800
        page.window.min_width, page.window.min_height = 380, 600
    prefs = ft.SharedPreferences()  # Storage del dispositivo (localStorage sul web)
    # Chi accede (webapp da iPhone, app Android...), registrato in client_usage all'accesso (Fase 6)
    client = aggiornamenti.client_info(page.web, native, getattr(page.platform, "value", None), versione.VERSIONE)

    # Stato della sessione in questa pagina (sul web una per browser: niente variabili globali)
    session: dict = {"token": None, "user": None, "dashboard": None, "signature": None,
                     "busy": False, "pending": None, "back_armed_at": 0.0,
                     "update": None,  # Configurazione di una versione più nuova (barra "Disponibile..."), Fase 5
                     # Webapp da Android/Windows/Mac: barra "C'è l'app" finché non si chiude (fino al ricaricamento)
                     "app_hint": APP_PLATFORMS.get(page.platform) if page.web else None}

    def show(control: ft.Control) -> None:
        """Contenuto della pagina dentro l'area sicura (barra di stato, notch, barra dei gesti)."""
        page.clean()
        page.add(ft.SafeArea(content=control, expand=True))
        page.update()

    def centered(*controls: ft.Control) -> ft.Column:
        return ft.Column(list(controls), expand=True, alignment=ft.MainAxisAlignment.CENTER,
                         horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    def show_message(text: str, color: str = "white"):
        session["dashboard"] = None
        show(centered(ft.Text(text, color=color)))

    def show_login(message: str = ""):
        session.update(dashboard=None, token=None, user=None, pending=None)
        login = LoginView(page, on_login_success, client)
        if message:
            login.error_text.value = message
        show(login)

    def snack(text: str, color: str = "grey_800"):
        page.show_dialog(ft.SnackBar(ft.Text(text), bgcolor=color))  # Con page.overlay in Flet 0.82 non compare

    # --- Dati ---

    def load_user_data(bundle: dict | None, offline_profile: dict | None = None) -> tuple[dict | None, str | None]:
        """
        Applica il bundle dell'accesso alla cache locale e carica le squadre da mostrare. Nessuna richiesta di rete.
        Senza rete (offline_profile) usa solo la cache e il contesto salvato.
        Gira in un thread, quindi niente UI qui: restituisce (dati, None) oppure (None, errore).
        """
        source = offline_profile or bundle
        try:
            team_row = (source.get("fanta_teams") or [None])[0]
            if not team_row:
                return None, f"Nessuna squadra associata a {source['username']}"

            if offline_profile is None:
                league_cache.apply_snapshot(bundle)
                league_cache.apply_my_team(bundle.get("my_team"), team_row["name"])
                league = league_cache.parse_context(bundle.get("context") or {})
                TimeManager.sync_with_server(league["now"])
            else:
                league = league_cache.offline_context(offline_profile.get("context") or {})
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

    def build_dashboard(data: dict, banner: ft.Control | None = None, selected_index: int = 0) -> None:
        """Mostra la dashboard (con un eventuale avviso in alto), sul tab indicato."""
        team_row, league, teams = data["team_row"], data["league"], data["teams"]
        user = session["user"]
        # Le altre squadre (solo giornata in corso) sono già nella cache: nessuna richiesta all'apertura del tab
        current_gw = league["current_gw"]
        league_loader = (lambda: league_cache.load_other_teams(team_row["id"], current_gw)) \
                        if current_gw is not None else None
        dashboard = MainDashboard(
            user={"id": user["id"], "username": user["username"], "token": session["token"]}, team_row=team_row,
            current_team=teams.get(current_gw) if current_gw != league["edit_gw"] else None, current_gw=current_gw,
            edit_team=teams.get(league["edit_gw"]), edit_gw=league["edit_gw"],
            edit_deadline=league["deadline"],
            league_loader=league_loader,
            on_logout=logout,
            width=page.width,
            desktop=page.platform in DESKTOP_PLATFORMS,  # Mouse: frecce accanto alle barre scorrevoli (anche web da PC)
        )
        session["dashboard"] = dashboard
        session["pending"] = None
        if banner is None and session["update"]:
            banner = update_banner(session["update"])
        if banner is None and session["app_hint"]:
            banner = app_hint_banner(session["app_hint"])
        controls = ([banner] if banner else []) + [dashboard]
        show(ft.Column(controls, expand=True, spacing=0))
        if selected_index:
            page.run_task(dashboard.select_tab, selected_index)

    def banner(text: str, icon: ft.IconData, action_label: str, on_action, color: str = "#3a2a00") -> ft.Container:
        return ft.Container(
            bgcolor=color, padding=ft.Padding.symmetric(horizontal=12, vertical=4),
            content=ft.Row([
                ft.Icon(icon, size=18, color="amber"),
                ft.Text(text, size=12, expand=True),
                ft.TextButton(action_label, on_click=on_action),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    # --- Aggiornamenti (solo app installata, Fase 5) ---

    async def open_download(url: str) -> None:
        try:
            await page.launch_url(url)  # Browser del dispositivo: scarica l'APK o l'installer
        except Exception as e:
            print(f"Link di download non aperto: {e}")
            snack(f"Apri dal browser: {url}")

    def closable_bar(text: str, icon: ft.IconData, action_label: str, url: str, session_key: str) -> ft.Container:
        """Barra blu sopra la dashboard con un link e ×; chiusa, non ricompare finché session[session_key] è vuoto."""
        async def open_link(e):
            await open_download(url)

        def close(e):
            session[session_key] = None  # Fino al prossimo avvio (app) o ricaricamento della pagina (webapp)
            root = page.controls[0].content if page.controls else None
            if isinstance(root, ft.Column) and bar in root.controls:
                root.controls.remove(bar)
                root.update()

        bar = ft.Container(
            bgcolor="#1f2f4a", padding=ft.Padding.only(left=12, right=4, top=2, bottom=2),
            content=ft.Row([
                ft.Icon(icon, size=18, color="lightblue"),
                ft.Text(text, size=12, expand=True),
                ft.TextButton(action_label, on_click=open_link),
                ft.IconButton(ft.Icons.CLOSE, icon_size=16, tooltip="Chiudi", on_click=close),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )
        return bar

    def update_banner(info: dict) -> ft.Container:
        """Barra "Disponibile la versione X" con Scarica e ×: a ogni avvio finché non si aggiorna."""
        return closable_bar(f"Disponibile la versione {info.get('latest_version')}", ft.Icons.SYSTEM_UPDATE,
                            "Scarica", info["url"], "update")

    def app_hint_banner(system: str) -> ft.Container:
        """Webapp da Android/Windows/Mac (Fase 6): invito a installare l'app, più veloce e senza attese del server."""
        return closable_bar(f"Bonkest c'è anche come app per {system}: più veloce", ft.Icons.INSTALL_MOBILE,
                            "Scopri", RELEASES_URL, "app_hint")

    def show_update_required(info: dict) -> None:
        """Versione sotto la minima: niente accesso, solo il link per aggiornare (la webapp resta usabile)."""
        async def download(e):
            await open_download(info["url"])

        session["dashboard"] = None
        note = info.get("note") or ""
        show(ft.Container(padding=24, expand=True, content=centered(
            ft.Icon(ft.Icons.SYSTEM_UPDATE, size=56, color="amber"),
            ft.Text("Aggiornamento necessario", size=20, weight=ft.FontWeight.BOLD),
            ft.Text(f"Questa versione ({versione.VERSIONE}) non è più utilizzabile: "
                    f"installa la {info.get('latest_version')} per continuare.",
                    text_align=ft.TextAlign.CENTER),
            *([ft.Text(note, size=12, color="grey_400", text_align=ft.TextAlign.CENTER)] if note else []),
            ft.FilledButton("Scarica", icon=ft.Icons.DOWNLOAD, on_click=download),
            ft.Text("Nel frattempo puoi usare la versione web dal browser.", size=12, color="grey_500",
                    text_align=ft.TextAlign.CENTER),
        )))

    async def check_updates() -> bool:
        """
        Esito del controllo letto all'avvio (supabase_rest.warm_up): False se l'app non si può usare.
        Webapp, build di sviluppo, rete assente o configurazione mancante: nessun controllo.
        """
        if not native or not versione.VERSIONE:
            return True
        info = await asyncio.to_thread(rest.release_info)
        result = aggiornamenti.esito(info, versione.VERSIONE)
        if result == aggiornamenti.OBBLIGATORIA:
            show_update_required(info)
            return False
        if result == aggiornamenti.NUOVA:
            session["update"] = info
        return True

    async def save_last_profile(bundle: dict) -> None:
        """Solo app installata: profilo e contesto dell'ultimo accesso, per aprire la cache senza rete."""
        if not native:
            return
        profile = {"id": bundle["id"], "username": bundle["username"], "fanta_teams": bundle.get("fanta_teams"),
                   "context": bundle.get("context"), "saved_at": datetime.now(timezone.utc).isoformat()}
        try:
            await prefs.set(LAST_PROFILE_KEY, json.dumps(profile))
        except Exception as e:
            print(f"Profilo per l'uso senza rete non salvato: {e}")

    async def on_login_success(bundle: dict, remember: bool = False, token: str | None = None,
                               selected_index: int = 0):
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
        session.update(token=token, user={"id": bundle["id"], "username": bundle["username"]},
                       signature=_bundle_signature(bundle))
        build_dashboard(data, selected_index=selected_index)
        rest.misura_fine("accesso")
        page.run_task(save_last_profile, bundle)  # Dopo la dashboard, fuori dal percorso dell'avvio
        if native:
            page.run_task(asyncio.to_thread, foto.sync_missing)  # Foto mancanti nella cartella dati (senza rete poi)

    async def open_offline(token: str) -> bool:
        """Avvio senza rete (app installata, "Ricordami"): ultimi dati in cache con un avviso. False se non si può."""
        if not native:
            return False
        try:
            profile = json.loads(await prefs.get(LAST_PROFILE_KEY) or "null")
        except Exception:
            profile = None
        if not profile:
            return False
        data, error = await asyncio.to_thread(load_user_data, None, profile)
        if error:
            print(f"Cache non utilizzabile senza rete: {error}")
            return False
        session.update(token=token, user={"id": profile["id"], "username": profile["username"]}, signature=None)
        last = league_cache.last_sync()
        when = f" — dati del {last.astimezone(ITA_TZ):%d/%m alle %H:%M}" if last else ""
        build_dashboard(data, banner=banner(f"Senza connessione{when}", ft.Icons.WIFI_OFF, "Riprova", retry))
        return True

    async def logout(token: str | None):
        """Chiude la sessione (dispositivo e Supabase) e torna al login."""
        try:
            await prefs.remove(LOGIN_TOKEN_KEY)
            await prefs.remove(LAST_PROFILE_KEY)
            if token:
                await asyncio.to_thread(rest.logout, token)
        except Exception as e:
            print(f"Errore durante il logout: {e}")
        show_login()

    async def try_auto_login() -> bool:
        """Accesso con il token salvato. False = serve la schermata di login."""
        token = await prefs.get(LOGIN_TOKEN_KEY)
        if not token:
            return False
        rest.misura_inizio("accesso")
        show(centered(ft.ProgressRing(), ft.Text("Accesso in corso...")))
        try:
            bundle = await asyncio.to_thread(rest.token_bundle, token, league_cache.local_versions(), client)
        except Exception as e:
            print(f"Accesso automatico non riuscito: {e}")  # Server irraggiungibile: il token resta
            if rest.is_network_error(e) and await open_offline(token):
                return True
            return False
        if not bundle:
            # Scaduto o revocato (logout, cambio password da un altro dispositivo)
            await prefs.remove(LOGIN_TOKEN_KEY)
            await prefs.remove(LAST_PROFILE_KEY)
            return False
        await on_login_success(bundle, token=token)
        return True

    # --- Aggiornamento silenzioso (ritorno in primo piano, "Riprova") ---

    async def refresh(force: bool = False) -> None:
        """
        Una richiesta (token_bundle): controlla la sessione e scarica solo le parti cambiate. Se non è cambiato
        nulla non tocca la dashboard; se è cambiato, la ricostruisce sul tab corrente, salvo modifiche non
        salvate alla formazione (in quel caso propone di ricaricare).
        """
        dashboard, token = session["dashboard"], session["token"]
        if dashboard is None or not token or session["busy"]:
            return
        offline = session["signature"] is None  # Dashboard aperta dalla cache senza rete
        last = league_cache.last_sync()
        if not force and not offline and last and datetime.now(timezone.utc) - last < REFRESH_AFTER:
            return
        session["busy"] = True
        try:
            bundle = await asyncio.to_thread(rest.token_bundle, token, league_cache.local_versions())
        except Exception as e:
            print(f"Aggiornamento non riuscito: {e}")
            if force:
                snack("Ancora senza connessione" if rest.is_network_error(e) else "Aggiornamento non riuscito",
                      "red")
            return
        finally:
            session["busy"] = False
        if session["dashboard"] is not dashboard:
            return  # Nel frattempo logout o nuovo accesso
        if not bundle:
            await prefs.remove(LOGIN_TOKEN_KEY)
            await prefs.remove(LAST_PROFILE_KEY)
            show_login("Sessione scaduta, rifai l'accesso")
            return
        if not offline and _bundle_signature(bundle) == session["signature"] and not bundle.get("parts"):
            league_cache.apply_snapshot(bundle)  # Solo l'ora dell'ultimo aggiornamento
            return
        if dashboard.has_unsaved_changes():
            already_shown = session["pending"] is not None
            session["pending"] = bundle
            if not already_shown:
                show_pending_banner()
            return
        await on_login_success(bundle, token=token, selected_index=dashboard.selected_index)

    def show_pending_banner():
        """Dati nuovi ma formazione con modifiche non salvate: si ricarica solo su richiesta."""
        dashboard = session["dashboard"]
        root = page.controls[0].content if page.controls else None
        if dashboard is None or not isinstance(root, ft.Column) or dashboard not in root.controls:
            return
        # Sostituisce l'eventuale barra "Senza connessione": la rete è tornata
        root.controls = [banner("Dati aggiornati disponibili", ft.Icons.REFRESH, "Ricarica", reload_pending,
                                color="#1f3a1f"), dashboard]
        page.update()

    async def reload_pending(e=None):
        bundle, dashboard = session["pending"], session["dashboard"]
        if bundle and dashboard:
            await on_login_success(bundle, token=session["token"], selected_index=dashboard.selected_index)

    async def retry(e=None):
        await refresh(force=True)

    async def on_lifecycle(e: ft.AppLifecycleStateChangeEvent):
        if e.state in (ft.AppLifecycleState.RESUME, ft.AppLifecycleState.SHOW):
            await refresh()

    # --- Tasto Indietro (Android) ---

    async def on_back(e):
        """
        Indietro sulla vista radice: chiude il dialog aperto; con modifiche non salvate chiede un secondo
        Indietro; dagli altri tab torna a Squadra; dalla Squadra esce come le altre app.
        """
        view = page.views[0]
        while (dialog := page.pop_dialog()) is not None:
            if not isinstance(dialog, ft.SnackBar):  # Gli avvisi si chiudono e basta, non fermano l'Indietro
                await view.confirm_pop(False)
                return
        dashboard = session["dashboard"]
        if dashboard is not None:
            now = asyncio.get_running_loop().time()
            if dashboard.has_unsaved_changes() and now - session["back_armed_at"] > BACK_EXIT_WINDOW:
                session["back_armed_at"] = now
                snack("Formazione non salvata: premi di nuovo Indietro per uscire")
                await view.confirm_pop(False)
                return
            if dashboard.selected_index != 0:
                await dashboard.select_tab(0)
                await view.confirm_pop(False)
                return
        await view.confirm_pop(True)

    def on_resize(e):
        if session["dashboard"] is not None:
            session["dashboard"].apply_width(page.width)

    page.on_resize = on_resize
    page.on_app_lifecycle_state_change = on_lifecycle
    if not page.web and page.platform == ft.PagePlatform.ANDROID:
        page.views[0].can_pop = False
        page.views[0].on_confirm_pop = on_back
        try:
            # Solo verticale: il campo è pensato in verticale (sui tablet Android 16 può ignorarlo)
            await page.set_allowed_device_orientations([ft.DeviceOrientation.PORTRAIT_UP])
        except Exception as e:
            print(f"Orientamento non bloccato: {e}")

    # Avvio: controllo degli aggiornamenti (app installata), poi accesso automatico se c'è un token valido,
    # altrimenti schermata di login
    if not await check_updates():
        return
    if not await try_auto_login():
        show_login()
