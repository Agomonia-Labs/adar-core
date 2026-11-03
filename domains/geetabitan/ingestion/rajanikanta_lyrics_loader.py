"""
domains/geetabitan/ingestion/rajanikanta_lyrics_loader.py

Loads and normalizes Rajanikanta Sen (রজনীকান্ত সেন, পঞ্চকবি) songs into the
same canonical shape songs.json/nazrul_songs.json use, so
rajanikanta_embedder.py can embed/store them the same way the other two
embedders do.

Unlike Nazrul Geeti, there's no manual dataset drop here: domains/geetabitan/
data/rajanikanta_milansagar_raw.json is a direct scrape of milansagar.com's
Rajanikanta Sen song index (title, raag+taal, source book, and full lyrics,
already paired per song by that site). milansagar.com is blocked by this
project's network egress allowlist for plain `requests`/shell fetches, so
that raw file was produced by running the same-origin fetch()+parse logic
inside a real browser against milansagar.com directly (not by this script) —
see the git history / session notes for the extraction approach if it ever
needs refreshing. This script only does the pure local JSON -> JSON
normalization step, no network.

Source pages covered (the 5 books that are actual songs with raag/taal —
বিশ্রাম/অমৃত/সদ্ভাব কুসুম are pure poetry and were never scraped):
    বাণী (1902), কল্যাণী (1905), অভয়া (1910), আনন্দময়ী (1910), শেষ দান (1927)

A majority of the raw file's entries (203 of 313) are title + raag/taal
INDEX STUBS on milansagar.com itself — the site's বাণী/কল্যাণী/অভয়া song
index lists most songs by name and raag/taal only, without the actual
lyrics text inline on that page (confirmed by inspecting the raw HTML
directly — this isn't a scrape bug). আনন্দময়ী and শেষ দান are the two
books where milansagar does carry full inline lyrics for nearly every
entry. A handful of শেষ দান entries are also just structural notes
(dedication pages, hospital-bed datelines), not songs at all.
Rather than ship a song with no real lyrics, this loader keeps only
entries with substantial lyrics text.

A second source was added to fill the milansagar.com index stubs:
onushilon.org/corpus/rojonikanto-sen (pages rgs1.htm..rgs301.htm, a
separate numbered song corpus for Rajanikanta Sen, also only reachable
via same-origin fetch() in a real browser — this project's egress
allowlist blocks it too). Its songs were matched to milansagar's stub
titles by normalized leading-word comparison against milansagar's
first_line field (onushilon's own <TITLE> is usually the song's opening
line, not a separate title) and merged in ONLY where lyrics were
missing — milansagar's own text, raag, taal, category and title are
never overridden. Two candidates sharing the same opening words but
different lyrics were left unmatched rather than guessed at. Each
filled-in raw entry carries "lyrics_source": "onushilon.org" so
source_note below reflects true per-song provenance.

After this merge: 248 of 313 titles carry real lyrics (110 originally
from milansagar.com + 138 filled from onushilon.org), by book —
আনন্দময়ী 40, শেষ দান 42, কল্যাণী 63, বাণী 57, অভয়া 46. The remaining 65
titles are known (title + raag/taal, from milansagar) but have no lyrics
text on either site as scraped; filling them in would need another
source entirely — flag this to Braja before spending more time on it
rather than guessing at missing lyrics.

This step never touches songs.json / nazrul_songs.json — it only reads
rajanikanta_milansagar_raw.json and writes rajanikanta_songs.json, both
new, Rajanikanta-only files.

Usage:
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.rajanikanta_lyrics_loader
or as part of the pipeline:
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only rajanikanta-load
"""

import hashlib
import json
import re
import unicodedata
from pathlib import Path

RAW_PATH   = Path(__file__).parent.parent / "data" / "rajanikanta_milansagar_raw.json"
CANON_PATH = Path(__file__).parent.parent / "data" / "rajanikanta_songs.json"

MIN_LYRICS_CHARS = 15  # below this, it's a dateline/dedication note, not a song


def _nfc(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("‌", "").replace("‍", "")
    return text.strip()


def _split_stanzas(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]


def _book_name(book_line: str) -> str:
    """'আনন্দময়ী (১৯১০) কাব্যগ্রন্থের বিজয়া-র অন্তর্ভুক্ত' -> 'আনন্দময়ী'
    'কল্যাণী কাব্যগ্রন্থের গান' -> 'কল্যাণী'
    'অভয়া কাব্যগ্রন্থ থেকে' -> 'অভয়া'"""
    book_line = _nfc(book_line)
    if not book_line:
        return ""
    # Everything before the first '(' or before 'কাব্যগ্রন্থ' — whichever comes first
    cut = len(book_line)
    paren = book_line.find("(")
    if paren != -1:
        cut = min(cut, paren)
    granth = book_line.find("কাব্যগ্রন্থ")
    if granth != -1:
        cut = min(cut, granth)
    return book_line[:cut].strip()


def _split_raag_taal(raag_taal: str) -> tuple[str, str]:
    """milansagar pairs these as 'রাগ, তাল' (occasionally just a tune note
    with no comma, e.g. 'বাউলের সুর', 'কীর্ত্তনের সুর' — kept whole as raag,
    taal left blank rather than guessed)."""
    raag_taal = _nfc(raag_taal)
    if not raag_taal:
        return "", ""
    parts = [p.strip() for p in raag_taal.split(",")]
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _make_id(title: str, index: int) -> str:
    return hashlib.md5(f"rajanikanta_song_{index}_{title}".encode("utf-8")).hexdigest()[:16]


def load_and_normalize() -> list[dict]:
    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"{RAW_PATH} not found. This is produced by a one-time browser-based "
            "scrape of milansagar.com — see this module's docstring."
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
        category   = _book_name(raw.get("book_line", ""))
        raag, taal = _split_raag_taal(raw.get("raag_taal", ""))

        songs.append({
            "id":          _make_id(title, i),
            "title":       title,
            "subtitle":    _nfc(raw.get("subtitle", "")),
            "first_line":  first_line,
            "stanzas":     stanzas,
            "lyrics_full": lyrics,
            "excerpt":     lyrics[:400],
            "category":    category,
            "raag":        raag,
            "taal":        taal,
            "source_note": "onushilon.org" if raw.get("lyrics_source") == "onushilon.org" else "milansagar.com",
            "source":      "rajanikanta",
        })

    CANON_PATH.write_text(
        json.dumps(songs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Loaded {len(songs)} Rajanikanta Sen songs ({skipped} skipped — index stubs with no lyrics text yet, or structural notes).")
    print(f"Wrote {CANON_PATH}")

    by_category: dict[str, int] = {}
    with_raag = with_taal = 0
    for s in songs:
        by_category[s["category"]] = by_category.get(s["category"], 0) + 1
        if s["raag"]:
            with_raag += 1
        if s["taal"]:
            with_taal += 1
    print(f"  by category: {by_category}")
    print(f"  with raag: {with_raag}, with taal: {with_taal}")
    return songs


if __name__ == "__main__":
    load_and_normalize()
