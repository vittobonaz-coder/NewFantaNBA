import json
import os
from typing import List
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# Definiamo le zone
ITA_TZ = ZoneInfo("Europe/Rome")
NBA_TZ = ZoneInfo("America/New_York")
UTC = timezone.utc

# Orari dei cron
# - daily: fisso in UTC (08:00 = 9:00 italiane con l'ora solare, 10:00 con l'ora legale)
# - rollover: sempre alle 23:59 italiane. pg_cron (solo UTC) lo lancia alle 21:59 e alle 22:59 UTC
#   e lo script prosegue solo con il run che cade dalle 23:59 in poi (cron_test_script.rollover_due)
DAILY_CRON_UTC = time(8, 0)       # punteggi della notte NBA
ROLLOVER_TIME_ITA = time(23, 59)  # cambio giornata = chiusura dei cambi formazione
# Un run del rollover che parte dopo mezzanotte (fino alle 03:00) vale ancora per il giorno prima
ROLLOVER_GRACE = timedelta(hours=3)
# Ritardo massimo atteso di un run su GitHub Actions (usato solo se manca la tabella cron_runs)
CRON_DELAY_MARGIN = timedelta(minutes=45)

class TimeManager:
    """Classe utility per gestire logiche orarie e controlli temporali della lega."""
    _sim_offset: timedelta | None = None

    @classmethod
    def simulate_now(cls, fake_now: datetime | None) -> None:
        """Solo per i test: sposta l'orologio dell'app a fake_now (aware), da lì il tempo scorre normalmente."""
        cls._sim_offset = None if fake_now is None else fake_now - datetime.now(UTC)

    @classmethod
    def now(cls) -> datetime:
        """Istante attuale in UTC, eventualmente simulato con simulate_now."""
        real_now = datetime.now(UTC)
        return real_now + cls._sim_offset if cls._sim_offset is not None else real_now

    @staticmethod
    def rollover_instant(ita_day: date) -> datetime:
        """Istante (in UTC) del rollover nel giorno italiano indicato: le 23:59 italiane, con o senza ora legale."""
        return datetime.combine(ita_day, ROLLOVER_TIME_ITA, tzinfo=ITA_TZ).astimezone(UTC)

    @staticmethod
    def rollover_day(now: datetime) -> date:
        """Giorno italiano a cui appartiene un run del rollover (dopo mezzanotte conta ancora il giorno prima)."""
        return (now.astimezone(ITA_TZ) - ROLLOVER_GRACE).date()

    @staticmethod
    def last_scheduled_cron() -> datetime:
        """
        Ultimo orario programmato di un cron, passato da almeno CRON_DELAY_MARGIN (orologio reale).
        Ripiego per quando su Supabase non c'è traccia dei run (tabella cron_runs).
        """
        now = datetime.now(UTC)
        today_ita = now.astimezone(ITA_TZ).date()
        slots = [datetime.combine(now.date() - timedelta(days=d), DAILY_CRON_UTC, tzinfo=UTC) for d in (0, 1)]
        slots += [TimeManager.rollover_instant(today_ita - timedelta(days=d)) for d in (0, 1)]
        return max(s + CRON_DELAY_MARGIN for s in slots if s + CRON_DELAY_MARGIN <= now)

    @classmethod
    def get_league_context(cls, rounds: list[dict]) -> dict:
        """
        Stato della lega adesso, dalle giornate del calendario (date italiane):
        - current_gw: giornata in corso (o appena conclusa) da mostrare con i punteggi,
          None prima dell'inizio del campionato
        - edit_gw: prima giornata non ancora iniziata, a cui si applicano i cambi formazione;
          None se non ce ne sono altre (fine campionato)
        - deadline: chiusura dei cambi per edit_gw (UTC) = rollover del giorno prima del suo inizio
        I cambi sono quindi sempre aperti per la giornata successiva a quella in corso
        (e per la giornata 1 in pre-campionato): il salvataggio scrive su lineup_players
        da edit_gw in poi, senza toccare la giornata in corso.
        """
        context = {"current_gw": None, "edit_gw": None, "deadline": None}
        if not rounds:
            return context
        rounds = sorted(rounds, key=lambda r: r["start_date"])

        now = cls.now()
        today = now.astimezone(ITA_TZ).date()
        tomorrow = (today + timedelta(days=1)).isoformat()
        rollover = cls.rollover_instant(today)

        # Prima del rollover le partite di riferimento sono quelle di oggi, dopo quelle di domani
        # (la giornata di domani è appena stata azzerata dal cron)
        league_day = today.isoformat() if now < rollover else tomorrow

        started = [r for r in rounds if r["start_date"] <= league_day]
        if started:
            context["current_gw"] = started[-1]["round_number"]

        # Giornata modificabile: la prima non ancora iniziata rispetto a league_day.
        # Dopo il rollover della vigilia la giornata di domani è già "iniziata" (bloccata),
        # quindi i cambi passano subito a quella dopo ancora.
        upcoming = [r for r in rounds if r["start_date"] > league_day]
        if upcoming:
            next_round = upcoming[0]
            eve = date.fromisoformat(next_round["start_date"]) - timedelta(days=1)
            context.update(edit_gw=next_round["round_number"], deadline=cls.rollover_instant(eve))
        return context

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
        return datetime.now(ITA_TZ).strftime(fmt)

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
        now = datetime.now(ITA_TZ)
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
            today = datetime.now(ITA_TZ).date()
            
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

    @staticmethod
    def get_gameweek_dates(
        round_number: int, 
        calendar_path: str = os.path.join("data", "calendar.json"),
        fmt: str = "%Y-%m-%d"
    ) -> List[str]:
        """
        Legge il file calendar.json e restituisce la lista di date (stringhe)
        che compongono il round specificato (inclusi start_date ed end_date).

        Args:
            round_number (int): Il numero della gameweek/round da cercare.
            calendar_path (str): Percorso del file calendar.json.
            fmt (str): Formato delle date in output (default: "%Y-%m-%d").

        Returns:
            List[str]: Lista di stringhe rappresentanti le date del round.
                       Es: ['2026-10-04', '2026-10-05', ..., '2026-10-10']
        """
        if not os.path.exists(calendar_path):
            print(f"Errore: File '{calendar_path}' non trovato.")
            return []

        try:
            with open(calendar_path, "r", encoding="utf-8") as f:
                calendar_data = json.load(f)

            # Cerca il round specificato
            target_round = next(
                (r for r in calendar_data if r.get("round_number") == round_number), 
                None
            )

            if not target_round:
                print(f"Attenzione: Round number {round_number} non trovato nel calendario.")
                return []

            start_dt = datetime.strptime(target_round["start_date"], fmt).date()
            end_dt = datetime.strptime(target_round["end_date"], fmt).date()

            # Genera la sequenza di date da start_date a end_date inclusa
            date_list = []
            curr_dt = start_dt
            while curr_dt <= end_dt:
                date_list.append(curr_dt.strftime(fmt))
                curr_dt += timedelta(days=1)

            return date_list

        except Exception as e:
            print(f"Errore durante la lettura del calendario: {e}")
            return []


# dates_gw1 = TimeManager.get_gameweek_dates(round_number=1)
# print("Date GW1:", dates_gw1)




# from datetime import datetime, time, timedelta
# from zoneinfo import ZoneInfo

# def get_current_times():
#     now_ita = datetime.now(ITA_TZ)
#     now_nba = datetime.now(NBA_TZ)
#     return now_ita, now_nba



# target = get_nba_target_date()
# print(target)