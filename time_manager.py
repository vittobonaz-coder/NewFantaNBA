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
