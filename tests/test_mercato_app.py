"""Mercato lato app (mercato.py): lettura dello stato, tempo alla chiusura, chiamate alle RPC con un finto database."""
from datetime import datetime, timedelta, timezone

import pytest

from mercato import MarketService, MarketState, time_left_text

STATE_JSON = {
    "now": "2026-11-28T10:00:00.81321+00:00",  # PostgreSQL toglie gli zeri finali dei microsecondi
    "closing": False,
    "window": {"gameweek": 6, "closes_at": "2026-12-01T18:00:00+00:00", "first_gameweek": 7},
    "max_offers": 9,
    "offers": [
        {"id": 4, "out_id": 1, "out_name": "Jalen Brunson", "in_id": 2, "in_name": "Aaron Wiggins",
         "in_team": "OKC", "in_position": "Guard", "created_at": "2026-11-28T09:00:00+00:00"},
    ],
    "last": {
        "gameweek": 4, "closed_at": "2026-11-17T18:00:00+00:00",
        "my_offers": [{"out_name": "A", "in_name": "B", "status": "non_eseguita", "note": "Preso da X"}],
        "trades": [{"team": "X", "out_name": "C", "in_name": "B"}],
    },
}


def test_stato_letto_dal_json():
    state = MarketState.from_json(STATE_JSON)
    assert state.window.gameweek == 6 and state.window.first_gameweek == 7
    assert state.window.closes_at == datetime(2026, 12, 1, 18, tzinfo=timezone.utc)
    assert state.offers[0].in_name == "Aaron Wiggins" and state.offers[0].in_team == "OKC"
    assert not state.last.my_offers[0].executed and state.last.trades[0].team == "X"
    assert state.can_offer


def test_stato_senza_finestra_ne_storico():
    state = MarketState.from_json({"now": None, "closing": True, "window": None, "max_offers": 9,
                                   "offers": [], "last": None})
    assert state.window is None and state.last is None and state.closing
    assert not state.can_offer


def test_limite_offerte():
    data = dict(STATE_JSON, max_offers=1)
    assert not MarketState.from_json(data).can_offer


@pytest.mark.parametrize("delta, atteso", [
    (timedelta(days=3, hours=4, minutes=30), "3 g 4 h"),
    (timedelta(hours=5, minutes=12), "5 h 12 min"),
    (timedelta(minutes=8, seconds=30), "8 min"),
    (timedelta(seconds=20), "meno di un minuto"),
    (timedelta(seconds=-1), "scaduto"),
])
def test_tempo_alla_chiusura(delta, atteso):
    now = datetime(2026, 11, 28, 10, tzinfo=timezone.utc)
    assert time_left_text(now + delta, now) == atteso


class FintoDatabase:
    """Registra le chiamate e restituisce una risposta fissa (Test Double: un finto al posto della rete)."""
    def __init__(self, response=None):
        self.calls: list[tuple[str, dict]] = []
        self.response = response

    def __call__(self, name, args):
        self.calls.append((name, args))
        return self.response


def test_offerta_normalizza_il_nome():
    db = FintoDatabase()
    MarketService("tok", db).offer(10, "  Luka Dončić Jr. ")
    assert db.calls == [("market_offer", {"p_token": "tok", "p_out_player": 10, "p_in_name": "luka doncic"})]


def test_offerta_senza_nome_non_chiama_il_database():
    db = FintoDatabase()
    with pytest.raises(ValueError):
        MarketService("tok", db).offer(10, "   ")
    assert db.calls == []


def test_stato_e_annullamento():
    db = FintoDatabase(STATE_JSON)
    service = MarketService("tok", db)
    assert service.state().window.gameweek == 6
    service.cancel(4)
    assert db.calls[-1] == ("market_cancel", {"p_token": "tok", "p_offer_id": 4})
