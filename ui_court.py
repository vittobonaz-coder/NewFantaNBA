import flet as ft
import os
import json
import asyncio
from datetime import datetime
from fanta_obj import Player, Team, has_played, ROLE_MULTIPLIERS
from time_manager import TimeManager, ITA_TZ


ROLE_CONFIGS = {
    "STARTER": {"width": 100, "height": 130, "avatar": 55, "font": 15, "opacity": 1.0, "mult": ROLE_MULTIPLIERS["STARTER"], "button_size": 20, "button_left": -5, "button_top": -5},
    "SIXTH": {"width": 100, "height": 130, "avatar": 55, "font": 15, "opacity": 1.0, "mult": ROLE_MULTIPLIERS["SIXTH"], "button_size": 20, "button_left": -5, "button_top": -5},
    "BENCH": {"width": 80, "height": 110, "avatar": 40, "font": 13, "opacity": 1.0, "mult": ROLE_MULTIPLIERS["BENCH"], "button_size": 15, "button_left": -8, "button_top": -8},
    "RESERVE": {"width": 80, "height": 110, "avatar": 40, "font": 13, "opacity": 0.6, "mult": ROLE_MULTIPLIERS["RESERVE"], "button_size": 15, "button_left": -8, "button_top": -8},
}

# Posizioni richieste dagli slot titolari (0-4) per ogni modulo
LINEUP_ROLES = {
    "2-2-1": ['C', 'A', 'A', 'G', 'G'],
    "2-1-2": ['C', 'C', 'A', 'G', 'G'],
    "1-2-2": ['C', 'C', 'A', 'A', 'G'],
    "3-1-1": ['C', 'A', 'G', 'G', 'G'],
    "1-3-1": ['C', 'A', 'A', 'A', 'G'],
}

def find_starter_assignment(roles: list[str], players: list[Player]) -> list[int] | None:
    """
    Cerca giocatori distinti che coprano le posizioni richieste dagli slot titolari.
    Restituisce, per ogni slot, l'indice del giocatore scelto; None se il modulo è impossibile.
    Per fare meno scambi possibili preferisce chi è già nello slot, poi gli altri titolari,
    poi sesto uomo, panchina e riserve.
    """
    n_starters = len(roles)

    def candidates(k):
        return [k] + [i for i in range(n_starters) if i != k] + list(range(n_starters, len(players)))

    def assign(k, used):
        if k == n_starters:
            return []
        for idx in candidates(k):
            if idx not in used and roles[k] in players[idx].position.split('/'):
                rest = assign(k + 1, used | {idx})
                if rest is not None:
                    return [idx] + rest
        return None

    return assign(0, frozenset())

def infer_lineup(players: list[Player], preferred: str) -> str | None:
    """
    Restituisce il modulo che i primi 5 giocatori (titolari) rispettano già, senza scambi.
    Se ne vanno bene più di uno (giocatori con doppia posizione) preferisce preferred.
    """
    for lineup in [preferred] + [l for l in LINEUP_ROLES if l != preferred]:
        roles = LINEUP_ROLES.get(lineup)
        if roles and len(players) >= len(roles) and all(r in p.position.split('/') for r, p in zip(roles, players)):
            return lineup
    return None

class PlayerCard(ft.Container):
    """Classe per le cards dei giocatori"""

    def __init__(self, player: Player, score: float | None, role_type: str, slot_index: int, show_swap: bool = True):
        super().__init__()
        self.player = player
        self.score = score
        self.role_type = role_type
        self.slot_index = slot_index
        self.show_swap = show_swap  # False nelle formazioni in sola lettura (squadre avversarie)
        # Swap Button
        self.swap_button = ft.PopupMenuButton(
            icon=ft.Icons.SWAP_VERT_CIRCLE, icon_color="white", bgcolor="black"
        )
        
        # Setup UI
        self.setup_ui()

    def setup_ui(self):
        conf = ROLE_CONFIGS.get(self.role_type, ROLE_CONFIGS["STARTER"])
        self.configure_container(conf)
        self.content = self.build_content(conf)

    def configure_container(self, conf):
        self.border_radius = 12
        self.bgcolor = ft.Colors.GREY_900
        self.border = ft.Border.all(2, ft.Colors.GREY)
        self.padding = 5
        self.width = conf["width"]
        self.height = conf["height"]
        self.opacity = conf["opacity"]

    def build_content(self, conf):
        name_parts = self.player.name.split()
        first_initial = name_parts[0][0]
        surname = ' '.join(name_parts[1:])
        # Le riserve non contribuiscono al totale (mult 0), ma mostriamo il punteggio
        # grezzo tra parentesi per aiutare l'allenatore a decidere se schierarle
        is_reserve = self.role_type == "RESERVE"
        if not has_played(self.score):
            score_text = "-"
        elif is_reserve:
            score_text = f"({self.score:.1f})"
        else:
            score_text = f"{self.score * conf['mult']:.1f}"
        score_control = ft.Text(
            score_text,
            size=conf["font"],
            weight="normal" if is_reserve else "bold",
            italic=is_reserve,
            color="grey" if is_reserve else None,
        )

        btn_container = ft.Container(
            content=self.swap_button,
            left=conf["button_left"], top=conf["button_top"]
        )

        return ft.Stack(
            alignment=ft.alignment.Alignment.TOP_CENTER,
            controls=[
                ft.Column(
                    spacing=0,
                    horizontal_alignment="center",
                    controls=[
                        ft.Image(src=self.player.get_avatar_img(), width=conf["avatar"], height=conf["avatar"]),
                        ft.Text(f"{first_initial}. {surname}", size=conf["font"], weight="bold", no_wrap=True),
                        ft.Text(f"{self.player.team_abbreviation} | {self.player.position}", size=9, color="grey"),
                        score_control,
                    ]
                ),
            ] + ([btn_container] if self.show_swap else [])
        )
    
    def update_data(self, new_player: Player, new_score: float | None):
        """Aggiorna i dati della card e rinfresca solo questa"""
        self.player = new_player
        self.score = new_score
        self.setup_ui()

class LoadingOverlay(ft.Container):
    """Velo semitrasparente con spinner sopra la schermata: la formazione resta visibile sotto."""
    PAINT_DELAY = 0.05  # Secondi lasciati al client per disegnare il velo prima del lavoro pesante

    def __init__(self):
        super().__init__(
            content=ft.ProgressRing(color="amber"),
            alignment=ft.alignment.Alignment.CENTER,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            left=0, top=0, right=0, bottom=0,  # Copre tutto lo Stack
            visible=False,
            on_click=lambda e: None,  # Assorbe i tocchi: niente doppi click durante il caricamento
        )

    async def show(self):
        """
        Mostra il velo e lascia libero il loop per un attimo: i gestori di Flet girano nel suo
        loop asyncio, quindi senza questa pausa il velo arriverebbe al client insieme al resto.
        """
        self.visible = True
        self.update()
        await asyncio.sleep(self.PAINT_DELAY)

    def hide(self):
        self.visible = False
        self.update()


class Court(ft.Column):
    def __init__(self, team_instance: Team, gameweek: int, edit_deadline: datetime | None = None, read_only: bool = False):
        super().__init__()
        self.horizontal_alignment = "center"
        self.scroll = ft.ScrollMode.AUTO
        self.expand = True
        self.spacing = 0
        self.team = team_instance
        self.gameweek = gameweek            # Giornata mostrata, a cui si applicano anche i cambi
        self.edit_deadline = edit_deadline  # Chiusura dei cambi (UTC); None = cambi chiusi
        self.read_only = read_only          # Formazione di un'altra squadra: niente modulo né scambi
        self.editable = not read_only and edit_deadline is not None and TimeManager.now() < edit_deadline
        self.loading: LoadingOverlay | None = None  # Velo di caricamento, assegnato da TeamView
        self.lineup = self.team.lineup if self.team.lineup in LINEUP_ROLES else "2-2-1"

        # Testo UI legato al campo 'score' del Team
        self.total_score_text = ft.Text(
            f"TOTAL SCORE: {self.team.score:.1f}",
            size=20, weight="bold", color="amber"
        )
        self.status_text = ft.Text("", size=12, color="grey")

        # CARDS
        self.cards = []
        # ordered_players = self.team.get_ordered_roster()
        ordered_players = self.team.players
        for i, p in enumerate(ordered_players):
            card = PlayerCard(
                player=p,
                score=p.score,
                role_type=self.team.roles_map[p.id],
                slot_index=i,
                show_swap=not read_only
            )
            self.cards.append(card)

        # MODULI DISPONIBILI: solo quelli che la rosa riesce a schierare
        # (calcolati una volta sola: gli scambi non cambiano i giocatori della rosa)
        self.available_lineups = [
            l for l in LINEUP_ROLES
            if find_starter_assignment(LINEUP_ROLES[l], self.team.players) is not None
        ] or [self.lineup]  # nessun modulo possibile: lasciamo quello salvato

        # MODULO INIZIALE: quello che i titolari rispettano già. Il modulo è salvato solo in locale
        # (su Render il file può mancare), quindi lo si ricava dai giocatori. I titolari vengono
        # riorganizzati solo se nessun modulo combacia e i cambi sono aperti: a formazione bloccata
        # si mostra esattamente quella su Supabase, con cui il cron calcola il punteggio.
        inferred = infer_lineup(self.team.players, self.lineup)
        if inferred:
            self.lineup = inferred
        elif self.editable:
            if self.lineup not in self.available_lineups:
                self.lineup = self.available_lineups[0]
            self.auto_fix_starters(self.lineup)

        # Popoliamo lo stato iniziale dopo aver creato le cards
        self._capture_current_state()

        # DROPDOWN FORMAZIONE
        self.lineup_dd = ft.Dropdown(
            width=110, height=50, text_size=12, value=self.lineup,
            options=[ft.dropdown.Option(x) for x in self.available_lineups],
            filled=True, fill_color="#1a1a1a", border_color="grey",
            on_select=self.change_lineup
        )
        
        self.starters_container = ft.Container(width=320, height=450)

        # 2. BOTTONI SALVA / ANNULLA
        self.btn_save = ft.ElevatedButton(
            "Salva", icon=ft.Icons.SAVE,
            bgcolor=ft.Colors.GREEN_700, color="white",
            on_click=self.handle_save
        )
        self.btn_cancel = ft.ElevatedButton(
            "Annulla", icon=ft.Icons.UNDO,
            bgcolor=ft.Colors.RED_700, color="white",
            on_click=self.handle_cancel
        )
        self.controls_bar = ft.Row(
            [self.btn_cancel, self.btn_save], 
            alignment=ft.MainAxisAlignment.CENTER,
            visible=False # Nascosti all'inizio
        )

        self.apply_lock()
        self.setup_static_ui()
        self.update_starters_layout()
        self.refresh_menus()
        self.refresh_ui_and_data()


    def _capture_current_state(self):
        """Memorizza la posizione attuale dei giocatori e la formazione."""
        self.initial_state = [(c.player, c.score) for c in self.cards]
        self.initial_lineup = self.lineup

    def toggle_buttons(self, visible: bool):
        """Mostra o nasconde la barra dei comandi."""
        self.controls_bar.visible = visible
        self.update()

    def status_message(self) -> str:
        if self.read_only:
            return f"Giornata {self.gameweek}"
        if self.editable:
            deadline = self.edit_deadline.astimezone(ITA_TZ)
            return f"Giornata {self.gameweek} · cambi aperti fino al {deadline:%d/%m} alle {deadline:%H:%M}"
        return f"Giornata {self.gameweek} · formazione bloccata"

    def apply_lock(self):
        """Disattiva dropdown e bottoni di scambio quando i cambi sono chiusi."""
        self.lineup_dd.disabled = not self.editable
        for card in self.cards:
            card.swap_button.disabled = not self.editable
        if not self.editable:
            self.controls_bar.visible = False
        self.status_text.value = self.status_message()

    def show_message(self, text: str, color: str):
        sb = ft.SnackBar(ft.Text(text), bgcolor=color)
        self.page.overlay.append(sb) # Metodo più robusto per Flet
        sb.open = True
        self.page.update()

    async def handle_save(self, e):
        """Salva su Supabase (dalla giornata self.gameweek in poi) e in locale, poi nasconde i bottoni."""
        # I cambi potrebbero essersi chiusi mentre l'app era aperta
        if TimeManager.now() >= self.edit_deadline:
            self.restore_saved_state()
            self.editable = False
            self.apply_lock()
            self.update()
            self.show_message("Cambi chiusi: formazione non salvata", "red")
            return

        # Aggiorniamo i dati nel team (incluso l'ordine dei giocatori)
        self.refresh_ui_and_data()

        # Solo le chiamate di rete vanno nel thread: gli update della UI restano nel loop di Flet
        if self.loading:
            await self.loading.show()
        try:
            saved = await asyncio.to_thread(self._push_lineup)
        finally:
            if self.loading:
                self.loading.hide()
        if not saved:
            self.show_message("Errore nel salvataggio della formazione, riprova", "red")
            return

        self.team.save_to_json()
        # Il nuovo stato corrente diventa il punto di ripristino per futuri cambi
        self._capture_current_state()
        self.toggle_buttons(False)
        self.show_message(f"Formazione di {self.team.name} salvata!", "green")

    def _push_lineup(self) -> bool:
        """Scrive rosa e formazione su Supabase (eseguito in un thread: niente UI qui)."""
        from supabase_manager import SupabaseSync

        sync = SupabaseSync()
        try:
            team_id = sync.get_team_id_by_name(self.team.name)
            sync.update_roster_positions(self.team, team_id)
            # Tutti i giocatori, dalla giornata modificabile in poi (mai quella in corso):
            # riallinea anche eventuali righe disallineate delle giornate future
            return sync.update_lineup_slots(self.team, self.gameweek)
        except Exception as ex:
            print(f"Errore durante il salvataggio della formazione: {ex}")
            return False

    async def handle_cancel(self, e):
        """Ripristina l'ultimo salvataggio mostrando il velo di caricamento."""
        if self.loading:
            await self.loading.show()
        try:
            self.restore_saved_state()
        finally:
            if self.loading:
                self.loading.hide()

    def restore_saved_state(self):
        """Ripristina i dati all'ultimo salvataggio."""
        # Ripristina Giocatori nelle card
        for i, (old_p, old_s) in enumerate(self.initial_state):
            self.cards[i].update_data(old_p, old_s)
        
        # Ripristina Formazione
        self.lineup = self.initial_lineup
        self.lineup_dd.value = self.lineup
        
        self.update_starters_layout()
        self.refresh_ui_and_data()
        self.refresh_menus()
        self.toggle_buttons(False)
        self.update()
    
    def refresh_ui_and_data(self):
        """Sincronizza i ruoli nel Team in base alla posizione delle cards e ricalcola."""
        new_ordered_players = []
        # 1. Aggiorna la roles_map nel Team in base a dove si trovano i giocatori ora
        for card in self.cards:
            self.team.roles_map[card.player.id] = card.role_type
            new_ordered_players.append(card.player)

        # Cruciale: aggiorniamo la lista players del Team con l'ordine delle cards
        self.team.players = new_ordered_players
        self.team.lineup = self.lineup # Salviamo il modulo nel team
        
        # 2. Chiedi al Team di ricalcolare il suo punteggio interno
        new_total = self.team.calculate_total_score(ROLE_CONFIGS)
        
        # 3. Aggiorna la UI
        self.total_score_text.value = f"TOTAL SCORE: {new_total:.1f}"
    
    def change_lineup(self, e):
        """Cambio modulo"""
        new_val = self.lineup_dd.value
        if new_val == self.lineup:
            return
        # 1. Correggi i giocatori incompatibili (sui dati)
        self.auto_fix_starters(new_val)
        # 2. Aggiorna la variabile di stato della formazione
        self.lineup = new_val
        self.toggle_buttons(True)
        # 3. Sposta fisicamente le righe dell'interfaccia
        self.update_starters_layout()
        # 4. Ricalcola tutti i menu a tendina per gli scambi futuri
        self.refresh_menus()
        # 5. Manda TUTTO a schermo in un colpo solo
        self.refresh_ui_and_data()
        self.update()
    
    def setup_static_ui(self):
        self.controls = [
            # Punteggio Squadra
            self.total_score_text,
            # Giornata e stato dei cambi
            self.status_text,
            # Dropdown formazione (nascosto in sola lettura)
            ft.Container(
                content=ft.Row([self.lineup_dd], alignment=ft.MainAxisAlignment.START),
                width=330, height=80,
                visible=not self.read_only
            ),
            # Titolari
            self.starters_container,

            self.controls_bar, # Barra Salva/Annulla

            # Panchina
            ft.Container(
                content= ft.Column(
                    controls=[
                        ft.Row(controls=[self.cards[5], self.cards[6], self.cards[7]], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row(controls=[ft.Container(width=110, height=110), self.cards[8], self.cards[9]], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    ]
                ),
                width=290, height=300
            ),
            # Riserve
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(controls=[self.cards[10], self.cards[11], self.cards[12]], alignment="center"),
                        ft.Row(controls=[self.cards[13], self.cards[14]], alignment="center"),
                    ]
                )
            )
        ]

    def update_starters_layout(self):
        """Cambia SOLO il contenuto del rettangolo dei titolari"""
        # Il modulo è Guardie-Ali-Centri, le righe vanno dall'alto: Centri, Ali, Guardie
        row_sizes = [int(n) for n in reversed(self.lineup.split('-'))]
        rows = []
        start = 0
        for size in row_sizes:
            row_cards = self.cards[start:start + size]
            start += size
            if size == 1:
                rows.append(ft.Row(controls=row_cards, alignment=ft.MainAxisAlignment.CENTER))
            elif size == 3:
                rows.append(ft.Row(controls=row_cards, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, spacing=8))
            else:
                rows.append(ft.Row(controls=row_cards, alignment=ft.MainAxisAlignment.SPACE_EVENLY))

        self.starters_container.content = ft.Column(controls=rows)
    
    def get_starter_roles(self, lineup_str):
        """Restituisce solo la mappa dei ruoli per i primi 5 slot (Titolari)"""
        return LINEUP_ROLES[lineup_str]

    def auto_fix_starters(self, new_lineup):
        """
        Riorganizza i titolari perché rispettino il nuovo modulo, cercando
        i sostituti tra sesto uomo, panchina e riserve con il minor numero di scambi.
        """
        roles = self.get_starter_roles(new_lineup)
        current = [(c.player, c.score) for c in self.cards]
        players = [p for p, _ in current]

        assignment = find_starter_assignment(roles, players)
        if assignment is None:
            return  # Modulo impossibile (non dovrebbe succedere: il dropdown li esclude)

        new_state = list(current)
        # I titolari scelti vanno negli slot 0-4
        for slot, src in enumerate(assignment):
            new_state[slot] = current[src]
        # I titolari esclusi prendono i posti lasciati liberi in panchina/riserve
        displaced = [i for i in range(len(roles)) if i not in assignment]
        vacated = [i for i in assignment if i >= len(roles)]
        for slot, src in zip(vacated, displaced):
            new_state[slot] = current[src]

        for card, (p, s) in zip(self.cards, new_state):
            if card.player is not p:
                card.update_data(p, s)

    def handle_swap(self, origin_idx: int, target_idx: int):
        """Logica di scambio"""
        origin_card = self.cards[origin_idx]
        target_card = self.cards[target_idx]
        old_player, old_score = origin_card.player, origin_card.score

        old_player = origin_card.player
        old_score = origin_card.score

        origin_card.update_data(target_card.player, target_card.score)
        target_card.update_data(old_player, old_score)

        self.toggle_buttons(True)
        # Ricalcola le opzioni valide per tutti visto che il campo è cambiato
        self.refresh_ui_and_data()
        self.refresh_menus()
        self.update()
    
    def refresh_menus(self):
        """
        Rigenera i menu di scambio applicando solo il vincolo di slot
        dei titolari (le posizioni richieste dal modulo per gli slot 0-4).
        """
        if not self.editable:
            for card in self.cards:
                card.swap_button.items = []
            return

        starter_roles = self.get_starter_roles(self.lineup)

        for i, card in enumerate(self.cards):
            valid_items = []

            for j, other_card in enumerate(self.cards):
                if i == j: continue

                # Simuliamo lo scambio
                temp_players = [c.player for c in self.cards]
                temp_players[i], temp_players[j] = temp_players[j], temp_players[i]

                # Vincolo di Posizione Individuale (Solo per i Titolari 0-4)
                if any(starter_roles[idx] not in temp_players[idx].position.split('/') for idx in range(5)):
                    continue

                # Se passa il test, lo scambio è legale
                valid_items.append(
                    ft.PopupMenuItem(
                        content=ft.Text(other_card.player.name.split()[-1]),
                        on_click=lambda e, f=i, t=j: self.handle_swap(f, t)
                    )
                )
            card.swap_button.items = valid_items


WEEKDAYS_IT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]

class RoundTabs(ft.Tabs):
    """
    Una tab per giornata (etichetta = numero); build_round costruisce il contenuto di ciascuna.
    Con lazy=True una giornata si costruisce solo alla prima apertura: il calendario NBA completo
    sono migliaia di controlli, troppi da spedire al browser tutti insieme al login.
    In quel caso le giornate non stanno in un TabBarView (il client non ridisegna le pagine già
    create) ma in un unico contenitore, a cui si cambia il contenuto quando cambia la giornata,
    con il velo di caricamento sopra finché la nuova giornata non è stata spedita al browser.
    """
    def __init__(self, rounds: list[dict], build_round, lazy: bool = False):
        super().__init__(content=None, length=len(rounds))
        self.selected_index = 0
        self.expand = True
        self.rounds = rounds
        self.build_round = build_round
        self.lazy = lazy
        self.current = 0  # Giornata selezionata
        self.built_views = {}  # Giornate già costruite (solo lazy), per indice

        if lazy:
            self.on_change = self.handle_change
            self.loading = LoadingOverlay()
            self.body = ft.Container(left=0, top=0, right=0, bottom=0)  # Riempie lo Stack
            body_area = ft.Stack([self.body, self.loading], expand=True)
        else:
            body_area = self.body = ft.TabBarView(expand=True, controls=[build_round(r) for r in rounds])

        self.content = ft.Column(
            expand=True,
            controls=[
                ft.TabBar(
                    label_text_style=ft.TextStyle(size=20),
                    unselected_label_text_style=ft.TextStyle(size=17),
                    label_color=ft.Colors.ORANGE,           # Colore testo selezionato
                    unselected_label_color=ft.Colors.GREY,  # Colore testo non selezionato
                    indicator_color=ft.Colors.ORANGE,       # Colore della linea sotto la tab
                    tabs=[ft.Tab(label=f"{r['round_number']}") for r in rounds]
                ),
                body_area,
            ],
        )

    async def show_current(self):
        """
        Mostra la giornata selezionata, costruendola se serve. Il velo resta sopra la giornata
        precedente finché la nuova non è stata spedita al browser.
        """
        if not self.lazy or not self.rounds:
            return
        view = self.built_views.get(self.current)
        if view is not None and self.body.content is view:
            return  # Già visibile: niente velo
        await self.loading.show()
        try:
            if view is None:
                view = self.built_views[self.current] = self.build_round(self.rounds[self.current])
            self.body.content = view
            self.body.update()
        finally:
            self.loading.hide()

    async def handle_change(self, e):
        self.current = int(e.data)  # e.data = indice della tab selezionata
        await self.show_current()


class CalendarView(ft.Tabs):
    """Calendario: scontri diretti della lega e partite NBA, divisi per giornata."""
    def __init__(self):
        super().__init__(content=None, length=2)
        self.expand = True # Permette alla dashboard di occupare tutto lo spazio
        self.selected_index = 0
        self.animation_duration = 300

        calendar_data = self.load_calendar()
        if calendar_data is None:
            league_view = nba_view = ft.Text("Calendario non trovato.")
        else:
            league_view = RoundTabs(calendar_data, self.build_league_round)
            # Le giornate NBA si costruiscono solo quando si aprono (vedi RoundTabs)
            nba_view = self.nba_tabs = RoundTabs(calendar_data, self.build_nba_round, lazy=True)
            self.on_change = self.handle_change

        self.content = ft.Column(
            expand=True,
            controls=[
                ft.TabBar(
                    label_color=ft.Colors.ORANGE,
                    unselected_label_color=ft.Colors.GREY,
                    indicator_color=ft.Colors.ORANGE,
                    tabs=[ft.Tab(label="Calendario Lega"), ft.Tab(label="Calendario NBA")]
                ),
                ft.TabBarView(expand=True, controls=[league_view, nba_view]),
            ],
        )

    async def handle_change(self, e):
        """All'apertura del Calendario NBA mostra (e alla prima volta costruisce) la giornata selezionata."""
        if int(e.data) == 1:
            await self.nba_tabs.show_current()

    def load_calendar(self) -> list[dict] | None:
        cal_path = os.path.join("data", "calendar.json")
        if not os.path.exists(cal_path):
            return None
        with open(cal_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def build_league_round(self, round_data: dict) -> ft.Column:
        """Scontri diretti della giornata."""
        col = ft.Column(
            controls=[
                ft.Text(f"{round_data['start_date']} - {round_data['end_date']}", size=16, weight="bold", color="amber"),
                ft.Divider()
            ]
        )
        for m in round_data["matchups"]:
            # Formattiamo i punteggi a 1 decimale
            h_score = m.get('home_score', 0.0)
            a_score = m.get('away_score', 0.0)

            # Se la partita non è stata ancora giocata o ha punteggio a 0, possiamo mostrare uno stato diverso
            # (Opzionale: se vuoi mantenere lo 0.0 o mostrare "vs" quando non è stata giocata)
            score_text = f"{h_score:.1f} - {a_score:.1f}" if m.get('was_played', False) or h_score > 0 or a_score > 0 else " vs "

            col.controls.append(
                ft.Container(
                    content=ft.Row([
                        # Squadra di casa
                        ft.Text(f"{m['home_team']}", expand=True, text_align="right", size=14),

                        # Punteggio centrale
                        ft.Container(
                            # Largo abbastanza per due punteggi a 3 cifre sulla stessa riga
                            content=ft.Text(score_text, weight="bold", color="amber", no_wrap=True),
                            width=125,
                            alignment=ft.alignment.Alignment.CENTER
                        ),

                        # Squadra in trasferta
                        ft.Text(f"{m['away_team']}", expand=True, text_align="left", size=14),
                    ]),
                    padding=10,
                    bgcolor=ft.Colors.GREY_900,
                    border_radius=8
                )
            )
        return col

    def build_nba_round(self, round_data: dict) -> ft.ListView:
        """Partite NBA della giornata, raggruppate per data italiana (ospiti a sinistra, casa a destra)."""
        games_by_date = round_data.get("nba_games") or {}
        view = ft.ListView(expand=True, spacing=6, controls=[
            ft.Text(f"{round_data['start_date']} - {round_data['end_date']}", size=16, weight="bold", color="amber"),
            ft.Divider()
        ])
        if not games_by_date:
            view.controls.append(ft.Text("Nessuna partita NBA disponibile", color="grey"))
            return view

        for ita_date in sorted(games_by_date):
            day = datetime.strptime(ita_date, "%Y-%m-%d")
            view.controls.append(
                ft.Text(f"{WEEKDAYS_IT[day.weekday()]} {day:%d/%m}", size=14, weight="bold", color=ft.Colors.ORANGE)
            )
            for g in games_by_date[ita_date]:
                view.controls.append(self.build_nba_game(g))
        return view

    def build_nba_game(self, g: dict) -> ft.Container:
        status = g.get("status")
        played = status in ("final", "in_progress") and g.get("home_score") is not None
        if played:
            center = f"{g['away_score']} - {g['home_score']}"
        elif status == "postponed":
            center = "Rinviata"
        else:
            center = g.get("time") or "vs"

        # A partita finita la vincente è in grassetto, la perdente in grigio
        def team_text(team, own, other, align):
            won = status == "final" and own is not None and other is not None and own > other
            lost = status == "final" and own is not None and other is not None and own < other
            return ft.Text(team, expand=True, text_align=align, size=14,
                           weight="bold" if won else None, color="grey" if lost else None)

        return ft.Container(
            content=ft.Row([
                team_text(g["away_team"], g.get("away_score"), g.get("home_score"), "right"),
                ft.Container(
                    content=ft.Column([
                        ft.Text(center, weight="bold", color="amber", no_wrap=True),
                    ] + ([ft.Text("in corso", size=10, color="grey")] if status == "in_progress" else []),
                        spacing=0, horizontal_alignment="center"),
                    width=125,
                    alignment=ft.alignment.Alignment.CENTER
                ),
                team_text(f"@ {g['home_team']}", g.get("home_score"), g.get("away_score"), "left"),
            ]),
            padding=8,
            bgcolor=ft.Colors.GREY_900,
            border_radius=8
        )


class StandingsView(ft.Column):
    def __init__(self, json_path: str = os.path.join("data", "standings.json")):
        super().__init__()
        self.json_path = json_path
        self.expand = True
        self.scroll = ft.ScrollMode.AUTO
        self.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        
        self.setup_ui()

    def load_standings_data(self) -> list:
        """Carica la classifica dal file JSON e la ordina per vittorie descrescenti."""
        if not os.path.exists(self.json_path):
            return []

        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Ordina: prima per vittorie (Wins), in caso di parità per Punti Fatti (total_score)
            data.sort(key=lambda x: (x.get("wins", 0), x.get("total_score", 0.0)), reverse=True)
            return data
        except Exception as err:
            print(f"Errore durante il caricamento della classifica: {err}")
            return []

    def setup_ui(self):
        standings_data = self.load_standings_data()

        if not standings_data:
            self.controls = [
                ft.Container(
                    content=ft.Text("Nessun dato classifica disponibile.", size=16, color="grey"),
                    padding=20
                )
            ]
            return

        # Costruzione righe della DataTable (Posizione + Campi JSON filtrati)
        data_rows = []
        for pos, team in enumerate(standings_data, start=1):
            data_rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(f"{pos}", weight="bold", color="amber" if pos <= 3 else "white")),
                        ft.DataCell(ft.Text(team.get("team_name", "-"), weight="bold")),
                        ft.DataCell(ft.Text(str(team.get("wins", 0)), color="green_400")),
                        ft.DataCell(ft.Text(str(team.get("losses", 0)), color="red_400")),
                        ft.DataCell(ft.Text(f"{team.get('total_score', 0.0):.1f}")),
                        ft.DataCell(ft.Text(f"{team.get('total_points_against', 0.0):.1f}")),
                    ]
                )
            )

        # Tabella reattiva Flet
        standings_table = ft.DataTable(
            bgcolor=ft.Colors.GREY_900,
            border_radius=10,
            column_spacing=18,
            heading_row_height=45,
            columns=[
                ft.DataColumn(ft.Text("#", weight="bold")),
                ft.DataColumn(ft.Text("Squadra", weight="bold")),
                ft.DataColumn(ft.Text("V", weight="bold", color="green_400")),
                ft.DataColumn(ft.Text("P", weight="bold", color="red_400")),
                ft.DataColumn(ft.Text("PF", weight="bold"), numeric=True),
                ft.DataColumn(ft.Text("PS", weight="bold"), numeric=True),
            ],
            rows=data_rows
        )

        self.controls = [
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Classifica Campionato", size=20, weight="bold", color="amber"),
                        ft.Divider(color="grey_800"),
                        ft.Row([standings_table], alignment=ft.MainAxisAlignment.CENTER)
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER
                ),
                padding=10
            )
        ]


class SettingsView(ft.Tabs):
    def __init__(self):
        super().__init__(content=None, length=0)
        self.expand = True
        self.length = 5
        self.selected_index = 0
        self.animation_duration = 300

        self.profile_view = ft.Text("Gestione Profilo - Prossimamente", size=20)
        self.rules_filepath = os.path.join("data", "rules.json")
        self.rules_view = self._build_multi_table_view(self.rules_filepath)
        
        self.content = ft.Column(
            expand=True,
            controls=[
                ft.TabBar(
                    tabs=[
                        ft.Tab(label="Gestione Profilo", icon=ft.Icons.SPORTS_BASKETBALL),
                        ft.Tab(label="Regolamento", icon=ft.Icons.MANAGE_SEARCH)
                    ]
                ),
                ft.TabBarView(
                    expand=True,
                    controls=[
                        ft.Container(content=self.profile_view, padding=0),
                        ft.Container(content=self.rules_view, padding=10)
                    ],
                ),
            ],
        )

    def _load_json_rules(self, filepath: str):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _build_multi_table_view(self, filepath: str):
        data = self._load_json_rules(filepath)
        if not data:
            return ft.Text("Errore di caricamento delle regole.", color=ft.Colors.RED)

        # view_controls = [ft.Text("Regolamento e Punteggi Ufficiali", size=18, weight=ft.FontWeight.BOLD)]
        view_controls = []

        for category_name, rows in data.items():
            view_controls.append(
                ft.Text(category_name.replace("_", " ").upper(), size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE)
            )
            
            data_rows = []
            for item in rows:
                score = str(item["punteggio"])
                score_color = ft.Colors.GREEN_400 if not score.startswith("-") else ft.Colors.RED_400
                data_rows.append(
                    ft.DataRow(cells=[
                        # Font leggermente ingrandito a 13
                        ft.DataCell(ft.Text(item["azione"], size=13)),
                        ft.DataCell(ft.Text(score, size=13, weight=ft.FontWeight.BOLD, color=score_color))
                    ])
                )

            table = ft.DataTable(
                border=ft.border.all(1, ft.Colors.GREY_800),
                border_radius=6,
                # Linee di divisione verticali e orizzontali per una griglia pulita
                vertical_lines=ft.border.BorderSide(1, ft.Colors.GREY_800),
                horizontal_lines=ft.border.BorderSide(1, ft.Colors.GREY_800),
                columns=[
                    # Diamo più spazio alla colonna di sinistra impostando una larghezza fissa (es. 190 pixel)
                    ft.DataColumn(ft.Text("Azione", weight=ft.FontWeight.BOLD)),
                    # Rimozione di numeric=True per evitare lo shift sull'ultima riga testuale
                    ft.DataColumn(ft.Text("Punti", weight=ft.FontWeight.BOLD)),
                ],
                rows=data_rows,
            )
            view_controls.append(table)
            view_controls.append(ft.Divider(height=15, color=ft.Colors.TRANSPARENT))

        return ft.ListView(expand=True, padding=5, controls=view_controls)


class TeamView(ft.Column):
    """
    Schermata Squadra: la giornata in corso con i punteggi e, nella finestra dei cambi,
    la formazione modificabile della giornata successiva (selezionabili con due pulsanti).
    """
    def __init__(self, current_team: Team | None, current_gw: int | None,
                 edit_team: Team | None = None, edit_gw: int | None = None,
                 edit_deadline: datetime | None = None):
        super().__init__()
        self.expand = True
        self.horizontal_alignment = "center"

        self.courts: list[tuple[str, Court]] = []
        if current_team is not None:
            self.courts.append((f"Giornata {current_gw}", Court(current_team, current_gw)))
        if edit_team is not None:
            self.courts.append((f"Formazione G{edit_gw}", Court(edit_team, edit_gw, edit_deadline)))

        # Velo di caricamento sopra le formazioni (cambio giornata, Salva, Annulla)
        self.loading = LoadingOverlay()
        for _, court in self.courts:
            court.loading = self.loading

        # Gestore async senza lambda (Flet riconosce come async solo le coroutine function): l'indice va in data
        self.switch_buttons = [
            ft.ElevatedButton(label, data=i, on_click=self.handle_switch_click)
            for i, (label, _) in enumerate(self.courts)
        ]
        content = ft.Column(expand=True, horizontal_alignment="center", left=0, top=0, right=0, bottom=0)
        content.controls = ([ft.Row(self.switch_buttons, alignment=ft.MainAxisAlignment.CENTER)]
                            if len(self.courts) > 1 else [])
        content.controls += [court for _, court in self.courts]
        self.controls = [ft.Stack([content, self.loading], expand=True)]
        self.show_court(0, refresh=False)

    async def handle_switch_click(self, e):
        await self.switch_court(e.control.data)

    async def switch_court(self, index: int):
        """Passa all'altra formazione mostrando il velo mentre il client la disegna."""
        if self.courts[index][1].visible:
            return  # Già selezionata: niente velo
        await self.loading.show()
        try:
            self.show_court(index)
        finally:
            self.loading.hide()

    def show_court(self, index: int, refresh: bool = True):
        """Mostra solo la formazione selezionata (le altre restano in memoria con le loro modifiche)."""
        for i, (_, court) in enumerate(self.courts):
            court.visible = i == index
        for i, button in enumerate(self.switch_buttons):
            button.bgcolor = "amber" if i == index else ft.Colors.GREY_800
            button.color = "black" if i == index else "white"
        if refresh:
            self.update()


class LeagueView(ft.Column):
    """
    Formazioni e punteggi della giornata in corso delle altre squadre, una per tab.
    I dati si scaricano solo alla prima apertura del tab (loader), non al login.
    """
    def __init__(self, gameweek: int | None, loader=None):
        super().__init__()
        self.expand = True
        self.horizontal_alignment = "center"
        self.alignment = ft.MainAxisAlignment.CENTER
        self.gameweek = gameweek
        self.loader = loader  # Restituisce la lista dei Team; None = nessuna giornata in corso
        self.loaded = False
        if loader is None:
            self.controls = [ft.Text("Nessuna giornata in corso", size=16, color="grey")]
        else:
            self.controls = [ft.ProgressRing(), ft.Text("Caricamento squadre...")]

    async def load(self):
        """Scarica (o legge dalla cache locale) le altre squadre e costruisce un tab per ognuna."""
        if self.loaded or self.loader is None:
            return
        self.loaded = True
        try:
            # In un thread: il loop di Flet resta libero e lo spinner si vede (e gira)
            teams = await asyncio.to_thread(self.loader)
        except Exception as e:
            print(f"Errore nel caricamento delle altre squadre: {e}")
            self.loaded = False  # Riprova alla prossima apertura del tab
            self.controls = [ft.Text("Impossibile scaricare le squadre, riprova", color="red")]
            self.update()
            return

        self.alignment = ft.MainAxisAlignment.START
        if not teams:
            self.controls = [ft.Text("Nessuna formazione disponibile", size=16, color="grey")]
        else:
            self.controls = [ft.Tabs(
                length=len(teams),
                selected_index=0,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[
                        ft.TabBar(
                            scrollable=True,
                            label_color=ft.Colors.ORANGE,
                            unselected_label_color=ft.Colors.GREY,
                            indicator_color=ft.Colors.ORANGE,
                            tabs=[ft.Tab(label=t.name) for t in teams]
                        ),
                        ft.TabBarView(
                            expand=True,
                            controls=[Court(t, self.gameweek, read_only=True) for t in teams]
                        ),
                    ],
                ),
            )]
        self.update()


class MainDashboard(ft.Tabs):
    def __init__(self, current_team: Team | None, current_gw: int | None,
                 edit_team: Team | None = None, edit_gw: int | None = None,
                 edit_deadline: datetime | None = None, league_loader=None):
        super().__init__(content=None, length=0)
        self.expand = True # Permette alla dashboard di occupare tutto lo spazio
        self.length = 5
        self.selected_index=0
        self.animation_duration=300
        self.on_change = self.handle_tab_change

        # Inizializziamo le varie viste
        self.team_view = TeamView(current_team, current_gw, edit_team, edit_gw, edit_deadline)
        self.league_view = LeagueView(current_gw, league_loader)
        self.calendar_view = CalendarView()
        self.championship_view = StandingsView()
        self.settings_view = SettingsView()
        
        self.content=ft.Column(
            expand=True,
            controls=[
                ft.TabBar(
                    label_text_style=ft.TextStyle(size=9.3),
                    unselected_label_text_style=ft.TextStyle(size=7.2),
                    label_color=ft.Colors.ORANGE,           # Colore testo selezionato
                    unselected_label_color=ft.Colors.GREY,  # Colore testo non selezionato
                    indicator_color=ft.Colors.ORANGE,       # Colore della linea sotto la tab
                    tabs=[
                        ft.Tab(label="Squadra", icon=ft.Icons.SPORTS_BASKETBALL),
                        ft.Tab(label="Altre Squadre", icon=ft.Icons.GROUPS),
                        ft.Tab(label="Calendario", icon=ft.Icons.CALENDAR_MONTH),
                        ft.Tab(label="Campionato", icon=ft.Icons.EMOJI_EVENTS),
                        ft.Tab(label="Impostazioni", icon=ft.Icons.SETTINGS),
                    ]
                ),
                ft.TabBarView(
                    expand=True,
                    controls=[
                        # Squadra
                        self.team_view,
                        # Avversari
                        ft.Container(
                            content=self.league_view,
                            padding=0
                        ),
                        # Calendario
                        ft.Container(
                            content=(
                                self.calendar_view
                            )
                        ),
                        # Campionato
                        ft.Container(
                            content=self.championship_view
                        ),
                        # Impostazioni
                        ft.Container(
                            content=self.settings_view
                        ),
                    ],
                ),
            ],
        )

    async def handle_tab_change(self, e):
        """Al primo ingresso nel tab Avversari scarica le formazioni delle altre squadre."""
        if int(e.data) == 1:  # e.data = indice del tab selezionato
            await self.league_view.load()


class LoginView(ft.Column):
    def __init__(self, page: ft.Page, on_login_success):
        super().__init__()
        self.app_page = page
        self.on_login_success = on_login_success
        self.alignment = ft.MainAxisAlignment.CENTER
        self.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        
        self.username_field = ft.TextField(label="Username", width=280, bgcolor="#1a1a1a")
        self.password_field = ft.TextField(label="Password", width=280, password=True, can_reveal_password=True, bgcolor="#1a1a1a")
        self.error_text = ft.Text("", color="red")
        self.login_button = ft.ElevatedButton("Entra", on_click=self._check_login, bgcolor="amber", color="black")

        self.controls = [
            ft.Icon(ft.Icons.SPORTS_BASKETBALL, size=80, color="amber"),
            ft.Text("NewFantaNBA Login", size=24, weight="bold"),
            self.username_field,
            self.password_field,
            self.error_text,
            self.login_button
        ]

    async def _check_login(self, e):
        with open("data/profiles.json", "r") as f:
            profiles = json.load(f)

        for user in profiles:
            if user["username"] == self.username_field.value and user["password"] == self.password_field.value:
                # Niente doppi click mentre si caricano i dati
                self.login_button.disabled = True
                self.update()
                await self.on_login_success(user)
                return
        
        self.error_text.value = "Credenziali errate"
        self.update()