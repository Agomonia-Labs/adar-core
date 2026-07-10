#!/usr/bin/env python3
"""
Delete ARCL records whose division is Sponsored Div.

Dry-run by default. Pass --execute to actually delete.

Examples:
  cd ~/project/adar-core

  # Preview Sponsored Div records for Spring 2026
  PYTHONPATH=$PWD python /path/to/delete_sponsored_div_data.py --season-id 69

  # Delete after reviewing the dry-run output
  PYTHONPATH=$PWD python /path/to/delete_sponsored_div_data.py --season-id 69 --execute

  # If needed, scan all seasons intentionally
  PYTHONPATH=$PWD python /path/to/delete_sponsored_div_data.py --all-seasons
"""

import argparse
import asyncio
import os
import re
from collections import defaultdict

from dotenv import load_dotenv
from google.cloud import firestore


DEFAULT_COLLECTIONS = [
    "arcl_teams",
    "arcl_player_seasons",
    "arcl_team_schedules",
]


def normalize_division(value) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_sponsored_div(value) -> bool:
    normalized = normalize_division(value)
    #if "sponsor" in normalized:
    #    print(normalized)
    #return normalized in ["sponsored", "sponsored_div"]
    return normalized in {
        "sponsored",
        "sponsor div",
        "sponsored division",
        "sponsors",
    }


def parse_collections(raw: str) -> list[str]:
    if not raw:
        return DEFAULT_COLLECTIONS
    return [item.strip() for item in raw.split(",") if item.strip()]


async def matching_docs(db, collection: str, season_id: int | None, league_id: int | None):
    query = db.collection(collection)
    if season_id is not None:
        query = query.where("season_id", "==", season_id)
    if league_id is not None:
        query = query.where("league_id", "==", league_id)

    async for doc in query.stream():
        data = doc.to_dict() or {}
        if is_sponsored_div(data.get("division")):
            data["doc_id"] = doc.id
            data.pop("embedding", None)
            yield doc.reference, data


async def main():
    parser = argparse.ArgumentParser(
        description="Dry-run/delete ARCL Firestore records with division Sponsored Div."
    )
    parser.add_argument("--env-file", default=".env", help="dotenv file to load")
    parser.add_argument(
        "--collections",
        default=",".join(DEFAULT_COLLECTIONS),
        help="Comma-separated Firestore collections to scan",
    )
    parser.add_argument("--season-id", type=int, help="Optional ARCL season_id filter")
    parser.add_argument("--league-id", type=int, help="Optional ARCL league_id filter")
    parser.add_argument(
        "--all-seasons",
        action="store_true",
        help="Allow scanning/deleting without --season-id",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete matching docs. Omit for dry-run.",
    )
    args = parser.parse_args()

    if args.season_id is None and not args.all_seasons:
        raise SystemExit("Pass --season-id, or pass --all-seasons intentionally.")

    load_dotenv(args.env_file, override=True)

    project_id = os.getenv("GCP_PROJECT_ID")
    database = os.getenv("FIRESTORE_DATABASE")
    if not project_id or not database:
        raise SystemExit("Missing GCP_PROJECT_ID or FIRESTORE_DATABASE")

    db = firestore.AsyncClient(project=project_id, database=database)
    collections = parse_collections(args.collections)

    matches = []
    counts = defaultdict(int)

    for collection in collections:
        async for ref, row in matching_docs(db, collection, args.season_id, args.league_id):
            matches.append((collection, ref, row))
            counts[collection] += 1

    print("Sponsored Div cleanup")
    print(f"Project: {project_id} | Database: {database}")
    print(f"Collections: {', '.join(collections)}")
    print(f"season_id={args.season_id if args.season_id is not None else 'ALL'}")
    print(f"league_id={args.league_id if args.league_id is not None else 'ALL'}")
    print(f"Matches: {len(matches)}")

    if counts:
        print("\nMatches by collection:")
        for collection in collections:
            if counts[collection]:
                print(f"- {collection}: {counts[collection]}")

    if matches:
        print("\nDocuments:")
        for collection, _, row in matches:
            label = row.get("team_name") or row.get("player_name") or row.get("content", "")[:60]
            print(
                f"- {collection}/{row['doc_id']} | "
                f"division={row.get('division')} | "
                f"season={row.get('season')} ({row.get('season_id')}) | "
                f"league_id={row.get('league_id')} | {label}"
            )

    if not args.execute:
        print("\nDry run only. Re-run with --execute to delete these records.")
        return

    for _, ref, _ in matches:
        await ref.delete()

    print(f"\nDeleted {len(matches)} Sponsored Div records.")


if __name__ == "__main__":
    asyncio.run(main())
