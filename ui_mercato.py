"""
Schermata Mercato (sotto-tab di Campionato): scadenza della finestra, nuova offerta, le mie offerte in ordine
di preferenza con Annulla, esiti dell'ultima finestra. I dati arrivano da mercato.MarketService (RPC), solo
all'apertura della schermata e dopo ogni operazione: niente dati del mercato nella cache locale, così le
offerte restano solo sul database.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Callable

import flet as ft

import supabase_rest as rest
from fanta_obj import Player
from mercato import MarketOffer, MarketService, MarketState, time_left_text
from time_manager import ITA_TZ

WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
STATUS_TEXT = {"eseguita": ("Eseguito", "green_400"), "non_eseguita": ("Non eseguito", "grey_500")}


def _when(moment: datetime) -> str:
    """'martedì 01/12 alle 19:00' nell'ora italiana."""
    local = moment.astimezone(ITA_TZ)
    return f"{WEEKDAYS[local.weekday()]} {local:%d/%m} alle {local:%H:%M}"


def _title(text: str) -> ft.Text:
    return ft.Text(text, size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE)


class MarketView(ft.Stack):
    """
    Vista del mercato. roster_loader restituisce i giocatori della mia squadra (per scegliere chi cedere);
    service è il MarketService della sessione. load() va chiamato alla prima apertura (e da "Aggiorna").
    """

    def __init__(self, service: MarketService | None, roster_loader: Callable[[], list[Player]]):
        super().__init__(expand=True)
        self.service = service            # None: sessione senza token (avvio senza rete)
        self.roster_loader = roster_loader
        self.state: MarketState | None = None
        self.loaded = False

        self.body = ft.ListView(padding=15, spacing=10, left=0, top=0, right=0, bottom=0)
        self.loading = ft.Container(
            content=ft.ProgressRing(color="amber"), alignment=ft.alignment.Alignment.CENTER,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK), left=0, top=0, right=0, bottom=0,
            visible=False, on_click=lambda e: None,  # Assorbe i tocchi durante le richieste
        )
        self.out_dropdown = ft.Dropdown(label="Giocatore da cedere", expand=True, enable_search=False,
                                        filled=True, fill_color="#1a1a1a")
        self.in_field = ft.TextField(label="Giocatore da prendere", hint_text="Nome copiato dall'Excel",
                                     bgcolor="#1a1a1a", expand=True, on_submit=self.add_offer)
        self.body.controls = [ft.Text("Caricamento mercato...", color="grey")]
        self.controls = [self.body, self.loading]

    # --- Dati ---

    async def load(self, force: bool = False) -> None:
        """Scarica lo stato del mercato e ridisegna. Errori: messaggio nella vista, si riprova con Aggiorna."""
        if self.loaded and not force:
            return
        if self.service is None:
            self._render_message("Serve la connessione per il mercato: riapri l'app quando sei online")
            return
        await self._busy(True)
        try:
            self.state = await asyncio.to_thread(self.service.state)
            self.loaded = True
            self._render()
        except Exception as err:
            print(f"Mercato non caricato: {err}")
            self._render_message(self._error_text(err, "Impossibile caricare il mercato"))
        finally:
            await self._busy(False)

    async def add_offer(self, e=None) -> None:
        if self.out_dropdown.value is None:
            self._snack("Scegli il giocatore da cedere", "red")
            return
        out_id, in_name = int(self.out_dropdown.value), self.in_field.value or ""
        if await self._call(lambda: self.service.offer(out_id, in_name), "Offerta aggiunta in fondo alla lista"):
            self.in_field.value = ""
            await self.load(force=True)

    async def ask_cancel(self, e) -> None:
        offer: MarketOffer = e.control.data

        async def confirm(_):
            self.page.pop_dialog()
            if await self._call(lambda: self.service.cancel(offer.id), "Offerta annullata"):
                await self.load(force=True)

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Annullare l'offerta?"),
            content=ft.Text(f"Cedi {offer.out_name}, prendi {offer.in_name}.\n"
                            "Se la rifai, finisce in fondo alla lista (ultima preferenza)."),
            actions=[ft.TextButton("No", on_click=lambda _: self.page.pop_dialog()),
                     ft.TextButton("Annulla offerta", on_click=confirm)],
        ))

    async def refresh(self, e=None) -> None:
        await self.load(force=True)

    async def _call(self, action, success: str) -> bool:
        """Esegue action in un thread con il velo; True se riuscita, altrimenti mostra l'errore."""
        await self._busy(True)
        try:
            await asyncio.to_thread(action)
        except Exception as err:
            if not isinstance(err, ValueError):
                print(f"Operazione di mercato non riuscita: {err}")
            self._snack(self._error_text(err, "Operazione non riuscita, riprova"), "red")
            return False
        finally:
            await self._busy(False)
        self._snack(success, "green")
        return True

    @staticmethod
    def _error_text(err: Exception, fallback: str) -> str:
        """Errori previsti (RpcError è un ValueError) col loro messaggio; rete assente; tutto il resto generico."""
        if isinstance(err, ValueError):
            return str(err)
        if rest.is_network_error(err):
            return "Serve la connessione: riprova"
        return fallback

    # --- Interfaccia ---

    async def _busy(self, on: bool) -> None:
        self.loading.visible = on
        if self.page:
            self.loading.update()
            if on:
                await asyncio.sleep(0.05)  # Lascia al client il tempo di disegnare il velo

    def _snack(self, text: str, color: str) -> None:
        self.page.show_dialog(ft.SnackBar(ft.Text(text), bgcolor=color))

    def _refresh_button(self) -> ft.Control:
        return ft.Row([ft.TextButton("Aggiorna", icon=ft.Icons.REFRESH, on_click=self.refresh)],
                      alignment=ft.MainAxisAlignment.END)

    def _render_message(self, text: str) -> None:
        self.body.controls = [ft.Text(text, color="red"), self._refresh_button()]
        self._update()

    def _update(self) -> None:
        if self.page:
            self.update()

    def _render(self) -> None:
        state = self.state
        controls: list[ft.Control] = [self._header(state)]
        if state.window is not None:
            controls += [self._new_offer(state), self._my_offers(state)]
        if state.last is not None:
            controls.append(self._last_window(state))
        controls.append(self._refresh_button())
        self.body.controls = controls
        self._update()

    def _header(self, state: MarketState) -> ft.Control:
        if state.closing:
            lines = [_title("Mercato in chiusura"),
                     ft.Text("Gli scambi si stanno eseguendo: riprova tra qualche minuto.", color="amber")]
        elif state.window is None:
            lines = [_title("Mercato chiuso"), ft.Text("Non ci sono altre finestre di mercato.", color="grey")]
        else:
            w = state.window
            left = time_left_text(w.closes_at, state.now or datetime.now(ITA_TZ))
            lines = [
                _title(f"Mercato aperto — finestra giornata {w.gameweek}"),
                ft.Text(f"Chiude {_when(w.closes_at)} (tra {left})", weight=ft.FontWeight.BOLD),
                ft.Text(f"Il nuovo giocatore gioca dalla giornata {w.first_gameweek}.", size=12, color="grey"),
                ft.Text("Uno scambio per finestra: cedi un tuo giocatore e prendi un free agent. Metti le offerte "
                        "in ordine di preferenza: alla chiusura sceglie prima chi è più in basso in classifica e "
                        "ottiene la prima offerta ancora possibile. Le offerte sono segrete fino alla chiusura.",
                        size=12, color="grey"),
            ]
        return ft.Column(lines, spacing=4)

    def _new_offer(self, state: MarketState) -> ft.Control:
        roster = sorted(self.roster_loader() or [], key=lambda p: p.name)
        self.out_dropdown.options = [ft.DropdownOption(key=str(p.id), text=f"{p.name} ({p.position})")
                                     for p in roster]
        if self.out_dropdown.value not in {o.key for o in self.out_dropdown.options}:
            self.out_dropdown.value = None
        count = f"Offerte: {len(state.offers)} su {state.max_offers}"
        if not state.can_offer:
            return ft.Column([_title("Nuova offerta"),
                              ft.Text(f"{count}: annullane una per farne un'altra.", color="amber")])
        return ft.Column([
            _title("Nuova offerta"),
            ft.Row([self.out_dropdown]),
            ft.Row([self.in_field]),
            ft.Row([ft.Text(count, size=12, color="grey", expand=True),
                    ft.FilledButton("Aggiungi offerta", icon=ft.Icons.ADD, on_click=self.add_offer)]),
        ], spacing=8)

    def _my_offers(self, state: MarketState) -> ft.Control:
        if not state.offers:
            rows: list[ft.Control] = [ft.Text("Nessuna offerta.", color="grey")]
        else:
            rows = [ft.Container(
                bgcolor=ft.Colors.GREY_900, border_radius=8, padding=ft.Padding.only(left=10, right=2),
                content=ft.Row([
                    ft.Text(f"{i}.", weight=ft.FontWeight.BOLD, color="amber", width=24),
                    ft.Column([
                        ft.Text(f"Prendi {o.in_name}", weight=ft.FontWeight.BOLD),
                        # Ruolo coi codici dell'app (G, A, C) anche per i giocatori caricati in formato NBA
                        ft.Text(f"{o.in_team} · {Player(position=o.in_position).position} — cedi {o.out_name}",
                                size=12, color="grey"),
                    ], spacing=0, expand=True),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Annulla offerta", data=o,
                                  on_click=self.ask_cancel),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ) for i, o in enumerate(state.offers, start=1)]
        return ft.Column([_title("Le mie offerte (in ordine di preferenza)"), *rows], spacing=6)

    def _last_window(self, state: MarketState) -> ft.Control:
        last = state.last
        mine: list[ft.Control] = []
        for o in last.my_offers:
            label, color = STATUS_TEXT.get(o.status, (o.status, "grey"))
            mine.append(ft.Text(f"{label}: cedi {o.out_name}, prendi {o.in_name}"
                                + (f" — {o.note}" if o.note else ""), size=12, color=color))
        trades = [ft.Text(f"{t.team}: esce {t.out_name}, entra {t.in_name}", size=12) for t in last.trades]
        return ft.Column([
            ft.Divider(color="grey_800"),
            _title(f"Esiti mercato giornata {last.gameweek}"),
            *(mine or [ft.Text("Non avevi offerte.", size=12, color="grey")]),
            ft.Text("Scambi eseguiti", weight=ft.FontWeight.BOLD),
            *(trades or [ft.Text("Nessuno scambio.", size=12, color="grey")]),
        ], spacing=4)
