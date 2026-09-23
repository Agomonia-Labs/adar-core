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

from src.adar.config import (
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


def _stable_doc_id(chunk: ScrapedChunk) -> str:
    """
    Deterministic Firestore doc ID for a chunk, so re-ingestion OVERWRITES the
    existing record for the same team/player/season instead of creating a new
    document next to it.

    This must be built only from a chunk's stable IDENTITY fields (who/where/
    when the record is about) — never from chunk.content or any field whose
    VALUE changes between ingestion runs. The previous implementation hashed
    `content[:80]`, and for "team" (standings) and "player_season" chunks the
    mutable stat values (wins/losses/points, batting/bowling numbers) fall
    inside that first-80-character slice. So every time a team's record or a
    player's stats changed, the hash — and therefore the doc_id — changed too,
    and `.set()` wrote a brand-new document instead of overwriting the old
    one. That's the direct cause of duplicate standings/stat records: nothing
    ever pointed at the same doc twice.
    """
    import hashlib

    pt = chunk.page_type
    if pt == "team":
        # One doc per team-per-division-per-season, regardless of that
        # team's current wins/losses/points.
        key_parts = ["team", chunk.team_id or chunk.team_name, chunk.season_id, chunk.league_id]
    elif pt == "player_season":
        # One doc per player-per-team-per-season, regardless of that
        # player's current batting/bowling numbers.
        key_parts = ["player_season", chunk.player_id or chunk.player_name,
                     chunk.season_id, chunk.team_id or chunk.league_id]
    elif pt == "player":
        key_parts = ["player", chunk.player_id or chunk.player_name]
    elif pt == "team_schedule":
        key_parts = ["team_schedule", chunk.team_id or chunk.team_name, chunk.season_id]
    else:
        # rules / faq / about — static reference text with no mutable
        # per-run stats, so content-keyed is still appropriate here.
        key_parts = [pt, chunk.source_url, chunk.content[:80]]

    id_src = ":".join(str(p) for p in key_parts)
    return hashlib.md5(id_src.encode()).hexdigest()


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
                doc_id = _stable_doc_id(chunk)
                await db.collection(collection).document(doc_id).set(doc)
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