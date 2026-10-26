"""
Avvio su Render: server web di Flet (FastAPI + uvicorn) costruito a mano invece di ft.run,
per servire il client Flutter (circa 20 MB tra main.dart.js, canvaskit e font) compresso e in cache.
Il piano Free di Render ha 0,1 CPU: senza compressione né cache l'avvio da browser è lentissimo.
"""
import os
import uvicorn
import flet_web.fastapi as flet_fastapi
from fastapi.middleware.gzip import GZipMiddleware
from app import main

# Il client Flutter si aggiorna solo con la versione di Flet: in cache per un giorno.
# index.html e service worker sempre riconvalidati, così un deploy arriva subito.
STATIC_MAX_AGE = 86400
NO_CACHE_PATHS = {"/", "/index.html", "/flutter_service_worker.js", "/manifest.json", "/version.json"}
SESSION_TIMEOUT = 600  # Secondi in cui una sessione disconnessa resta in memoria (default Flet: 3600)


class CacheControlMiddleware:
    """Aggiunge Cache-Control alle risposte HTTP (i websocket passano invariati)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope["path"]
        no_cache = path in NO_CACHE_PATHS or "." not in path.rsplit("/", 1)[-1]  # pagine dell'app = index.html
        value = "no-cache" if no_cache else f"public, max-age={STATIC_MAX_AGE}"

        async def send_with_cache(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [(b"cache-control", value.encode())]
            await send(message)

        await self.app(scope, receive, send_with_cache)


if __name__ == "__main__":
    # Render usa la variabile d'ambiente PORT
    port = int(os.environ.get("PORT", 8080))

    app = flet_fastapi.app(
        main,
        assets_dir=os.path.abspath("assets"),
        session_timeout_seconds=SESSION_TIMEOUT,
    )
    app.add_middleware(CacheControlMiddleware)
    # Livello medio: comprimere 9 MB a livello 9 con 0,1 CPU costerebbe troppo
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

    uvicorn.run(app, host="0.0.0.0", port=port, ws="websockets-sansio")
