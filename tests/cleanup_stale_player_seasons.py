#!/usr/bin/env python3
"""
Delete stale duplicate ARCL player-season stat records for a given league
and season (arcl_player_seasons / ARCL_PLAYER_SEASON_COLLECTION).

Mirrors cleanup_stale_standings.py's logic, adapted for player stats. Groups
by (player_id or player_name, team_id) rather than just player -- a player
can legitimately have separate records in the same season if they played
for more than one team, so team_id must stay part of the identity or those
real records would be wrongly deleted as "duplicates" alongside the actual
stale ones.

Keeps one "best/current" record per (player, team):
  1. highest recorded activity = batting_innings + bowling_overs
     (the player-stat equivalent of "games played" for team standings --
     the more of the season a record has captured, the more current it is)
  2. newest created_at, if present

Dry-run by default. Pass --execute to delete.

Example:
  cd ~/project/adar-core
  PYTHONPATH=$PWD python /path/to/cleanup_stale_player_seasons.py --season-id 70 --league-id 10
  PYTHONPATH=$PWD python /path/to/cleanup_stale_player_seasons.py --season-id 70 --league-id 10 --execute
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


def as_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


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


def record_score(row: dict) -> tuple[float, float]:
    activity = as_int(row.get("batting_innings")) + as_float(row.get("bowling_overs"))
    return (
        activity,
        created_sort_value(row.get("created_at")),
    )


def identity_key(row: dict) -> tuple:
    player_key = row.get("player_id") or row.get("player_name") or "(unknown player)"
    team_key = row.get("team_id") or row.get("team_name") or "(unknown team)"
    return (player_key, team_key)


async def main():
    parser = argparse.ArgumentParser(
        description="Remove stale duplicate ARCL player-season stat records."
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
    collection = args.collection or os.getenv("ARCL_PLAYER_SEASON_COLLECTION", "arcl_player_seasons")

    if not project_id or not database:
        raise SystemExit("Missing GCP_PROJECT_ID or FIRESTORE_DATABASE")

    db = firestore.AsyncClient(project=project_id, database=database)
    query = (
        db.collection(collection)
        .where("season_id", "==", args.season_id)
        .where("league_id", "==", args.league_id)
    )

    by_identity = defaultdict(list)
    async for doc in query.stream():
        data = doc.to_dict()
        data["doc_id"] = doc.id
        data.pop("embedding", None)
        by_identity[identity_key(data)].append((doc.reference, data))

    stale = []
    kept = []

    for key, docs in sorted(by_identity.items(), key=lambda kv: str(kv[0])):
        if len(docs) == 1:
            kept.append(docs[0][1])
            continue

        keep_ref, keep_row = max(docs, key=lambda item: record_score(item[1]))
        kept.append(keep_row)
        for ref, row in docs:
            if ref.id != keep_ref.id:
                stale.append((ref, row, keep_row))

    print(
        f"Scanned {sum(len(v) for v in by_identity.values())} records "
        f"for season_id={args.season_id}, league_id={args.league_id}"
    )
    print(f"Player-team pairs: {len(by_identity)} | Keeping: {len(kept)} | Stale duplicates: {len(stale)}")

    if stale:
        print("\nStale records:")
        for _, row, keep_row in stale:
            print(
                f"- DELETE {row['doc_id']} | {row.get('player_name')} ({row.get('team_name')}) | "
                f"innings {row.get('batting_innings')} overs {row.get('bowling_overs')} | "
                f"keep {keep_row['doc_id']} "
                f"(innings {keep_row.get('batting_innings')} overs {keep_row.get('bowling_overs')})"
            )

    if not args.execute:
        print("\nDry run only. Re-run with --execute to delete stale records.")
        return

    for ref, _, _ in stale:
        await ref.delete()

    print(f"\nDeleted {len(stale)} stale records.")


if __name__ == "__main__":
    asyncio.run(main())
