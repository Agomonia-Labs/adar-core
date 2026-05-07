"""
ingest_team.py — Auto-ingest team data when a new team subscribes.

Called by payments.py after checkout.session.completed.
Runs teamstats ingestion for the team's league + current season.
Updates ingestion_status in Firestore throughout.
"""
import asyncio
import logging
from datetime import datetime, timezone



logger = logging.getLogger(__name__)

CURRENT_SEASON = 69  # Spring 2026
ARCL_BASE      = "https://www.arcl.org"


async def _find_team_league(team_name: str) -> int | None:
    """Search all ARCL divisions to find which league_id this team plays in."""
    import httpx
    import re
    from bs4 import BeautifulSoup

    all_league_ids = [2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
    name_lower = team_name.strip().lower()

    async with httpx.AsyncClient(timeout=20) as client:
        for league_id in all_league_ids:
            try:
                url = (f"{ARCL_BASE}/Pages/UI/DivHome.aspx"
                       f"?league_id={league_id}&season_id={CURRENT_SEASON}")
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                soup = BeautifulSoup(r.text, "html.parser")
                for link in soup.find_all("a", href=True):
                    if "TeamStats" in link["href"]:
                        if link.text.strip().lower() == name_lower:
                            logger.info(f"Found {team_name} in league_id={league_id}")
                            return league_id
            except Exception as e:
                logger.debug(f"League {league_id} search error: {e}")
                continue

    logger.warning(f"Could not find league for team: {team_name}")
    return None


async def _update_status(db, team_id: str, status: str, message: str = ""):
    """Update ingestion_status in Firestore."""
    try:
        await db.collection("adar_teams").document(team_id).update({
            "ingestion_status":  status,
            "ingestion_message": message,
            "ingestion_updated": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.warning(f"Could not update ingestion status: {e}")


async def ingest_team_data(team_id: str, team_name: str):
    """
    Main entry point — called after Stripe checkout.session.completed.
    Scrapes and indexes teamstats for the team's current season league.
    """
    from google.cloud import firestore
    import os
    _project  = os.environ.get("GCP_PROJECT_ID", "bdas-493785")
    _database = os.environ.get("FIRESTORE_DATABASE", "tigers-arcl")
    db = firestore.AsyncClient(project=_project, database=_database)

    logger.info(f"Auto-ingest started: team={team_id} name={team_name}")
    await _update_status(db, team_id, "running", "Finding your team on arcl.org...")

    try:
        # 1. Find which league this team plays in
        league_id = await _find_team_league(team_name)

        if not league_id:
            # Fallback — ingest all leagues for current season (slower but complete)
            league_id = None
            await _update_status(db, team_id, "running",
                                 "Running full season ingest — takes ~4 minutes...")
        else:
            await _update_status(db, team_id, "running",
                                 f"Scraping your league stats — takes ~2 minutes...")

        # 2. Run teamstats ingestion for this league + current season
        try:
            from domains.arcl.ingestion.run_ingestion import run as run_ingestion
        except ImportError:
            from ingestion.run_ingestion import run as run_ingestion

        league_arg = str(league_id) if league_id else ""
        season_arg = str(CURRENT_SEASON)

        logger.info(f"Running ingestion: league={league_arg} season={season_arg}")
        try:
            await run_ingestion(
                only="teamstats",
                leagues=league_arg,
                seasons=season_arg,
                tenant="arcl",
            )
        except TypeError:
            # Some versions of run() don't have tenant param
            await run_ingestion(
                only="teamstats",
                leagues=league_arg,
                seasons=season_arg,
            )

        await _update_status(db, team_id, "complete",
                             "Your team stats are ready!")
        logger.info(f"Auto-ingest complete: team={team_id}")

    except Exception as e:
        logger.error(f"Auto-ingest failed for {team_id}: {e}", exc_info=True)
        await _update_status(db, team_id, "failed",
                             "Ingest failed — your data will be available after the next weekly update.")