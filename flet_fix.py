"""
Correzioni di prestazioni per Flet 0.82 (Fase 4, docs/fase4_piano.md). Si applicano solo a Flet 0.82.x:
con un aggiornamento di Flet (previsto a fine migrazione) non fanno nulla e questo file si toglie.

1. Patch lente. In flet/controls/object_patch.py (0.82) _compare_lists e _compare_dataclasses chiamano
   logger.debug(f"... {src} {dst}"): la f-string si calcola sempre, anche col debug spento, e fa il repr
   di tutto il sottoalbero dei controlli a ogni lista e a ogni controllo visitato. Un update() del campo
   costava ~450 ms sul PC (~3 s sul telefono) anche senza modifiche. Qui il repr dei controlli diventa
   brevissimo ("<Container>"): Flet non lo usa per altro che per i log. Corretto a monte da Flet 0.83.0.
2. Aggiornamento automatico. Dopo ogni evento Flet chiama da sé update() sulla pagina intera
   (Session.after_event). I nostri gestori aggiornano già i controlli che cambiano: lo si spegne per tutta
   l'app (la stessa cosa che fa ft.context.disable_auto_update(), ma valida per tutte le sessioni).
"""
import flet as ft
from flet.controls.base_control import BaseControl
from flet.controls.context import UpdateBehavior

VERSIONI = ("0.82.",)


def _repr_breve(self) -> str:
    return f"<{type(self).__name__}>"


def _repr_brevi() -> int:
    """repr brevi su tutte le classi di controlli che ne definiscono uno proprio. Restituisce quante."""
    count, stack, seen = 0, [BaseControl], set()
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        if "__repr__" in cls.__dict__ and cls.__dict__["__repr__"] is not _repr_breve:
            cls.__repr__ = _repr_breve
            count += 1
        stack.extend(cls.__subclasses__())
    return count


def applica() -> bool:
    """Applica le correzioni (idempotente). False se la versione di Flet non è quella prevista."""
    if not ft.__version__.startswith(VERSIONI):
        return False
    _repr_brevi()
    # Valore predefinito del contesto di ogni evento: reset_auto_update lo copia nel contesto dell'evento
    UpdateBehavior._auto_update_enabled = False
    return True
