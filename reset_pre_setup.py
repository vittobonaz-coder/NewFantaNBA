"""
Reset completo prima del setup di una nuova stagione: cancella i file locali in data/ (tranne
fanta_teams.json e rules.json), le foto in assets/players e TUTTE le righe delle tabelle di Supabase,
profili compresi. Usa la chiave segreta (.env): senza --conferma non cancella nulla.

  python reset_pre_setup.py --conferma
"""
import argparse
from pathlib import Path
from supabase import Client
from supabase_manager import get_client

# --- CONFIGURAZIONE ---
DATA_DIR = Path("data")
PLAYERS_DIR = Path("assets/players")
KEEP_FILES = {"fanta_teams.json", "rules.json"}

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
    print("🧹 Pulizia della cartella 'assets/players'...")
    if PLAYERS_DIR.exists() and PLAYERS_DIR.is_dir():
        for file_path in PLAYERS_DIR.iterdir():
            if file_path.is_file():
                try:
                    file_path.unlink()
                    print(f"   [Eliminato] {file_path}")
                except Exception as e:
                    print(f"   [Errore] Impossibile eliminare {file_path}: {e}")
    else:
        print("   La cartella 'assets/players' non esiste.")

def clean_database():
    """3. Cancella tutte le righe dalle tabelle di Supabase rispettando i vincoli di foreign key."""
    print("🗄️ Svuotamento delle tabelle del database tramite Supabase Client...")
    
    # Client con la chiave segreta (.env): con la chiave pubblicabile le RLS bloccano le cancellazioni
    supabase: Client = get_client(admin=True)
    
    # Ordine inverso rispetto alle dipendenze (prima le tabelle figlie, poi quelle genitrici)
    tables = [
        "nba_games",
        "player_stats",
        "lineup_players",
        "matchups",
        "rosters",
        "standings_adjustments",  # riferisce fanta_teams (senza cascade)
        "fanta_teams",
        "nba_players",
        "profiles"
    ]
    
    try:
        for table in tables:
            query = supabase.table(table).delete()
            
            # Applichiamo il filtro corretto in base alla tipologia di ID della tabella
            if table == "nba_games":
                # Chiave primaria testuale (id evento ESPN)
                query.neq("game_id", "").execute()
            elif table == "player_stats":
                # Chiave primaria composta (player_id, game_id)
                query.neq("player_id", -1).execute()
            elif table == "nba_players":
                # L'id è un intero
                query.neq("id", -1).execute()
            else:
                # Tutte le altre tabelle hanno id di tipo UUID
                query.neq("id", "00000000-0000-0000-0000-000000000000").execute()
            
            print(f"   [Tabella svuotata] {table}")
            
        print("   Tutte le tabelle del database sono state ripulite con successo.")
    except Exception as e:
        print(f"   [Errore Database] Impossibile completare la pulizia delle tabelle: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cancella dati locali e TUTTE le tabelle di Supabase (profili compresi)")
    parser.add_argument("--conferma", action="store_true", help="obbligatorio: senza non viene cancellato nulla")
    if not parser.parse_args().conferma:
        parser.error("operazione irreversibile: rilancia con --conferma se vuoi davvero cancellare tutto")
    get_client(admin=True)  # Senza chiave segreta si ferma qui, prima di cancellare i file locali
    print("=== AVVIO PROCEDURA DI RESET ===")
    clean_local_files()
    print("-" * 40)
    clean_database()
    print("=== PROCEDURA COMPLETATA ===")