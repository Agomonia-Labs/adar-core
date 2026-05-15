"""
domains/geetabitan/ingestion/nltr_swaralipi_scraper.py

Scrapes swaralipi using two-step approach:
  1. Chain-crawl NLTR to get song titles + node IDs (lyrics pages work fine)
  2. Fetch notation PNG from geetabitan.com, OCR with Gemini Vision
  3. Match to Firestore, save notation_text + source links

WHY TWO SOURCES:
  - NLTR: best for chain-crawling all ~2000 songs (navigation links work)
  - geetabitan.com: notation available as PNG images (no JS needed)
  - Gemini Vision: reads the notation PNG and converts to Bengali sargam text

USAGE:
  pip install requests beautifulsoup4

  # Dry run — স্বদেশ, first 5 songs
  DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \\
  python -m domains.geetabitan.ingestion.nltr_swaralipi_scraper \\
    --paryay স্বদেশ --limit 5 --dry-run

  # Full paryay
  DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \\
  python -m domains.geetabitan.ingestion.nltr_swaralipi_scraper \\
    --paryay পূজা

  # All paryays
  DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \\
  python -m domains.geetabitan.ingestion.nltr_swaralipi_scraper --resume
"""

import asyncio
import argparse
import base64
import json
import logging
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types as genai_types

from google.cloud import firestore as _firestore

FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "geetabitan_songs")

def get_songs_db():
    """Connect directly to the geetabitan-db Firestore database."""
    db_name = os.environ.get("AUTH_FIRESTORE_DATABASE",
              os.environ.get("FIRESTORE_DATABASE", "geetabitan-db"))
    project = os.environ.get("GCP_PROJECT_ID",
              os.environ.get("GOOGLE_CLOUD_PROJECT", "bdas-493785"))
    return _firestore.AsyncClient(project=project, database=db_name)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

NLTR_BASE  = "https://rabindra-rachanabali.nltr.org"
GB_BASE    = "https://www.geetabitan.com"
SOURCE_TAG = "geetabitan.com (notation PNG, OCR by Gemini)"
NLTR_TAG   = "rabindra-rachanabali.nltr.org (SNLTR)"
CHECKPOINT = Path("/tmp/nltr_checkpoint.json")

# First node of each paryay (chain start)
PARYAY_STARTS = {
    "পূজা":             3648,
    "প্রেম":             4902,
    "স্বদেশ":           4673,
    "প্রকৃতি":           5291,
    "বিচিত্র":           6254,
    "নাট্যগীতি":         9672,
    "আনুষ্ঠানিক":       6346,
    "প্রেম ও প্রকৃতি":  4920,
    "পূজা ও প্রার্থনা": 4518,
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "bn,en-US;q=0.9",
    "Referer":         f"{NLTR_BASE}/",
})

_gem = None
def gemini():
    global _gem
    if not _gem:
        _gem = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY",""))
    return _gem


# ── NLTR chain-crawl helpers ──────────────────────────────────────────────────

def fetch_nltr(node_id: int) -> Optional[BeautifulSoup]:
    for i in range(3):
        try:
            r = SESSION.get(f"{NLTR_BASE}/node/{node_id}", timeout=20)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            r.encoding = "utf-8"
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            logger.warning(f"  NLTR fetch error ({i+1}/3): {e}")
            time.sleep(2 ** i)
    return None


def parse_nltr_page(soup: BeautifulSoup) -> tuple[str, str, Optional[int]]:
    """
    Returns (song_first_line, paryay, next_node_id).
    Song first line = first meaningful line of #kobita = song title in Firestore.
    """
    # Page title format: "পূজা - গান,২৪ | রবীন্দ্র রচনাবলী"
    paryay = ""
    pt = soup.find("title")
    if pt:
        m = re.match(r"^([^|]+?)\s*[-–]", pt.get_text())
        if m:
            paryay = m.group(1).strip()

    # Song first line from #kobita
    # Content uses <br/> for line breaks; text within a line wraps across HTML newlines
    # So we must use ONLY <br/> as the line separator, not \n
    song_title = ""
    kobita = soup.find(id="kobita")
    if kobita:
        # Replace <br/> with a unique separator, keep everything else as-is
        SEP = "|||BR|||"
        raw_html = str(kobita)
        raw_html = re.sub(r"<br\s*/?>", SEP, raw_html, flags=re.IGNORECASE)
        # Now parse to get clean text
        parts_soup = BeautifulSoup(raw_html, "html.parser")
        full_text  = parts_soup.get_text(separator=" ")
        # Split on our separator
        for part in full_text.split(SEP):
            # Collapse all whitespace to single space
            line    = re.sub(r"\s+", " ", part).strip()
            bengali = sum(1 for c in line if '\u0980' <= c <= '\u09FF')
            if bengali >= 5:
                song_title = line
                break

    # পরবর্তী next link
    next_id = None
    for a in soup.find_all("a", href=True):
        if "পরবর্তী" in a.get_text():
            m = re.search(r"/node/(\d+)$", a["href"])
            if m:
                nid = int(m.group(1))
                if 3000 < nid < 16000:
                    next_id = nid
                    break

    return song_title, paryay, next_id


# ── Geetabitan.com notation PNG ───────────────────────────────────────────────

def title_to_slug(title: str) -> str:
    """Convert Bengali song title to geetabitan.com URL slug."""
    # Transliterate common Bengali characters
    TRANSLITERATE = {
        'অ':'o','আ':'a','ই':'i','ঈ':'i','উ':'u','ঊ':'u','এ':'e','ও':'o',
        'ক':'k','খ':'kh','গ':'g','ঘ':'gh','চ':'ch','ছ':'chh','জ':'j','ঝ':'jh',
        'ট':'t','ঠ':'th','ড':'d','ঢ':'dh','ত':'t','থ':'th','দ':'d','ধ':'dh',
        'ন':'n','প':'p','ফ':'ph','ব':'b','ভ':'bh','ম':'m','য':'y','র':'r',
        'ল':'l','শ':'sh','ষ':'sh','স':'s','হ':'h','ড়':'r','ঢ়':'rh',
        'ং':'n','ঃ':'h','ঁ':'n',
        'া':'a','ি':'i','ী':'i','ু':'u','ূ':'u','ে':'e','ো':'o','্':'',
        'ৃ':'ri',
    }
    slug = ""
    for ch in title:
        if ch in TRANSLITERATE:
            slug += TRANSLITERATE[ch]
        elif 'a' <= ch <= 'z' or 'A' <= ch <= 'Z' or '0' <= ch <= '9':
            slug += ch.lower()
        elif ch in ' -,।':
            slug += '-'
    # Clean up
    slug = re.sub(r'-+', '-', slug).strip('-').lower()
    return slug


def get_notation_png_from_doc(doc_data: dict) -> Optional[bytes]:
    """
    Fetch notation PNG from geetabitan.com using source_url from Firestore.
    source_url: https://www.geetabitan.com/lyrics/A/amar-sonar-bangla-lyric.html
    PNG at:     https://www.geetabitan.com/lyrics/baani-pdf-a/amar-sonar-bangla.png
    """
    source_url = doc_data.get("source_url", "")
    gb_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer":    f"{GB_BASE}/",
    }

    slug   = ""
    letter = ""

    if source_url and "geetabitan.com" in source_url:
        # Pattern 1: /lyrics/A/slug-lyric.html  (uppercase letter)
        m = re.search(r"/lyrics/([A-Za-z])/(.+?)(?:-lyric)?\.html", source_url)
        if m:
            letter = m.group(1).lower()
            slug   = m.group(2)
        # Pattern 2: /lyrics/rs-a/slug-lyric.html  (older rs- prefix)
        if not slug:
            m = re.search(r"/lyrics/rs-([a-z])/(.+?)(?:-lyric)?\.html", source_url)
            if m:
                letter = m.group(1).lower()
                slug   = m.group(2)

    if slug and letter:
        png_url = f"{GB_BASE}/lyrics/baani-pdf-{letter}/{slug}.png"
        try:
            r = requests.get(png_url, headers=gb_headers, timeout=20)
            if r.status_code == 200 and "image" in r.headers.get("Content-Type",""):
                logger.info(f"  PNG ({len(r.content)} bytes): {png_url}")
                return r.content
            else:
                logger.info(f"  PNG not found: {png_url} ({r.status_code})")
        except Exception as e:
            logger.warning(f"  PNG fetch error: {e}")

    return None


# ── Gemini Vision OCR ─────────────────────────────────────────────────────────

OCR_PROMPT = """\
This is a scanned image of swaralipi (স্বরলিপি — Indian musical notation) 
for a Rabindra Sangeet (Tagore song) from the Swarabitan collection.

Please extract the complete musical notation from this image.
The notation uses Bengali sargam: সা রে গ মা পা ধা নি
with octave markers (dots above/below) and beat separators (|).

Transcribe ONLY the notation, not the song lyrics or title.
If no musical notation is visible in the image, reply: NO_NOTATION

Respond with only the notation text."""

async def ocr_notation_png(png_bytes: bytes) -> Optional[str]:
    """Use Gemini Vision to OCR the notation PNG."""
    b64 = base64.standard_b64encode(png_bytes).decode()
    try:
        loop = asyncio.get_event_loop()
        res  = await loop.run_in_executor(None, lambda: gemini().models.generate_content(
            model="gemini-2.5-flash",
            contents=[{
                "parts": [
                    {"inline_data": {"mime_type": "image/png", "data": b64}},
                    {"text": OCR_PROMPT},
                ]
            }],
            config=genai_types.GenerateContentConfig(
                temperature=0.1, max_output_tokens=4096
            ),
        ))
        text = (res.text or "").strip()
        return None if text == "NO_NOTATION" else text or None
    except Exception as e:
        logger.warning(f"  Gemini OCR error: {e}")
        return None


# ── Firestore match ────────────────────────────────────────────────────────────

async def find_in_firestore(title: str) -> Optional[tuple[str, dict]]:
    """Match NLTR Bengali first line to Firestore doc using first_line field."""
    db    = get_songs_db()
    clean = re.sub(r"[।,\.\!\?॥\s]+$", "", title).strip()
    # Use first 8 Bengali chars as prefix (matches first_line field)
    prefix = clean[:8] if len(clean) >= 8 else clean

    candidates = []

    # Search by first_line (Bengali Unicode — exact match for NLTR titles)
    async for doc in db.collection(FIRESTORE_COLLECTION)\
            .where("first_line",">=",prefix)\
            .where("first_line","<",prefix+"\uffff").limit(10).stream():
        candidates.append((doc.id, doc.to_dict()))

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Pick best match via Gemini
    ctitles = [d.get("first_line","") or d.get("title","") for _,d in candidates]
    try:
        loop = asyncio.get_event_loop()
        res  = await loop.run_in_executor(None, lambda: gemini().models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                f"Song first line from NLTR: '{clean}'\n"
                f"Which stored first_line best matches?\n"
                + "\n".join(f"{i+1}. {t}" for i,t in enumerate(ctitles))
                + f"\nReply with only a number 1-{len(ctitles)} or 0."
            ),
        ))
        idx = int((res.text or "0").strip()) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]
    except Exception:
        return candidates[0]

    return None




# ── Checkpoint ─────────────────────────────────────────────────────────────────

def load_done() -> set:
    return set(json.loads(CHECKPOINT.read_text()).get("done",[])) \
           if CHECKPOINT.exists() else set()

def mark_done(done: set, nid: int):
    done.add(str(nid))
    CHECKPOINT.write_text(json.dumps({"done": list(done)}))


# ── Main pipeline ──────────────────────────────────────────────────────────────

async def process_paryay(
    name: str, start: int,
    dry_run: bool, limit: Optional[int], delay: float, done: set, stats: dict
):
    logger.info(f"\n{'='*55}")
    logger.info(f"Paryay: {name} — start node {start}")

    cur, count = start, 0

    while cur is not None:
        if limit and count >= limit:
            logger.info(f"  Limit {limit} reached"); break

        logger.info(f"\n  node/{cur}")

        # Fetch NLTR page for title + next link
        soup = fetch_nltr(cur)
        if not soup:
            logger.warning(f"  Failed to fetch node/{cur}"); break

        song_title, paryay, next_id = parse_nltr_page(soup)
        logger.info(f"  Title: {song_title[:50]!r}")
        logger.info(f"  Next:  {next_id}")

        if str(cur) not in done:
            if song_title:
                # Match Firestore first to get source_url for correct PNG URL
                match = await find_in_firestore(song_title)
                if match:
                    doc_id, doc_data = match
                    logger.info(f"  Firestore: {doc_data.get('title','')[:40]}")

                    # Fetch notation PNG using source_url from Firestore doc
                    png = get_notation_png_from_doc(doc_data)
                    if png:
                        notation = await ocr_notation_png(png)
                        if notation:
                            logger.info(f"  Notation: {notation[:60]}…")
                            if not dry_run:
                                db = get_songs_db()
                                await db.collection(FIRESTORE_COLLECTION)\
                                    .document(doc_id).update({
                                    "notation_text":   notation,
                                    "notation_source": SOURCE_TAG,
                                    "nltr_node_id":    cur,
                                    "nltr_url":        f"{NLTR_BASE}/node/{cur}",
                                    "nltr_paryay":     name,
                                })
                                logger.info(f"  ✓ Saved → {doc_id}")
                            else:
                                logger.info(f"  [DRY-RUN] Would save → {doc_id}")
                            stats["ingested"] += 1
                        else:
                            logger.info(f"  No notation in PNG")
                            stats["no_notation"] += 1
                    else:
                        logger.info(f"  No PNG found")
                        stats["no_notation"] += 1
                else:
                    logger.warning(f"  No Firestore match for: {song_title[:40]}")
                    stats["no_match"] += 1
            else:
                logger.info(f"  No title extracted — skipping")
                stats["error"] += 1

            mark_done(done, cur)
            count += 1

        cur = next_id
        await asyncio.sleep(delay)


async def run(paryay_filter, dry_run, limit, delay, resume):
    done  = load_done() if resume else set()
    stats = {"ingested": 0, "no_notation": 0, "no_match": 0, "error": 0}

    targets = {k: v for k, v in PARYAY_STARTS.items()
               if paryay_filter is None or k == paryay_filter}

    for name, start in targets.items():
        await process_paryay(name, start, dry_run, limit, delay, done, stats)

    logger.info(f"\n{'='*55}\nFinal stats: {stats}")


async def main():
    from dotenv import load_dotenv
    load_dotenv(os.environ.get("DOTENV_FILE",".env.geetabitan"), override=True)

    p = argparse.ArgumentParser(description="NLTR swaralipi scraper")
    p.add_argument("--dry-run",    action="store_true")
    p.add_argument("--paryay",     default=None,
                   help="e.g. পূজা, স্বদেশ, প্রেম")
    p.add_argument("--limit",      type=int,   default=None)
    p.add_argument("--delay",      type=float, default=1.5)
    p.add_argument("--resume",     action="store_true")
    p.add_argument("--list",       action="store_true")
    args = p.parse_args()

    if args.list:
        for k, v in PARYAY_STARTS.items():
            print(f"  {k} → node/{v}")
        return

    await run(args.paryay, args.dry_run, args.limit, args.delay, args.resume)

if __name__ == "__main__":
    asyncio.run(main())