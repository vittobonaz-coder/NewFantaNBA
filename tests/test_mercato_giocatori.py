"""Test di carica_giocatori.build_rows e di nomi.normalize_name (nessun accesso al database)."""
from carica_giocatori import NbaPlayerRow, build_rows, duplicate_names
from nomi import normalize_name


def test_normalize_name_toglie_accenti_e_suffissi():
    assert normalize_name("Luka Dončić Jr.") == "luka doncic"
    assert normalize_name("  Shai Gilgeous-Alexander ") == "shai gilgeous alexander"


def test_build_rows_tiene_squadra_e_posizione_del_database():
    info = [{"PLAYER_ID": 1, "PLAYER_NAME": "Mario Rossi", "TEAM": "BOS", "POSITION": "Guard"},
            {"PLAYER_ID": 2, "PLAYER_NAME": "Nuovo Libero", "TEAM": "LAL", "POSITION": "Center"}]
    existing = [{"id": 1, "full_name": "Mario Rossi", "nba_team": "NYK", "position": "Guard-Forward"},
                {"id": 3, "full_name": "Ceduto Storico", "nba_team": "MIA", "position": "Forward"}]
    rows = build_rows(info, existing, {"1": "e1", "2": "e2"})

    assert rows == [
        NbaPlayerRow(1, "Mario Rossi", "NYK", "Guard-Forward", "e1", "mario rossi"),   # dal database
        NbaPlayerRow(2, "Nuovo Libero", "LAL", "Center", "e2", "nuovo libero"),        # dal file
        NbaPlayerRow(3, "Ceduto Storico", "MIA", "Forward", None, "ceduto storico"),   # resta, senza ESPN
    ]


def test_duplicate_names():
    rows = [NbaPlayerRow(1, "A B", "", "", None, "a b"), NbaPlayerRow(2, "A. B", "", "", None, "a b"),
            NbaPlayerRow(3, "C", "", "", None, "c")]
    assert duplicate_names(rows) == {"a b": [1, 2]}
