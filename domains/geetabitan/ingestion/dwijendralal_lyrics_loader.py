"""
domains/geetabitan/ingestion/dwijendralal_lyrics_loader.py

Loads and normalizes Dwijendralal Roy (দ্বিজেন্দ্রলাল রায়, পঞ্চকবি) songs into
the same canonical shape songs.json/nazrul_songs.json/rajanikanta_songs.json/
atulprasad_songs.json use, so dwijendralal_embedder.py can embed/store them
the same way the other embedders do.

Source and data-quality notes (read before touching this file):

domains/geetabitan/data/dwijendralal_songs_raw.json is NOT a clean site
scrape like Rajanikanta's milansagar.com or Atulprasad's onushilon.org
corpus. Dwijendralal is a much harder case — unlike the other three
composers, no single site carries a comprehensive lyrics+raag+taal index
for him. The 18 songs in that raw file were pulled directly from the
primary source: a 1965 public-domain anthology on archive.org
("Dwijendralal-rachanasambhar", ed. Pramathanath Bishi, item
in.ernet.dli.2015.458180), via tesseract OCR of the scanned pages, read
back and manually transcribed/normalized (not scraped structured data).
14 of his 5 anthologized plays (সাজাহান, চন্দ্রগুপ্ত, মেবার পতন, রাণা প্রতাপ
সিংহ) contributed songs; সীতা (written entirely in continuous rhymed verse,
no prose/song boundary to find) and মন্ত্র (a philosophical poem, not a
play) contributed none. 4 of the 18 carry raag+taal straight from the
source text (হাম্বির, খাম্বাজ, ভীমপলশ্রী, বারোয়া); the rest have none, same
as most of Atulprasad's and Rajanikanta's corpora.

A separate web-sourced title index (musicgoln.com + kaliokalam.com,
87 titles, kept in dwijendralal_index_raw.json / the merged review draft,
NOT in this raw file) was deliberately left OUT of the main ingestion
input: only 1 of those 87 titles ("ধনধান্য পুষ্পভরা") had independently
confirmed full lyrics, and that song turned out to already be present in
this raw file (it's originally a সাজাহান play-song, sung by child
minstrels for the character মহামায়া — not the standalone piece musicgoln's
category listing implied). Shipping the other 86 title-only stubs as
"songs" with empty lyrics would contradict this project's own
never-guess-data rule and this composer's every-entry-needs-real-lyrics
convention — they're left as a flagged future-sourcing lead instead (see
the review doc from the data-gathering session), not ingested here.

Every entry's "ocr_confidence_note" field is carried through unchanged
into the canonical output so the Firestore doc keeps that provenance
flag — this composer's data has NOT been verified against the scanned
page images the way a normal site-scrape would be; treat lyrics as
good-faith OCR transcriptions pending spot-check, not as certainly exact.

This step never touches songs.json / nazrul_songs.json /
rajanikanta_songs.json / atulprasad_songs.json — it only reads
dwijendralal_songs_raw.json and writes dwijendralal_songs.json, both new,
Dwijendralal-only files.

Usage:
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.dwijendralal_lyrics_loader
or as part of the pipeline:
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only dwijendralal-load
"""

import hashlib
import json
import re
import unicodedata
from pathlib import Path

RAW_PATH   = Path(__file__).parent.parent / "data" / "dwijendralal_songs_raw.json"
CANON_PATH = Path(__file__).parent.parent / "data" / "dwijendralal_songs.json"

MIN_LYRICS_CHARS = 15  # below this, it's a fragment, not a song


def _nfc(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("‌", "").replace("‍", "")
    return text.strip()


def _split_stanzas(text: str) -> list[str]:
    # The raw lyrics were transcribed one line per verse line without
    # blank-line stanza breaks (unlike milansagar's HTML, the OCR text has
    # no reliable stanza markers) — a single stanza per song is honest here
    # rather than guessing where a stanza break "should" go.
    stanzas = [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]
    return stanzas if stanzas else ([text.strip()] if text.strip() else [])


def _make_id(title: str, index: int) -> str:
    return hashlib.md5(f"dwijendralal_song_{index}_{title}".encode("utf-8")).hexdigest()[:16]


def load_and_normalize() -> list[dict]:
    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"{RAW_PATH} not found. This is produced by manual OCR transcription "
            "of the archive.org 1965 anthology — see this module's docstring."
        )

    raw_songs = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    songs: list[dict] = []
    skipped = 0

    for i, raw in enumerate(raw_songs):
        title  = _nfc(raw.get("title", ""))
        lyrics = _nfc(raw.get("lyrics", ""))
        if not title or len(lyrics) < MIN_LYRICS_CHARS:
            skipped += 1
            continue

        stanzas    = _split_stanzas(lyrics)
        first_line = _nfc(raw.get("first_line", "")) or (stanzas[0].split("\n")[0] if stanzas else "")
        # "category" here is ALWAYS the play name (সাজাহান / চন্দ্রগুপ্ত /
        # মেবার পতন / রাণা প্রতাপ সিংহ) — Dwijendralal's songs are organized by
        # the play they were written for, the same organizing-field role
        # Rajanikanta's and Nazrul's own books/সংকলন play for them. A
        # secondary genre label (দেশাত্মবোধক, হাস্যরসাত্মক, ...), where the
        # raw entry happens to carry one from the cross-referenced web
        # index, is kept in its own "genre" field rather than overriding
        # category — mixing the two would make get_songs_by_category /
        # CATEGORY_ORGANIZED_COMPOSERS filtering inconsistent across songs
        # from the very same play.
        category = _nfc(raw.get("play", ""))
        genre    = _nfc(raw.get("genre", ""))

        songs.append({
            "id":          _make_id(title, i),
            "title":       title,
            "first_line":  first_line,
            "stanzas":     stanzas,
            "lyrics_full": lyrics,
            "excerpt":     lyrics[:400],
            "category":    category,
            "genre":       genre,
            "raag":        _nfc(raw.get("raag", "")),
            "taal":        _nfc(raw.get("taal", "")),
            "source_note": raw.get("src", "archive.org in.ernet.dli.2015.458180"),
            "source":      "dwijendralal",
            "ocr_confidence_note": raw.get("ocr_confidence_note", ""),
        })

    CANON_PATH.write_text(
        json.dumps(songs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Loaded {len(songs)} Dwijendralal Roy songs ({skipped} skipped — too short / no lyrics text).")
    print(f"Wrote {CANON_PATH}")

    by_category: dict[str, int] = {}
    with_raag = with_taal = 0
    for s in songs:
        by_category[s["category"]] = by_category.get(s["category"], 0) + 1
        if s["raag"]:
            with_raag += 1
        if s["taal"]:
            with_taal += 1
    print(f"  by category (play): {by_category}")
    print(f"  with raag: {with_raag}, with taal: {with_taal}")
    return songs


if __name__ == "__main__":
    load_and_normalize()
