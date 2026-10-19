import flet as ft
from ui_court import MainDashboard, LoginView
from fanta_obj import Team


SIM_DATE = "2026-10-13"
SIM_NBA_DATE = "2026-10-12"


def main(page: ft.Page) -> None:
    page.title = 'Fanta NBA - Dashboard'
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 358
    page.window.height = 757

    def on_login_success(user_data):
        team_name = user_data["username"].replace("_user", "") 
        team = Team(name=team_name)

        team.load_from_json()

        page.clean()
        page.add(MainDashboard(team, SIM_NBA_DATE))
        page.update()
            
    # Avvio con schermata di login
    page.add(LoginView(page, on_login_success))
        
if __name__ == "__main__":
    ft.run(main=main)