import json
import os
import pandas as pd
from datetime import datetime, timedelta
from fanta_obj import Player
from api_nba import NbaDataManager

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
    manager = NbaDataManager(player_ids=player_ids, season="2025-26", s_type="Regular Season")

    # NUOVO: 2.1 Scarica le informazioni anagrafiche dei giocatori (Squadra e Ruolo)
    print("Scaricamento delle informazioni di base dei giocatori in corso...")
    players_info_list = manager.fetch_players_info(player_ids)
    
    # Creiamo un dizionario per associare velocemente le info aggiuntive tramite PLAYER_ID
    info_dict = {p["PLAYER_ID"]: p for p in players_info_list}

    # 3. Definisci le date della regular season 2025-2026
    start_date = datetime(2025, 10, 21)
    end_date = datetime(2026, 4, 15)

    all_boxscores = []
    
    # 4. Scarica i boxscore per ogni giorno della stagione
    print("Scaricamento dei boxscore in corso...")
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        try:
            daily_boxscores = manager.fetch_boxscores(date_str)
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

        if not p_boxscores:
            # Nessun dato giocato per il giocatore, ma inseriamo comunque Ruolo e Squadra
            results.append({
                "Giocatore": pname,
                "Posizione": clean_position,
                "Squadra": team,
                "Punteggio fanta": "-",
                "Numero di partite giocate": "-",
                "Minuti giocati": "-",
                "Punti fatti": "-",
                "Rimbalzi difensivi": "-",
                "Rimbalzi offensivi": "-",
                "Assist": "-",
                "Palle rubate": "-",
                "Stoppate": "-",
                "Turnover": "-",
                "FGM": "-",
                "FGA": "-",
                "FG3M": "-",
                "FG3A": "-",
                "FTM": "-",
                "FTA": "-",
                "Plus/Minus": "-"
            })
            continue

        games_played = len(p_boxscores)
        
        # Calcolo Fantapunteggio
        fanta_score = player_obj.calculate_score(all_boxscores, average=True)

        # Funzione helper per le medie
        def calc_avg(stat_key):
            total = 0.0
            for b in p_boxscores:
                val = b.get(stat_key, 0)
                if stat_key == "MIN":
                    if isinstance(val, str) and ":" in val:
                        m, s = val.split(":")
                        total += int(m) + int(s) / 60.0
                    else:
                        try:
                            total += float(val)
                        except ValueError:
                            pass
                else:
                    try:
                        total += float(val)
                    except ValueError:
                        pass
            return round(total / games_played, 2)

        # Creazione della riga del giocatore
        results.append({
            "Giocatore": pname,
            "Posizione": clean_position,
            "Squadra": team,
            "Punteggio fanta": round(fanta_score, 2),
            "Numero di partite giocate": games_played,
            "Minuti giocati": calc_avg("MIN"),
            "Punti fatti": calc_avg("PTS"),
            "Rimbalzi difensivi": calc_avg("DREB"),
            "Rimbalzi offensivi": calc_avg("OREB"),
            "Assist": calc_avg("AST"),
            "Palle rubate": calc_avg("STL"),
            "Stoppate": calc_avg("BLK"),
            "Turnover": calc_avg("TOV"),
            "FGM": calc_avg("FGM"),
            "FGA": calc_avg("FGA"),
            "FG3M": calc_avg("FG3M"),
            "FG3A": calc_avg("FG3A"),
            "FTM": calc_avg("FTM"),
            "FTA": calc_avg("FTA"),
            "Plus/Minus": calc_avg("PLUS_MINUS")
        })

    # 6. Salvataggio su file Excel
    df = pd.DataFrame(results)
    output_filename = "nba_stats_2025_2026.xlsx"
    df.to_excel(output_filename, index=False)
    print(f"File '{output_filename}' generato con successo!")

if __name__ == "__main__":
    main()