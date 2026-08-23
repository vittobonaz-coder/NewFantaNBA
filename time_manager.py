from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

# Definiamo le zone
ITA_TZ = ZoneInfo("Europe/Rome")
NBA_TZ = ZoneInfo("America/New_York")

def get_current_times():
    now_ita = datetime.now(ITA_TZ)
    now_nba = datetime.now(NBA_TZ)
    return now_ita, now_nba

def get_nba_target_date():
    """Restituisce la data NBA target in base all'ora 
    (se non sono passate le 9 prende il giorno prima)"""
    now_ita = datetime.now(ITA_TZ)
    if now_ita.hour < 9:
        target_date = now_ita - timedelta(days=2)
    else:
        target_date = now_ita - timedelta(days=1)
        
    return target_date.strftime("%Y-%m-%d")

target = get_nba_target_date()
print(target)