"""Embedding pipeline for restaurant menu items."""

from __future__ import annotations

import asyncio
import random
from domains.restaurants.db import (
    connect,
    menu_items_missing_embeddings,
    update_menu_embedding,
)


def embedding_text(item: dict) -> str:
    parts = [
        item.get("name") or "",
        item.get("description") or "",
        item.get("category") or "",
        " ".join(item.get("cuisine_tags") or []),
        " ".join(item.get("meal_tags") or []),
        " ".join(item.get("dietary_tags") or []),
    ]
    return " ".join(part for part in parts if part).strip()


async def embed_with_retry(
    text: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
    max_attempts: int = 5,
    base_delay: float = 1.0,
) -> list[float] | None:
    from src.adar.db import embed_text

    for attempt in range(1, max_attempts + 1):
        try:
            return await embed_text(text, task_type=task_type)
        except Exception as exc:
            message = str(exc)
            retryable = any(
                token in message
                for token in [
                    "503",
                    "UNAVAILABLE",
                    "429",
                    "RESOURCE_EXHAUSTED",
                    "timeout",
                    "temporarily",
                ]
            )
            if not retryable or attempt == max_attempts:
                print(f"Embedding failed after {attempt} attempt(s): {message[:300]}")
                return None

            sleep_for = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            print(
                f"Embedding attempt {attempt}/{max_attempts} failed; "
                f"retrying in {sleep_for:.1f}s. Error: {message[:180]}"
            )
            await asyncio.sleep(sleep_for)

    return None


async def embed_missing_menu_items(limit: int = 100, delay: float = 0.25) -> int:
    conn = await connect()
    updated = 0
    skipped = 0
    try:
        rows = await menu_items_missing_embeddings(conn, limit=limit)
        total = len(rows)
        for row in rows:
            item = dict(row)
            text = embedding_text(item)
            if not text:
                skipped += 1
                continue

            embedding = await embed_with_retry(text, task_type="RETRIEVAL_DOCUMENT")
            if embedding is None:
                skipped += 1
                continue

            await update_menu_embedding(conn, item["id"], embedding)
            updated += 1
            if updated % 25 == 0 or updated == total:
                print(f"Embedded {updated}/{total} menu items; skipped={skipped}")
            if delay:
                await asyncio.sleep(delay)
    finally:
        await conn.close()
    if skipped:
        print(f"Embedding complete with skips: embedded={updated}, skipped={skipped}")
    return updated
