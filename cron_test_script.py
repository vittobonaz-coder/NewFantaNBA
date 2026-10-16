from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import sys

def main():
    # 1. Otteniamo l'ora attuale in UTC (offset-aware)
    now_utc = datetime.now(timezone.utc)
    
    # 2. Convertiamo l'ora UTC nel fuso orario italiano ("Europe/Rome")
    italy_tz = ZoneInfo("Europe/Rome")
    now_italy = now_utc.astimezone(italy_tz)
    
    print(f"🚀 Script Python eseguito con successo!")
    print(f"📅 Timestamp UTC:    {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🇮🇹 Timestamp Italia: {now_italy.strftime('%Y-%m-%d %H:%M:%S')} ({now_italy.tzname()})")

if __name__ == "__main__":
    main()