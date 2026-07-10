#!/usr/bin/env python3
"""
Delete ARCL Firestore data for one season only.

Dry-run by default. Pass --execute to actually delete.

Examples:
  cd ~/project/adar-core

  # Preview Spring 2025 deletes
  PYTHONPATH=$PWD python /path/to/delete_arcl_season_data.py --season-id 67

  # Delete Spring 2025 data after reviewing output
  PYTHONPATH=$PWD python /path/to/delete_arcl_season_data.py --season-id 67 --execute
"""

import argparse
import asyncio
import os
from collections import defaultdict

from dotenv import load_dotenv
from google.cloud import firestore


DEFAULT_COLLECTIONS = [
    "arcl_teams",
    "arcl_player_seasons",
    "arcl_team_schedules",
]


def parse_collections(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


async def main():
    parser = argparse.ArgumentParser(
        description="Dry-run/delete ARCL Firestore records for one season_id."
    )
    parser.add_argument("--env-file", default=".env", help="dotenv file to load")
    parser.add_argument("--season-id", type=int, required=True, help="ARCL season_id to delete")
    parser.add_argument(
        "--league-id",
        type=int,
        help="Optional league_id filter if you only want one division/league",
    )
    parser.add_argument(
        "--collections",
        default=",".join(DEFAULT_COLLECTIONS),
        help="Comma-separated Firestore collections to scan/delete",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=450,
        help="Firestore delete batch size. Must be 1-500. Default: 450.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete matching docs. Omit for dry-run.",
    )
    args = parser.parse_args()

    if args.batch_size < 1 or args.batch_size > 500:
        raise SystemExit("--batch-size must be between 1 and 500.")

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
        query = db.collection(collection).where("season_id", "==", args.season_id)
        if args.league_id is not None:
            query = query.where("league_id", "==", args.league_id)

        async for doc in query.stream():
            data = doc.to_dict() or {}
            data["doc_id"] = doc.id
            data.pop("embedding", None)
            matches.append((collection, doc.reference, data))
            counts[collection] += 1

    print("ARCL season delete")
    print(f"Project: {project_id} | Database: {database}")
    print(f"season_id={args.season_id}")
    print(f"league_id={args.league_id if args.league_id is not None else 'ALL'}")
    print(f"Collections: {', '.join(collections)}")
    print(f"Matches: {len(matches)}")

    if counts:
        print("\nMatches by collection:")
        for collection in collections:
            if counts[collection]:
                print(f"- {collection}: {counts[collection]}")

    if matches:
        print("\nSample documents:")
        for collection, _, row in matches[:50]:
            label = row.get("team_name") or row.get("player_name") or row.get("content", "")[:60]
            print(
                f"- {collection}/{row['doc_id']} | "
                f"season={row.get('season')} ({row.get('season_id')}) | "
                f"league_id={row.get('league_id')} | "
                f"division={row.get('division')} | {label}"
            )
        if len(matches) > 50:
            print(f"... {len(matches) - 50} more not shown")

    if not args.execute:
        print("\nDry run only. Re-run with --execute to delete these records.")
        return

    deleted = 0
    refs = [ref for _, ref, _ in matches]
    for start in range(0, len(refs), args.batch_size):
        batch_refs = refs[start:start + args.batch_size]
        batch = db.batch()
        for ref in batch_refs:
            batch.delete(ref)
        await batch.commit()
        deleted += len(batch_refs)
        print(f"Deleted batch {start // args.batch_size + 1}: {deleted}/{len(refs)}")

    print(f"\nDeleted {deleted} records for season_id={args.season_id}.")


if __name__ == "__main__":
    asyncio.run(main())
