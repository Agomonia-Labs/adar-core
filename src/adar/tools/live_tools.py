import logging
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from src.adar.config import settings, CRICCLUBS_STANDINGS, CRICCLUBS_SCHEDULE, CRICCLUBS_RESULTS

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def _fetch_page(url: str) -> BeautifulSoup | None:
    """Fetch a page and return a BeautifulSoup object."""
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


async def get_standings(division: str = "") -> dict:
    """
    Get the current ARCL points table / standings.

    Reads from Firestore (arcl_teams, kept fresh by the arcl.org
    ingestion pipeline — domains/arcl/ingestion/run_ingestion.py
    --only standings) via the same team_tools.get_teams_in_division()
    that team_agent already uses. No live cricclubs.com dependency —
    that endpoint (CRICCLUBS_STANDINGS) pointed at the wrong page
    (listMatches.do, a match list, not a points table) and was
    identical to CRICCLUBS_RESULTS; it was unreliable for this.

    Args:
        division: Division name e.g. 'Division A', 'Div H', 'Women' (optional)

    Returns:
        Dict with standings table data and fetch timestamp
    """
    from domains.arcl.tools.team_tools import get_teams_in_division

    teams = await get_teams_in_division(division)

    if not teams:
        return {
            "standings": [],
            "division": division or "All divisions",
            "source": "Firestore arcl_teams (arcl.org ingestion)",
            "fetched_at": datetime.utcnow().isoformat(),
            "note": (
                f"No standings found for '{division}'. Data may not be "
                "ingested yet for this division/season — run "
                "`python -m ingestion.run_ingestion --only standings "
                "--leagues <id>` from domains/arcl."
            ) if division else "No standings found.",
        }

    standings = [
        {
            "position": i + 1,
            "team": t.get("team_name"),
            "played": (t.get("wins", 0) or 0) + (t.get("losses", 0) or 0),
            "won": t.get("wins", 0),
            "lost": t.get("losses", 0),
            "points": t.get("points", 0),
        }
        for i, t in enumerate(teams)
    ]

    return {
        "standings": standings,
        "division": division or "All divisions",
        "source": "Firestore arcl_teams (arcl.org ingestion)",
        "fetched_at": datetime.utcnow().isoformat(),
    }


async def get_schedule(team_name: str = "", upcoming_only: bool = True) -> dict:
    """
    Get the ARCL match schedule.

    Args:
        team_name: Filter by team name (optional)
        upcoming_only: If True, return only future matches

    Returns:
        Dict with list of scheduled matches
    """
    soup = await _fetch_page(CRICCLUBS_SCHEDULE)
    if not soup:
        return {
            "error": "Could not fetch schedule from cricclubs.com",
            "fetched_at": datetime.utcnow().isoformat(),
        }

    matches = []
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows[1:]:
            cols = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cols) >= 3:
                match = {
                    "date": cols[0] if cols else "",
                    "home_team": cols[1] if len(cols) > 1 else "",
                    "away_team": cols[2] if len(cols) > 2 else "",
                    "venue": cols[3] if len(cols) > 3 else "",
                    "time": cols[4] if len(cols) > 4 else "",
                }
                if team_name:
                    if team_name.lower() in match["home_team"].lower() or \
                       team_name.lower() in match["away_team"].lower():
                        matches.append(match)
                else:
                    matches.append(match)
        if matches:
            break

    return {
        "matches": matches[:20],
        "team_filter": team_name or "All teams",
        "source": CRICCLUBS_SCHEDULE,
        "fetched_at": datetime.utcnow().isoformat(),
    }


async def get_recent_results(team_name: str = "", limit: int = 10) -> dict:
    """
    Get recent ARCL match results.

    Args:
        team_name: Filter by team name (optional)
        limit: Number of results to return

    Returns:
        Dict with list of recent match results
    """
    soup = await _fetch_page(CRICCLUBS_RESULTS)
    if not soup:
        return {
            "error": "Could not fetch results from cricclubs.com",
            "fetched_at": datetime.utcnow().isoformat(),
        }

    results = []
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows[1:]:
            cols = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cols) >= 3:
                result = {
                    "date": cols[0] if cols else "",
                    "home_team": cols[1] if len(cols) > 1 else "",
                    "away_team": cols[2] if len(cols) > 2 else "",
                    "result": cols[3] if len(cols) > 3 else "",
                    "scorecard_url": "",
                }
                # Extract scorecard link if present
                link = row.find("a", href=True)
                if link:
                    result["scorecard_url"] = f"https://cricclubs.com{link['href']}"

                if team_name:
                    if team_name.lower() in result["home_team"].lower() or \
                       team_name.lower() in result["away_team"].lower():
                        results.append(result)
                else:
                    results.append(result)
        if results:
            break

    return {
        "results": results[:limit],
        "team_filter": team_name or "All teams",
        "source": CRICCLUBS_RESULTS,
        "fetched_at": datetime.utcnow().isoformat(),
    }


async def get_announcements() -> dict:
    """
    Get the latest ARCL announcements from the home page.

    Returns:
        Dict with list of recent announcements
    """
    url = f"{settings.ARCL_BASE_URL}"
    soup = await _fetch_page(url)
    if not soup:
        return {
            "error": "Could not fetch announcements from arcl.org",
            "fetched_at": datetime.utcnow().isoformat(),
        }

    announcements = []

    # Try to find announcement sections
    for tag in soup.find_all(["div", "section", "li"]):
        text = tag.get_text(strip=True)
        if len(text) > 20 and len(text) < 500:
            class_str = " ".join(tag.get("class", []))
            if any(kw in class_str.lower() for kw in ["announce", "news", "alert", "notice"]):
                announcements.append({"text": text, "source": url})

    # Fallback — grab paragraphs with useful content
    if not announcements:
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 30:
                announcements.append({"text": text, "source": url})
            if len(announcements) >= 5:
                break

    return {
        "announcements": announcements[:10],
        "source": url,
        "fetched_at": datetime.utcnow().isoformat(),
    }
