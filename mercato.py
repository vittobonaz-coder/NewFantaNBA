"""
Mercato (sql/2026-11_mercato.sql), lato app: i dati restituiti dalle RPC come oggetti e il servizio che le chiama.
Nessuna interfaccia qui (la vista è in ui_mercato.py), così la logica si prova con pytest senza Flet né rete.

Regole (le applica il database, qui solo per l'utente): uno scambio per finestra, un giocatore del proprio
roster per un free agent; le offerte sono in ordine di preferenza; alla chiusura sceglie prima chi è più in
basso in classifica; le offerte restano segrete fino alla chiusura.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from nomi import normalize_name

# Funzione che chiama una RPC: (nome, argomenti) -> JSON. Nell'app è supabase_rest.rpc, nei test un finto.
RpcCall = Callable[[str, dict[str, Any]], Any]


def _parse_time(value: str | None) -> datetime | None:
    """Istante ISO di PostgREST ('2026-12-01T18:00:00+00:00') con fuso orario; None se assente."""
    return datetime.fromisoformat(value) if value else None


@dataclass(frozen=True)
class MarketWindow:
    """Finestra aperta: si chiude a closes_at, i nuovi giocatori contano dalla giornata first_gameweek."""
    gameweek: int
    closes_at: datetime
    first_gameweek: int


@dataclass(frozen=True)
class MarketOffer:
    """Offerta attiva: cedo out_name, prendo in_name. L'ordine nella lista è la mia preferenza."""
    id: int
    out_id: int
    out_name: str
    in_id: int
    in_name: str
    in_team: str = ""
    in_position: str = ""


@dataclass(frozen=True)
class OfferOutcome:
    """Esito di una mia offerta nell'ultima finestra eseguita (status: eseguita / non_eseguita)."""
    out_name: str
    in_name: str
    status: str
    note: str | None = None

    @property
    def executed(self) -> bool:
        return self.status == "eseguita"


@dataclass(frozen=True)
class Trade:
    """Scambio eseguito da una squadra (pubblico dopo la chiusura)."""
    team: str
    out_name: str
    in_name: str


@dataclass(frozen=True)
class LastWindow:
    """Ultima finestra eseguita: i miei esiti e gli scambi di tutti."""
    gameweek: int
    closed_at: datetime | None
    my_offers: tuple[OfferOutcome, ...]
    trades: tuple[Trade, ...]


@dataclass(frozen=True)
class MarketState:
    """Stato del mercato per la mia squadra (RPC market_state)."""
    now: datetime | None
    closing: bool                  # Una finestra è scaduta e la chiusura non è ancora stata eseguita
    window: MarketWindow | None    # Finestra in cui si fanno offerte adesso (None se chiusa o finita)
    max_offers: int
    offers: tuple[MarketOffer, ...]
    last: LastWindow | None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> MarketState:
        window = data.get("window")
        last = data.get("last")
        return cls(
            now=_parse_time(data.get("now")),
            closing=bool(data.get("closing")),
            window=MarketWindow(window["gameweek"], _parse_time(window["closes_at"]), window["first_gameweek"])
                   if window else None,
            max_offers=int(data.get("max_offers") or 0),
            offers=tuple(MarketOffer(o["id"], o["out_id"], o["out_name"], o["in_id"], o["in_name"],
                                     o.get("in_team") or "", o.get("in_position") or "")
                         for o in data.get("offers") or []),
            last=LastWindow(
                last["gameweek"], _parse_time(last.get("closed_at")),
                tuple(OfferOutcome(o["out_name"], o["in_name"], o["status"], o.get("note"))
                      for o in last.get("my_offers") or []),
                tuple(Trade(t["team"], t["out_name"], t["in_name"]) for t in last.get("trades") or []),
            ) if last else None,
        )

    @property
    def can_offer(self) -> bool:
        """Si possono aggiungere offerte: finestra aperta e limite non raggiunto."""
        return self.window is not None and len(self.offers) < self.max_offers


def time_left_text(closes_at: datetime, now: datetime) -> str:
    """Tempo alla chiusura in parole brevi: '3 g 4 h', '5 h 12 min', '8 min', 'meno di un minuto'."""
    left = closes_at - now
    if left <= timedelta(0):
        return "scaduto"
    minutes = int(left.total_seconds() // 60)
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days} g {hours} h"
    if hours:
        return f"{hours} h {mins} min"
    return f"{mins} min" if mins else "meno di un minuto"


class MarketService:
    """
    Le tre RPC del mercato per la sessione di un utente. Gli errori previsti arrivano come RpcError
    (un ValueError con il messaggio in italiano già pronto da mostrare): qui non si traducono.
    """

    def __init__(self, token: str, rpc: RpcCall):
        self._token = token
        self._rpc = rpc  # Iniettata: l'app passa supabase_rest.rpc, i test un finto database

    def state(self) -> MarketState:
        return MarketState.from_json(self._rpc("market_state", {"p_token": self._token}) or {})

    def offer(self, out_player_id: int, in_name: str) -> None:
        """Nuova offerta in fondo alla lista. Il nome si normalizza come search_name in nba_players."""
        name = normalize_name(in_name or "")
        if not name:
            raise ValueError("Scrivi il nome del giocatore da prendere")
        self._rpc("market_offer", {"p_token": self._token, "p_out_player": out_player_id, "p_in_name": name})

    def cancel(self, offer_id: int) -> None:
        self._rpc("market_cancel", {"p_token": self._token, "p_offer_id": offer_id})
