"""
domains/geetabitan/ingestion/nazrul_raag_taal_scraper.py

Fills in missing raag/taal for Nazrul Geeti songs in the nazrulgeeti_songs
Firestore collection, by scraping nazrulgeeti.org — "the world's largest
Nazrulgeeti portal" (per its own footer text), which publishes per-song
lyrics, raag, taal, audio/video, and (for many songs) a swaralipi notation
image, for its full ~2,100+ song catalog.

This is purely additive: it only sets `raag`/`taal` on a song doc when that
field is currently empty, never overwrites anything, and never touches
geetabitan_songs (Rabindra Sangeet).

BONUS: when a song's nazrulgeeti.org page has a swaralipi image (many do —
one small per-song JPG, not a giant scanned PDF), this script also saves its
URL as `nazrulgeeti_org_swaralipi_image_url` (additive, no OCR performed
here — that's a natural follow-up: this is a much more precisely-scoped
swaralipi source than the Nazrul Institute's 99-page volume PDFs, since each
song gets its own small image instead of needing page-grouping heuristics).

USAGE:
  pip install requests beautifulsoup4

  # Dry run — first 10 songs
  DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \\
  python -m domains.geetabitan.ingestion.nazrul_raag_taal_scraper --limit 10 --dry-run

  # Full run (resumable)
  DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \\
  python -m domains.geetabitan.ingestion.nazrul_raag_taal_scraper --resume
"""

import argparse
import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from domains.geetabitan.ingestion.nazrul_swaralipi_scraper import (
    find_in_firestore, get_songs_db,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE = "https://nazrulgeeti.org"
CHECKPOINT = Path("/tmp/nazrul_raag_taal_checkpoint.json")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "bn,en-US;q=0.9",
})


def fetch(url: str, retries: int = 3) -> Optional[str]:
    for i in range(retries):
        try:
            r = SESSION.get(url, timeout=20)
            r.raise_for_status()
            return r.text
        except Exception as e:
            logger.warning(f"  fetch error ({i+1}/{retries}) {url}: {e}")
            time.sleep(2 ** i)
    return None


def list_all_songs() -> list[dict]:
    """Chain through /all-song-list?start=N until a page yields no song
    links. Returns [{title, href}, ...] for the full catalog."""
    songs, seen_hrefs = [], set()
    start = 0
    while True:
        html = fetch(f"{BASE}/all-song-list?start={start}")
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")
        links = [a for a in soup.find_all("a", href=True) if "/au/" in a["href"]]
        if not links:
            break
        new_count = 0
        for a in links:
            href = a["href"]
            if not href.startswith("http"):
                href = BASE + href
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            title = a.get_text(strip=True)
            if title:
                songs.append({"title": title, "href": href})
                new_count += 1
        logger.info(f"  all-song-list start={start}: +{new_count} (total {len(songs)})")
        if new_count == 0:
            break
        start += 25
    return songs


def _extract_panel(html: str, panel_id: str) -> str:
    """Grab the inner HTML of one accordion panel's panel-content div."""
    m = re.search(
        re.escape(f'id="{panel_id}"') + r'[\s\S]*?panel-content">([\s\S]*?)</div>\s*</div>',
        html,
    )
    return m.group(1) if m else ""


def parse_song_page(html: str) -> dict:
    raag_panel = _extract_panel(html, "rlta-panel-raga-o-tala")
    raag_m = re.search(r"রাগ[ঃ:]\s*([^<\n]+)", raag_panel)
    taal_m = re.search(r"তাল[ঃ:]\s*([^<\n]+)", raag_panel)

    swar_panel = _extract_panel(html, "rlta-panel-sbaralipi")
    img_m = re.search(r'data-src="([^"]+)"', swar_panel)

    return {
        "raag": (raag_m.group(1).strip() if raag_m else ""),
        "taal": (taal_m.group(1).strip() if taal_m else ""),
        "swaralipi_image_url": (img_m.group(1).strip() if img_m else ""),
    }


def load_checkpoint() -> dict:
    return json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {}

def save_checkpoint(cp: dict):
    CHECKPOINT.write_text(json.dumps(cp))


async def run(dry_run: bool, limit: Optional[int], resume: bool, delay: float):
    cp = load_checkpoint() if resume else {}
    songs = cp.get("song_list")
    if not songs:
        logger.info("Fetching full song list from nazrulgeeti.org ...")
        songs = list_all_songs()
        cp["song_list"] = songs
        cp.setdefault("done_hrefs", [])
        save_checkpoint(cp)
    logger.info(f"Total songs found on nazrulgeeti.org: {len(songs)}")

    done = set(cp.get("done_hrefs", []))
    stats = {"filled_raag": 0, "filled_taal": 0, "filled_swaralipi_url": 0,
              "no_match": 0, "no_data": 0, "skipped_done": 0}

    targets = songs if not limit else songs[:limit]

    for song in targets:
        href = song["href"]
        if href in done:
            stats["skipped_done"] += 1
            continue

        html = fetch(href)
        if not html:
            done.add(href)
            continue

        data = parse_song_page(html)
        if not data["raag"] and not data["taal"] and not data["swaralipi_image_url"]:
            stats["no_data"] += 1
            done.add(href)
            cp["done_hrefs"] = sorted(done)
            save_checkpoint(cp)
            continue

        match = await find_in_firestore(song["title"])
        if not match:
            # Deliberately NOT marked done: title-matching heuristics may
            # improve later, so a --resume run retries no-match songs
            # instead of permanently skipping them. Genuinely-absent songs
            # just keep showing up here, which is fine (cheap to re-check).
            logger.warning(f"  No Firestore match for: {song['title'][:40]}")
            stats["no_match"] += 1
            continue

        doc_id, doc_data = match
        update = {}
        if data["raag"] and not (doc_data.get("raag") or "").strip():
            update["raag"] = data["raag"]
            stats["filled_raag"] += 1
        if data["taal"] and not (doc_data.get("taal") or "").strip():
            update["taal"] = data["taal"]
            stats["filled_taal"] += 1
        if data["swaralipi_image_url"] and not (doc_data.get("nazrulgeeti_org_swaralipi_image_url") or "").strip():
            update["nazrulgeeti_org_swaralipi_image_url"] = data["swaralipi_image_url"]
            stats["filled_swaralipi_url"] += 1

        if update:
            logger.info(f"  {song['title'][:35]:35s} -> {update}")
            if not dry_run:
                db = get_songs_db()
                from domains.geetabitan.config import NAZRUL_FIRESTORE_COLLECTION
                await db.collection(NAZRUL_FIRESTORE_COLLECTION).document(doc_id).update(update)

        done.add(href)
        cp["done_hrefs"] = sorted(done)
        save_checkpoint(cp)
        await asyncio.sleep(delay)

    logger.info(f"\n{'='*55}\nFinal stats: {stats}")


async def main():
    from dotenv import load_dotenv
    load_dotenv(os.environ.get("DOTENV_FILE", ".env.geetabitan"), override=True)

    p = argparse.ArgumentParser(description="Backfill Nazrul Geeti raag/taal from nazrulgeeti.org")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--delay", type=float, default=0.5)
    args = p.parse_args()

    await run(args.dry_run, args.limit, args.resume, args.delay)


if __name__ == "__main__":
    asyncio.run(main())
