from tools.rules_tools import vector_search_rules, get_rule_section, get_faq_answer
from tools.player_tools import (
    search_player, get_player_stats, get_player_season_stats,
    get_player_teams, get_top_performers,
)
from tools.team_tools import (
    search_team, get_team_history, get_team_season,
    get_team_players_live, get_team_schedule,
    get_teams_in_division, get_season_info, list_divisions,
    get_team_career_stats, get_match_scorecard, get_player_dismissals,
)
from tools.live_tools import get_standings, get_schedule, get_recent_results, get_announcements

TOOL_REGISTRY = {
    # Rules
    "vector_search_rules":     vector_search_rules,
    "get_rule_section":        get_rule_section,
    "get_faq_answer":          get_faq_answer,
    # Player
    "search_player":           search_player,
    "get_player_stats":        get_player_stats,
    "get_player_season_stats": get_player_season_stats,
    "get_player_teams":        get_player_teams,
    "get_top_performers":      get_top_performers,
    # Team
    "search_team":             search_team,
    "get_team_history":        get_team_history,
    "get_team_season":         get_team_season,
    "get_team_schedule":       get_team_schedule,
    "get_teams_in_division":   get_teams_in_division,
    "get_season_info":         get_season_info,
    "list_divisions":          list_divisions,
    "get_match_scorecard":     get_match_scorecard,
    "get_player_dismissals":   get_player_dismissals,
    "get_team_career_stats":   get_team_career_stats,
    "get_team_players_live":   get_team_players_live,
    # Live
    "get_standings":           get_standings,
    "get_schedule":            get_schedule,
    "get_recent_results":      get_recent_results,
    "get_announcements":       get_announcements,
}

__all__ = ["TOOL_REGISTRY"]