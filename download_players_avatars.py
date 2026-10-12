import os
import json
import requests
import time

FANTA_TEAMS_PATH = os.path.join("data", "fanta_teams.json")
ALL_PLAYERS_PATH = os.path.join("data", "all_players.json")

def download_all_avatars(teams_path=FANTA_TEAMS_PATH, players_path=ALL_PLAYERS_PATH):
    # 1. Carica la lista delle squadre e dei roster
    try:
        with open(teams_path, "r", encoding="utf-8") as f:
            fanta_teams = json.load(f)
    except FileNotFoundError:
        print(f"Errore: Il file {teams_path} non è stato trovato!")
        return

    # 2. Carica il dizionario/lista globale dei giocatori con i relativi ID
    try:
        with open(players_path, "r", encoding="utf-8") as f:
            all_players = json.load(f)
    except FileNotFoundError:
        print(f"Errore: Il file {players_path} non è stato trovato!")
        return

    # Creiamo un dizionario di supporto per associare il nome (in minuscolo per sicurezza) al PLAYER_ID
    name_to_id = {}
    for p in all_players:
        name = p.get("PLAYER_NAME")
        p_id = p.get("PLAYER_ID")
        if name and p_id:
            name_to_id[name.lower()] = p_id

    # 3. Estrai tutti i nomi unici dei giocatori presenti nei fanta team
    unique_player_names = set()
    for team_name, roster in fanta_teams.items():
        for player_name in roster.keys():
            unique_player_names.add(player_name)

    # 4. Ricava gli ID corrispondenti dai nomi
    player_ids = []
    not_found = []
    
    for name in unique_player_names:
        p_id = name_to_id.get(name.lower())
        if p_id:
            player_ids.append(int(p_id))
        else:
            not_found.append(name)

    if not_found:
        print(f"Attenzione: Impossibile trovare l'ID in all_players.json per i seguenti giocatori: {not_found}")

    # Rimuoviamo eventuali duplicati
    player_ids = list(set(player_ids))

    # 5. Prepara la cartella di destinazione
    folder = os.path.join("assets", "players")
    if not os.path.exists(folder):
        os.makedirs(folder)

    print(f"Trovati {len(player_ids)} giocatori da scaricare. Inizio download...")

    # 6. Ciclo di download
    for i, p_id in enumerate(player_ids):
        target_path = os.path.join(folder, f"{p_id}.png")
        
        # Salta se già scaricato
        if os.path.exists(target_path):
            continue

        # URL Risoluzione Bassa (260x190) della NBA CDN
        url = f"https://cdn.nba.com/headshots/nba/latest/260x190/{p_id}.png"
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                with open(target_path, "wb") as f:
                    f.write(response.content)
                print(f"[{i+1}/{len(player_ids)}] Scaricato ID: {p_id}")
            else:
                print(f"[{i+1}/{len(player_ids)}] Immagine non disponibile per ID: {p_id}")
            
            # Un piccolo delay per non sovraccaricare il server NBA
            time.sleep(0.1) 
            
        except Exception as e:
            print(f"Errore su ID {p_id}: {e}")

    print("Operazione completata!")

if __name__ == "__main__":
    download_all_avatars()