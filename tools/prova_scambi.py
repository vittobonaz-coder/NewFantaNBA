"""
Prova automatica degli scambi (Fase 4, senza rete né database): per ogni formazione in cache esegue operazioni
casuali (scambi dal menu, cambi modulo, Annulla) su un campo modificabile e dopo ognuna controlla che:
- ogni card aggiornata sul posto mostri esattamente ciò che mostrerebbe una card nuova (testi, foto, badge...);
- le voci dei menu di scambio siano quelle giuste (scambi che rispettano il modulo);
- giocatori, ruoli e punteggio totale della squadra seguano le card;
- la patch di Flet (con flet_fix) resti piccola e veloce.

  python tools/prova_scambi.py [--operazioni 200] [--seme 1]
"""
import argparse
import glob
import os
import random
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import builtins  # noqa: E402
_print = builtins.print

import flet as ft  # noqa: E402
import msgpack  # noqa: E402
from flet.controls.base_control import BaseControl  # noqa: E402
from flet.controls.object_patch import ObjectPatch  # noqa: E402
from flet.messaging.protocol import configure_encode_object_for_msgpack  # noqa: E402

import flet_fix  # noqa: E402
import league_cache  # noqa: E402
import ui_court  # noqa: E402
from fanta_obj import LINEUP_ROLES, ROLE_MULTIPLIERS, has_played  # noqa: E402

ENCODER = configure_encode_object_for_msgpack(BaseControl)


def signature(control) -> list:
    """Ciò che si vede di un sottoalbero: tipo e proprietà visibili di ogni controllo, in ordine."""
    out, stack = [], [control]
    while stack:
        c = stack.pop()
        if isinstance(c, (ft.PopupMenuButton, ft.PopupMenuItem)):
            continue  # I menu si controllano a parte
        if isinstance(c, BaseControl) and c.visible is False:
            out.append((type(c).__name__, "nascosto"))  # Le proprietà di un controllo nascosto non si vedono
            continue
        if isinstance(c, BaseControl):
            props = {k: getattr(c, k, None) for k in ("value", "src", "icon", "color", "bgcolor", "visible",
                                                      "width", "height", "size", "weight", "italic", "opacity")}
            out.append((type(c).__name__, repr(sorted((k, str(v)) for k, v in props.items()))))
            for f in c.__dataclass_fields__:
                v = getattr(c, f, None)
                if isinstance(v, BaseControl):
                    stack.append(v)
                elif isinstance(v, list):
                    stack.extend(reversed([x for x in v if isinstance(x, BaseControl)]))
    return out


def expected_menu(court, i: int) -> list[str]:
    roles = LINEUP_ROLES[court.lineup]
    players = [c.player for c in court.cards]
    labels = []
    for j in range(len(players)):
        if j == i:
            continue
        tmp = list(players)
        tmp[i], tmp[j] = tmp[j], tmp[i]
        if all(roles[k] in tmp[k].position.split("/") for k in range(5)):
            labels.append(players[j].name.split()[-1])
    return labels


def check(court) -> list[str]:
    errors = []
    for i, card in enumerate(court.cards):
        fresh = ui_court.PlayerCard(card.player, card.score, card.role_type, card.slot_index,
                                    show_swap=card.show_swap, schedules=card.schedules, injuries=card.injuries,
                                    sub_hints=card.sub_hints)
        if signature(card) != signature(fresh):
            errors.append(f"card {i} ({card.player.name}) diversa da una card nuova")
        got = [it.content.value for it in card.swap_button.items or []]
        if court.editable and got != expected_menu(court, i):
            errors.append(f"menu della card {i}: {got} invece di {expected_menu(court, i)}")
    if [c.player for c in court.cards] != court.team.players:
        errors.append("ordine dei giocatori del Team diverso dalle card")
    total = sum(c.score * ROLE_MULTIPLIERS[c.role_type] for c in court.cards if has_played(c.score))
    if abs(total - court.team.score) > 1e-6:
        errors.append(f"totale {court.team.score} invece di {total}")
    return errors


def patch(control) -> tuple[float, int]:
    t = time.perf_counter()
    p, _, _ = ObjectPatch.from_diff(control, control, control_cls=BaseControl)
    raw = msgpack.packb(["patch", p.to_message()], default=ENCODER)  # Come Flet: diff + codifica
    return (time.perf_counter() - t) * 1000, len(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operazioni", type=int, default=200)
    parser.add_argument("--seme", type=int, default=1)
    args = parser.parse_args()
    rng = random.Random(args.seme)
    if not flet_fix.applica():
        _print("flet_fix non applicato (versione di Flet diversa)")
    ft.Control.update = lambda self, *a, **k: None  # Nessuna pagina: le patch si calcolano a mano
    ui_court.Court.page = property(lambda self: None)  # Nessuna pagina in questo script
    builtins.print = lambda *a, **k: None           # Silenzia i print di caricamento

    files = sorted(glob.glob(str(league_cache.app_paths.data_file("*_gw*_state.json"))))
    deadline = datetime.now(timezone.utc) + timedelta(days=1)
    errors, times, sizes, n_ops, n_teams = [], [], [], {}, 0
    for path in files:
        m = re.match(r"(.+)_gw(\d+)_state\.json$", os.path.basename(path))
        team = league_cache.load_team(m.group(1), int(m.group(2))) if m else None
        if team is None:
            continue
        n_teams += 1
        court = ui_court.Court(team, team.gameweek, deadline, token="prova")
        root = ft.Column([court])  # Genitore, come nella pagina
        # Primo invio (montaggio): la codifica msgpack registra lo stato da cui partono le patch successive
        p, _, _ = ObjectPatch.from_diff(None, root, control_cls=BaseControl)
        msgpack.packb(["patch", p.to_message()], default=ENCODER)
        for _ in range(args.operazioni):
            r = rng.random()
            if r < 0.75:
                options = [(i, it) for i, c in enumerate(court.cards) for it in (c.swap_button.items or [])]
                if not options:
                    continue
                _, item = rng.choice(options)
                item.on_click(None)
                op = "scambio"
            elif r < 0.95 and len(court.available_lineups) > 1:
                court.lineup_dd.value = rng.choice([x for x in court.available_lineups if x != court.lineup])
                court.change_lineup(None)
                op = "modulo"
            else:
                court.restore_saved_state()
                op = "annulla"
            ms, size = patch(court)
            n_ops[op] = n_ops.get(op, 0) + 1
            times.append((op, ms))
            sizes.append((op, size))
            errors += [f"{os.path.basename(path)} dopo {op}: {e}" for e in check(court)]
            if len(errors) > 20:
                break

    builtins.print = _print
    print(f"{n_teams} formazioni, operazioni: {n_ops}")
    for op in n_ops:
        t = [ms for o, ms in times if o == op]
        b = [s for o, s in sizes if o == op]
        print(f"  {op}: patch {statistics.median(t):.1f} ms (max {max(t):.1f}), "
              f"{statistics.median(b):.0f} byte (max {max(b)})")
    if errors:
        print("ERRORI:\n  " + "\n  ".join(errors[:20]))
        return 1
    print("Nessun errore")
    return 0


if __name__ == "__main__":
    sys.exit(main())
