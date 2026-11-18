"""
Cache locale dei dati di lega (cartella di app_paths: data/ su Render e negli script, cartella dati
dell'utente nell'app installata), senza supabase-py: la usano l'app e, per le stesse
trasformazioni, supabase_manager.py negli script.

I dati arrivano dalle RPC login_bundle, token_bundle e get_snapshot (sql/2026-11_fase2a_snapshot_bundle.sql):
lo snapshot è diviso in parti (calendar, standings, injuries, lineups), ognuna con una versione. Il client
manda le versioni che ha e riceve solo le parti cambiate; qui si trasformano nei file letti dall'interfaccia.
"""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import app_paths
from fanta_obj import Team, NOT_PLAYED_SCORE, ROLE_MULTIPLIERS, DEFAULT_LINEUP, LINEUP_ROLES, has_played
from time_manager import TimeManager, ITA_TZ

PARTS = ("calendar", "standings", "injuries", "lineups")
LAST_SYNC_KEY = "_last_sync"  # In snapshot_meta.json: ora (UTC, ISO) dell'ultimo aggiornamento riuscito


# Percorsi come funzioni: la cartella si decide all'avvio (app_paths.set_data_dir nell'app installata)
def calendar_path() -> Path:
    return app_paths.data_file("calendar.json")


def standings_path() -> Path:
    return app_paths.data_file("standings.json")


def injuries_path() -> Path:
    return app_paths.data_file("injuries.json")


def league_teams_path() -> Path:
    """Parte lineups: giornata e squadre (non versionato)."""
    return app_paths.data_file("league_teams.json")


def snapshot_meta_path() -> Path:
    """Versioni delle parti in cache e ora dell'ultimo aggiornamento (non versionato)."""
    return app_paths.data_file("snapshot_meta.json")


def valid_lineup(value) -> str | None:
    """Il modulo se è uno di quelli previsti, altrimenti None (es. la stringa "NULL" dei vecchi calendari)."""
    return value if value in LINEUP_ROLES else None


def write_json(path: str | Path, data: Any, indent: int | None = None) -> None:
    """
    Scrittura atomica (file temporaneo + rename): chi legge non vede mai un file a metà (su Render data/ è condivisa).
    Senza indent il JSON è compatto (calendario 382 -> ~166 KB, scrittura più rapida); indent per i file piccoli
    che conviene poter leggere a occhio.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent,
                      separators=None if indent is not None else (",", ":"))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def read_json(path: str | Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


# --- Trasformazioni (righe nella forma di PostgREST -> file dell'app) ---

def build_calendar(matchups: list[dict], nba_games: list[dict]) -> list[dict]:
    """
    Calendario per giornata: {"round_number", "start_date", "end_date", "matchups": [...],
    "nba_games": {data italiana: [partite in ordine di inizio]}}.
    matchups: righe con home_team/away_team = {"name"}; nba_games: righe di nba_games in ordine di inizio.
    """
    rounds: dict[int, dict] = {}
    for row in sorted(matchups, key=lambda r: r["gameweek"]):
        gw = row["gameweek"]
        if gw not in rounds:
            rounds[gw] = {"round_number": gw, "start_date": str(row["start_date"]), "end_date": str(row["end_date"]),
                          "matchups": [], "nba_games": {}}
        rounds[gw]["matchups"].append({
            "home_team": row["home_team"]["name"] if row.get("home_team") else "Unknown",
            "away_team": row["away_team"]["name"] if row.get("away_team") else "Unknown",
            "home_score": float(row["home_score"] or 0.0),
            "away_score": float(row["away_score"] or 0.0),
            "was_played": bool(row["was_played"]),
            "home_lineup": valid_lineup(row["home_lineup"]) or DEFAULT_LINEUP,
            "away_lineup": valid_lineup(row["away_lineup"]) or DEFAULT_LINEUP,
        })

    for g in nba_games:
        round_data = rounds.get(g["gameweek"])
        if round_data is None:
            continue
        if g.get("start_time"):
            start = datetime.fromisoformat(g["start_time"]).astimezone(ITA_TZ)
            ita_date, ita_time = start.date().isoformat(), f"{start:%H:%M}"
        else:
            ita_date, ita_time = TimeManager.nba_date_to_italian_date(str(g["nba_date"])), ""
        round_data["nba_games"].setdefault(ita_date, []).append({
            "home_team": g["home_team"],
            "away_team": g["away_team"],
            "home_score": g["home_score"],
            "away_score": g["away_score"],
            "status": g["status"],
            "time": ita_time,
        })
    return list(rounds.values())


def injuries_by_player(rows: list[dict]) -> dict[str, dict]:
    """Righe di player_injuries -> {nba_player_id (str): riga}."""
    return {str(r["nba_player_id"]): r for r in rows}


def write_lineup_state(team_name: str, gameweek: int, rows: list[dict], lineup: str | None = None,
                       data_as_of: str = "", data_dir: str | Path | None = None) -> None:
    """
    Scrive il file <nome_team>_gw<N>_state.json dalle righe di lineup_players (ordinate per slot, con
    nba_players(nba_team, position)) e dal modulo salvato in matchups (se manca resta quello del file locale).
    """
    roster, target_date = [], ""
    for row in rows:
        if row.get("target_date"):
            target_date = row["target_date"]
        nba_info = row.get("nba_players") or {}
        roster.append({
            "id": row.get("nba_player_id"),
            "name": row.get("player_name"),
            "team": nba_info.get("nba_team", ""),
            "pos": nba_info.get("position", ""),
            "score": float(row["score"]) if row.get("score") is not None else NOT_PLAYED_SCORE,
            "role": row.get("role") or "RESERVE",
            "entered_game": bool(row.get("entered_game")),
            "auto_sub": row.get("auto_sub"),
        })

    # Totale ricalcolato dai punteggi scaricati (come fa il cron)
    total_score = sum(p["score"] * ROLE_MULTIPLIERS.get(p["role"], 0.0) for p in roster if has_played(p["score"]))
    json_path = Path(data_dir or app_paths.data_dir()) / Path(Team(team_name, gameweek=gameweek).filename).name
    state = {
        "team_name": team_name,
        "target_date": target_date,
        "gameweek": gameweek,
        "data_as_of": data_as_of,
        "total_score": round(total_score, 2),
        "lineup": valid_lineup(lineup) or DEFAULT_LINEUP,
        "roster": roster,
    }
    # Senza modulo su Supabase preserva quello salvato in locale (l'app lo verifica comunque sui titolari)
    if valid_lineup(lineup) is None and json_path.exists():
        state["lineup"] = (read_json(json_path, {}) or {}).get("lineup", DEFAULT_LINEUP)
    write_json(json_path, state, indent=4)


# --- Snapshot ---

def _parts_files_exist(part: str) -> bool:
    """True se i file locali della parte ci sono ancora (altrimenti la versione salvata non vale)."""
    if part == "calendar":
        return calendar_path().exists()
    if part == "standings":
        return standings_path().exists()
    if part == "injuries":
        return injuries_path().exists()
    league = read_json(league_teams_path())
    if not isinstance(league, dict):
        return False
    gw = league.get("gameweek")
    return gw is None or all(os.path.exists(Team(t["name"], gameweek=gw).filename) for t in league.get("teams", []))


def local_versions() -> dict[str, str]:
    """Versioni delle parti presenti in cache, da mandare alle RPC: le parti mancanti tornano complete."""
    meta = read_json(snapshot_meta_path(), {})
    if not isinstance(meta, dict):
        return {}
    return {p: v for p, v in meta.items() if p in PARTS and isinstance(v, str) and _parts_files_exist(p)}


def apply_snapshot(snapshot: dict) -> None:
    """
    Scrive le parti ricevute ({"parts": {...}, "versions": {...}}) nei file locali.
    La versione di una parte si salva solo dopo averne scritto i file: se qualcosa va storto
    la parte torna completa alla richiesta successiva.
    """
    parts: dict = snapshot.get("parts") or {}
    versions: dict = snapshot.get("versions") or {}
    meta = read_json(snapshot_meta_path(), {})
    meta = {p: v for p, v in meta.items() if p in PARTS} if isinstance(meta, dict) else {}

    for part, data in parts.items():
        if part == "calendar":
            write_json(calendar_path(), build_calendar(data.get("matchups") or [], data.get("nba_games") or []))
        elif part == "standings":
            write_json(standings_path(), data or [])
        elif part == "injuries":
            write_json(injuries_path(), injuries_by_player(data or []))
        elif part == "lineups":
            gw, lineups = data.get("gameweek"), data.get("lineups") or {}
            rows = data.get("rows") or []
            teams = data.get("teams") or []
            if gw is not None:
                for t in teams:
                    team_rows = [r for r in rows if r.get("fanta_team_id") == t["id"]]
                    if team_rows:
                        write_lineup_state(t["name"], gw, team_rows, lineups.get(t["id"]), versions.get("lineups", ""))
            write_json(league_teams_path(), {"gameweek": gw, "teams": teams})
        else:
            continue
        if part in versions:
            meta[part] = versions[part]
    meta[LAST_SYNC_KEY] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json(snapshot_meta_path(), meta, indent=4)


def last_sync() -> datetime | None:
    """Ora (UTC) dell'ultimo aggiornamento riuscito dal database, None se la cache è vuota."""
    meta = read_json(snapshot_meta_path(), {})
    value = meta.get(LAST_SYNC_KEY) if isinstance(meta, dict) else None
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def apply_my_team(my_team: dict | None, team_name: str) -> None:
    """Formazione modificabile della propria squadra (sempre aggiornata nel bundle) nel suo file locale."""
    if my_team and my_team.get("gameweek") is not None and my_team.get("rows"):
        write_lineup_state(team_name, my_team["gameweek"], my_team["rows"], my_team.get("lineup"))


def parse_context(context: dict) -> dict:
    """Contesto della lega dal database: giornate, scadenza (datetime UTC o None) e ora del server."""
    deadline, now = context.get("deadline"), context.get("now")
    return {
        "current_gw": context.get("current_gw"),
        "edit_gw": context.get("edit_gw"),
        "deadline": datetime.fromisoformat(deadline) if deadline else None,
        "now": datetime.fromisoformat(now) if now else None,
    }


def offline_context(saved: dict) -> dict:
    """
    Contesto senza rete: quello salvato all'ultimo accesso (stessa forma della RPC); se la sua scadenza è
    passata, ricalcolato con TimeManager.get_league_context sul calendario in cache (regola del database,
    senza deroga).
    """
    league = parse_context(saved or {})
    deadline = league["deadline"]
    if league["edit_gw"] is not None and (deadline is None or TimeManager.now() < deadline):
        return league
    rounds = read_json(calendar_path(), []) or []
    local = TimeManager.get_league_context(rounds)
    return {**local, "now": None}


def load_team(team_name: str, gameweek: int | None) -> Team | None:
    """Squadra della giornata dal file locale, None se manca o non è valida."""
    if gameweek is None:
        return None
    team = Team(team_name, gameweek=gameweek)
    return team if team.load_from_json() and team.is_valid_roster() else None


def load_other_teams(exclude_id: str, gameweek: int | None) -> list[Team]:
    """Formazioni delle altre squadre nella giornata in corso, dalla parte lineups dello snapshot (nessuna richiesta)."""
    league = read_json(league_teams_path(), {}) or {}
    if gameweek is None or league.get("gameweek") != gameweek:
        return []
    teams = [load_team(t["name"], gameweek) for t in league.get("teams", []) if t["id"] != exclude_id]
    return [t for t in teams if t is not None]
