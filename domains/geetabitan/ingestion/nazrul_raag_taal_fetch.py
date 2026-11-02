"""
domains/geetabitan/ingestion/nazrul_raag_taal_fetch.py

STEP 1 of 3 in the raag/taal backfill pipeline (fetch -> match -> ingest).

Pure scrape, no Firestore, no Gemini, no credentials needed — just
`requests`. Crawls nazrulgeeti.org's full song list and saves the raw
per-song data (title, raag, taal, swaralipi image URL if any) to a JSON
file. This is the only step of the pipeline that needs to hit the open
internet broadly, so it's kept dependency-free and safe to run from any
normal terminal.

Next steps (run after this):
  2. nazrul_raag_taal_match_candidates.py — fuzzy-matches this raw data
     against your local nazrul_songs.json catalog and writes a CSV for you
     to review/edit by hand (no network needed — Claude can run this step).
  3. nazrul_raag_taal_ingest.py — reads your reviewed CSV and writes the
     approved raag/taal (and swaralipi image URL) into Firestore, additively.

USAGE:
  pip install requests beautifulsoup4
  python -m domains.geetabitan.ingestion.nazrul_raag_taal_fetch

Output: domains/geetabitan/data/nazrulgeeti_org_raw.json
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE = "https://nazrulgeeti.org"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "nazrulgeeti_org_raw.json"
CHECKPOINT = Path("/tmp/nazrul_raag_taal_fetch_checkpoint.json")

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


def main():
    import argparse
    p = argparse.ArgumentParser(description="Scrape nazrulgeeti.org raag/taal/swaralipi (no Firestore/Gemini)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--delay", type=float, default=0.4)
    args = p.parse_args()

    cp = load_checkpoint() if args.resume else {}
    songs = cp.get("song_list")
    if not songs:
        logger.info("Fetching full song list from nazrulgeeti.org ...")
        songs = list_all_songs()
        cp["song_list"] = songs
        cp["results"] = cp.get("results", {})
        save_checkpoint(cp)
    logger.info(f"Total songs found: {len(songs)}")

    results = cp.get("results", {})
    targets = songs if not args.limit else songs[:args.limit]

    for i, song in enumerate(targets):
        href = song["href"]
        if href in results:
            continue
        html = fetch(href)
        if not html:
            continue
        data = parse_song_page(html)
        results[href] = {"title": song["title"], "href": href, **data}
        if (i + 1) % 25 == 0:
            logger.info(f"  {i+1}/{len(targets)} done")
            cp["results"] = results
            save_checkpoint(cp)
        time.sleep(args.delay)

    cp["results"] = results
    save_checkpoint(cp)

    out = list(results.values())
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    logger.info(f"\nWrote {len(out)} songs to {OUT_PATH}")
    with_raag = sum(1 for s in out if s["raag"])
    with_taal = sum(1 for s in out if s["taal"])
    with_swar = sum(1 for s in out if s["swaralipi_image_url"])
    logger.info(f"  with raag: {with_raag}, with taal: {with_taal}, with swaralipi image: {with_swar}")


if __name__ == "__main__":
    main()
