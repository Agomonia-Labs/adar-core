"""
domains/geetabitan/ingestion/bengali_lyrics_fetcher.py

Enriches songs.json with Bengali Unicode lyrics from a public GitHub corpus,
since geetabitan.com serves Bengali text as PNG images (not HTML text).

Source corpus: https://github.com/prtk418/rabindra-sangeet-lyrics
  - Contains ~2000+ Tagore songs as UTF-8 Bengali text files
  - File names are romanized slugs matching geetabitan.com URLs

Run AFTER the scraper:
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.bengali_lyrics_fetcher

Or as part of ingestion:
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only bengali
"""

import asyncio
import json
import re
import unicodedata
from pathlib import Path

import httpx

SONGS_PATH   = Path(__file__).parent.parent / "data" / "songs.json"
CORPUS_BASE  = "https://raw.githubusercontent.com/prtk418/rabindra-sangeet-lyrics/main/lyrics"

HEADERS = {"User-Agent": "geetabitan-research-bot/2.0"}


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip()) if text else ""


def _slug_from_url(source_url: str) -> str:
    """Extract slug from source_url. e.g. '.../J/jodi-prem-dile-na-lyric.html' → 'jodi-prem-dile-na'"""
    name = source_url.rstrip("/").split("/")[-1]
    return name.replace("-lyric.html", "")


def _split_stanzas(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]


async def fetch_bengali_lyrics(client: httpx.AsyncClient, slug: str) -> str | None:
    """Try to fetch Bengali lyrics from GitHub corpus by slug."""
    # The corpus uses the same slug naming as geetabitan.com
    url = f"{CORPUS_BASE}/{slug}.txt"
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code == 200:
            return _nfc(resp.text)
    except Exception:
        pass
    return None


async def enrich_all(delay: float = 0.2):
    if not SONGS_PATH.exists():
        raise FileNotFoundError(f"songs.json not found at {SONGS_PATH}. Run scraper first.")

    songs    = json.loads(SONGS_PATH.read_text(encoding="utf-8"))
    enriched = 0
    missing  = 0

    print(f"Fetching Bengali lyrics for {len(songs)} songs …")

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for i, song in enumerate(songs):
            # Skip if already has Bengali text (non-roman characters)
            existing = song.get("lyrics_full", "")
            if existing and any("\u0980" <= c <= "\u09FF" for c in existing):
                enriched += 1
                continue

            slug   = _slug_from_url(song.get("source_url", ""))
            lyrics = await fetch_bengali_lyrics(client, slug)

            if lyrics:
                song["lyrics_full"]  = lyrics
                song["lyrics_roman"] = song.get("lyrics_roman", existing)
                song["stanzas"]      = _split_stanzas(lyrics)
                song["first_line"]   = song["stanzas"][0].split("\n")[0] if song["stanzas"] else ""
                enriched += 1
            else:
                missing += 1

            await asyncio.sleep(delay)
            if (i + 1) % 100 == 0:
                print(f"  {i + 1}/{len(songs)} — enriched: {enriched}, missing: {missing}")
                # Checkpoint save
                SONGS_PATH.write_text(
                    json.dumps(songs, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    SONGS_PATH.write_text(
        json.dumps(songs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nDone. Bengali lyrics enriched: {enriched}/{len(songs)}, missing: {missing}")
    if missing > 0:
        print(f"Songs without Bengali lyrics will use English transliteration for search.")


if __name__ == "__main__":
    asyncio.run(enrich_all())
