"""
Versione dell'app (Fase 5, docs/fase5_piano.md).

Nella repository vale per webapp e sviluppo: nessuna versione, quindi nessun controllo degli aggiornamenti.
tools/prepara_build.py riscrive questo file in app_src/ con i valori del build (da pyproject.toml).
"""
VERSIONE: str | None = None  # "X.Y.Z" nell'app installata
BUILD: int = 0               # tool.flet.build_number
TAG: str = ""                # tag del rilascio (es. v1.0.0-rc.1), vuoto nei build locali senza tag
COMMIT: str = ""             # commit da cui è stato fatto il build


def descrizione(nativa: bool) -> str:
    """Riga mostrata nelle Impostazioni."""
    if not nativa:
        return "Bonkest — versione web"
    if VERSIONE is None:
        return "Bonkest — sviluppo"
    extra = TAG.removeprefix(f"v{VERSIONE}").lstrip("-")  # es. "rc.1"
    return f"Bonkest {VERSIONE}" + (f" ({extra})" if extra else "")
