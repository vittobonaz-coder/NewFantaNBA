from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Definiamo le zone
ITA_TZ = ZoneInfo("Europe/Rome")
NBA_TZ = ZoneInfo("America/New_York")

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

    @staticmethod
    def is_date_before_today(date_str: str, date_format: str = "%Y-%m-%d") -> bool:
        """
        Verifica se la data fornita sotto forma di stringa è antecedente a oggi.
        Args:
            date_str (str): La data da verificare (es. "1970-01-01" o "01/01/1970").
            date_format (str): Il formato della stringa (default: ISO "%Y-%m-%d").
        Returns:
            bool: True se la data è strettamente minore di oggi, False altrimenti.
        """
        try:
            # Converti la stringa in oggetto date
            input_date = datetime.strptime(date_str, date_format).date()
            
            # Ottieni la data odierna
            today = date.today()
            
            # Confronto diretto tra oggetti date
            return input_date < today
            
        except ValueError:
            print(f"Errore: La stringa '{date_str}' non corrisponde al formato '{date_format}'.")
            return False

    @staticmethod
    def nba_date_to_italian_date(nba_date_str: str, fmt: str = "%Y-%m-%d") -> str:
        """
        Converte la data NBA (fuso USA) nella corrispondente data italiana (+1 giorno).
        Es: '2026-10-03' (USA) -> '2026-10-04' (Italia)
        """
        try:
            nba_dt = datetime.strptime(nba_date_str, fmt).date()
            italian_dt = nba_dt + timedelta(days=1)
            return italian_dt.strftime(fmt)
        except ValueError:
            print(f"Errore formato data: {nba_date_str}")
            return nba_date_str

    @staticmethod
    def italian_date_to_nba_date(italian_date_str: str, fmt: str = "%Y-%m-%d") -> str:
        """
        Converte la data italiana nella corrispondente data NBA (-1 giorno).
        Es: '2026-10-04' (Italia) -> '2026-10-03' (USA)
        """
        try:
            ita_dt = datetime.strptime(italian_date_str, fmt).date()
            nba_dt = ita_dt - timedelta(days=1)
            return nba_dt.strftime(fmt)
        except ValueError:
            print(f"Errore formato data: {italian_date_str}")
            return italian_date_str

    @staticmethod
    def get_nba_target_date():
        """Restituisce la data NBA target in base all'ora (se non sono passate le 8 prende il giorno prima)"""
        now_ita = datetime.now(ITA_TZ)
        if now_ita.hour < 8:
            target_date = now_ita - timedelta(days=2)
        else:
            target_date = now_ita - timedelta(days=1)
            
        return target_date.strftime("%Y-%m-%d")

print(TimeManager().get_nba_target_date())





# from datetime import datetime, time, timedelta
# from zoneinfo import ZoneInfo



# def get_current_times():
#     now_ita = datetime.now(ITA_TZ)
#     now_nba = datetime.now(NBA_TZ)
#     return now_ita, now_nba



# target = get_nba_target_date()
# print(target)