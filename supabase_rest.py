"""
Chiamate dirette all'API REST di Supabase (PostgREST) con httpx, senza supabase-py.
Per ora solo le RPC dell'app (login, profilo, salvataggio formazione: sql/2026-11_fase1a_password_rpc.sql);
le letture passano qui nelle fasi successive. httpx è già installato con flet: nessuna dipendenza nuova.
"""
import threading
from typing import Any

import httpx

SUPABASE_URL = "https://ifqiarpfsbcrfpmabdus.supabase.co"
# Chiave pubblicabile: è pubblica per definizione (finisce anche nell'APK). Con le RLS della Fase 1
# permette solo di leggere i dati di lega e di chiamare le RPC. Mai qui la chiave segreta.
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_KNhdTSkcs0XuzDwKqNbIOA_XpiJlqFZ"

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class RpcError(ValueError):
    """
    Errore previsto restituito da una RPC (errcode P0001): messaggio in italiano da mostrare all'utente
    e codice macchina (hint): SESSIONE_SCADUTA, PASSWORD_ERRATA, ROSA_CAMBIATA, NON_VALIDO.
    È un ValueError, come gli errori di validazione che l'interfaccia già mostra all'utente.
    """
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


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
