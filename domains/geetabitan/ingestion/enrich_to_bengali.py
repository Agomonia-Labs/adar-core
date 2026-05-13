"""
domains/geetabitan/ingestion/enrich_to_bengali.py

Enriches songs.json with:
1. Bengali metadata — converts "Swadesh"→"স্বদেশ", "Dadra"→"দাদরা" via lookup
2. Bengali lyrics   — batched Gemini calls (10 songs/call, 5 concurrent)

WHY IT WAS SLOW:
  Old version: 2179 sequential Gemini calls × ~2s each = ~60 minutes
  This version: 218 batched calls × 5 concurrent = ~3-5 minutes

Run:
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only enrich
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only enrich --meta-only
"""

import asyncio
import json
import os
import re
from pathlib import Path

from google import genai

SONGS_PATH  = Path(__file__).parent.parent / "data" / "songs.json"
BATCH_SIZE  = 10    # songs per Gemini call
CONCURRENCY = 5     # parallel Gemini calls at once

# ── Metadata lookup tables ────────────────────────────────────────────────────

PARYAY_MAP = {
    "puja": "পূজা", "swadesh": "স্বদেশ", "prem": "প্রেম",
    "prakriti": "প্রকৃতি", "bichitra": "বিচিত্র",
    "anushthanic": "আনুষ্ঠানিক", "anushthanik": "আনুষ্ঠানিক",
    "anusthanik": "আনুষ্ঠানিক",
}

TAAL_MAP = {
    "dadra": "দাদরা", "kaharwa": "কাহারবা", "kahaarba": "কাহারবা",
    "teentaal": "তিনতাল", "teen taal": "তিনতাল", "tritaal": "ত্রিতাল",
    "rupakra": "রূপকড়া", "rupak": "রূপকড়া",
    "jhaptaal": "ঝাঁপতাল", "ektaal": "একতাল", "ek taal": "একতাল",
    "teora": "তেওরা", "jhumra": "ঝুমরা", "chautaal": "চৌতাল",
    "chautal": "চৌতাল", "kirtan": "কীর্তন", "deepchandi": "দীপচন্দী",
}

RAAG_MAP = {
    "bhairavi": "ভৈরবী", "baul": "বাউল", "kafi": "কাফি",
    "emon": "ইমন", "yaman": "ইমন", "yaman kalyan": "ইমন",
    "pilu": "পিলু", "behag": "বেহাগ", "bhairav": "ভৈরব",
    "bhupali": "ভূপালি", "desh": "দেশ", "kirtan": "কীর্তন",
    "mishra": "মিশ্র", "malkauns": "মালকোষ", "kedar": "কেদার",
    "todi": "তোড়ি", "sarang": "সারঙ্গ", "bibhas": "বিভাস",
    "basant": "বসন্ত", "lalit": "ললিত", "joyjayanti": "জয়জয়ন্তী",
    "hamir": "হামির", "purbi": "পূরবী", "asavari": "আসাবরী",
    "pahadi": "পহাড়ি", "khamaj": "খাম্বাজ", "darbari": "দরবারি",
    "sahana": "সাহানা", "sohini": "সোহিনী", "nat": "নট",
}


def _has_bengali(s: str) -> bool:
    return any("\u0980" <= c <= "\u09FF" for c in s)


def _normalize_metadata(song: dict) -> dict:
    for field, lookup in [("paryay", PARYAY_MAP), ("taal", TAAL_MAP), ("raag", RAAG_MAP)]:
        val = song.get(field, "")
        if val and not _has_bengali(val):
            song[field] = lookup.get(val.lower().strip(), val)
    return song


def _split_stanzas(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]


# ── Gemini batched transliterator ─────────────────────────────────────────────

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))
    return _client


BATCH_PROMPT = """\
তুমি রবীন্দ্রসঙ্গীত বিশেষজ্ঞ। নিচে {n}টি গানের ইংরেজি ট্রান্সলিটারেশন দেওয়া হলো।
প্রতিটি গানকে সঠিক বাংলা ইউনিকোডে রূপান্তর করো।

নির্দেশনা:
- শুধু বাংলা গানের কথা লেখো, কোনো ব্যাখ্যা বা মন্তব্য নয়
- প্রতিটি গান এই ফরম্যাটে দাও: ===SONG_N=== (N হলো গানের নম্বর) তারপর বাংলা কথা
- স্তবকের মধ্যে একটি ফাঁকা লাইন দাও
- রবীন্দ্রনাথের প্রামাণিক বানান ব্যবহার করো

{songs}"""


async def _transliterate_batch(
    batch: list[dict],
    semaphore: asyncio.Semaphore,
) -> list[str | None]:
    """One Gemini call for up to BATCH_SIZE songs. Returns list of Bengali strings."""
    async with semaphore:
        songs_text = ""
        for i, song in enumerate(batch):
            roman = song.get("lyrics_roman") or song.get("lyrics_full", "")
            songs_text += (
                f"---গান {i+1}: {song.get('title', '')} "
                f"({song.get('paryay', '')})---\n"
                f"{roman[:1500]}\n\n"
            )

        prompt = BATCH_PROMPT.format(n=len(batch), songs=songs_text)
        try:
            response = _get_client().models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            raw = response.text

            # Parse ===SONG_1===, ===SONG_2=== … markers
            results: list[str | None] = []
            for i in range(len(batch)):
                marker      = f"===SONG_{i+1}==="
                next_marker = f"===SONG_{i+2}==="
                start = raw.find(marker)
                if start == -1:
                    results.append(None)
                    continue
                start += len(marker)
                end = raw.find(next_marker) if i + 1 < len(batch) else len(raw)
                results.append(raw[start:end].strip() or None)
            return results

        except Exception as exc:
            print(f"    Batch Gemini error: {exc}")
            return [None] * len(batch)


# ── Main enrichment ───────────────────────────────────────────────────────────

async def enrich_all(transliterate: bool = True):
    if not SONGS_PATH.exists():
        raise FileNotFoundError(f"songs.json not found. Run scraper first.")

    songs = json.loads(SONGS_PATH.read_text(encoding="utf-8"))
    total = len(songs)
    print(f"Enriching {total} songs …")

    # Step 1: fix metadata (instant, no API)
    meta_fixed = 0
    for i, song in enumerate(songs):
        before = song.get("paryay", "")
        songs[i] = _normalize_metadata(song)
        if songs[i].get("paryay") != before:
            meta_fixed += 1
    print(f"  Metadata fixed: {meta_fixed} songs")

    if not transliterate:
        SONGS_PATH.write_text(
            json.dumps(songs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("Done (metadata only).")
        return

    # Step 2: find songs that still need Bengali lyrics
    to_translate = [
        (i, s) for i, s in enumerate(songs)
        if not _has_bengali(s.get("lyrics_full", ""))
    ]
    print(f"  Songs needing transliteration: {len(to_translate)}")

    if not to_translate:
        print("  All songs already have Bengali text. Nothing to do.")
        SONGS_PATH.write_text(
            json.dumps(songs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return

    # Step 3: batch + concurrent Gemini calls
    semaphore     = asyncio.Semaphore(CONCURRENCY)
    lyrics_fixed  = 0
    errors        = 0
    batches       = [
        to_translate[j:j+BATCH_SIZE]
        for j in range(0, len(to_translate), BATCH_SIZE)
    ]
    total_batches = len(batches)
    print(f"  Batches: {total_batches}  (size={BATCH_SIZE}, concurrent={CONCURRENCY})")
    print(f"  Estimated time: ~{max(1, total_batches // CONCURRENCY * 3)} minutes\n")

    async def process_batch(batch_idx: int, batch: list[tuple[int, dict]]):
        nonlocal lyrics_fixed, errors
        indices = [b[0] for b in batch]
        batch_songs = [b[1] for b in batch]
        results = await _transliterate_batch(batch_songs, semaphore)

        for orig_idx, bengali in zip(indices, results):
            if bengali:
                songs[orig_idx]["lyrics_roman"] = songs[orig_idx].get("lyrics_full", "")
                songs[orig_idx]["lyrics_full"]  = bengali
                songs[orig_idx]["stanzas"]      = _split_stanzas(bengali)
                first_stanza = songs[orig_idx]["stanzas"]
                songs[orig_idx]["first_line"]   = first_stanza[0].split("\n")[0] if first_stanza else ""
                lyrics_fixed += 1
            else:
                errors += 1

        done = batch_idx + 1
        if done % 10 == 0 or done == total_batches:
            pct = done / total_batches * 100
            print(f"  [{done}/{total_batches}] {pct:.0f}% — converted: {lyrics_fixed}, errors: {errors}")
            # Checkpoint save every 10 batches
            SONGS_PATH.write_text(
                json.dumps(songs, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    # Run all batches — asyncio.gather respects the semaphore for concurrency
    await asyncio.gather(*[
        process_batch(idx, batch)
        for idx, batch in enumerate(batches)
    ])

    # Final save
    SONGS_PATH.write_text(
        json.dumps(songs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nDone.")
    print(f"  Metadata fixed:   {meta_fixed}")
    print(f"  Lyrics converted: {lyrics_fixed}")
    print(f"  Errors:           {errors}")
    print(f"\nNext step — re-embed:")
    print(f"  PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only songs")


if __name__ == "__main__":
    asyncio.run(enrich_all())