"""
domains/geetabitan/ingestion/geetabitan_embedder.py
Embeds each song using db.py's embed_text() (gemini-embedding-001, 768-dim)
and upserts the document into Firestore geetabitan_songs collection.

Uses the same embedding function as the rest of the system so vector search
distances are consistent at query time.
"""

import hashlib

from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector

from src.adar.db import embed_text, get_db
from domains.geetabitan.config import (
    EMBED_TEXT_TEMPLATE,
    FIRESTORE_COLLECTION,
)
from domains.geetabitan.data.raag_metadata import TAAL_DATA


async def embed_and_store(song: dict) -> str:
    """Embed one song and upsert into Firestore.
    Returns the Firestore document ID (MD5 hash for deduplication)."""
    db = get_db()

    # Build embed text from template — includes raag_mood for fuzzy search
    text = EMBED_TEXT_TEMPLATE.format(
        title     = song.get("title",     ""),
        first_line= song.get("first_line",""),
        paryay    = song.get("paryay",    ""),
        raag      = song.get("raag",      ""),
        taal      = song.get("taal",      ""),
        raag_mood = song.get("raag_mood", ""),
    )

    # MD5 dedup key — same pattern as arcl_embedder.py
    doc_id = hashlib.md5(
        f"geetabitan_song_{song['id']}_{song['title']}".encode("utf-8")
    ).hexdigest()

    # Use db.py's embed_text — same model (gemini-embedding-001) as vector_search
    vector = await embed_text(text, task_type="RETRIEVAL_DOCUMENT")

    # Enrich taal_beats from reference data if not already set
    taal_meta  = TAAL_DATA.get(song.get("taal", ""), {})
    taal_beats = song.get("taal_beats") or taal_meta.get("beats", 0)

    await db.collection(FIRESTORE_COLLECTION).document(doc_id).set({
        # Identity
        "id":          song["id"],
        "firestore_id": doc_id,
        "source_url":  song.get("source_url", ""),
        # Core text
        "title":       song["title"],
        "first_line":  song.get("first_line",  ""),
        "stanzas":     song.get("stanzas",     []),
        "lyrics_full": song.get("lyrics_full", ""),
        "excerpt":     (song.get("lyrics_full") or "")[:400],
        # Classification
        "paryay":      song.get("paryay",      ""),
        # Raag metadata
        "raag":        song.get("raag",        ""),
        "raag_family": song.get("raag_family", ""),
        "raag_time":   song.get("raag_time",   ""),
        "raag_mood":   song.get("raag_mood",   ""),
        # Taal metadata
        "taal":        song.get("taal",        ""),
        "taal_beats":  taal_beats,
        "taal_vibhag": taal_meta.get("vibhag", ""),
        "taal_tempo":  taal_meta.get("tempo",  ""),
        # Vector — wrapped in Firestore Vector type for find_nearest
        "embedding":   Vector(vector),
        "source":      "geetabitan",
    })
    return doc_id