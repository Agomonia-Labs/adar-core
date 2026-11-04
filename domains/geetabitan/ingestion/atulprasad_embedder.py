"""
domains/geetabitan/ingestion/atulprasad_embedder.py
Embeds each Atulprasad Sen song using db.py's embed_text() (gemini-embedding-001,
768-dim — the same model/dimension as geetabitan_embedder.py, nazrul_embedder.py
and rajanikanta_embedder.py, so vector-search distances stay comparable across
every composer's collection) and upserts the document into Firestore's
atulprasad_songs collection.

This never touches FIRESTORE_COLLECTION / geetabitan_songs,
NAZRUL_FIRESTORE_COLLECTION / nazrulgeeti_songs, or
RAJANIKANTA_FIRESTORE_COLLECTION / rajanikanta_songs — Rabindra Sangeet,
Nazrul Geeti and Rajanikanta Sen stay completely untouched.
"""

import hashlib

from google.cloud.firestore_v1.vector import Vector

from src.adar.db import embed_text, get_db
from domains.geetabitan.config import (
    ATULPRASAD_EMBED_TEXT_TEMPLATE,
    ATULPRASAD_FIRESTORE_COLLECTION,
)
from domains.geetabitan.data.raag_metadata import TAAL_DATA


async def embed_and_store(song: dict) -> str:
    """Embed one Atulprasad Sen song and upsert into Firestore.
    Returns the Firestore document ID (MD5 hash for deduplication)."""
    db = get_db()

    text = ATULPRASAD_EMBED_TEXT_TEMPLATE.format(
        title     = song.get("title",     ""),
        first_line= song.get("first_line",""),
        raag      = song.get("raag",      ""),
        taal      = song.get("taal",      ""),
    )

    doc_id = hashlib.md5(
        f"atulprasad_song_{song['id']}_{song['title']}".encode("utf-8")
    ).hexdigest()

    vector = await embed_text(text, task_type="RETRIEVAL_DOCUMENT")

    # TAAL_DATA is keyed by clean single-term taal names (e.g. "ত্রিতাল");
    # a descriptive taal sentence (one song, see the loader's docstring)
    # simply won't match and taal_meta stays empty — never guessed.
    taal_meta  = TAAL_DATA.get(song.get("taal", ""), {})
    taal_beats = song.get("taal_beats") or taal_meta.get("beats", 0)

    await db.collection(ATULPRASAD_FIRESTORE_COLLECTION).document(doc_id).set({
        # Identity
        "id":          song["id"],
        "firestore_id": doc_id,
        "source_url":  song.get("source_note", ""),
        # Core text
        "title":       song["title"],
        "first_line":  song.get("first_line",  ""),
        "stanzas":     song.get("stanzas",     []),
        "lyrics_full": song.get("lyrics_full", ""),
        "excerpt":     (song.get("lyrics_full") or "")[:400],
        # Atulprasad has no comprehensive category/book scheme (confirmed on
        # only 4 of 205 songs — see atulprasad_lyrics_loader.py's docstring),
        # so "paryay"/"anga" are carried through as sparse sourced metadata
        # only, never used for grouping or filtering like Nazrul/Rajanikanta's
        # "category" field.
        "paryay":      song.get("paryay",      ""),
        "anga":        song.get("anga",        ""),
        # Raag metadata — family/time/mood aren't backfilled for Atulprasad
        # (no confirmed source), left blank rather than guessed
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
        "source":      "atulprasad",
    })
    return doc_id


async def embed_all(songs: list[dict]) -> list[dict]:
    """Embed every song in the list, returning it with firestore_id set on each."""
    total = len(songs)
    print(f"Embedding {total} Atulprasad Sen songs into Firestore …")
    for i, song in enumerate(songs):
        song["firestore_id"] = await embed_and_store(song)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{total} embedded")
    print("Atulprasad Sen embedding complete.")
    return songs
