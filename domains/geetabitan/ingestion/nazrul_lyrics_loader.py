"""
domains/geetabitan/ingestion/nazrul_lyrics_loader.py

Loads and normalizes Nazrul Geeti (Kazi Nazrul Islam) lyrics into the same
canonical shape songs.json uses for Rabindra Sangeet, so nazrul_embedder.py
can embed/store them the same way geetabitan_embedder.py does.

Unlike Rabindra Sangeet, there is no live-scrapable source here: the lyrics
text comes from the BanglaMusicStylo dataset on IEEE DataPort
(DOI 10.21227/qsbr-kw16), Kazi Nazrul Islam folder — a manual, one-time
download Braja does himself while logged into IEEE DataPort, cross-checked
against the Nazrul Institute's published catalog for category/raag/taal
where available. Drop that extracted content into:

    domains/geetabitan/data/nazrul_songs_raw.json

...as a flat list of objects shaped like:
    {
        "title":      "বাগিচায় বুলবুলি তুই",
        "lyrics_full": "<raw Bengali lyrics text, stanzas separated by blank lines>",
        "category":   "বুলবুল",      # book/collection name — leave "" if unconfirmed
        "raag":       "",             # leave "" rather than guessing
        "taal":       "",
        "source_note": "BanglaMusicStylo / IEEE DataPort qsbr-kw16"
    }

Then run:
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.nazrul_lyrics_loader
or as part of the pipeline:
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only nazrul-load

This step never touches songs.json / geetabitan_songs — it only reads
nazrul_songs_raw.json and writes nazrul_songs.json, both new, Nazrul-only
files.
"""

import hashlib
import json
import re
import unicodedata
from pathlib import Path

RAW_PATH     = Path(__file__).parent.parent / "data" / "nazrul_songs_raw.json"
CANON_PATH   = Path(__file__).parent.parent / "data" / "nazrul_songs.json"


def _nfc(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("‌", "").replace("‍", "")
    return text.strip()


def _split_stanzas(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]


def _make_id(title: str, index: int) -> str:
    return hashlib.md5(f"nazrul_song_{index}_{title}".encode("utf-8")).hexdigest()[:16]


def load_and_normalize() -> list[dict]:
    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"{RAW_PATH} not found. Drop the Nazrul Geeti lyrics there first "
            "— see the module docstring in nazrul_lyrics_loader.py for the shape."
        )

    raw_songs = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    songs: list[dict] = []
    skipped = 0

    for i, raw in enumerate(raw_songs):
        title = _nfc(raw.get("title", ""))
        lyrics = _nfc(raw.get("lyrics_full", "") or raw.get("lyrics", ""))
        if not title or not lyrics:
            skipped += 1
            continue

        stanzas = _split_stanzas(lyrics)
        first_line = stanzas[0].split("\n")[0] if stanzas else ""

        songs.append({
            "id":          _make_id(title, i),
            "title":       title,
            "first_line":  first_line,
            "stanzas":     stanzas,
            "lyrics_full": lyrics,
            "excerpt":     lyrics[:400],
            "category":    _nfc(raw.get("category", "")),
            "raag":        _nfc(raw.get("raag", "")),
            "raag_family": _nfc(raw.get("raag_family", "")),
            "raag_time":   _nfc(raw.get("raag_time", "")),
            "raag_mood":   _nfc(raw.get("raag_mood", "")),
            "taal":        _nfc(raw.get("taal", "")),
            "source_note": raw.get("source_note", "BanglaMusicStylo / IEEE DataPort qsbr-kw16"),
            "source":      "nazrul",
        })

    CANON_PATH.write_text(
        json.dumps(songs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Loaded {len(songs)} Nazrul Geeti songs ({skipped} skipped — missing title/lyrics).")
    print(f"Wrote {CANON_PATH}")
    return songs


if __name__ == "__main__":
    load_and_normalize()
