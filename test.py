import flet as ft
from datetime import datetime
from app import main
from time_manager import TimeManager


if __name__ == "__main__":
    # Simulazione dell'orologio dell'app (None = ora reale): cambia solo le giornate mostrate e
    # la finestra dei cambi, i punteggi sono sempre quelli presenti su Supabase.
    # Es. datetime.fromisoformat("2026-10-27T12:00:00+01:00") = ultimo giorno della GW1:
    # si vedono la GW1 con i punteggi e la formazione della GW2
    TimeManager.simulate_now(None)
    ft.run(main=main)
