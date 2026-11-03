"""
domains/geetabitan/ingestion/rajanikanta_embedder.py
Embeds each Rajanikanta Sen song using db.py's embed_text() (gemini-embedding-001,
768-dim — the same model/dimension as geetabitan_embedder.py and nazrul_embedder.py,
so vector-search distances stay comparable across all three collections) and
upserts the document into Firestore's rajanikanta_songs collection.

This never touches FIRESTORE_COLLECTION / geetabitan_songs or
NAZRUL_FIRESTORE_COLLECTION / nazrulgeeti_songs — Rabindra Sangeet and Nazrul
Geeti stay completely untouched.
"""

import hashlib

from google.cloud.firestore_v1.vector import Vector

from src.adar.db import embed_text, get_db
from domains.geetabitan.config import (
    RAJANIKANTA_EMBED_TEXT_TEMPLATE,
    RAJANIKANTA_FIRESTORE_COLLECTION,
)
from domains.geetabitan.data.raag_metadata import TAAL_DATA


async def embed_and_store(song: dict) -> str:
    """Embed one Rajanikanta Sen song and upsert into Firestore.
    Returns the Firestore document ID (MD5 hash for deduplication)."""
    db = get_db()

    text = RAJANIKANTA_EMBED_TEXT_TEMPLATE.format(
        title     = song.get("title",     ""),
        first_line= song.get("first_line",""),
        category  = song.get("category",  ""),
        raag      = song.get("raag",      ""),
        taal      = song.get("taal",      ""),
    )

    doc_id = hashlib.md5(
        f"rajanikanta_song_{song['id']}_{song['title']}".encode("utf-8")
    ).hexdigest()

    vector = await embed_text(text, task_type="RETRIEVAL_DOCUMENT")

    taal_meta  = TAAL_DATA.get(song.get("taal", ""), {})
    taal_beats = song.get("taal_beats") or taal_meta.get("beats", 0)

    await db.collection(RAJANIKANTA_FIRESTORE_COLLECTION).document(doc_id).set({
        # Identity
        "id":          song["id"],
        "firestore_id": doc_id,
        "source_url":  song.get("source_note", ""),
        # Core text
        "title":       song["title"],
        "subtitle":    song.get("subtitle",    ""),
        "first_line":  song.get("first_line",  ""),
        "stanzas":     song.get("stanzas",     []),
        "lyrics_full": song.get("lyrics_full", ""),
        "excerpt":     (song.get("lyrics_full") or "")[:400],
        # Classification — Rajanikanta's own book name, not paryay
        "category":    song.get("category",    ""),
        # Raag metadata — mood/family/time aren't backfilled for Rajanikanta
        # yet (no confirmed source), left blank rather than guessed
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
        "source":      "rajanikanta",
    })
    return doc_id


async def embed_all(songs: list[dict]) -> list[dict]:
    """Embed every song in the list, returning it with firestore_id set on each."""
    total = len(songs)
    print(f"Embedding {total} Rajanikanta Sen songs into Firestore …")
    for i, song in enumerate(songs):
        song["firestore_id"] = await embed_and_store(song)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{total} embedded")
    print("Rajanikanta Sen embedding complete.")
    return songs
