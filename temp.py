import os
import json
from fanta_obj import Team
from api_nba import NbaDataManager
from ui_court import ROLE_CONFIGS


TARGET_DATE = "2026-10-03"

def calculate_all_team_scores(target_date: str, role_config=ROLE_CONFIGS):
    api_mgr = NbaDataManager(player_ids=[])
    teams_scores = {}
    teams_path = os.path.join("data", "fanta_teams.json")
    with open(teams_path, "r", encoding="utf-8") as f:
        for t_name, roles_map in json.load(f).items():
            team = Team(t_name)
            team.update_team_scores_for_date(api_mgr, target_date, list(roles_map.keys()), roles_map)
            teams_scores[t_name] = team.calculate_total_score(role_config)

    return teams_scores


print(calculate_all_team_scores(TARGET_DATE))

