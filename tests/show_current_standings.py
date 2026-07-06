#!/usr/bin/env python3
"""
Show current ARCL standings stored in Firestore for a given league and season.

If duplicate snapshots still exist, this script shows the same "best/current"
record selection used by cleanup_stale_standings.py:
  1. highest completed games = wins + losses + tied
  2. highest points
  3. newest created_at, if present

Example:
  cd ~/project/adar-core
  PYTHONPATH=$PWD python /path/to/show_current_standings.py --season-id 69 --league-id 10
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


def display_value(value, width: int, align: str = "left") -> str:
    text = str(value if value is not None else "")
    if len(text) > width:
        text = text[: width - 1] + "…"
    return text.rjust(width) if align == "right" else text.ljust(width)


async def main():
    parser = argparse.ArgumentParser(description="Show current ARCL standings.")
    parser.add_argument("--env-file", default=".env", help="dotenv file to load")
    parser.add_argument("--collection", default="", help="Firestore collection name")
    parser.add_argument("--season-id", type=int, required=True, help="ARCL season_id")
    parser.add_argument("--league-id", type=int, required=True, help="ARCL league_id")
    parser.add_argument(
        "--team",
        default="",
        help="Optional team-name filter, case-insensitive substring match",
    )
    parser.add_argument(
        "--show-doc-id",
        action="store_true",
        help="Include Firestore document ID in output",
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
        if args.team and args.team.lower() not in team_name.lower():
            continue
        by_team[team_name].append(data)

    rows = []
    duplicate_count = 0
    for team_name, docs in by_team.items():
        duplicate_count += max(0, len(docs) - 1)
        current = max(docs, key=record_score)
        rows.append(current)

    rows.sort(
        key=lambda row: (
            as_int(row.get("points")),
            as_int(row.get("wins")),
            -as_int(row.get("losses")),
        ),
        reverse=True,
    )

    print(
        f"Current standings from {collection} "
        f"for season_id={args.season_id}, league_id={args.league_id}"
    )
    print(f"Teams: {len(rows)} | Duplicate snapshots ignored: {duplicate_count}")

    if not rows:
        return

    headers = ["Rank", "Team", "P", "W", "L", "T", "Pts", "Div"]
    widths = [5, 28, 3, 3, 3, 3, 5, 10]
    if args.show_doc_id:
        headers.append("Doc ID")
        widths.append(24)

    print()
    print(" ".join(display_value(h, w) for h, w in zip(headers, widths)))
    print(" ".join("-" * w for w in widths))

    for idx, row in enumerate(rows, start=1):
        played = (
            as_int(row.get("wins"))
            + as_int(row.get("losses"))
            + as_int(row.get("tied"))
        )
        values = [
            idx,
            row.get("team_name", ""),
            played,
            row.get("wins", 0),
            row.get("losses", 0),
            row.get("tied", 0),
            row.get("points", 0),
            row.get("division", ""),
        ]
        aligns = ["right", "left", "right", "right", "right", "right", "right", "left"]
        if args.show_doc_id:
            values.append(row.get("doc_id", ""))
            aligns.append("left")
        print(
            " ".join(
                display_value(value, width, align)
                for value, width, align in zip(values, widths, aligns)
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
