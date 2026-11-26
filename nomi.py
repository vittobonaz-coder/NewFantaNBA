"""Nomi dei giocatori confrontabili tra fonti diverse (NBA, ESPN, Excel incollato dagli utenti).

Modulo senza dipendenze esterne: lo usano sia gli script (tramite api_nba) sia l'app, che normalizza il nome
scritto nel mercato prima di mandarlo al database (confrontato con nba_players.search_name).
"""
import re
import unicodedata


def normalize_name(name: str) -> str:
    """Nome confrontabile (es. 'Luka Dončić Jr.' -> 'luka doncic')."""
    # Rimuove accenti e diacritici (es. Dončić -> Doncic)
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
    name = name.lower()
    # Rimuove apostrofi, punti e trattini
    name = name.replace(".", "").replace("'", "").replace("-", " ")
    # Rimuove suffissi comuni
    name = re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', name)
    # Rimuove doppi spazi causati dalle pulizie precedenti
    name = " ".join(name.split())
    return name
