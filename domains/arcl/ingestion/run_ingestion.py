"""
ARCL ingestion pipeline — all data from arcl.org.

Usage:
  python -m ingestion.run_ingestion                          # full pipeline
  python -m ingestion.run_ingestion --only rules
  python -m ingestion.run_ingestion --only players
  python -m ingestion.run_ingestion --only standings
  python -m ingestion.run_ingestion --only teamstats
  python -m ingestion.run_ingestion --only teamstats --leagues 7,8
  python -m ingestion.run_ingestion --only teamstats --seasons 60,61,62,63
  python -m ingestion.run_ingestion --only players --letters A,B,C
  python -m ingestion.run_ingestion --clear

Parallel terminal examples (split by league):
  Terminal 1: python -m ingestion.run_ingestion --only teamstats --leagues 7
  Terminal 2: python -m ingestion.run_ingestion --only teamstats --leagues 8
  Terminal 3: python -m ingestion.run_ingestion --only teamstats --leagues 2,9,10
  Terminal 4: python -m ingestion.run_ingestion --only players --letters A,B,C,D,E
  Terminal 5: python -m ingestion.run_ingestion --only players --letters F,G,H,I,J,K

Parallel terminal examples (split by season range):
  Terminal 1: python -m ingestion.run_ingestion --only teamstats --seasons 35,36,37,38,39,40,41,42,43,44,45
  Terminal 2: python -m ingestion.run_ingestion --only teamstats --seasons 46,47,48,49,50,51,52,53,54,55
  Terminal 3: python -m ingestion.run_ingestion --only teamstats --seasons 56,57,58,59,60,61,62,63,64,65,66,67,68,69
"""
import asyncio
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from domains.arcl.ingestion.arcl_scraper import (
    scrape_arcl_rules,
    scrape_arcl_players,
    scrape_arcl_teams,
    scrape_all_standings,
    scrape_all_standings_and_stats,
    LEAGUE_IDS,
)
from domains.arcl.ingestion.arcl_embedder import embed_and_store_chunks, clear_collection
from config import (
    ARCL_RULES_COLLECTION,
    ARCL_PLAYERS_COLLECTION,
    ARCL_TEAMS_COLLECTION,
    ARCL_FAQ_COLLECTION,
    ARCL_PLAYER_SEASON_COLLECTION,
)

ARCL_TEAM_SCHEDULE_COLLECTION = "arcl_team_schedules"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def run(
    only: str = "",
    clear: bool = False,
    letters: str = "",
    leagues: str = "",
    seasons: str = "",
):
    import string
    alpha = letters.upper().replace(",", "").replace(" ", "") if letters else string.ascii_uppercase

    # Parse league IDs
    league_ids = None
    if leagues:
        league_ids = [int(l.strip()) for l in leagues.split(",") if l.strip()]
        logger.info(f"Filtering to leagues: {league_ids} ({[LEAGUE_IDS.get(l, l) for l in league_ids]})")

    # Parse season IDs — accepts both numeric IDs and season names
    season_ids = None
    if seasons:
        from config import ARCL_SEASON_NAME_TO_ID, ARCL_SEASON_MAP
        raw_seasons = [s.strip() for s in seasons.split(",") if s.strip()]
        season_ids = []
        for s in raw_seasons:
            if s.isdigit():
                season_ids.append(int(s))
            else:
                # Try to match season name e.g. "Spring 2025" or "fall 2025"
                matched = None
                for name, sid in ARCL_SEASON_NAME_TO_ID.items():
                    if s.lower() == name.lower():
                        matched = sid
                        break
                if matched:
                    season_ids.append(matched)
                else:
                    logger.warning(f"Unknown season '{s}' — skipping. "
                                   f"Use season_id or exact name e.g. 'Spring 2025'")

        # Log with names
        season_names = [ARCL_SEASON_MAP.get(sid, str(sid)) for sid in season_ids]
        logger.info(f"Filtering to seasons: {list(zip(season_ids, season_names))}")

    total = {}

    if only in ("", "rules", "faq"):
        if clear:
            await clear_collection(ARCL_RULES_COLLECTION)
            await clear_collection(ARCL_FAQ_COLLECTION)
        logger.info("=== Scraping rules + FAQ ===")
        chunks = await scrape_arcl_rules()
        stored = await embed_and_store_chunks(chunks)
        total.update(stored)

    if only in ("", "players"):
        if clear:
            await clear_collection(ARCL_PLAYERS_COLLECTION)
        logger.info(f"=== Scraping players (letters: {alpha}) ===")
        chunks = await scrape_arcl_players(letters=alpha)
        stored = await embed_and_store_chunks(chunks)
        total.update(stored)

    if only in ("", "teams"):
        if clear:
            await clear_collection(ARCL_TEAMS_COLLECTION)
        logger.info("=== Scraping team names ===")
        chunks = await scrape_arcl_teams(letters=alpha)
        stored = await embed_and_store_chunks(chunks)
        total.update(stored)

    if only in ("", "standings"):
        if clear:
            await clear_collection(ARCL_TEAMS_COLLECTION)
        logger.info("=== Scraping standings ===")
        chunks = await scrape_all_standings(
            league_filter=league_ids,
            season_filter=season_ids,
        )
        stored = await embed_and_store_chunks(chunks)
        total.update(stored)

    if only == "teamstats":
        # Don't clear when running in parallel — each terminal writes to the same collection
        if clear and not leagues and not seasons:
            logger.info("Clearing collections before full teamstats run...")
            await clear_collection(ARCL_TEAMS_COLLECTION)
            await clear_collection(ARCL_PLAYER_SEASON_COLLECTION)
            await clear_collection(ARCL_TEAM_SCHEDULE_COLLECTION)
        elif clear and (leagues or seasons):
            logger.warning(
                "--clear skipped when --leagues or --seasons is set "
                "(would delete data from other parallel terminals)"
            )

        logger.info("=== Scraping standings + TeamStats ===")
        standings_chunks, player_chunks = await scrape_all_standings_and_stats(
            scrape_team_stats_too=True,
            league_filter=league_ids,
            season_filter=season_ids,
        )
        stored = await embed_and_store_chunks(standings_chunks + player_chunks)
        total.update(stored)

    # Full pipeline also includes teamstats
    if only == "":
        if clear:
            await clear_collection(ARCL_PLAYER_SEASON_COLLECTION)
        standings_chunks, player_chunks = await scrape_all_standings_and_stats(
            scrape_team_stats_too=True,
            league_filter=league_ids,
            season_filter=season_ids,
        )
        stored = await embed_and_store_chunks(standings_chunks + player_chunks)
        total.update(stored)

    logger.info("=== Ingestion complete ===")
    for col, count in total.items():
        logger.info(f"  {col}: {count} documents stored")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARCL ingestion pipeline")
    parser.add_argument(
        "--only",
        choices=["rules", "faq", "players", "teams", "standings", "teamstats"],
        default="",
    )
    parser.add_argument("--clear", action="store_true",
        help="Clear collection before indexing. Skipped if --leagues or --seasons set.")
    parser.add_argument("--clear-only", action="store_true",
        help="Only clear the collections for --only phase, do not run ingestion. "
             "Safe to run once before starting parallel terminals.")
    parser.add_argument("--letters", default="",
        help="Player letters to scrape e.g. A,B,C or ABC")
    parser.add_argument("--leagues", default="",
        help="Comma-separated league IDs to scrape e.g. 7,8 (7=Men A-D, 8=Men E-H, 2=Women, 9=Men G-H, 10=Men H)")
    parser.add_argument("--seasons", default="",
        help="Comma-separated season IDs to scrape e.g. 60,61,62,63")
    args = parser.parse_args()
    if args.clear_only:
        async def do_clear():
            targets = {
                "rules":      [ARCL_RULES_COLLECTION, ARCL_FAQ_COLLECTION],
                "faq":        [ARCL_FAQ_COLLECTION],
                "players":    [ARCL_PLAYERS_COLLECTION],
                "teams":      [ARCL_TEAMS_COLLECTION],
                "standings":  [ARCL_TEAMS_COLLECTION],
                "teamstats":  [ARCL_TEAMS_COLLECTION, ARCL_PLAYER_SEASON_COLLECTION, ARCL_TEAM_SCHEDULE_COLLECTION],
                "":           [ARCL_RULES_COLLECTION, ARCL_FAQ_COLLECTION,
                               ARCL_PLAYERS_COLLECTION, ARCL_TEAMS_COLLECTION,
                               ARCL_PLAYER_SEASON_COLLECTION, ARCL_TEAM_SCHEDULE_COLLECTION],
            }
            collections = targets.get(args.only, [ARCL_TEAMS_COLLECTION, ARCL_PLAYER_SEASON_COLLECTION])
            for col in collections:
                logger.info(f"Clearing {col}...")
                await clear_collection(col)
            logger.info("Clear complete. Safe to start parallel ingestion terminals.")
        asyncio.run(do_clear())
    else:
        asyncio.run(run(
            only=args.only,
            clear=args.clear,
            letters=args.letters,
            leagues=args.leagues,
            seasons=args.seasons,
        ))