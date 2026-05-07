import logging
from typing import Optional

from src.adar.db import vector_search, direct_query
from src.adar.config import ARCL_PLAYERS_COLLECTION, ARCL_PLAYER_SEASON_COLLECTION

logger = logging.getLogger(__name__)


def _fmt_batting(r: dict) -> dict:
    """Only include fields that have real data (non-zero or non-empty)."""
    out = {}
    if r.get("batting_innings"):  out["innings"]      = r["batting_innings"]
    if r.get("batting_runs"):     out["runs"]         = r["batting_runs"]
    if r.get("batting_balls"):    out["balls_faced"]  = r["batting_balls"]
    if r.get("batting_fours"):    out["fours"]        = r["batting_fours"]
    if r.get("batting_sixes"):    out["sixes"]        = r["batting_sixes"]
    if r.get("batting_sr"):       out["strike_rate"]  = r["batting_sr"]
    if r.get("batting_highest"):  out["highest"]      = r["batting_highest"]
    if r.get("batting_average"):  out["average"]      = r["batting_average"]
    if r.get("batting_not_out"):  out["not_out"]      = r["batting_not_out"]
    # Always include runs even if 0
    if "runs" not in out:         out["runs"]         = r.get("batting_runs", 0)
    return out


def _fmt_bowling(r: dict) -> dict:
    """Only include fields that have real data."""
    out = {}
    if r.get("bowling_innings"):  out["innings"]      = r["bowling_innings"]
    if r.get("bowling_overs"):    out["overs"]        = r["bowling_overs"]
    if r.get("bowling_maidens") is not None: out["maidens"] = r["bowling_maidens"]
    if r.get("bowling_runs"):     out["runs_given"]   = r["bowling_runs"]
    if r.get("bowling_wickets") is not None: out["wickets"] = r["bowling_wickets"]
    if r.get("bowling_average"):  out["average"]      = r["bowling_average"]
    if r.get("bowling_economy"):  out["economy"]      = r["bowling_economy"]
    if r.get("bowling_sr"):       out["strike_rate"]  = r["bowling_sr"]
    if r.get("bowling_best"):     out["best_figures"] = r["bowling_best"]
    # Always include wickets even if 0
    if "wickets" not in out:      out["wickets"]      = r.get("bowling_wickets", 0)
    return out


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


async def get_top_performers_live(
    category: str = "batting",
    season: str = "Spring 2026",
    division: str = "",
    limit: int = 10,
) -> list[dict]:
    """
    Get top batting or bowling performers by scraping ALL teams in a division live.
    Use this when a division is specified — fetches real data from arcl.org for every team.

    Args:
        category: 'batting' or 'bowling'
        season:   Season name e.g. 'Spring 2026'
        division: Division filter e.g. 'Div H'
        limit:    Number of results to return
    """
    from domains.arcl.tools.team_tools import get_team_players_live, ARCL_BASE, _resolve_season
    from src.adar.config import settings
    import httpx
    from bs4 import BeautifulSoup

    # Resolve season ID
    season_id, season_resolved = _resolve_season(season)
    if not season_id:
        season_id = 69  # default Spring 2026

    # Division → league_id map
    DIV_TO_LEAGUE = {
        "H": 10, "DIV H": 10, "G": 9, "DIV G": 9,
        "A": 7, "B": 7, "C": 7, "D": 7, "E": 8, "F": 8,
        "WOMEN": 2, "KIDS": 4, "CHAMPIONS": 6,
    }
    div_key = division.strip().upper().replace("DIB","DIV").replace("DIV ","").replace("DIVISION ","")
    league_id = DIV_TO_LEAGUE.get(div_key) or DIV_TO_LEAGUE.get(division.strip().upper(), 10)

    import re as _re
    from bs4 import BeautifulSoup

    # Scrape all teams AND their team_ids directly from DivHome.aspx
    teams_found = []
    try:
        url = f"{ARCL_BASE}/Pages/UI/DivHome.aspx?league_id={league_id}&season_id={season_id}"
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(r.text, "html.parser")
            seen_ids = set()
            for link in soup.find_all("a", href=True):
                if "TeamStats" in link["href"]:
                    name = link.text.strip()
                    tid = _re.search(r"team_id=(\d+)", link["href"])
                    if name and tid:
                        team_id = int(tid.group(1))
                        if team_id not in seen_ids:
                            seen_ids.add(team_id)
                            teams_found.append({"name": name, "team_id": team_id})
    except Exception as e:
        logger.warning(f"Failed to get teams from DivHome: {e}")

    if not teams_found:
        return [{"error": f"No teams found in {division} for {season}. Check division name (e.g. 'Div H')."}]

    logger.info(f"Found {len(teams_found)} teams in {division}")

    # Fetch TeamStats directly using team_id — no name lookup needed
    all_players = []
    async with httpx.AsyncClient(timeout=30) as client:
        for team in teams_found[:14]:
            team_name = team["name"]
            team_id   = team["team_id"]
            try:
                stats_url = (f"{ARCL_BASE}/Pages/UI/TeamStats.aspx"
                             f"?team_id={team_id}&league_id={league_id}&season_id={season_id}")
                r = await client.get(stats_url, headers={"User-Agent": "Mozilla/5.0"})
                soup = BeautifulSoup(r.text, "html.parser")
                tables = soup.find_all("table")
                # Table index 2 = batting, table index 3 = bowling (confirmed structure)
                tbl_idx = 2 if category == "batting" else 3
                if len(tables) <= tbl_idx:
                    continue
                tbl = tables[tbl_idx]
                rows = tbl.find_all("tr")
                if len(rows) < 2:
                    continue
                headers = [th.text.strip().lower() for th in rows[0].find_all(["th","td"])]
                for row in rows[1:]:
                    cols = [td.text.strip() for td in row.find_all("td")]
                    if not cols or len(cols) < 3:
                        continue
                    try:
                        if category == "batting":
                            all_players.append({
                                "player_name": cols[0] if len(cols)>0 else "",
                                "team_name":   team_name,
                                "innings":     int(cols[3]) if len(cols)>3 else 0,
                                "runs":        int(cols[4]) if len(cols)>4 else 0,
                                "balls":       int(cols[5]) if len(cols)>5 else 0,
                                "fours":       int(cols[6]) if len(cols)>6 else 0,
                                "sixes":       int(cols[7]) if len(cols)>7 else 0,
                                "strike_rate": float(cols[8]) if len(cols)>8 else 0.0,
                            })
                        else:
                            all_players.append({
                                "player_name": cols[0] if len(cols)>0 else "",
                                "team_name":   team_name,
                                "innings":     int(cols[3]) if len(cols)>3 else 0,
                                "overs":       float(cols[4]) if len(cols)>4 else 0.0,
                                "wickets":     int(cols[8]) if len(cols)>8 else 0,
                                "economy":     float(cols[9]) if len(cols)>9 else 0.0,
                            })
                    except (ValueError, IndexError):
                        continue
            except Exception as e:
                logger.warning(f"Failed to scrape {team_name}: {e}")
                continue

    if not all_players:
        return [{"error": f"No player data found for {division} {season}"}]

    # Sort by runs or wickets
    sort_field = "runs" if category == "batting" else "wickets"
    all_players.sort(key=lambda x: int(x.get(sort_field, 0) or 0), reverse=True)

    # Deduplicate by player name + team
    seen = set()
    result = []
    for p in all_players:
        key = (p.get("player_name", ""), p.get("team_name", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "player_name": p.get("player_name", ""),
            "team":        p.get("team_name", ""),
            "season":      season,
            "division":    division,
            "runs":        p.get("runs", 0),
            "innings":     p.get("innings", 0),
            "balls":       p.get("balls", 0),
            "fours":       p.get("fours", 0),
            "sixes":       p.get("sixes", 0),
            "strike_rate": p.get("strike_rate", 0.0),
            "wickets":     p.get("wickets", 0),
            "overs":       p.get("overs", 0),
            "economy":     p.get("economy", 0.0),
        })
        if len(result) >= limit:
            break

    return result


async def get_player_season_records(
    player_name: str,
    season: Optional[str] = None,
) -> list[dict]:
    """Direct lookup for player season stats by exact player_name."""
    from config import ARCL_PLAYER_SEASON_COLLECTION
    filters = {"player_name": player_name}
    if season:
        filters["season"] = season
    records = await direct_query(ARCL_PLAYER_SEASON_COLLECTION, filters, limit=50)
    records.sort(key=lambda x: x.get("season", ""), reverse=True)
    return records