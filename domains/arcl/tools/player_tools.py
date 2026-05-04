import logging
from src.adar.db import vector_search, get_player_season_records
from src.adar.config import ARCL_PLAYERS_COLLECTION, ARCL_PLAYER_SEASON_COLLECTION

logger = logging.getLogger(__name__)


def _fmt_batting(r: dict) -> dict:
    return {
        "runs":         r.get("batting_runs", 0),
        "balls_faced":  r.get("batting_balls", 0),
        "fours":        r.get("batting_fours", 0),
        "sixes":        r.get("batting_sixes", 0),
        "strike_rate":  r.get("batting_sr", 0.0),
        "highest":      r.get("batting_highest", 0),
        "average":      r.get("batting_average", 0.0),
        "innings":      r.get("batting_innings", 0),
    }


def _fmt_bowling(r: dict) -> dict:
    return {
        "overs":        r.get("bowling_overs", 0.0),
        "maidens":      r.get("bowling_maidens", 0),
        "runs_given":   r.get("bowling_runs", 0),
        "wickets":      r.get("bowling_wickets", 0),
        "average":      r.get("bowling_average", 0.0),
        "economy":      r.get("bowling_economy", 0.0),
        "strike_rate":  r.get("bowling_sr", 0.0),
        "best_figures": r.get("bowling_best", "-"),
    }


async def search_player(name: str, top_k: int = 5) -> list[dict]:
    """
    Search for an ARCL player by name.

    Args:
        name: Player name (full or partial)
        top_k: Number of results
    """
    results = await vector_search(ARCL_PLAYERS_COLLECTION, name, top_k=top_k)
    return [
        {
            "player_name": r.get("player_name", ""),
            "player_id":   r.get("player_id", ""),
            "profile_url": r.get("profile_url", r.get("source", "")),
            "teams":       r.get("teams", []),
            "seasons":     r.get("seasons", []),
        }
        for r in results
    ]


async def get_player_stats(player_name: str, season: str = "") -> dict:
    """
    Get batting AND bowling stats for a player, presented separately.
    If season provided returns stats for that season, otherwise most recent.

    Args:
        player_name: Player full name
        season: Season e.g. 'Spring 2025' (optional)

    Returns:
        Dict with player_id, batting stats section, bowling stats section
    """
    records = await get_player_season_records(player_name, season=season if season else None)

    if not records and season:
        all_records = await get_player_season_records(player_name)
        records = [r for r in all_records if season.lower() in r.get("season", "").lower()]

    if not records:
        vs = await vector_search(ARCL_PLAYER_SEASON_COLLECTION, f"{player_name} {season}".strip(), top_k=10)
        records = [r for r in vs if player_name.lower() in r.get("player_name", "").lower()]
        if season:
            records = [r for r in records if season.lower() in r.get("season", "").lower()]

    if records:
        r = records[0]
        return {
            "player_name": r.get("player_name", player_name),
            "player_id":   r.get("player_id", ""),
            "profile_url": r.get("profile_url", ""),
            "team":        r.get("team_name", ""),
            "season":      r.get("season", season),
            "division":    r.get("division", ""),
            "batting":     _fmt_batting(r),
            "bowling":     _fmt_bowling(r),
        }

    career = await vector_search(ARCL_PLAYERS_COLLECTION, player_name, top_k=1)
    if career:
        r = career[0]
        return {
            "player_name": r.get("player_name", player_name),
            "player_id":   r.get("player_id", ""),
            "profile_url": r.get("profile_url", r.get("source", "")),
            "teams":       r.get("teams", []),
            "seasons":     r.get("seasons", []),
            "note": "Detailed per-season batting/bowling stats not yet indexed. Run teamstats ingestion.",
        }

    return {
        "error":      f"No stats found for '{player_name}'.",
        "suggestion": "Check arcl.org/Pages/UI/Players.aspx for the correct player name.",
    }


async def get_player_season_stats(player_name: str) -> list[dict]:
    """
    Get a player's batting AND bowling stats broken down by season.

    Args:
        player_name: Player full name

    Returns:
        List of seasons, each with separate batting and bowling sections
    """
    records = await get_player_season_records(player_name)

    if not records:
        vs = await vector_search(ARCL_PLAYER_SEASON_COLLECTION, player_name, top_k=20)
        records = [r for r in vs if player_name.lower() in r.get("player_name", "").lower()]

    if not records:
        return [{
            "message":    f"No season stats found for '{player_name}'.",
            "suggestion": "Run: python -m ingestion.run_ingestion --only teamstats",
        }]

    seasons = []
    for r in records:
        seasons.append({
            "season":      r.get("season", ""),
            "team":        r.get("team_name", ""),
            "division":    r.get("division", ""),
            "player_id":   r.get("player_id", ""),
            "profile_url": r.get("profile_url", ""),
            "batting":     _fmt_batting(r),
            "bowling":     _fmt_bowling(r),
        })

    seasons.sort(key=lambda x: x.get("season", ""), reverse=True)
    return seasons


async def get_player_teams(player_name: str) -> dict:
    """
    Get all teams and seasons a player has represented.

    Args:
        player_name: Player name
    """
    records = await get_player_season_records(player_name)
    teams   = list({r.get("team_name", "") for r in records if r.get("team_name")})
    seasons = list({r.get("season", "")    for r in records if r.get("season")})

    if not teams:
        career = await vector_search(ARCL_PLAYERS_COLLECTION, player_name, top_k=1)
        if career:
            teams   = career[0].get("teams", [])
            seasons = career[0].get("seasons", [])

    player_id   = records[0].get("player_id", "") if records else ""
    profile_url = records[0].get("profile_url", "") if records else ""

    return {
        "player_name":       player_name,
        "player_id":         player_id,
        "profile_url":       profile_url,
        "teams_represented": sorted(set(teams)),
        "seasons_played":    sorted(set(seasons), reverse=True),
        "total_teams":       len(set(teams)),
        "total_seasons":     len(set(seasons)),
        "note": "A player can only represent one team per season per ARCL rules.",
    }


async def get_top_performers(
    category: str = "batting",
    season: str = "",
    division: str = "",
    limit: int = 10,
) -> list[dict]:
    """
    Get top batting or bowling performers.

    Args:
        category: 'batting' (sort by runs) or 'bowling' (sort by wickets)
        season: Season filter e.g. 'Spring 2025' (optional)
        division: Division filter e.g. 'Div H' (optional)
        limit: Number of results

    Returns:
        List sorted by runs (batting) or wickets (bowling),
        each entry with separate batting and bowling stats
    """
    query = f"top {category} performers ARCL {season} {division}".strip()
    records = await vector_search(ARCL_PLAYER_SEASON_COLLECTION, query, top_k=80)

    if season:
        records = [r for r in records if season.lower() in r.get("season", "").lower()]
    if division:
        records = [r for r in records if division.lower() in r.get("division", "").lower()]

    performers = []
    seen = set()
    for r in records:
        key = (r.get("player_name", ""), r.get("season", ""))
        if key in seen:
            continue
        seen.add(key)
        performers.append({
            "player_name": r.get("player_name", ""),
            "player_id":   r.get("player_id", ""),
            "team":        r.get("team_name", ""),
            "season":      r.get("season", ""),
            "division":    r.get("division", ""),
            "batting":     _fmt_batting(r),
            "bowling":     _fmt_bowling(r),
        })

    sort_key = ("batting", "runs") if category == "batting" else ("bowling", "wickets")
    performers.sort(key=lambda x: x.get(sort_key[0], {}).get(sort_key[1], 0), reverse=True)
    return performers[:limit]