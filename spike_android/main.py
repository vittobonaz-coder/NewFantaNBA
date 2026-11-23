"""
Prova tecnica della Fase 0 (docs/piano_migrazione_C1.md): mini-app Flet che fa login e legge
una tabella di lega con le stesse dipendenze dell'app vera.

- Due client a confronto: supabase-py e chiamate REST dirette (httpx, già dipendenza di supabase).
- Dalla Fase 1 il login usa la RPC login: un login riuscito crea un token di sessione di 7 giorni
  (come l'app senza "Ricordami"); a parte questo, solo letture.
- Misura l'avvio a freddo (creazione del processo -> prima schermata) e lo scrive in un file
  nella cartella dati dell'app, per verificare anche i percorsi scrivibili.

NON FUNZIONA PIÙ dopo la migrazione 2C (sql/2026-11_2C_chiusura_letture.sql): la RPC login e la lettura
diretta di matchups non sono più permesse alla chiave pubblicabile. Resta come documentazione della Fase 0;
la cartella serve ancora per il suo ambiente Python (spike_android/.venv), usato da flet build.
"""
import time

T_MODULE = time.time()  # Primo istante in cui gira codice Python dell'app

import asyncio
import json
import os
import platform
import sys
from pathlib import Path

import flet as ft

try:
    from config import SUPABASE_KEY, SUPABASE_URL
except ImportError:  # Manca config.py: va copiato da config.example.py
    SUPABASE_URL = SUPABASE_KEY = ""

PREFS_KEY = "fantanba_spike.ultimo_avvio"
LOG_NAME = "spike_avvii.jsonl"


def process_start_time() -> float | None:
    """Istante (epoch) di creazione del processo: su Android e Linux da /proc, su Windows da GetProcessTimes."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            creation, exit_, kernel, user = (wintypes.FILETIME() for _ in range(4))
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE  # Pseudo-handle -1: va passato a 64 bit
            kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            handle = kernel32.GetCurrentProcess()
            if not kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_),
                                            ctypes.byref(kernel), ctypes.byref(user)):
                return None
            ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime  # 100 ns dal 1601-01-01
            return ticks / 1e7 - 11644473600
        # Android / Linux: starttime (campo 22 di /proc/self/stat) in tick dal boot, confrontato con
        # /proc/uptime (su Android /proc/stat, che ha btime, non è leggibile dalle app)
        stat = Path("/proc/self/stat").read_text()
        start_s = int(stat.rsplit(")", 1)[1].split()[19]) / os.sysconf("SC_CLK_TCK")
        uptime_s = float(Path("/proc/uptime").read_text().split()[0])
        return time.time() - (uptime_s - start_s)
    except Exception:
        return None


async def data_dir(page: ft.Page) -> Path | None:
    """Cartella dati dell'app: variabile impostata da flet build, altrimenti StoragePaths; None sul web."""
    env = os.getenv("FLET_APP_STORAGE_DATA")
    if env:
        return Path(env)
    if page.web:
        return None
    try:
        return Path(await ft.StoragePaths().get_application_support_directory())
    except Exception:
        return None


# --- Client 1: supabase-py ---

def login_supabase_py(username: str, password: str) -> dict:
    """Stesse query dell'app (authenticate e pull_calendar) con supabase-py; restituisce i tempi in ms."""
    t0 = time.perf_counter()
    from supabase import create_client
    t_import = time.perf_counter()
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    t_client = time.perf_counter()
    # Login con la RPC della Fase 1 (sql/2026-11_fase1a_password_rpc.sql), come l'app
    data = client.rpc("login", {"p_username": username, "p_password": password, "p_remember": False}).execute().data
    profile = [data] if data else []
    t_login = time.perf_counter()
    matchups = (client.table("matchups").select(
        "gameweek, start_date, end_date, home_score, away_score, was_played, home_lineup, away_lineup, "
        "home_team:fanta_teams!home_team_id(name), away_team:fanta_teams!away_team_id(name)"
    ).order("gameweek").execute()).data
    t_read = time.perf_counter()
    return _result("supabase-py", profile, matchups, t0, t_import, t_client, t_login, t_read)


# --- Client 2: REST diretto (PostgREST) con httpx ---

def login_rest(username: str, password: str) -> dict:
    """Stesse query via REST diretto: solo l'header apikey, come richiesto dalle chiavi pubblicabili."""
    t0 = time.perf_counter()
    import httpx
    t_import = time.perf_counter()
    try:
        client = httpx.Client(base_url=f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY},
                              http2=True, timeout=20)
    except ImportError:  # h2 non disponibile: HTTP/1.1
        client = httpx.Client(base_url=f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY}, timeout=20)
    t_client = time.perf_counter()
    with client:
        # Login con la RPC della Fase 1 (sql/2026-11_fase1a_password_rpc.sql), come l'app
        r = client.post("/rpc/login", json={"p_username": username, "p_password": password, "p_remember": False})
        r.raise_for_status()
        profile = [r.json()] if r.json() else []
        t_login = time.perf_counter()
        r = client.get("/matchups", params={
            "select": "gameweek,start_date,end_date,home_score,away_score,was_played,home_lineup,away_lineup,"
                      "home_team:fanta_teams!home_team_id(name),away_team:fanta_teams!away_team_id(name)",
            "order": "gameweek"})
        r.raise_for_status()
        matchups = r.json()
        t_read = time.perf_counter()
    return _result("REST httpx", profile, matchups, t0, t_import, t_client, t_login, t_read)


def _result(mode: str, profile: list, matchups: list, t0, t_import, t_client, t_login, t_read) -> dict:
    ms = lambda a, b: round((b - a) * 1000)
    team = (profile[0].get("fanta_teams") or [{}])[0].get("name") if profile else None
    return {
        "modo": mode,
        "login_ok": bool(profile),
        "squadra": team,
        "righe_matchups": len(matchups or []),
        "ms_import": ms(t0, t_import),
        "ms_client": ms(t_import, t_client),
        "ms_login": ms(t_client, t_login),
        "ms_lettura": ms(t_login, t_read),
    }


MODE_KEY = "fantanba_spike.modo"  # "rest" oppure "supabase": client usato per la lettura automatica all'avvio


def read_matchups(mode: str) -> dict:
    """Import del client + prima lettura di matchups (connessione inclusa), come al primo avvio dell'app."""
    fn = login_rest if mode == "rest" else login_supabase_py
    return fn("__spike_nessun_utente__", "-")  # Login volutamente a vuoto: conta solo la lettura


async def main(page: ft.Page) -> None:
    t_main = time.time()
    page.title = "FantaNBA spike"
    page.theme_mode = ft.ThemeMode.DARK
    page.scroll = ft.ScrollMode.AUTO
    prefs = ft.SharedPreferences()

    log = ft.Column(spacing=4)
    username = ft.TextField(label="Username", autofocus=False, width=320)
    password = ft.TextField(label="Password", password=True, can_reveal_password=True, width=320)
    use_rest = ft.Switch(label="REST diretto (httpx) invece di supabase-py (vale anche dal prossimo avvio)",
                         value=False)

    def write(text: str, color: str | None = None) -> None:
        log.controls.append(ft.Text(text, color=color, selectable=True, size=13))
        page.update()

    async def do_login(e=None) -> None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            write("Manca config.py (copiarlo da config.example.py)", "red")
            return
        fn = login_rest if use_rest.value else login_supabase_py
        write(f"Login con {'REST' if use_rest.value else 'supabase-py'}...")
        try:
            res = await asyncio.to_thread(fn, username.value.strip(), password.value)
        except Exception as ex:
            write(f"Errore: {type(ex).__name__}: {ex}", "red")
            return
        write(json.dumps(res, ensure_ascii=False), "green" if res["login_ok"] else "orange")

    async def to_password(e) -> None:
        await password.focus()

    async def save_mode(e) -> None:
        await prefs.set(MODE_KEY, "rest" if use_rest.value else "supabase")

    password.on_submit = do_login
    username.on_submit = to_password
    use_rest.on_change = save_mode

    page.add(ft.SafeArea(content=ft.Column([
        ft.Text("FantaNBA — prova tecnica", size=20, weight=ft.FontWeight.BOLD),
        username, password, use_rest,
        ft.ElevatedButton("Accedi", on_click=do_login),
        ft.Divider(),
        log,
    ])))
    page.update()
    t_first = time.time()  # Prima schermata inviata a Flutter

    # Lettura automatica di matchups con il client scelto: misura "tocco dell'icona -> primi dati"
    mode = "supabase"
    try:
        mode = await prefs.get(MODE_KEY) or "supabase"
        use_rest.value = mode == "rest"
        page.update()
    except Exception as ex:
        write(f"SharedPreferences: errore ({ex})", "red")
    try:
        data = await asyncio.to_thread(read_matchups, mode)
    except Exception as ex:
        data = {"errore": f"{type(ex).__name__}: {ex}"}
    t_data = time.time()

    t_proc = process_start_time()
    rel = lambda t: round((t - t_proc) * 1000) if t_proc else None
    info = {
        "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
        "piattaforma": str(page.platform),
        "python": platform.python_version(),
        "modo": mode,
        "ms_processo_a_python": rel(T_MODULE),
        "ms_python_a_main": round((t_main - T_MODULE) * 1000),
        "ms_main_a_schermata": round((t_first - t_main) * 1000),
        "ms_processo_a_schermata": rel(t_first),
        "ms_processo_a_dati": rel(t_data),
        "lettura": data,
        # Istanti assoluti: su Android l'avvio del processo si ricava dal log di sistema (adb logcat -v epoch)
        "epoch_python": round(T_MODULE, 3),
        "epoch_schermata": round(t_first, 3),
        "epoch_dati": round(t_data, 3),
    }
    write(f"Avvio: {json.dumps(info, ensure_ascii=False)}")

    # Un avvio per riga, così le prove restano tutte. Su Android anche nella cache esterna, leggibile da adb.
    folders = [await data_dir(page)]
    if page.platform == ft.PagePlatform.ANDROID:
        try:
            folders += [Path(d) for d in (await ft.StoragePaths().get_external_cache_directories() or [])[:1]]
        except Exception as ex:
            write(f"Cache esterna non disponibile ({ex})", "orange")
    for folder in filter(None, folders):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / LOG_NAME, "a", encoding="utf-8") as f:
                f.write(json.dumps(info) + "\n")
            write(f"Scritto in {folder}")
        except Exception as ex:
            write(f"Cartella {folder}: scrittura fallita ({ex})", "red")

    # SharedPreferences: devono sopravvivere al riavvio (base del "Ricordami")
    try:
        previous = await prefs.get(PREFS_KEY)
        await prefs.set(PREFS_KEY, info["quando"])
        write(f"SharedPreferences OK, avvio precedente: {previous or 'nessuno'}")
    except Exception as ex:
        write(f"SharedPreferences: errore ({ex})", "red")


if __name__ == "__main__":
    ft.run(main=main)
