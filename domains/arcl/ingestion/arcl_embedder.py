"""
Embeds scraped ARCL content chunks using gemini-embedding-001
truncated to 768 dimensions (Firestore max is 2048).
"""
import asyncio
import logging
from typing import Optional

from google import genai
from google.genai import types as genai_types
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector

from config import (
    settings,
    ARCL_RULES_COLLECTION,
    ARCL_PLAYERS_COLLECTION,
    ARCL_TEAMS_COLLECTION,
    ARCL_FAQ_COLLECTION,
    ARCL_PLAYER_SEASON_COLLECTION,
)
from ingestion.arcl_scraper import ScrapedChunk

logger = logging.getLogger(__name__)

ARCL_TEAM_SCHEDULE_COLLECTION = "arcl_team_schedules"

COLLECTION_MAP = {
    "rules":          ARCL_RULES_COLLECTION,
    "faq":            ARCL_FAQ_COLLECTION,
    "player":         ARCL_PLAYERS_COLLECTION,
    "player_season":  ARCL_PLAYER_SEASON_COLLECTION,
    "team":           ARCL_TEAMS_COLLECTION,
    "team_schedule":  ARCL_TEAM_SCHEDULE_COLLECTION,   # match schedule per team per season
    "about":          ARCL_RULES_COLLECTION,
}

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM   = 768

_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    return _client


async def embed_text(text: str) -> Optional[list[float]]:
    try:
        client = get_client()
        response = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=genai_types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=EMBEDDING_DIM,
            ),
        )
        return response.embeddings[0].values
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return None


def _chunk_to_doc(chunk: ScrapedChunk, embedding: list[float]) -> dict:
    doc = {
        "content":    chunk.content,
        "source":     chunk.source_url,
        "page_type":  chunk.page_type,
        "embedding":  Vector(embedding),
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    if chunk.section:      doc["section"]      = chunk.section
    if chunk.player_name:  doc["player_name"]  = chunk.player_name
    if chunk.player_id:    doc["player_id"]    = chunk.player_id
    if chunk.team_name:    doc["team_name"]    = chunk.team_name
    if chunk.team_id:      doc["team_id"]      = chunk.team_id
    if chunk.season:       doc["season"]       = chunk.season
    if chunk.season_id:    doc["season_id"]    = chunk.season_id
    if chunk.league_id:    doc["league_id"]    = chunk.league_id
    if chunk.division:     doc["division"]     = chunk.division
    if chunk.extra:
        # Promote key fields from extra to top-level for direct querying
        for key in ("player_id", "profile_url", "team_id", "batting_runs",
                    "batting_matches", "batting_highest", "batting_fifties",
                    "batting_hundreds", "batting_average", "bowling_wickets",
                    "bowling_economy", "bowling_average", "bowling_best"):
            if key in chunk.extra and chunk.extra[key]:
                doc[key] = chunk.extra[key]
        doc.update(chunk.extra)
    return doc


async def embed_and_store_chunks(
    chunks: list[ScrapedChunk],
    batch_size: int = 10,
    delay_seconds: float = 0.5,
) -> dict[str, int]:
    db = firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=settings.FIRESTORE_DATABASE,
    )

    stored_counts: dict[str, int] = {}
    failed = 0

    logger.info(f"Embedding and storing {len(chunks)} chunks...")

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        logger.info(f"Batch {i // batch_size + 1}/{(len(chunks) + batch_size - 1) // batch_size} ({len(batch)} chunks)...")

        for chunk in batch:
            collection = COLLECTION_MAP.get(chunk.page_type, ARCL_RULES_COLLECTION)
            embedding = await embed_text(chunk.content)
            if not embedding:
                failed += 1
                continue

            doc = _chunk_to_doc(chunk, embedding)
            try:
                _, ref = await db.collection(collection).add(doc)
                stored_counts[collection] = stored_counts.get(collection, 0) + 1
            except Exception as e:
                logger.error(f"Store failed: {e}")
                failed += 1

        if i + batch_size < len(chunks):
            await asyncio.sleep(delay_seconds)

    logger.info(f"Stored: {stored_counts} | Failed: {failed}")
    return stored_counts


async def clear_collection(collection: str):
    """
    Delete all docs using list_documents() which fetches refs only.
    Avoids index timeouts from full collection stream.
    """
    db = firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=settings.FIRESTORE_DATABASE,
    )
    count = 0
    batch = db.batch()
    async for doc_ref in db.collection(collection).list_documents():
        batch.delete(doc_ref)
        count += 1
        if count % 400 == 0:
            await batch.commit()
            batch = db.batch()
            logger.info(f"  Deleted {count} docs from {collection}...")
    if count % 400 != 0:
        await batch.commit()
    logger.info(f"Cleared {count} docs from {collection}")