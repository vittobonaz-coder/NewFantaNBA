"""
Sostituisce giocatori di una fanta-squadra con free agent (giocatori NBA che non sono in nessuna fanta-squadra).

  python swap_players.py <squadra> "<esce>:<entra>" ["<esce>:<entra>" ...] [--from-gw N] [--dry-run]

  es. python swap_players.py Bonaz "Robert Williams III:Jaden Akins" "Payton Pritchard:1630173"

I giocatori si indicano per nome (come in data/all_players.json, accenti e maiuscole non contano) o per ID NBA.
Il nuovo giocatore prende il posto del vecchio con lo stesso ruolo e lo stesso slot.

Cosa viene modificato:
- Supabase: nba_players (inserisce il nuovo giocatore), rosters, lineup_players dalla giornata --from-gw in poi
- data/fanta_teams.json (anche i nomi delle squadre rinominate dall'app), data/<squadra>_info.json, data/<squadra>_state.json,
  data/<squadra>_gw<N>_state.json delle giornate da --from-gw in poi, data/nba_to_espn_players.json
- assets/players/<id>.png: foto del nuovo giocatore
I punteggi passati restano invariati: le giornate precedenti a --from-gw (righe di lineup_players, matchups,
file locali) continuano a riferirsi al vecchio giocatore, che resta anche in nba_players.

Opzioni:
  --from-gw N   prima giornata con il nuovo giocatore (default: la prima non ancora iniziata,
                la stessa a cui l'app applica i cambi formazione). Le giornate già chiuse sono rifiutate.
  --dry-run     controlla e stampa le modifiche senza scrivere nulla
"""
import argparse
import json
import os
import sys
import time

import requests
from nba_api.stats.endpoints import commonplayerinfo

from api_nba import NbaDataManager, normalize_name
from fanta_obj import Player, Team, NOT_PLAYED_SCORE
from supabase_manager import SupabaseSync
from time_manager import TimeManager

DATA_DIR = "data"
FANTA_TEAMS_PATH = os.path.join(DATA_DIR, "fanta_teams.json")
ALL_PLAYERS_PATH = os.path.join(DATA_DIR, "all_players.json")
AVATARS_DIR = os.path.join("assets", "players")


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data, ensure_ascii: bool = False) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=ensure_ascii)


def resolve_player(value: str, candidates: dict[int, str], source: str) -> int:
    """ID NBA a partire da un ID o da un nome tra i candidati {id: nome}."""
    value = value.strip()
    if value.isdigit():
        return int(value)
    matches = [p_id for p_id, name in candidates.items() if normalize_name(name) == normalize_name(value)]
    if not matches:
        raise ValueError(f"Giocatore '{value}' non trovato in {source}: usa l'ID NBA")
    if len(matches) > 1:
        ids = ", ".join(f"{candidates[p_id]} ({p_id})" for p_id in matches)
        raise ValueError(f"Nome '{value}' ambiguo: {ids}. Usa l'ID NBA")
    return matches[0]


def fetch_player_info(p_id: int) -> dict:
    """Anagrafica del giocatore dalla NBA API, nel formato dei file <squadra>_info.json."""
    data = commonplayerinfo.CommonPlayerInfo(player_id=p_id).get_dict()
    result = data["resultSets"][0]
    info = dict(zip(result["headers"], result["rowSet"][0]))
    return {
        "PLAYER_ID": p_id,
        "PLAYER_NAME": info.get("DISPLAY_FIRST_LAST"),
        "TEAM": info.get("TEAM_ABBREVIATION"),
        "POSITION": info.get("POSITION"),
    }


def default_from_gw(sync: SupabaseSync) -> int | None:
    """Prima giornata non ancora iniziata, come per i cambi formazione dell'app."""
    rounds = [{"round_number": r["gameweek"], "start_date": r["start_date"]} for r in sync.get_gameweek_ranges()]
    return TimeManager.get_league_context(rounds)["edit_gw"]


def download_avatar(p_id: int) -> None:
    target_path = os.path.join(AVATARS_DIR, f"{p_id}.png")
    if os.path.exists(target_path):
        print(f"Foto già presente: {target_path}")
        return
    os.makedirs(AVATARS_DIR, exist_ok=True)
    url = f"https://cdn.nba.com/headshots/nba/latest/260x190/{p_id}.png"
    response = requests.get(url, timeout=10)
    if response.status_code == 200:
        with open(target_path, "wb") as f:
            f.write(response.content)
        print(f"Foto scaricata: {target_path}")
    else:
        print(f"Attenzione: foto non disponibile per l'ID {p_id} (HTTP {response.status_code})")


def replace_in_state_file(path: str, swaps: list[dict]) -> None:
    """Sostituisce i giocatori nel roster di un file <squadra>[_gwN]_state.json, mantenendo posizione e ruolo."""
    state = load_json(path)
    by_old_id = {s["old_id"]: s for s in swaps}
    for i, p in enumerate(state.get("roster", [])):
        s = by_old_id.get(p.get("id"))
        if s:
            new = s["new_player"]
            state["roster"][i] = {
                "id": new.id,
                "name": new.name,
                "team": new.team_abbreviation,
                "pos": new.position,
                "score": NOT_PLAYED_SCORE,
                "role": p.get("role", "RESERVE"),
            }
    save_json(path, state)
    print(f"Aggiornato {path}")


def update_local_files(team_name: str, from_gw: int, swaps: list[dict]) -> None:
    # 1. fanta_teams.json: stessa posizione e stesso ruolo del giocatore sostituito
    fanta_teams = load_json(FANTA_TEAMS_PATH)
    renames = {s["old_name"]: s["new_player"].name for s in swaps}
    old_roster = fanta_teams.get(team_name, {})
    missing = [name for name in renames if name not in old_roster]
    if missing:
        print(f"Attenzione: {missing} non presenti in {FANTA_TEAMS_PATH} per '{team_name}'")
    fanta_teams[team_name] = {renames.get(name, name): role for name, role in old_roster.items()}
    save_json(FANTA_TEAMS_PATH, fanta_teams, ensure_ascii=True)
    print(f"Aggiornato {FANTA_TEAMS_PATH}")

    # 2. <squadra>_info.json
    info_path = os.path.join(DATA_DIR, f"{team_name.replace(' ', '_').lower()}_info.json")
    if os.path.exists(info_path):
        by_old_id = {s["old_id"]: s["new_info"] for s in swaps}
        save_json(info_path, [by_old_id.get(int(p["PLAYER_ID"]), p) for p in load_json(info_path)])
        print(f"Aggiornato {info_path}")

    # 3. File di stato: quello generale e quelli delle giornate da from_gw in poi (le precedenti restano com'erano)
    state_paths = [Team(team_name).filename]
    prefix = f"{team_name.replace(' ', '_').lower()}_gw"
    for filename in os.listdir(DATA_DIR):
        if filename.startswith(prefix) and filename.endswith("_state.json"):
            gw = filename[len(prefix):-len("_state.json")]
            if gw.isdigit() and int(gw) >= from_gw:
                state_paths.append(os.path.join(DATA_DIR, filename))
    for path in state_paths:
        if os.path.exists(path):
            replace_in_state_file(path, swaps)


def main():
    # La console di Windows (cp1252) non stampa nomi come Jokić
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Sostituisce giocatori di una fanta-squadra con free agent")
    parser.add_argument("team", help="nome della fanta-squadra, es. Bonaz")
    parser.add_argument("swaps", nargs="+", help='coppie "esce:entra" (nomi o ID NBA)')
    parser.add_argument("--from-gw", type=int, help="prima giornata con il nuovo giocatore")
    parser.add_argument("--dry-run", action="store_true", help="non scrive nulla")
    args = parser.parse_args()

    sync = SupabaseSync()
    db = sync.supabase
    all_players = {int(p["PLAYER_ID"]): p["PLAYER_NAME"] for p in load_json(ALL_PLAYERS_PATH)}

    # 1. Squadra e giornata di partenza
    team_id = sync.get_team_id_by_name(args.team)
    if not team_id:
        sys.exit(f"Squadra '{args.team}' non trovata su Supabase.")
    # I nomi cambiati dall'app esistono solo su Supabase: riallineiamo prima i file locali
    sync.align_fanta_teams_json(dry_run=args.dry_run)

    from_gw = args.from_gw or default_from_gw(sync)
    if from_gw is None:
        sys.exit("Nessuna giornata ancora da giocare: indica --from-gw.")
    gw_info = sync.get_gameweek_info(from_gw)
    if gw_info is None:
        sys.exit(f"GW {from_gw} inesistente.")
    if gw_info["was_played"]:
        sys.exit(f"GW {from_gw} già chiusa: i punteggi passati non si toccano.")
    if gw_info["start_date"] <= TimeManager.get_today_str():
        print(f"Attenzione: la GW {from_gw} è già iniziata ({gw_info['start_date']}): "
              f"i punteggi del vecchio giocatore in questa giornata andranno persi.")

    # 2. Controlli sui giocatori: chi esce deve essere nella squadra, chi entra in nessuna squadra
    team_roster = db.table("rosters").select("nba_player_id, player_name") \
        .eq("fanta_team_id", team_id).execute().data or []
    team_ids = {int(r["nba_player_id"]): r["player_name"] for r in team_roster}
    taken_ids = {int(r["nba_player_id"]) for r in db.table("rosters").select("nba_player_id").execute().data or []}

    swaps = []
    for pair in args.swaps:
        if pair.count(":") != 1:
            sys.exit(f"Formato non valido '{pair}': usa \"esce:entra\".")
        try:
            old_id = resolve_player(pair.split(":")[0], team_ids, f"rosa di {args.team}")
            new_id = resolve_player(pair.split(":")[1], all_players, ALL_PLAYERS_PATH)
        except ValueError as e:
            sys.exit(str(e))
        if old_id not in team_ids:
            sys.exit(f"Il giocatore {old_id} non è nella rosa di {args.team}.")
        if new_id in taken_ids:
            sys.exit(f"Il giocatore {new_id} è già in una fanta-squadra: non è un free agent.")
        if any(s["new_id"] == new_id or s["old_id"] == old_id for s in swaps):
            sys.exit(f"Giocatore ripetuto in '{pair}'.")

        new_info = fetch_player_info(new_id)
        time.sleep(0.6)  # pausa precauzionale per la NBA API
        new_player = Player(id=new_id, name=new_info["PLAYER_NAME"],
                            team_abbreviation=new_info["TEAM"], position=new_info["POSITION"])
        swaps.append({"old_id": old_id, "old_name": team_ids[old_id], "new_id": new_id,
                      "new_info": new_info, "new_player": new_player})

    print(f"=== {args.team}: sostituzioni dalla GW {from_gw} in poi | dry-run: {args.dry_run} ===")
    for s in swaps:
        p = s["new_player"]
        print(f"- esce {s['old_name']} ({s['old_id']}) -> entra {p.name} ({p.id}, {p.team_abbreviation}, {p.position})")
    if args.dry_run:
        return

    # 3. Supabase. Le righe di lineup_players delle giornate precedenti restano al vecchio giocatore
    #    (che resta quindi in nba_players): punteggi e classifiche passate non cambiano.
    db.table("nba_players").upsert([{
        "id": s["new_player"].id,
        "full_name": s["new_player"].name,
        "nba_team": s["new_player"].team_abbreviation,
        "position": s["new_player"].position,
    } for s in swaps]).execute()

    for s in swaps:
        new = s["new_player"]
        db.table("rosters") \
            .update({"nba_player_id": new.id, "player_name": new.name}) \
            .eq("fanta_team_id", team_id) \
            .eq("nba_player_id", s["old_id"]) \
            .execute()
        # Slot e ruolo restano quelli del giocatore sostituito
        rows = db.table("lineup_players") \
            .update({"nba_player_id": new.id, "player_name": new.name, "score": NOT_PLAYED_SCORE}) \
            .eq("fanta_team_id", team_id) \
            .gte("gameweek", from_gw) \
            .eq("nba_player_id", s["old_id"]) \
            .execute().data or []
        print(f"Supabase: {s['old_name']} -> {new.name} (rosters + {len(rows)} righe di lineup_players)")

    # 4. File locali, mappa NBA -> ESPN (usata dal cron per i tabellini) e foto
    update_local_files(args.team, from_gw, swaps)
    not_mapped = NbaDataManager(player_ids=[]).map_missing_players({s["new_id"]: s["new_player"].name for s in swaps})
    if not_mapped:
        print(f"Attenzione: {not_mapped} non trovati nei roster ESPN, il cron non potrà calcolarne i punteggi.")
    for s in swaps:
        download_avatar(s["new_id"])

    print("\nSostituzioni completate. L'app online riscarica le formazioni dopo il prossimo run del cron.")


if __name__ == "__main__":
    main()
