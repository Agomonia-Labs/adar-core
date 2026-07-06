#!/usr/bin/env python3
"""
Delete stale duplicate ARCL standings records for a given league and season.

Keeps one "best/current" record per team:
  1. highest completed games = wins + losses + tied
  2. highest points
  3. newest created_at, if present

Dry-run by default. Pass --execute to delete.

Example:
  cd ~/project/adar-core
  PYTHONPATH=$PWD python /path/to/cleanup_stale_standings.py --season-id 69 --league-id 10
  PYTHONPATH=$PWD python /path/to/cleanup_stale_standings.py --season-id 69 --league-id 10 --execute
"""

import argparse
import asyncio
import os
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv
from google.cloud import firestore


def as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def created_sort_value(value) -> float:
    if not value:
        return 0.0
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def record_score(row: dict) -> tuple[int, int, float]:
    completed_games = (
        as_int(row.get("wins"))
        + as_int(row.get("losses"))
        + as_int(row.get("tied"))
    )
    return (
        completed_games,
        as_int(row.get("points")),
        created_sort_value(row.get("created_at")),
    )


async def main():
    parser = argparse.ArgumentParser(
        description="Remove stale duplicate ARCL standings records."
    )
    parser.add_argument("--env-file", default=".env", help="dotenv file to load")
    parser.add_argument("--collection", default="", help="Firestore collection name")
    parser.add_argument("--season-id", type=int, required=True, help="ARCL season_id")
    parser.add_argument("--league-id", type=int, required=True, help="ARCL league_id")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete stale records. Omit for dry-run.",
    )
    args = parser.parse_args()

    load_dotenv(args.env_file, override=True)

    project_id = os.getenv("GCP_PROJECT_ID")
    database = os.getenv("FIRESTORE_DATABASE")
    collection = args.collection or os.getenv("ARCL_TEAMS_COLLECTION", "arcl_teams")

    if not project_id or not database:
        raise SystemExit("Missing GCP_PROJECT_ID or FIRESTORE_DATABASE")

    db = firestore.AsyncClient(project=project_id, database=database)
    query = (
        db.collection(collection)
        .where("season_id", "==", args.season_id)
        .where("league_id", "==", args.league_id)
    )

    by_team = defaultdict(list)
    async for doc in query.stream():
        data = doc.to_dict()
        data["doc_id"] = doc.id
        data.pop("embedding", None)
        team_name = data.get("team_name") or "(unknown team)"
        by_team[team_name].append((doc.reference, data))

    stale = []
    kept = []

    for team_name, docs in sorted(by_team.items()):
        if len(docs) == 1:
            kept.append(docs[0][1])
            continue

        keep_ref, keep_row = max(docs, key=lambda item: record_score(item[1]))
        kept.append(keep_row)
        for ref, row in docs:
            if ref.id != keep_ref.id:
                stale.append((ref, row, keep_row))

    print(
        f"Scanned {sum(len(v) for v in by_team.values())} records "
        f"for season_id={args.season_id}, league_id={args.league_id}"
    )
    print(f"Teams: {len(by_team)} | Keeping: {len(kept)} | Stale duplicates: {len(stale)}")

    if stale:
        print("\nStale records:")
        for _, row, keep_row in stale:
            print(
                f"- DELETE {row['doc_id']} | {row.get('team_name')} | "
                f"W-L-T {row.get('wins')}-{row.get('losses')}-{row.get('tied', 0)} "
                f"Pts {row.get('points')} | keep {keep_row['doc_id']} "
                f"({keep_row.get('wins')}-{keep_row.get('losses')}-{keep_row.get('tied', 0)}, "
                f"Pts {keep_row.get('points')})"
            )

    if not args.execute:
        print("\nDry run only. Re-run with --execute to delete stale records.")
        return

    for ref, _, _ in stale:
        await ref.delete()

    print(f"\nDeleted {len(stale)} stale records.")


if __name__ == "__main__":
    asyncio.run(main())
