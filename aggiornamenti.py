"""
Controllo degli aggiornamenti dell'app installata (Fase 5, docs/fase5_piano.md).

La configurazione sta su Supabase (tabella app_release, RPC app_release): ultima versione, versione minima e
link di download per piattaforma. La legge supabase_rest.warm_up all'avvio, in parallelo con l'import di flet.
La webapp e i build di sviluppo (versione.VERSIONE None) non fanno il controllo.
"""
import re

OK = "ok"
NUOVA = "nuova"                # C'è una versione più nuova: barra chiudibile sopra la dashboard
OBBLIGATORIA = "obbligatoria"  # Versione sotto la minima: l'app non si usa finché non si aggiorna

_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)\s*$")


def parse(version: str | None) -> tuple[int, int, int] | None:
    """"1.2.3" (anche "v1.2.3") -> (1, 2, 3); None se manca o non è nel formato X.Y.Z."""
    m = _VERSION_RE.match(version or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def esito(info: dict | None, installata: str | None) -> str:
    """
    Confronta la versione installata con la configurazione letta da Supabase.
    Nel dubbio (configurazione assente o malformata, build di sviluppo) non blocca nulla: OK.
    """
    mia = parse(installata)
    if mia is None or not isinstance(info, dict):
        return OK
    minima, ultima = parse(info.get("min_version")), parse(info.get("latest_version"))
    if minima and mia < minima:
        return OBBLIGATORIA
    if ultima and mia < ultima:
        return NUOVA
    return OK


def piattaforma(flet_platform: str | None) -> str | None:
    """Nome della piattaforma in app_release da FLET_PLATFORM ("android", "windows", "macos"); None per le altre."""
    value = (flet_platform or "").lower()
    return value if value in ("android", "windows", "macos") else None


def client_info(web: bool, native: bool, platform: str | None, version: str | None) -> dict:
    """
    Chi sta accedendo, per la tabella client_usage (Fase 6, sql/2026-11_fase6_client_usage.sql):
    {"client": "android" | "windows" (app installata) | "web-ios", "web-android"... (webapp dal browser di quel
    sistema) | "sviluppo", "version": "X.Y.Z" o None}. platform: valore di page.platform ("android", "ios"...).
    """
    system = re.sub(r"[^a-z]", "", (platform or "").lower()) or "altro"
    if web:
        return {"client": f"web-{system}", "version": None}
    if native:
        return {"client": system, "version": version}
    return {"client": "sviluppo", "version": None}
