"""
Da lanciare una volta: compila home_lineup/away_lineup di matchups per tutte le giornate,
ricavando il modulo dalle posizioni dei titolari in lineup_players (a parità di moduli possibili: 2-2-1).
Poi il modulo lo scrivono l'app (al salvataggio della formazione) e il cron (al rollover).

  python backfill_lineups.py [--dry-run]
"""
import argparse
import sys

from supabase_manager import SupabaseSync


def main():
    # La console di Windows (cp1252) non stampa nomi come Jokić
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Compila i moduli in matchups dai titolari di lineup_players")
    parser.add_argument("--dry-run", action="store_true", help="stampa le modifiche senza scriverle")
    args = parser.parse_args()

    SupabaseSync().backfill_matchup_lineups(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
