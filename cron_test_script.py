"""
Cron job dei punteggi (GitHub Actions, lanciato da Supabase pg_cron).

  python cron_test_script.py daily      ogni mattina: scarica i tabellini e aggiorna i punteggi
  python cron_test_script.py rollover   ogni sera alle 23:59 italiane: se domani inizia una nuova
                                        giornata, chiude quella di oggi e azzera la successiva
                                        (lanciato alle 21:59 e alle 22:59 UTC, prosegue solo dalle 23:59)

Opzioni per test e recuperi:
  --date YYYY-MM-DD   (daily) data NBA da elaborare al posto di ieri
  --days N            (daily) quante date NBA elaborare all'indietro (default: 2, oppure 1 con --date)
  --today YYYY-MM-DD  data italiana da considerare come oggi (salta il controllo dell'orario del rollover)
  --force             (rollover) esegue subito, senza controllare l'orario
  --dry-run           calcola e stampa senza scrivere su Supabase
"""
import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone

from api_nba import NbaDataManager, NBA_TO_ESPN_TEAM, ESPN_TO_NBA_TEAM
from fanta_obj import Player, Team, ROLE_MULTIPLIERS
from supabase_manager import SupabaseSync
from time_manager import TimeManager, ITA_TZ

ROLE_CONFIGS = {role: {"mult": mult} for role, mult in ROLE_MULTIPLIERS.items()}
FETCH_ATTEMPTS = 3


def shift_date(date_str: str, days: int) -> str:
    return (datetime.strptime(date_str, "%Y-%m-%d").date() + timedelta(days=days)).isoformat()


def fetch_boxscores(manager: NbaDataManager, nba_date: str) -> list[dict]:
    """Tabellini definitivi (solo partite concluse, DNP inclusi) di tutta la NBA.
    Solleva un'eccezione se ESPN non risponde: meglio fallire che scrivere punteggi sbagliati."""
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            return manager.fetch_boxscores(nba_date, only_completed=True, include_dnp=True, strict=True)
        except Exception as e:
            print(f"Tentativo {attempt}/{FETCH_ATTEMPTS} fallito per {nba_date}: {e}")
            if attempt == FETCH_ATTEMPTS:
                raise
            time.sleep(30)


def compute_player_scores(rows: list[dict], boxscores: list[dict], nba_date: str,
                          nba_to_espn_map: dict) -> tuple[dict[int, float | None], list[str]]:
    """
    Fanta-punteggio di ogni giocatore schierato, per la data NBA indicata:
    - a referto in una partita conclusa -> punteggio calcolato (0.0 se DNP)
    - non a referto, ma la sua squadra NBA ha giocato -> 0.0
    - la sua squadra NBA non ha giocato (o la partita non è conclusa) -> None
    """
    listed_ids = {b["PLAYER_ID"] for b in boxscores}
    teams_played = {b["TEAM"] for b in boxscores}
    errors = []

    player_ids = [int(r["nba_player_id"]) for r in rows]
    scores = Player.calculate_scores([p for p in player_ids if p in listed_ids], boxscores, target_date=nba_date)

    for row in rows:
        p_id = int(row["nba_player_id"])
        if p_id in scores:
            continue
        if str(p_id) not in nba_to_espn_map:
            # Senza ID ESPN il giocatore non compare mai nei tabellini: dargli 0.0 sarebbe sbagliato
            errors.append(f"{row['player_name']} ({p_id}) non è nella mappa NBA->ESPN: punteggio non calcolato")
            scores[p_id] = None
            continue
        nba_team = (row.get("nba_players") or {}).get("nba_team", "")
        scores[p_id] = 0.0 if NBA_TO_ESPN_TEAM.get(nba_team, nba_team) in teams_played else None

    return scores, errors


def sync_nba_teams(sync: SupabaseSync, rows: list[dict], boxscores: list[dict], dry_run: bool) -> None:
    """Allinea nba_players.nba_team alla squadra con cui il giocatore è a referto (scambi, firme di svincolati)."""
    team_by_player = {b["PLAYER_ID"]: ESPN_TO_NBA_TEAM.get(b["TEAM"], b["TEAM"]) for b in boxscores}
    for row in rows:
        p_id = int(row["nba_player_id"])
        new_team = team_by_player.get(p_id)
        old_team = (row.get("nba_players") or {}).get("nba_team", "")
        if new_team and new_team != old_team:
            print(f"  {row['player_name']}: squadra {old_team} -> {new_team}")
            if not dry_run:
                sync.update_nba_player_team(p_id, new_team)


def update_team_scores(sync: SupabaseSync, gameweek: int, rows: list[dict], dry_run: bool) -> None:
    """Ricalcola il punteggio di ogni fanta-squadra della giornata dai punteggi dei suoi 15 giocatori."""
    teams: dict[str, Team] = {}
    for row in rows:
        team = teams.setdefault(row["fanta_team_id"], Team(name=row["fanta_team_id"]))
        score = float(row["score"]) if row["score"] is not None else None
        team.add_player(Player(id=int(row["nba_player_id"]), score=score), row["role"])

    for team_id, team in teams.items():
        total = round(team.calculate_total_score(ROLE_CONFIGS), 2)
        print(f"  Squadra {team_id}: {total}")
        if not dry_run:
            sync.update_team_score_for_gameweek(team_id, gameweek, total)


def process_nba_date(sync: SupabaseSync, manager: NbaDataManager, nba_date: str, dry_run: bool) -> list[str]:
    """Aggiorna lineup_players e matchups con le partite della data NBA indicata. Restituisce gli errori."""
    ita_date = TimeManager.nba_date_to_italian_date(nba_date)
    gameweek = sync.get_gameweek_by_date(ita_date, before_start_as_first=False)
    if gameweek is None:
        print(f"[{nba_date}] Nessuna giornata per la data italiana {ita_date}: niente da fare.")
        return []
    if sync.get_gameweek_info(gameweek)["was_played"]:
        print(f"[{nba_date}] GW {gameweek} già chiusa: punteggi non modificati.")
        return []

    rows = sync.get_lineup_rows_for_gameweek(gameweek)
    if not rows:
        return [f"GW {gameweek}: nessuna riga in lineup_players"]

    # Giocatori assenti dalla mappa NBA->ESPN (es. rookie): li cerca per nome nei roster ESPN.
    # Va fatto prima di scaricare i tabellini, che usano la mappa per convertire gli ID.
    manager.map_missing_players({
        int(r["nba_player_id"]): (r.get("nba_players") or {}).get("full_name") or r["player_name"]
        for r in rows
    })
    boxscores = fetch_boxscores(manager, nba_date)

    new_scores, errors = compute_player_scores(rows, boxscores, nba_date, manager.nba_to_espn_map)
    sync_nba_teams(sync, rows, boxscores, dry_run)

    # Per il log: chi è a referto ed è entrato in campo, chi è a referto ma DNP
    played_ids = {b["PLAYER_ID"] for b in boxscores if not b.get("DNP")}
    dnp_ids = {b["PLAYER_ID"] for b in boxscores if b.get("DNP")}

    # Ogni giocatore tiene la prestazione migliore della giornata:
    # si scrive solo se il nuovo punteggio supera quello salvato (o se non ce n'era uno).
    # Nel log compaiono tutti i giocatori schierati la cui squadra NBA ha giocato,
    # anche quelli il cui punteggio non migliora.
    updated = 0
    for row in rows:
        p_id = int(row["nba_player_id"])
        new_score = new_scores[p_id]
        if new_score is None:
            continue  # la sua squadra NBA non ha giocato (o la partita non è conclusa)
        new_score = round(new_score, 2)
        old_score = float(row["score"]) if row["score"] is not None else None

        if p_id in played_ids:
            note = ""
        elif p_id in dnp_ids:
            note = " [DNP]"
        else:
            note = " [non a referto]"

        if old_score is not None and new_score <= old_score:
            esito = "invariato" if new_score == old_score else "non migliorato"
            print(f"  {row['player_name']}: {old_score} (questa data {new_score}{note}, {esito})")
            continue

        print(f"  {row['player_name']}: {old_score} -> {new_score}{note}")
        row["score"] = new_score
        updated += 1
        if not dry_run and not sync.update_lineup_player_score(gameweek, new_score, nba_player_id=p_id):
            errors.append(f"Scrittura fallita per {row['player_name']} (GW {gameweek})")

    print(f"[{nba_date}] GW {gameweek}: {len(boxscores)} tabellini, {updated} punteggi migliorati.")
    update_team_scores(sync, gameweek, rows, dry_run)
    return errors


def run_daily(sync: SupabaseSync, nba_dates: list[str], dry_run: bool) -> list[str]:
    manager = NbaDataManager(player_ids=[])  # nessun filtro: tabellini di tutta la NBA
    errors = []
    for nba_date in nba_dates:
        errors += process_nba_date(sync, manager, nba_date, dry_run)

    # Calendario NBA: risultati delle stesse date (non influisce sui punteggi)
    if dry_run:
        print("Calendario NBA non aggiornato (dry-run).")
    else:
        try:
            sync.sync_nba_games(nba_dates)
        except Exception as e:
            errors.append(f"Calendario NBA non aggiornato: {e}")
    return errors


def rollover_due(sync: SupabaseSync, today: str) -> bool:
    """
    pg_cron lancia il rollover alle 21:59 e alle 22:59 UTC: alle 23:59 italiane cade il run delle 22:59 UTC
    con l'ora solare e quello delle 21:59 UTC con l'ora legale. Si prosegue quindi solo dalle 23:59 italiane
    in poi e una volta sola al giorno: se il rollover di oggi è già riuscito, il run successivo viene saltato.
    Con l'ora legale il run delle 22:59 UTC cade alle 00:59, ma today è ancora il giorno prima
    (TimeManager.rollover_day), quindi fa da secondo tentativo se il primo è fallito.
    """
    rollover = TimeManager.rollover_instant(date.fromisoformat(today))
    now = datetime.now(timezone.utc)
    if now < rollover:
        print(f"Sono le {now.astimezone(ITA_TZ):%H:%M} italiane, il rollover è alle "
              f"{rollover.astimezone(ITA_TZ):%H:%M}: run saltato.")
        return False
    last_run = sync.get_cron_run("rollover")
    if last_run and last_run["ok"] and last_run["finished_at"] >= rollover:
        print("Rollover di oggi già eseguito: run saltato.")
        return False
    return True


def run_rollover(sync: SupabaseSync, today: str, dry_run: bool) -> list[str]:
    """
    Lanciato ogni giorno alle 23:59 italiane, agisce solo se domani inizia una nuova giornata
    (la giornata di domani comprende anche le partite che iniziano stasera, data NBA = oggi):
    - chiude la giornata di oggi: ultimo ricalcolo dei totali e was_played = True
    - azzera la giornata di domani: score dei giocatori NULL, punteggi delle squadre 0.0
    - allinea ai titolari il modulo in matchups di entrambe (storico dei moduli; i cambi di domani ora sono chiusi)
    - riscarica le partite NBA della giornata di domani (rinvii e cambi d'orario)
    """
    current_gw = sync.get_gameweek_by_date(today, before_start_as_first=False)
    next_gw = sync.get_gameweek_by_date(shift_date(today, 1), before_start_as_first=False)
    if next_gw is None or next_gw == current_gw:
        print(f"[{today}] Nessun cambio di giornata: niente da fare.")
        return []

    if current_gw is not None:
        print(f"Chiusura GW {current_gw}...")
        update_team_scores(sync, current_gw, sync.get_lineup_rows_for_gameweek(current_gw), dry_run)
        # Storico dei moduli: quello della giornata chiusa deve corrispondere ai titolari che hanno giocato
        sync.align_lineups_with_starters(current_gw, dry_run)
        if not dry_run:
            sync.set_gameweek_played(current_gw)

    if sync.get_gameweek_info(next_gw)["was_played"]:
        return [f"GW {next_gw} risulta già giocata: azzeramento annullato"]

    print(f"Azzeramento GW {next_gw}...")
    if not dry_run:
        sync.reset_lineup_scores_for_gameweek(next_gw)
        sync.reset_matchup_scores_for_gameweek(next_gw)
    sync.align_lineups_with_starters(next_gw, dry_run)
    if not dry_run:
        try:
            sync.sync_nba_games(sync.get_gameweek_nba_dates(next_gw))
        except Exception as e:
            return [f"Calendario NBA della GW {next_gw} non aggiornato: {e}"]
    return []


def main():
    # La console di Windows (cp1252) non stampa nomi come Jokić
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Cron job punteggi FantaNBA")
    parser.add_argument("mode", nargs="?", default="daily", choices=["daily", "rollover"])
    parser.add_argument("--date", help="(daily) data NBA da elaborare, YYYY-MM-DD")
    parser.add_argument("--days", type=int, help="(daily) quante date NBA elaborare all'indietro")
    parser.add_argument("--today", help="data italiana da considerare come oggi, YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="(rollover) esegue senza controllare l'orario")
    parser.add_argument("--dry-run", action="store_true", help="non scrive su Supabase")
    args = parser.parse_args()

    sync = SupabaseSync()
    if args.today:
        today = args.today
    elif args.mode == "rollover":
        today = TimeManager.rollover_day(datetime.now(timezone.utc)).isoformat()
    else:
        today = TimeManager.get_today_str()
    print(f"=== Cron {args.mode} | oggi (ITA) {today} | dry-run: {args.dry_run} ===")

    # Dei due lanci giornalieri del rollover ne lavora uno solo (i run manuali con --today o --force sempre).
    # Il run saltato non viene registrato in cron_runs, così l'app non riscarica dati inutilmente.
    if args.mode == "rollover" and not (args.today or args.force) and not rollover_due(sync, today):
        return

    errors = None  # resta None se il run si interrompe con un'eccezione
    try:
        if args.mode == "rollover":
            errors = run_rollover(sync, today, args.dry_run)
        else:
            last_nba_date = args.date or TimeManager.italian_date_to_nba_date(today)
            days = args.days or (1 if args.date else 2)
            nba_dates = [shift_date(last_nba_date, -i) for i in reversed(range(days))]  # dalla più vecchia
            errors = run_daily(sync, nba_dates, args.dry_run)
    finally:
        # Anche un run fallito può aver scritto qualcosa: l'app deve comunque riscaricare i dati
        if not args.dry_run:
            sync.record_cron_run(args.mode, ok=errors == [])

    if errors:
        print("\nERRORI:")
        for err in errors:
            print(f"- {err}")
        sys.exit(1)  # il run risulta fallito su GitHub, che manda una mail
    print("\nCompletato senza errori.")


if __name__ == "__main__":
    main()
