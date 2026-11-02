import json
import os
import pandas as pd
from datetime import datetime, timedelta
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from fanta_obj import Player
from api_nba import NbaDataManager, normalize_name
from supabase_manager import SupabaseSync

# Riga dei giocatori che sono già in una fanta-squadra
ROSTERED_FILL = PatternFill(fill_type="solid", start_color="FFFF00", end_color="FFFF00")
PERCENT_COLUMNS = ["FG%", "3P%", "FT%"]
COLUMN_WIDTHS = {"Giocatore": 24, "Note infortunio": 30, "Fanta-squadra": 16}


def fetch_injuries_by_player(manager, players_data):
    """Infortuni ESPN di tutta la NBA: {PLAYER_ID: {"INJ", "Note infortunio"}} (vuoto se ESPN non risponde)."""
    try:
        injuries = NbaDataManager.fetch_injuries()
    except Exception as e:
        print(f"Infortuni non disponibili: {e}")
        return {}

    by_name = {normalize_name(p["PLAYER_NAME"]): p["PLAYER_ID"] for p in players_data}
    result = {}
    for inj in injuries:
        nba_id = manager.espn_to_nba_map.get(inj["espn_id"]) if inj["espn_id"] else None
        nba_id = int(nba_id) if nba_id else by_name.get(normalize_name(inj["name"]))
        if nba_id is None:
            continue

        notes = inj["injury_type"] or ""
        if inj["return_date"]:
            return_date = datetime.strptime(inj["return_date"][:10], "%Y-%m-%d").strftime("%d/%m")
            notes = f"{notes} - rientro stimato {return_date}" if notes else f"Rientro stimato {return_date}"
        result[nba_id] = {
            "INJ": inj["fantasy_status"] or inj["status"],
            "Note infortunio": notes,
        }
    return result


def format_excel(path, rostered_rows):
    """Tabella con filtri, prima riga bloccata, percentuali e righe gialle per i giocatori delle fanta-squadre."""
    wb = load_workbook(path)
    ws = wb.active
    headers = [c.value for c in ws[1]]

    table = Table(displayName="TabellaStatistiche", ref=ws.dimensions)
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(table)
    ws.freeze_panes = "A2"

    for idx, header in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = COLUMN_WIDTHS.get(header, 9)
        if header in PERCENT_COLUMNS:
            for (cell,) in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                cell.number_format = "0.0%"

    for row_idx in rostered_rows:
        for cell in ws[row_idx]:
            cell.fill = ROSTERED_FILL

    wb.save(path)


def main():
    # 1. Carica i giocatori dal file json
    all_players_file = os.path.join("data", "all_players.json")
    if not os.path.exists(all_players_file):
        print(f"Errore: Il file {all_players_file} non esiste.")
        return

    with open(all_players_file, "r", encoding="utf-8") as f:
        players_data = json.load(f)

    player_ids = [p["PLAYER_ID"] for p in players_data]

    # 2. Inizializza NbaDataManager
    manager = NbaDataManager(player_ids=player_ids, season="2026-27", s_type="Regular Season")

    # Giocatori assenti dalla mappa NBA->ESPN (es. rookie): senza questo passaggio i loro tabellini verrebbero scartati
    manager.map_missing_players({p["PLAYER_ID"]: p["PLAYER_NAME"] for p in players_data})

    # NUOVO: 2.1 Scarica le informazioni anagrafiche dei giocatori (Squadra e Ruolo)
    print("Scaricamento delle informazioni di base dei giocatori in corso...")
    players_info_list = manager.fetch_players_info(player_ids)

    # Creiamo un dizionario per associare velocemente le info aggiuntive tramite PLAYER_ID
    info_dict = {p["PLAYER_ID"]: p for p in players_info_list}

    # 2.2 Fanta-squadra di ogni giocatore (da Supabase) e infortuni attuali di tutta la NBA (da ESPN)
    rostered = SupabaseSync().get_rostered_players()
    injuries = fetch_injuries_by_player(manager, players_data)

    # 3. Definisci le date della regular season 2026-2027 (date USA)
    start_date = datetime(2026, 10, 20)
    end_date = datetime(2026, 11, 1)

    all_boxscores = []

    # 4. Scarica i boxscore per ogni giorno della stagione
    print("Scaricamento dei boxscore in corso...")
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        try:
            # Solo partite concluse: quelle in corso avrebbero statistiche parziali
            daily_boxscores = manager.fetch_boxscores(date_str, only_completed=True)
            if daily_boxscores:
                all_boxscores.extend(daily_boxscores)
        except Exception as e:
            pass
        current_date += timedelta(days=1)

    print(f"Scaricamento completato. {len(all_boxscores)} prestazioni totali trovate.")

    # 5. Elabora le statistiche per ogni giocatore
    results = []
    for p_data in players_data:
        pid = p_data["PLAYER_ID"]
        pname = p_data["PLAYER_NAME"]

        # Recupera le informazioni di base (Squadra, Ruolo) dal dizionario
        p_info = info_dict.get(pid, {})
        team = p_info.get("TEAM", "-")
        raw_position = p_info.get("POSITION", "")

        # Inizializza il giocatore e formatta la posizione
        player_obj = Player()
        player_obj.id = pid
        player_obj.position = raw_position
        clean_position = player_obj.get_clean_position() if raw_position else "-"

        # Filtra i boxscore di questo giocatore
        p_boxscores = [b for b in all_boxscores if b.get("PLAYER_ID") == pid]

        injury = injuries.get(pid, {})
        extra = {
            "INJ": injury.get("INJ"),
            "Note infortunio": injury.get("Note infortunio"),
            "Fanta-squadra": rostered.get(pid),
        }

        if not p_boxscores:
            # Nessun dato giocato per il giocatore: celle statistiche vuote, così nei filtri finiscono in fondo
            results.append({"Giocatore": pname, "POS": clean_position, "TEAM": team, **extra})
            continue

        games_played = len(p_boxscores)

        # Calcolo Fantapunteggio
        fanta_score = player_obj.calculate_score(all_boxscores, average=True)

        def total(stat_key):
            tot = 0.0
            for b in p_boxscores:
                val = b.get(stat_key, 0)
                if stat_key == "MIN" and isinstance(val, str) and ":" in val:
                    m, s = val.split(":")
                    tot += int(m) + int(s) / 60.0
                    continue
                try:
                    tot += float(val)
                except ValueError:
                    pass
            return tot

        # Funzione helper per le medie
        def calc_avg(stat_key):
            return round(total(stat_key) / games_played, 2)

        # Percentuale sui totali della stagione (vuota se nessun tiro tentato)
        def calc_pct(made_key, attempted_key):
            attempted = total(attempted_key)
            return round(total(made_key) / attempted, 3) if attempted else None

        # Creazione della riga del giocatore
        results.append({
            "Giocatore": pname,
            "POS": clean_position,
            "TEAM": team,
            "FPTS": round(fanta_score, 2),
            "GP": games_played,
            "MIN": calc_avg("MIN"),
            "PTS": calc_avg("PTS"),
            "DREB": calc_avg("DREB"),
            "OREB": calc_avg("OREB"),
            "AST": calc_avg("AST"),
            "STL": calc_avg("STL"),
            "BLK": calc_avg("BLK"),
            "TOV": calc_avg("TOV"),
            "FG%": calc_pct("FGM", "FGA"),
            "3P%": calc_pct("FG3M", "FG3A"),
            "FT%": calc_pct("FTM", "FTA"),
            "+/-": calc_avg("PLUS_MINUS"),
            **extra,
        })

    # 6. Salvataggio su file Excel (nel nome la data dell'ultima giornata NBA inclusa)
    columns = ["Giocatore", "POS", "TEAM", "FPTS", "GP", "MIN", "PTS", "DREB", "OREB", "AST", "STL", "BLK",
               "TOV", "FG%", "3P%", "FT%", "+/-", "INJ", "Note infortunio", "Fanta-squadra"]
    df = pd.DataFrame(results, columns=columns)
    output_filename = f"nba_stats_2026_2027_{end_date.strftime('%Y-%m-%d')}.xlsx"
    df.to_excel(output_filename, index=False, sheet_name="Statistiche")

    # Righe Excel dei giocatori in una fanta-squadra (riga 1 = intestazioni)
    rostered_rows = [i + 2 for i, name in enumerate(df["Fanta-squadra"]) if pd.notna(name)]
    format_excel(output_filename, rostered_rows)
    print(f"File '{output_filename}' generato con successo! "
          f"{len(rostered_rows)} giocatori in una fanta-squadra, {len(df) - len(rostered_rows)} free agent.")

if __name__ == "__main__":
    main()
