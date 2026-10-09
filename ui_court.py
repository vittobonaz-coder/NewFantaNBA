import flet as ft
import os
import json
from fanta_obj import Player, Team


ROLE_CONFIGS = {
    "STARTER": {"width": 110, "height": 130, "avatar": 55, "font": 15, "opacity": 1.0, "mult": 1.0, "button_size": 20, "button_left": -5, "button_top": -5},
    "SIXTH": {"width": 110, "height": 130, "avatar": 55, "font": 15, "opacity": 1.0, "mult": 1.0, "button_size": 20, "button_left": -5, "button_top": -5},
    "BENCH": {"width": 80, "height": 110, "avatar": 40, "font": 13, "opacity": 1.0, "mult": 0.5, "button_size": 15, "button_left": -8, "button_top": -8},
    "RESERVE": {"width": 80, "height": 110, "avatar": 40, "font": 13, "opacity": 0.6, "mult": 0.0, "button_size": 15, "button_left": -8, "button_top": -8},
}

class PlayerCard(ft.Container):
    """Classe per le cards dei giocatori"""

    def __init__(self, player: Player, score: float, role_type: str, slot_index: int):
        super().__init__()
        self.player = player
        self.score = score
        self.role_type = role_type
        self.slot_index = slot_index
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
        final_score = self.score * conf["mult"]
            
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
                        ft.Text(f"{final_score:.1f}", size=conf["font"], weight="bold"),
                    ]
                ),
                btn_container
            ]
        )
    
    def update_data(self, new_player: Player, new_score: float):
        """Aggiorna i dati della card e rinfresca solo questa"""
        self.player = new_player
        self.score = new_score
        self.setup_ui()

class Court(ft.Column):
    def __init__(self, team_instance: Team):
        super().__init__()
        self.horizontal_alignment = "center"
        self.scroll = ft.ScrollMode.AUTO
        self.expand = True
        self.spacing = 0
        # self.spacing = 10
        self.team = team_instance
        self.lineup = self.team.lineup 

        # # 1. SALVATAGGIO STATO INIZIALE (per Annulla)
        # # Salviamo una lista di tuple (Giocatore, Score) per ogni card
        # self.initial_state = [] 
        # self.initial_lineup = self.lineup

        # Testo UI legato al campo 'score' del Team
        self.total_score_text = ft.Text(
            f"TOTAL SCORE: {self.team.score:.1f}", 
            size=20, weight="bold", color="amber"
        )

        # CARDS
        self.cards = []
        ordered_players = self.team.get_ordered_roster()
        for i, p in enumerate(ordered_players):
            card = PlayerCard(
                player=p,
                score=p.score,
                role_type=self.team.roles_map[p.id],
                slot_index=i
            )
            self.cards.append(card)

        # VALIDAZIONE AUTOMATICA ALL'AVVIO
        # Se i giocatori caricati non rispettano il modulo attuale, li scambiamo subito
        self.auto_fix_starters(self.lineup)

        # Popoliamo lo stato iniziale dopo aver creato le cards
        self._capture_current_state()

        # DROPDOWN FORMAZIONE
        self.lineup_dd = ft.Dropdown(
            width=110, height=50, text_size=12, value=self.lineup,
            options=[ft.dropdown.Option(x) for x in ["2-2-1", "2-1-2", "1-2-2"]],
            filled=True, fill_color="#1a1a1a", border_color="grey",
            on_select=self.change_lineup
        )
        
        self.starters_container = ft.Container(width=250, height=450)

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

    def handle_save(self, e):
        """Salva su Supabase, su file locale e nasconde i bottoni."""
        from supabase_manager import SupabaseSync
        sync = SupabaseSync()

        # Aggiorniamo i dati nel team (incluso l'ordine dei giocatori)
        self.refresh_ui_and_data()
        
        # Sincronizza Cloud e salva in locale
        sync.push_team(self.team, court=self)
        self.team.save_to_json()
        
        # Il nuovo stato corrente diventa il punto di ripristino per futuri cambi
        self._capture_current_state()
        self.toggle_buttons(False)

        # Feedback all'utente
        sb = ft.SnackBar(ft.Text(f"Formazione di {self.team.name} salvata!"), bgcolor="green")
        self.page.overlay.append(sb) # Metodo più robusto per Flet
        sb.open = True
        self.page.update()

    def handle_cancel(self, e):
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
            # Dropdown formazione
            ft.Container(
                content=ft.Row([self.lineup_dd], alignment=ft.MainAxisAlignment.START),
                width=330, height=80
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
                    controls=ft.Row(controls=[self.cards[10], self.cards[11], self.cards[12]], alignment="center")
                )
            )
        ]

    def update_starters_layout(self):
        """Cambia SOLO il contenuto del rettangolo dei titolari"""
        if self.lineup == "2-2-1":
            rows = [
                ft.Row(controls=[self.cards[0]], alignment=ft.MainAxisAlignment.CENTER),
                ft.Row(controls=[self.cards[1], self.cards[2]], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row(controls=[self.cards[3], self.cards[4]], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            ]
        elif self.lineup == "2-1-2":
            rows = [
                ft.Row(controls=[self.cards[0], self.cards[1]], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row(controls=[self.cards[2]], alignment=ft.MainAxisAlignment.CENTER),
                ft.Row(controls=[self.cards[3], self.cards[4]], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            ]
        else: # 1-2-2
            rows = [
                ft.Row(controls=[self.cards[0], self.cards[1]], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row(controls=[self.cards[2], self.cards[3]], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row(controls=[self.cards[4]], alignment=ft.MainAxisAlignment.CENTER)
            ]
        
        self.starters_container.content = ft.Column(controls=rows)
    
    def get_starter_roles(self, lineup_str):
        """Restituisce solo la mappa dei ruoli per i primi 5 slot (Titolari)"""
        if lineup_str == "2-2-1":
            return ['C', 'A', 'A', 'G', 'G']
        elif lineup_str == "2-1-2":
            return ['C', 'C', 'A', 'G', 'G']
        else: # 1-2-2
            return ['C', 'C', 'A', 'A', 'G']
        
    def auto_fix_starters(self, new_lineup):
        """
        Controlla i titolari e scambia quelli incompatibili con la panchina.
        Ottimizzato per fare il minor numero di scambi possibili.
        """
        new_roles = self.get_starter_roles(new_lineup)
        invalid_starters = []
        # 1. Troviamo quali titolari (indici 0-4) sono illegali nel nuovo modulo
        for i in range(5):
            req_role = new_roles[i]
            if req_role not in self.cards[i].player.position.split('/'):
                invalid_starters.append((i, req_role)) # Salviamo indice e ruolo richiesto

        if not invalid_starters:
            return # Nessun giocatore fuori posizione, usciamo subito!

        # 2. Cerchiamo i sostituti dalla panchina (indici 5-9)
        used_bench_indexes = set() # Per non scambiare due volte lo stesso panchinaro
        for starter_idx, req_role in invalid_starters:
            for bench_idx in range(5, 10):
                if bench_idx in used_bench_indexes:
                    continue
                
                # Se il panchinaro ha il ruolo che ci serve per tappare il buco
                if req_role in self.cards[bench_idx].player.position.split('/'):
                    # Facciamo uno scambio silente dei dati (stessa logica di handle_swap)
                    # TO DO: Non posso riutilizzare il metodo handle_swap
                    starter_card = self.cards[starter_idx]
                    bench_card = self.cards[bench_idx]
                    old_player = starter_card.player
                    old_score = starter_card.score
                    # update_data aggiorna i dati e ricalcola anche il moltiplicatore in base al fatto che uno diventa STARTER e l'altro BENCH
                    starter_card.update_data(bench_card.player, bench_card.score)
                    bench_card.update_data(old_player, old_score)
                    # Segniamo il panchinaro come usato e passiamo al prossimo titolare illegale
                    used_bench_indexes.add(bench_idx)
                    break

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
    
    def is_group_valid(self, players_subset, req_g, req_a, req_c):
        """Verifica se un blocco di giocatori può soddisfare esattamente i ruoli richiesti"""
        from itertools import product
        options = [p.position.split('/') for p in players_subset]
        return any(
            c.count('G') == req_g and 
            c.count('A') == req_a and 
            c.count('C') == req_c 
            for c in product(*options)
        )

    def refresh_menus(self):
        """
        Rigenera i menu di scambio applicando:
        1. Vincolo di Slot (Righe Titolari: C, A, G)
        2. Vincolo di Roster Attivo (0-9): Sempre 2C, 4A, 4G
        3. Vincolo di Riserve (10-12): Sempre 1C, 1A, 1G
        """
        if self.lineup == "2-2-1":
            slot_map = ['C', 'A', 'A', 'G', 'G', 'ANY', 'ANY', 'ANY', 'ANY', 'ANY', 'ANY', 'ANY', 'ANY']
        elif self.lineup == "2-1-2":
            slot_map = ['C', 'C', 'A', 'G', 'G', 'ANY', 'ANY', 'ANY', 'ANY', 'ANY', 'ANY', 'ANY', 'ANY']
        else:
            slot_map = ['C', 'C', 'A', 'A', 'G', 'ANY', 'ANY', 'ANY', 'ANY', 'ANY', 'ANY', 'ANY', 'ANY']

        for i, card in enumerate(self.cards):
            valid_items = []
            
            for j, other_card in enumerate(self.cards):
                if i == j: continue
                
                # 1. Simuliamo lo scambio
                temp_players = [c.player for c in self.cards]
                temp_players[i], temp_players[j] = temp_players[j], temp_players[i]
                
                # --- CONTROLLO A: Vincolo di Posizione Individuale (Solo per i Titolari 0-4) ---
                # Verifichiamo che i giocatori nei primi 5 slot abbiano il ruolo richiesto dalla riga
                illegal_position = False
                for idx in range(5):
                    required_role = slot_map[idx]
                    # Se il giocatore in quello slot non ha il ruolo richiesto tra i suoi possibili ruoli
                    if required_role not in temp_players[idx].position.split('/'):
                        illegal_position = True
                        break
                
                if illegal_position:
                    continue

                # --- CONTROLLO B: Integrità del Roster Attivo (Slot 0-9) ---
                # Titolari + Panchina devono SEMPRE poter garantire 2C, 4A, 4G
                if not self.is_group_valid(temp_players[0:10], req_g=4, req_a=4, req_c=2):
                    continue
                    
                # --- CONTROLLO C: Integrità delle Riserve (Slot 10-12) ---
                # Le 3 riserve devono SEMPRE poter garantire 1C, 1A, 1G
                if not self.is_group_valid(temp_players[10:13], req_g=1, req_a=1, req_c=1):
                    continue

                # Se passa tutti i test, lo scambio è legale
                valid_items.append(
                    ft.PopupMenuItem(
                        content=ft.Text(other_card.player.name.split()[-1]),
                        on_click=lambda e, f=i, t=j: self.handle_swap(f, t)
                    )
                )
            card.swap_button.items = valid_items


class CalendarView(ft.Tabs):
    def __init__(self):
        super().__init__(content=None, length=0)
        self.load_calendar()
        self.expand = True # Permette alla dashboard di occupare tutto lo spazio
        self.length = 5
        self.selected_index=0
        self.animation_duration=300

    def load_calendar(self):
        cal_path = os.path.join("data", "calendar.json")
        if not os.path.exists(cal_path):
            self.controls.append(ft.Text("Calendario non trovato."))
            return

        with open(cal_path, "r", encoding="utf-8") as f:
            calendar_data = json.load(f)

        round_tabs = []
        round_col = []

        for round_data in calendar_data:
            round_n = round_data['round_number']
            round_col.append(
                ft.Column(
                    controls=[
                        ft.Text(f"{round_data['start_date']} - {round_data['end_date']}", size=16, weight="bold", color="amber"),
                        ft.Divider()
                    ]
                )
            )
            for m in round_data["matchups"]:
                round_col[-1].controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text(f"{m['home_team']}", expand=True, text_align="right"),
                            ft.Text("vs", weight="bold"),
                            ft.Text(f"{m['away_team']}", expand=True, text_align="left"),
                        ]),
                        padding=10,
                        bgcolor=ft.Colors.GREY_900,
                        border_radius=8
                    )
                )
            round_tabs.append(ft.Tab(label=f"{round_n}"))
        
        self.content=ft.Column(
            expand=True,
            controls=[
                ft.TabBar(
                    label_text_style=ft.TextStyle(size=20),
                    unselected_label_text_style=ft.TextStyle(size=17),
                    label_color=ft.Colors.ORANGE,           # Colore testo selezionato
                    unselected_label_color=ft.Colors.GREY,  # Colore testo non selezionato
                    indicator_color=ft.Colors.ORANGE,       # Colore della linea sotto la tab
                    tabs=round_tabs
                ),
                ft.TabBarView(
                    expand=True,
                    controls=round_col
                ),
            ],
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


class MainDashboard(ft.Tabs):
    def __init__(self, team: Team):
        super().__init__(content=None, length=0)
        self.team = team
        self.expand = True # Permette alla dashboard di occupare tutto lo spazio
        self.length = 5
        self.selected_index=0
        self.animation_duration=300

        # Inizializziamo le varie viste
        self.team_view = Court(self.team)
        self.search_view = ft.Text("Vista Ricerca - Prossimamente", size=20)
        self.calendar_view = CalendarView()
        self.championship_view = StandingsView()
        self.settings_view = ft.Text("Vista Impostazioni - Prossimamente", size=20)
        
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
                        ft.Tab(label="Ricerca", icon=ft.Icons.MANAGE_SEARCH),
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
                        # Ricerca
                        ft.Container(
                            content=self.search_view,
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
        
        self.controls = [
            ft.Icon(ft.Icons.SPORTS_BASKETBALL, size=80, color="amber"),
            ft.Text("NewFantaNBA Login", size=24, weight="bold"),
            self.username_field,
            self.password_field,
            self.error_text,
            ft.ElevatedButton("Entra", on_click=self._check_login, bgcolor="amber", color="black")
        ]

    def _check_login(self, e):
        with open("data/profiles.json", "r") as f:
            profiles = json.load(f)
            
        for user in profiles:
            if user["username"] == self.username_field.value and user["password"] == self.password_field.value:
                self.on_login_success(user)
                return
        
        self.error_text.value = "Credenziali errate"
        self.update()