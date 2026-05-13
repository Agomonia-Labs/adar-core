"""
domains/geetabitan/ingestion/run_ingestion.py
One-stop CLI for the full Geetabitan ingestion pipeline.

Usage:
    # Full pipeline (scrape → embed → summarize)
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion

    # Individual steps
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only scrape
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only songs
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only summaries

    # Force-regenerate summaries (skip cache)
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only summaries --force
"""

import argparse
import asyncio
import json
from pathlib import Path

SONGS_PATH = Path(__file__).parent.parent / "data" / "songs.json"


async def step_scrape():
    from domains.geetabitan.ingestion.geetabitan_scraper import scrape_all
    print("=== Step 1: Scraping geetabitan.com ===")
    await scrape_all(delay=1.0)


async def step_bengali():
    from domains.geetabitan.ingestion.bengali_lyrics_fetcher import enrich_all
    print("=== Step 1b: Fetching Bengali lyrics from GitHub corpus ===")
    await enrich_all(delay=0.2)


async def step_enrich(meta_only: bool = False):
    from domains.geetabitan.ingestion.enrich_to_bengali import enrich_all
    print("=== Step 1c: Enriching metadata and lyrics to Bengali ===")
    await enrich_all(transliterate=not meta_only)


async def step_embed():
    from domains.geetabitan.ingestion.geetabitan_embedder import embed_and_store

    if not SONGS_PATH.exists():
        raise FileNotFoundError(
            f"songs.json not found at {SONGS_PATH}. "
            "Run --only scrape first."
        )
    songs = json.loads(SONGS_PATH.read_text(encoding="utf-8"))
    total = len(songs)
    print(f"=== Step 2: Embedding {total} songs into Firestore ===")

    for i, song in enumerate(songs):
        firestore_id         = await embed_and_store(song)
        song["firestore_id"] = firestore_id       # carry forward for summarizer
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{total} embedded")

    # Write back with firestore_ids for the summarizer step
    SONGS_PATH.write_text(
        json.dumps(songs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Embedding complete. songs.json updated with firestore_ids.")
    return songs


async def step_summarize(songs: list[dict] | None, force: bool):
    from domains.geetabitan.ingestion.geetabitan_summarizer import summarize_all

    if songs is None:
        if not SONGS_PATH.exists():
            raise FileNotFoundError(
                f"songs.json not found at {SONGS_PATH}. "
                "Run --only songs first."
            )
        songs = json.loads(SONGS_PATH.read_text(encoding="utf-8"))

    print(f"=== Step 3: Generating summaries (force={force}) ===")
    await summarize_all(songs, force=force, delay=0.5)


async def main(only: str | None, force: bool):
    songs = None

    if only == "scrape":
        await step_scrape()

    elif only == "bengali":
        await step_bengali()

    elif only == "enrich":
        await step_enrich(meta_only=getattr(args, 'meta_only', False))

    elif only == "songs":
        songs = await step_embed()

    elif only == "summaries":
        await step_summarize(songs=None, force=force)

    else:
        # Full pipeline
        await step_scrape()
        await step_bengali()   # fetch Bengali from GitHub corpus
        await step_enrich()    # fix metadata + transliterate Roman → Bengali
        songs = await step_embed()
        await step_summarize(songs=songs, force=force)

    print("\nAll done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Geetabitan ingestion pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--only",
        choices=["scrape", "bengali", "enrich", "songs", "summaries"],
        default=None,
        help="scrape | bengali | songs | summaries (default: all)",
    )
    parser.add_argument(
        "--meta-only", action="store_true",
        help="With --only enrich: fix metadata only, skip Gemini transliteration"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force-regenerate summaries even if already cached",
    )
    args = parser.parse_args()
    asyncio.run(main(only=args.only, force=args.force))
