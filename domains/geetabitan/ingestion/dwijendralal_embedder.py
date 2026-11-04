"""
domains/geetabitan/ingestion/dwijendralal_embedder.py
Embeds each Dwijendralal Roy song using db.py's embed_text()
(gemini-embedding-001, 768-dim — the same model/dimension as
geetabitan_embedder.py, nazrul_embedder.py, rajanikanta_embedder.py and
atulprasad_embedder.py, so vector-search distances stay comparable across
every composer's collection) and upserts the document into Firestore's
dwijendralal_songs collection.

This never touches FIRESTORE_COLLECTION / geetabitan_songs,
NAZRUL_FIRESTORE_COLLECTION / nazrulgeeti_songs,
RAJANIKANTA_FIRESTORE_COLLECTION / rajanikanta_songs, or
ATULPRASAD_FIRESTORE_COLLECTION / atulprasad_songs — Rabindra Sangeet,
Nazrul Geeti, Rajanikanta Sen and Atulprasad Sen stay completely untouched.
"""

import hashlib

from google.cloud.firestore_v1.vector import Vector

from src.adar.db import embed_text, get_db
from domains.geetabitan.config import (
    DWIJENDRALAL_EMBED_TEXT_TEMPLATE,
    DWIJENDRALAL_FIRESTORE_COLLECTION,
)
from domains.geetabitan.data.raag_metadata import TAAL_DATA


async def embed_and_store(song: dict) -> str:
    """Embed one Dwijendralal Roy song and upsert into Firestore.
    Returns the Firestore document ID (MD5 hash for deduplication)."""
    db = get_db()

    text = DWIJENDRALAL_EMBED_TEXT_TEMPLATE.format(
        title     = song.get("title",     ""),
        first_line= song.get("first_line",""),
        category  = song.get("category",  ""),
        raag      = song.get("raag",      ""),
        taal      = song.get("taal",      ""),
    )

    doc_id = hashlib.md5(
        f"dwijendralal_song_{song['id']}_{song['title']}".encode("utf-8")
    ).hexdigest()

    vector = await embed_text(text, task_type="RETRIEVAL_DOCUMENT")

    # TAAL_DATA is keyed by standard classical taal names; a couple of
    # Dwijendralal's in-text taal labels (e.g. "মধ্যমান", "ভরতঙ") aren't in
    # that table, so taal_meta simply stays empty for those rather than
    # guessed — see dwijendralal_lyrics_loader.py / the raw data's
    # ocr_confidence_note for the "ভরতঙ" OCR-uncertainty flag specifically.
    taal_meta  = TAAL_DATA.get(song.get("taal", ""), {})
    taal_beats = song.get("taal_beats") or taal_meta.get("beats", 0)

    await db.collection(DWIJENDRALAL_FIRESTORE_COLLECTION).document(doc_id).set({
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
        # Classification — the play (নাটক) the song was written for, not a
        # paryay. A secondary genre label is carried through where present
        # but is not used for grouping/filtering.
        "category":    song.get("category",    ""),
        "genre":       song.get("genre",        ""),
        # Raag metadata — family/time/mood aren't backfilled (no confirmed
        # source for this composer yet), left blank rather than guessed
        "raag":        song.get("raag",        ""),
        "raag_family": song.get("raag_family", ""),
        "raag_time":   song.get("raag_time",   ""),
        "raag_mood":   song.get("raag_mood",   ""),
        # Taal metadata
        "taal":        song.get("taal",        ""),
        "taal_beats":  taal_beats,
        "taal_vibhag": taal_meta.get("vibhag", ""),
        "taal_tempo":  taal_meta.get("tempo",  ""),
        # Provenance — this composer's lyrics are OCR transcriptions from a
        # 1965 anthology scan, not a clean site scrape; kept visible on the
        # doc itself rather than only in code comments.
        "ocr_confidence_note": song.get("ocr_confidence_note", ""),
        # Vector — wrapped in Firestore Vector type for find_nearest
        "embedding":   Vector(vector),
        "source":      "dwijendralal",
    })
    return doc_id


async def embed_all(songs: list[dict]) -> list[dict]:
    """Embed every song in the list, returning it with firestore_id set on each."""
    total = len(songs)
    print(f"Embedding {total} Dwijendralal Roy songs into Firestore …")
    for i, song in enumerate(songs):
        song["firestore_id"] = await embed_and_store(song)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{total} embedded")
    print("Dwijendralal Roy embedding complete.")
    return songs
