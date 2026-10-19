import os
import flet as ft
from app import main


if __name__ == "__main__":
    # Render usa la variabile d'ambiente PORT
    port = int(os.environ.get("PORT", 8080))

    ft.run(main=main,
        port=port,
        host="0.0.0.0",
        assets_dir="assets",
    )
