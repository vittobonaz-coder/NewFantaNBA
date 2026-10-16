import os
from pathlib import Path
from supabase import create_client, Client

# --- CONFIGURAZIONE ---
DATA_DIR = Path("data")
PLAYERS_DIR = Path("assets/players")
KEEP_FILES = {"fanta_teams.json", "rules.json"}

# Credenziali Supabase fornite
SUPABASE_URL = "https://ifqiarpfsbcrfpmabdus.supabase.co"
SUPABASE_KEY = "sb_publishable_KNhdTSkcs0XuzDwKqNbIOA_XpiJlqFZ"

def clean_local_files():
    """1. Pulisce la cartella data preservando i file essenziali."""
    print("🧹 Pulizia della cartella 'data'...")
    if DATA_DIR.exists() and DATA_DIR.is_dir():
        for file_path in DATA_DIR.iterdir():
            if file_path.is_file() and file_path.name not in KEEP_FILES:
                try:
                    file_path.unlink()
                    print(f"   [Eliminato] {file_path}")
                except Exception as e:
                    print(f"   [Errore] Impossibile eliminare {file_path}: {e}")
    else:
        print("   La cartella 'data' non esiste.")

    # """2. Pulisce la cartella assets/players."""
    # print("🧹 Pulizia della cartella 'assets/players'...")
    # if PLAYERS_DIR.exists() and PLAYERS_DIR.is_dir():
    #     for file_path in PLAYERS_DIR.iterdir():
    #         if file_path.is_file():
    #             try:
    #                 file_path.unlink()
    #                 print(f"   [Eliminato] {file_path}")
    #             except Exception as e:
    #                 print(f"   [Errore] Impossibile eliminare {file_path}: {e}")
    # else:
    #     print("   La cartella 'assets/players' non esiste.")

def clean_database():
    """3. Cancella tutte le righe dalle tabelle di Supabase rispettando i vincoli di foreign key."""
    print("🗄️ Svuotamento delle tabelle del database tramite Supabase Client...")
    
    # Inizializzazione del client Supabase
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Ordine inverso rispetto alle dipendenze (prima le tabelle figlie, poi quelle genitrici)
    tables = [
        "player_stats",
        "lineup_players",
        "matchups",
        "rosters",
        "fanta_teams",
        "nba_players",
        "profiles"
    ]
    
    try:
        for table in tables:
            query = supabase.table(table).delete()
            
            # Applichiamo il filtro corretto in base alla tipologia di ID della tabella
            if table == "player_stats":
                # Chiave primaria composta (player_id, game_id)
                response = query.neq("player_id", -1).execute()
            elif table == "nba_players":
                # L'id è un intero
                response = query.neq("id", -1).execute()
            else:
                # Tutte le altre tabelle hanno id di tipo UUID
                response = query.neq("id", "00000000-0000-0000-0000-000000000000").execute()
            
            print(f"   [Tabella svuotata] {table}")
            
        print("   Tutte le tabelle del database sono state ripulite con successo.")
    except Exception as e:
        print(f"   [Errore Database] Impossibile completare la pulizia delle tabelle: {e}")

if __name__ == "__main__":
    print("=== AVVIO PROCEDURA DI RESET ===")
    clean_local_files()
    print("-" * 40)
    clean_database()
    print("=== PROCEDURA COMPLETATA ===")