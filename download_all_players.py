from api_nba import NbaDataManager


nba = NbaDataManager(player_ids=[])
nba.download_all_players()
