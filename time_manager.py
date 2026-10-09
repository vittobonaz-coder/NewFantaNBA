from datetime import date, datetime, time, timedelta

class TimeManager:
    """Classe utility per gestire logiche orarie e controlli temporali della lega."""
    @staticmethod
    def get_today_str(fmt: str = "%Y-%m-%d") -> str:
        """
        Restituisce la data di oggi formattata come stringa.
        Args:
            fmt (str): Formato della data (default: "YYYY-MM-DD", es. "2026-10-09").
                       Puoi usare "%d/%m/%Y" per il formato italiano "09/10/2026".
        Returns:
            str: Data odierna formattata.
        """
        return date.today().strftime(fmt)

    @staticmethod
    def is_past_target_time(target_hour: int = 8, target_minute: int = 0) -> bool:
        """
        Verifica se l'ora corrente ha superato un determinato orario nella giornata odierna.
        Args:
            target_hour (int): L'ora target (di default 8 per le 8:00).
            target_minute (int): I minuti target (di default 0).    
        Returns:
            bool: True se l'ora attuale è passata rispetto al target, False altrimenti.
        """
        now = datetime.now()
        target_time = time(hour=target_hour, minute=target_minute)
        
        # Confronta l'orario attuale (time) con l'orario di target
        return now.time() >= target_time

    @staticmethod
    def is_past_eight_am() -> bool:
        """Metodo helper rapido per verificare se sono passate le 8:00 del mattino."""
        return TimeManager.is_past_target_time(target_hour=8, target_minute=0)


# print(TimeManager().get_today_str())





# from datetime import datetime, time, timedelta
# from zoneinfo import ZoneInfo

# # Definiamo le zone
# ITA_TZ = ZoneInfo("Europe/Rome")
# NBA_TZ = ZoneInfo("America/New_York")

# def get_current_times():
#     now_ita = datetime.now(ITA_TZ)
#     now_nba = datetime.now(NBA_TZ)
#     return now_ita, now_nba

# def get_nba_target_date():
#     """Restituisce la data NBA target in base all'ora 
#     (se non sono passate le 8 prende il giorno prima)"""
#     now_ita = datetime.now(ITA_TZ)
#     if now_ita.hour < 8:
#         target_date = now_ita - timedelta(days=2)
#     else:
#         target_date = now_ita - timedelta(days=1)
        
#     return target_date.strftime("%Y-%m-%d")

# target = get_nba_target_date()
# print(target)