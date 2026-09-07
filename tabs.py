import flet as ft
from ui_court import MainDashboard


tabs = ft.Tabs(
    length=2,
    expand=True,
    content=ft.Column(
        expand=True,
        controls=[
            ft.TabBar(
                tabs=[
                    ft.Tab(label="Overview"),
                    ft.Tab(label="Settings", icon=ft.Icons.SETTINGS),
                ]
            ),
            ft.TabBarView(
                expand=True,
                controls=[
                    ft.Column(
                        controls=ft.Text("Overview content"),
                    ),
                    ft.Column(
                        controls=ft.Text("Settings content"),
                    ),
                ],
            ),
        ],
    ),
)


def main(page: ft.Page):
    page.add(MainDashboard(current_team))
    page.add(tabs)


if __name__ == "__main__":
    ft.run(main)