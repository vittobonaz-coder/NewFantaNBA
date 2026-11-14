import flet as ft
from datetime import datetime
from app import main
from time_manager import TimeManager


if __name__ == "__main__":
    # Simulazione dell'orologio dell'app (None = ora reale). Dalla Fase 2 giornate mostrate e scadenza dei
    # cambi le decide il database con l'ora reale: la simulazione cambia solo il blocco dei cambi a video.
    # Es. datetime.fromisoformat("2026-10-27T12:00:00+01:00")
    TimeManager.simulate_now(None)
    ft.run(main=main)
