"""
Chiamate dirette all'API REST di Supabase (PostgREST) con httpx, senza supabase-py: è l'unico accesso
dell'app al database. L'app non legge tabelle: usa solo le RPC di sql/2026-11_fase1a_password_rpc.sql
(profilo, salvataggio) e sql/2026-11_fase2a_snapshot_bundle.sql (accesso con i dati, snapshot).
httpx è già installato con flet: nessuna dipendenza nuova.

Misure: con la variabile d'ambiente FANTANBA_MISURE=1 stampa ogni richiesta (percorso, stato, ms, byte,
compressione) e i tempi segnati con misura_inizio / misura_fine.
"""
import os
import threading
import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from fanta_obj import Team

SUPABASE_URL = "https://ifqiarpfsbcrfpmabdus.supabase.co"
# Chiave pubblicabile: è pubblica per definizione (finisce anche nell'APK). Con le RLS della Fase 1
# permette solo di leggere i dati di lega e di chiamare le RPC. Mai qui la chiave segreta.
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_KNhdTSkcs0XuzDwKqNbIOA_XpiJlqFZ"

TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MISURE = os.environ.get("FANTANBA_MISURE") == "1"


class RpcError(ValueError):
    """
    Errore previsto restituito da una RPC (errcode P0001): messaggio in italiano da mostrare all'utente
    e codice macchina (hint): SESSIONE_SCADUTA, PASSWORD_ERRATA, ROSA_CAMBIATA, CAMBI_CHIUSI, NON_VALIDO.
    È un ValueError, come gli errori di validazione che l'interfaccia già mostra all'utente.
    """
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


# --- Misure (solo con FANTANBA_MISURE=1) ---

_misura: dict[str, float] = {}
richieste_contate = 0


def _on_request(request: httpx.Request) -> None:
    request.extensions["t0"] = time.perf_counter()


def _on_response(response: httpx.Response) -> None:
    global richieste_contate
    response.read()
    ms = (time.perf_counter() - response.request.extensions.get("t0", time.perf_counter())) * 1000
    richieste_contate += 1
    size = response.num_bytes_downloaded
    print(f"[MISURE] {response.request.method} {response.request.url.path} -> {response.status_code} "
          f"{ms:.0f} ms, {size} byte trasferiti, {len(response.content)} byte, "
          f"compressione: {response.headers.get('content-encoding', 'nessuna')}")


def misura_inizio(label: str) -> None:
    if MISURE:
        _misura[label] = time.perf_counter()


def misura_fine(label: str) -> None:
    if MISURE and label in _misura:
        print(f"[MISURE] {label}: {(time.perf_counter() - _misura.pop(label)) * 1000:.0f} ms")


# Client unico per processo: la connessione (e il TLS) resta aperta tra una chiamata e l'altra.
# httpx.Client è thread-safe.
_client: httpx.Client | None = None
_client_lock = threading.Lock()


def get_http_client() -> httpx.Client:
    """Restituisce il client httpx condiviso, creandolo alla prima chiamata."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(
                    base_url=f"{SUPABASE_URL}/rest/v1",
                    headers={"apikey": SUPABASE_PUBLISHABLE_KEY},
                    timeout=TIMEOUT,
                    event_hooks={"request": [_on_request], "response": [_on_response]} if MISURE else None,
                )
    return _client


def rpc(name: str, args: dict[str, Any]) -> Any:
    """
    Chiama la funzione SQL public.<name> (POST /rest/v1/rpc/<name>) e restituisce il JSON della risposta
    (None per le funzioni void o quando restituiscono null).
    RpcError per gli errori previsti, httpx.HTTPStatusError per gli altri, httpx.HTTPError per la rete.
    """
    response = get_http_client().post(f"/rpc/{name}", json=args)
    if response.status_code >= 400:
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, dict) and body.get("code") == "P0001":
            raise RpcError(body.get("message") or "Operazione non riuscita", body.get("hint"))
        print(f"RPC {name}: HTTP {response.status_code} {body or response.text[:200]}")
        response.raise_for_status()
    if not response.content:
        return None
    return response.json()


# --- Accesso e dati (una richiesta: profilo, contesto, formazione modificabile, parti dello snapshot cambiate) ---

def login_bundle(username: str, password: str, remember: bool, versions: dict[str, str]) -> dict | None:
    """
    Login con username e password. None se le credenziali sono errate, altrimenti
    {"id", "username", "fanta_teams", "token", "expires_at", "context", "my_team", "versions", "parts"}.
    Il token dura 90 giorni con remember ("Ricordami", da salvare sul dispositivo), 7 senza.
    versions: versioni delle parti dello snapshot già in cache (league_cache.local_versions()).
    """
    return rpc("login_bundle", {"p_username": username, "p_password": password, "p_remember": remember,
                                "p_versions": versions})


def token_bundle(token: str, versions: dict[str, str]) -> dict | None:
    """Accesso con il token salvato sul dispositivo: come login_bundle, senza token. None se scaduto o revocato."""
    return rpc("token_bundle", {"p_token": token, "p_versions": versions})


def get_snapshot(versions: dict[str, str]) -> dict:
    """Parti dello snapshot cambiate rispetto a versions, con il contesto della lega: {"context", "versions", "parts"}."""
    return rpc("get_snapshot", {"p_versions": versions})


# --- Profilo e salvataggi (richiedono il token di sessione) ---

def logout(token: str) -> None:
    """Il token non vale più (anche sugli altri dispositivi che lo avessero)."""
    rpc("logout", {"p_token": token})


def change_username(token: str, password: str, new_username: str) -> None:
    """Cambia lo username, confermato dalla password attuale. RpcError (ValueError) se non valido o già usato."""
    rpc("change_username", {"p_token": token, "p_password": password, "p_new_username": new_username.strip()})


def change_password(token: str, old_password: str, new_password: str) -> None:
    """Cambia la password; gli altri dispositivi con "Ricordami" devono rifare l'accesso, questo no."""
    rpc("change_password", {"p_token": token, "p_old_password": old_password, "p_new_password": new_password})


def change_team_name(token: str, password: str, new_name: str) -> None:
    """
    Rinomina la fanta-squadra dell'utente. Il nome identifica la squadra anche nei file locali
    (<nome>_gwN_state.json): il database controlla che resti unico con la stessa regola dei nomi dei file
    e rigenera le parti dello snapshot che contengono i nomi.
    """
    rpc("change_team_name", {"p_token": token, "p_password": password, "p_new_name": new_name.strip()})


def save_lineup(token: str, team: "Team", gameweek: int) -> None:
    """
    Salva formazione e modulo della squadra dell'utente dalla giornata indicata in poi, in una sola
    richiesta e transazione: ruoli in rosters, slot e ruoli in lineup_players, modulo in matchups.
    Gli slot seguono l'ordine di team.players (1 = primo). RpcError con code "CAMBI_CHIUSI" se la giornata
    non è più modificabile, "ROSA_CAMBIATA" se la rosa su Supabase non coincide più con quella dell'app.
    """
    players = [{"nba_player_id": p.id, "slot": slot, "role": team.roles_map[p.id]}
               for slot, p in enumerate(team.players, start=1)]
    rpc("save_lineup", {"p_token": token, "p_gameweek": gameweek, "p_players": players, "p_lineup": team.lineup})
