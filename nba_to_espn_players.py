import json
import os
import unicodedata
import requests
from nba_api.stats.static import players


def normalize_name(name: str) -> str:
    """Normalizza il nome rimuovendo accenti/caratteri speciali, punti e trasformando in minuscolo.

    Esempio: "Bogdan Bogdanović" -> "bogdan bogdanovic"
             "P.J. Washington" -> "pj washington"
             "Luka Dončić" -> "luka doncic"
    """
    # 1. Decompone i caratteri accentati (es. 'ć' diventa 'c' + accento separato)
    normalized = unicodedata.normalize("NFKD", name)

    # 2. Rimuove i diacritici e mantiene solo i caratteri non appartenenti alla categoria 'Mn'
    ascii_name = "".join(
        c for c in normalized if unicodedata.category(c) != "Mn"
    )

    # 3. Trasforma in minuscolo e rimuove i punti
    return ascii_name.lower().replace(".", "").strip()


def build_player_id_map():
    # 1. Recupera giocatori NBA ufficiali
    nba_players = (
        players.get_active_players()
    )  # lista di dict con 'id', 'full_name'

    # 2. Recupera giocatori ESPN
    url_teams = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams?limit=30"
    resp = requests.get(url_teams).json()
    teams = resp["sports"][0]["leagues"][0]["teams"]

    espn_players = []
    for t in teams:
        t_id = t["team"]["id"]
        roster_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{t_id}/roster"
        r_data = requests.get(roster_url).json()
        for ath in r_data.get("athletes", []):
            espn_players.append(
                {"espn_id": str(ath["id"]), "name": ath["fullName"]}
            )

    # 3. Mappatura per Nome Normalizzato
    nba_to_espn = {}
    espn_to_nba = {}

    # Utilizziamo normalize_name invece del semplice .lower().replace('.', '')
    espn_dict = {normalize_name(p["name"]): p["espn_id"] for p in espn_players}

    for nba_p in nba_players:
        clean_name = normalize_name(nba_p["full_name"])
        nba_id = str(nba_p["id"])

        if clean_name in espn_dict:
            espn_id = espn_dict[clean_name]
            nba_to_espn[nba_id] = espn_id
            espn_to_nba[espn_id] = nba_id
        else:
            print(
                f"Attenzione: Nessuna corrispondenza ESPN trovata per"
                f" {nba_p['full_name']} (NBA ID: {nba_id})"
            )

    os.makedirs("data", exist_ok=True)
    with open("data/nba_to_espn_players.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "nba_to_espn": nba_to_espn,
                "espn_to_nba": espn_to_nba,
            },
            f,
            indent=4,
        )

    print(
        f"Mappa creata con successo! Mappati {len(nba_to_espn)} giocatori su"
        f" {len(nba_players)}."
    )


build_player_id_map()