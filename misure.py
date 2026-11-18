"""
Misure dei tempi per la Fase 4 (docs/fase4_piano.md, sezione 3). TEMPORANEO: a fine fase si toglie il tab
"Tempi" e restano solo le stampe [MISURE] di supabase_rest.py.

Le misure sono accese solo:
- nei build di prova dell'app installata (tools/prepara_build.py --misure aggiunge il file "misure_attive");
- con la variabile d'ambiente FANTANBA_MISURE=1 (sviluppo, webapp su Render durante le prove).
Spente, nessun modulo dell'app fa nulla di più del solito.

Cosa si misura:
- avvio: tappe in ms dall'inizio di Python (app installata) o dall'apertura della sessione (web);
- operazioni: ogni evento dell'interfaccia a cui un gestore ha dato un nome (etichetta), dall'arrivo
  dell'evento alla fine del gestore e dell'aggiornamento automatico di Flet ("py"), e fino alla risposta
  del client a una chiamata successiva ("client": la patch è arrivata al dispositivo ed è stata applicata).
Nessun dato personale: solo nomi delle operazioni, ms, byte, piattaforma.
"""
import json
import os
import statistics
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import app_paths

FLAG_FILE = "misure_attive"   # Nella cartella del codice (solo build di prova)
MISURE_FILE = "misure.jsonl"  # Nella cartella dati (solo app installata)
AVVII_FILE = "avvii.jsonl"    # Scritto da nativa.py
MAX_RIGHE = 300

T_START: float | None = None  # Primo istante di Python dell'app installata (nativa.py); None = web/sviluppo


_attive: bool | None = None


def attive() -> bool:
    """Misure accese? Deciso una volta per processo (variabile d'ambiente o file del build di prova)."""
    global _attive
    if _attive is None:
        _attive = os.environ.get("FANTANBA_MISURE") == "1" or app_paths.resource(FLAG_FILE).exists()
    return _attive


def imposta_inizio(t: float) -> None:
    global T_START
    T_START = t


class Registro:
    """Misure di una sessione (sul web una per browser, nell'app una sola)."""

    def __init__(self, page):
        self.page = page
        self.t0 = T_START if T_START is not None else time.perf_counter()  # Web: apertura della sessione
        self.tappe: dict[str, Any] = {}
        self.tipo = "avvio"  # avvio (dall'inizio di Python o della sessione), login, aggiornamento
        self.righe: deque[dict] = deque(maxlen=MAX_RIGHE)
        self.etichetta: tuple[str, dict] | None = None  # Nome dell'operazione dell'evento in corso
        self._prefs = None
        self._scritte = 0

    # --- Avvio ---

    def tappa(self, nome: str) -> None:
        """Istante dell'avvio, in ms da t0 (solo la prima volta per nome)."""
        self.tappe.setdefault(nome, round((time.perf_counter() - self.t0) * 1000))

    def riparti(self, tipo: str) -> None:
        """Nuova sequenza di tappe da adesso (login manuale, aggiornamento al ritorno)."""
        self.t0, self.tappe, self.tipo = time.perf_counter(), {}, tipo

    def chiudi_avvio(self, fine: str) -> None:
        """Fine della sequenza (dashboard o login a video): una riga con tutte le tappe."""
        if self.tappe:
            self.aggiungi({"op": "avvio", "tipo": self.tipo, "fine": fine, **self.tappe})
            self.tappe = {}

    # --- Operazioni ---

    def aggiungi(self, riga: dict[str, Any]) -> None:
        riga = {"quando": datetime.now(timezone.utc).isoformat(timespec="seconds"), **riga}
        self.righe.append(riga)
        if os.environ.get("FANTANBA_MISURE") == "1":
            print(f"[MISURE] {json.dumps(riga, ensure_ascii=False)}")
        if app_paths.is_native():
            self._scrivi(riga)

    def _scrivi(self, riga: dict) -> None:
        path = app_paths.data_file(MISURE_FILE)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(riga, ensure_ascii=False) + "\n")
            self._scritte += 1
            if self._scritte % 50 == 0:  # Tiene il file corto
                lines = path.read_text(encoding="utf-8").splitlines()[-MAX_RIGHE:]
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as e:
            print(f"Misura non salvata: {e}")

    async def giro_client(self) -> float | None:
        """ms di un'andata e ritorno col client (dopo la patch appena inviata: i messaggi sono in ordine)."""
        import flet as ft
        try:
            if self._prefs is None:
                self._prefs = ft.SharedPreferences()
            t = time.perf_counter()
            await self._prefs.contains_key("fantanba.misure")
            return (time.perf_counter() - t) * 1000
        except Exception as e:
            print(f"Giro col client non misurato: {e}")
            return None

    # --- Lettura ---

    def storico(self) -> list[dict]:
        """Righe salvate (app installata: anche delle sessioni precedenti) o della sessione."""
        if not app_paths.is_native():
            return list(self.righe)
        return _leggi_jsonl(app_paths.data_file(MISURE_FILE))

    def azzera(self) -> None:
        self.righe.clear()
        if app_paths.is_native():
            for name in (MISURE_FILE, AVVII_FILE):
                try:
                    os.remove(app_paths.data_file(name))
                except OSError:
                    pass


def _leggi_jsonl(path) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        return []


# --- Accesso dal codice dell'app (tutte no-op con le misure spente) ---

def registro(page) -> Registro | None:
    if page is None or not attive():
        return None
    reg = getattr(page, "_fantanba_misure", None)
    if reg is None:
        reg = Registro(page)
        page._fantanba_misure = reg
    return reg


def tappa(page, nome: str) -> None:
    if (reg := registro(page)) is not None:
        reg.tappa(nome)


def nota(page, nome: str, valore: Any) -> None:
    """Dato accanto alle tappe (es. byte scaricati)."""
    if (reg := registro(page)) is not None:
        reg.tappe[nome] = valore


def nota_rete(page, info: dict) -> None:
    """Fine della richiesta di accesso: tappa, ms di rete, byte e (la prima volta) creazione del client httpx."""
    if (reg := registro(page)) is None:
        return
    reg.tappa("rete")
    reg.tappe.update(rete_ms=info.get("ms"), rete_byte=info.get("byte"))
    for key, name in (("client_ms", "client_http_ms"), ("warm_up_ms", "connessione_anticipata_ms")):
        if key in info:
            reg.tappe[name] = info.pop(key)


def riparti(page, tipo: str) -> None:
    if (reg := registro(page)) is not None:
        reg.riparti(tipo)


def chiudi_avvio(page, fine: str) -> None:
    if (reg := registro(page)) is not None:
        reg.chiudi_avvio(fine)


def etichetta(page, nome: str, **extra) -> None:
    """Dà un nome all'operazione dell'evento in corso: verrà misurata (vedi installa_misura_eventi)."""
    if (reg := registro(page)) is not None and reg.etichetta is None:
        reg.etichetta = (nome, extra)


def durata(page, nome: str, ms: float, **extra) -> None:
    """Durata misurata a mano (es. la sola rete del salvataggio)."""
    if (reg := registro(page)) is not None:
        reg.aggiungi({"op": nome, "ms": round(ms), **extra})


def installa_misura_eventi() -> None:
    """
    Avvolge Session.dispatch_event di Flet: comprende il gestore e l'aggiornamento automatico che Flet fa
    dopo ogni evento. Si misurano solo gli eventi a cui il gestore ha dato un'etichetta.
    """
    if not attive():
        return
    from flet.messaging.session import Session
    if getattr(Session.dispatch_event, "_fantanba", False):
        return
    originale = Session.dispatch_event

    async def dispatch_event(self, control_id, event_name, event_data):
        reg = registro(self.page)
        if reg is None:
            return await originale(self, control_id, event_name, event_data)
        reg.etichetta = None
        t = time.perf_counter()
        await originale(self, control_id, event_name, event_data)
        if reg.etichetta is None:
            return
        nome, extra = reg.etichetta
        reg.etichetta = None
        py_ms = (time.perf_counter() - t) * 1000
        giro = await reg.giro_client()
        reg.aggiungi({"op": nome, "py": round(py_ms),
                      "client": round(py_ms + giro) if giro is not None else None, **extra})

    dispatch_event._fantanba = True
    Session.dispatch_event = dispatch_event


# --- Riepilogo per il tab "Tempi" ---

def _mediana(values: list[float]) -> str:
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return "-"
    return f"{statistics.median(values):.0f} ({min(values):.0f}–{max(values):.0f}, n={len(values)})"


def riepilogo(page) -> str:
    """Testo da copiare negli appunti: avvii (mediane) e operazioni (mediane e ultime)."""
    reg = registro(page)
    if reg is None:
        return "Misure spente"
    import flet as ft
    lines = [f"Bonkest — misure del {datetime.now():%d/%m/%Y %H:%M}",
             f"piattaforma {page.platform.value if page.platform else '?'}, web {page.web}, "
             f"nativa {app_paths.is_native()}, flet {ft.__version__}"]

    if app_paths.is_native():
        avvii = _leggi_jsonl(app_paths.data_file(AVVII_FILE))[-5:]
        if avvii:
            lines.append(f"\nAVVII (ultimi {len(avvii)}, ms dall'inizio di Python): mediana (min–max)")
            keys = [k for k in avvii[-1] if k not in ("quando", "piattaforma", "cache_vuota")]
            for k in keys:
                lines.append(f"  {k}: {_mediana([a.get(k) for a in avvii])}")
            lines.append(f"  cache vuota: {[a.get('cache_vuota') for a in avvii]}")

    righe = reg.storico()
    ops: dict[str, list[dict]] = {}
    for r in righe:
        ops.setdefault(r.get("op", "?"), []).append(r)
    avvio = ops.pop("avvio", [])
    if avvio:
        lines.append(f"\nACCESSI (ultimi 5 di {len(avvio)}, ms)")
        for r in avvio[-5:]:
            lines.append("  " + ", ".join(f"{k} {v}" for k, v in r.items() if k not in ("quando", "op")))
    if ops:
        lines.append("\nOPERAZIONI: py = Python + aggiornamento, client = fino al dispositivo; mediana (min–max)")
        for nome, rs in sorted(ops.items()):
            if any("py" in r for r in rs):
                lines.append(f"  {nome}: py {_mediana([r.get('py') for r in rs])}; "
                             f"client {_mediana([r.get('client') for r in rs])}")
            else:
                lines.append(f"  {nome}: {_mediana([r.get('ms') for r in rs])}")
        lines.append("\nULTIME 15")
        for r in righe[-15:]:
            if r.get("op") != "avvio":
                lines.append("  " + ", ".join(f"{k} {v}" for k, v in r.items() if k != "quando"))
    return "\n".join(lines)
