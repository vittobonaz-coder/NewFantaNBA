import flet as ft
from fanta_obj import Player
from fanta_obj import Team

ROLE_CONFIGS = {
    "STARTER": {"width": 110, "height": 130, "avatar": 55, "font": 15, "opacity": 1.0, "mult": 1.0, "button_size": 20, "button_left": -5, "button_top": -5},
    "SIXTH":   {"width": 110, "height": 130, "avatar": 55, "font": 15, "opacity": 1.0, "mult": 1.0, "button_size": 20, "button_left": -5, "button_top": -5},
    "BENCH":   {"width": 80,  "height": 110, "avatar": 40, "font": 13, "opacity": 1.0, "mult": 0.5, "button_size": 15, "button_left": -8, "button_top": -8},
    "RESERVE": {"width": 80,  "height": 110, "avatar": 40, "font": 13, "opacity": 0.6, "mult": 0.0, "button_size": 15, "button_left": -8, "button_top": -8},
}

class PlayerCard(ft.Container):
    """Classe per le cards dei giocatori"""
    def __init__(self, player: Player, score: float, role_type: str, slot_index: int):
        # role_type: "STARTER", "SIXTH", "BENCH", "RESERVE"
        super().__init__()
        self.player = player
        self.score = score
        self.role_type = role_type
        self.slot_index = slot_index # Indice univoco sul campo (da 0 a 12)

        self.border_radius = 12
        self.bgcolor = ft.Colors.GREY_900
        self.border = ft.Border.all(2, ft.Colors.GREY)
        self.padding = 5

        # Swap Button
        self.swap_button = ft.PopupMenuButton(
            icon=ft.Icons.SWAP_VERT_CIRCLE, icon_color="white", bgcolor="black"
        )
        
        self.setup_ui()

    # Caricamento configurazione
    def setup_ui(self):
        """Configura l'aspetto in base al ruolo attuale"""
        conf = ROLE_CONFIGS.get(self.role_type, ROLE_CONFIGS["STARTER"])
        self.width = conf["width"]
        self.height = conf["height"]
        self.opacity = conf["opacity"]
        self.content = self._build_content(conf)


    def _build_content(self, conf):
        surname = self.player.name.split()[-1]
        final_score = self.score * conf["mult"]
            
        btn_container = ft.Container(
            content=self.swap_button,
            left=conf["button_left"], top=conf["button_top"]
        )

        # CARD
        return ft.Stack(
            alignment=ft.alignment.Alignment.TOP_CENTER,
            controls=[
                ft.Column(
                    spacing=0,
                    horizontal_alignment="center",
                    controls=[
                        ft.Image(src=self.player.get_avatar_img(), width=conf["avatar"], height=conf["avatar"]),
                        ft.Text(surname, size=conf["font"], weight="bold", no_wrap=True),
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
        self.setup_ui() # Ricostruisce il content interno

class Court(ft.Column):
    def __init__(self, team_instance: Team):
        super().__init__()
        self.horizontal_alignment = "center"
        self.spacing = 10
        self.team = team_instance
        self.lineup = "2-2-1"

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

        # DROPDOWN FORMAZIONE
        self.lineup_dd = ft.Dropdown(
            width=110, height=50, text_size=12, value=self.lineup,
            options=[ft.dropdown.Option(x) for x in ["2-2-1", "2-1-2", "1-2-2"]],
            filled=True, fill_color="#1a1a1a", border_color="grey",
            on_select=self.change_lineup
        )
        
        self.starters_container = ft.Container(width=250, height=450)

        self.setup_static_ui()
        self.update_starters_layout()
        self.refresh_menus()
        self.refresh_ui_and_data()
    
    def refresh_ui_and_data(self):
        """Sincronizza i ruoli nel Team in base alla posizione delle cards e ricalcola."""
        # 1. Aggiorna la roles_map nel Team in base a dove si trovano i giocatori ora
        for card in self.cards:
            self.team.roles_map[card.player.id] = card.role_type
        
        # 2. Chiedi al Team di ricalcolare il suo punteggio interno
        new_total = self.team.calculate_total_score(ROLE_CONFIGS)
        
        # 3. Aggiorna la UI
        self.total_score_text.value = f"TOTAL SCORE: {new_total:.1f}"
    
    def change_lineup(self, e):
        new_val = self.lineup_dd.value
        if new_val == self.lineup:
            return
        # 1. Correggi i giocatori incompatibili (sui dati)
        self.auto_fix_starters(new_val)
        # 2. Aggiorna la variabile di stato della formazione
        self.lineup = new_val
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

        old_player = origin_card.player
        old_score = origin_card.score

        origin_card.update_data(target_card.player, target_card.score)
        target_card.update_data(old_player, old_score)

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

# def main(page: ft.Page) -> None:
#     page.title = 'Players Cards'
#     page.scroll = ft.ScrollMode.AUTO
#     page.vertical_alignment = ft.MainAxisAlignment.CENTER
#     page.theme_mode = ft.ThemeMode.DARK
#     page.window.width = 358
#     page.window.height = 757

#     players_data = [
#         {"id": 201143, "name": "Al Horford", "team": "GSW", "pos": "C/A", "score": 21.5, "role": "STARTER"},
#         {"id": 2544, "name": "Lebron James", "team": "LAL", "pos": "A", "score": 27.5, "role": "STARTER"},
#         {"id": 1629029, "name": "Luka Doncic", "team": "LAL", "pos": "A/G", "score": 58.0, "role": "STARTER"},
#         {"id": 201935, "name": "James Harden", "team": "LAC", "pos": "G", "score": 38.0, "role": "STARTER"},
#         {"id": 201939, "name": "Stephen Curry", "team": "GSW", "pos": "G", "score": 36.1, "role": "STARTER"},
#         {"id": 1629636, "name": "Darius Garland", "team": "LAC", "pos": "G", "score": 24.8, "role": "SIXTH"},
#         {"id": 1630163, "name": "LaMelo Ball", "team": "CHA", "pos": "G", "score": 44.5, "role": "BENCH"},
#         {"id": 1630567, "name": "Scottie Barnes", "team": "TOR", "pos": "A/G", "score": 39.5, "role": "BENCH"},
#         {"id": 1630578, "name": "Alperen Sengun", "team": "HOU", "pos": "C", "score": 41.0, "role": "BENCH"},
#         {"id": 1631323, "name": "Simone Fontecchio", "team": "MIA", "pos": "A/C", "score": 13.2, "role": "BENCH"},
#         {"id": 1641705, "name": "Victor Wembanyama", "team": "SAS", "pos": "A/C", "score": 48.3, "role": "RESERVE"},
#         {"id": 202331, "name": "Paul George", "team": "PHI", "pos": "A", "score": 32.0, "role": "RESERVE"},
#         {"id": 201566, "name": "Russell Westbrook", "team": "SAC", "pos": "G", "score": 28.2, "role": "RESERVE"},
#     ]
    
#     page.add(Court(players_data))
    

#     ## Verifica che la squadra sia composta da 5G, 5A, 3C
#     from itertools import product
#     # 1. Estrai le opzioni per ogni giocatore: "A/G" diventa ["A", "G"]
#     options = [d["pos"].split('/') for d in players_data]
#     # 2. Genera tutte le combinazioni e conta quante soddisfano i target (G:5, A:5, C:3)
#     valid = any(c.count('G')==5 and c.count('A')==5 and c.count('C')==3 for c in product(*options))
#     # 3. Visualizza solo se la condizione è True
#     if not valid:
#         page.clean()
#         page.add(ft.Text("Squadra non consentita"))

#     # page.add(Court(players_data))

# if __name__ == '__main__':
#     ft.run(main=main)