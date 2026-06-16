"""Export open menu curation queue items."""

from __future__ import annotations

import csv
from pathlib import Path

from domains.restaurants.db import connect


async def export_curation_queue(path: Path) -> dict[str, int]:
    conn = await connect()
    try:
        rows = await conn.fetch(
            """
            select
              q.id::text as queue_id,
              q.restaurant_id::text as restaurant_id,
              r.name as restaurant_name,
              r.website_url,
              q.source_url,
              q.reason,
              q.priority,
              q.details,
              q.created_at
            from menu_curation_queue q
            join restaurants r on r.id = q.restaurant_id
            where q.status = 'open'
            order by q.priority asc, q.created_at asc
            """
        )
    finally:
        await conn.close()

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "queue_id",
                "restaurant_id",
                "restaurant_name",
                "website_url",
                "source_url",
                "reason",
                "priority",
                "details",
                "created_at",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
    return {"rows": len(rows), "path": str(path)}

