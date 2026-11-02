"""
domains/geetabitan/ingestion/nazrul_swaralipi_scraper.py

Extracts swaralipi (notation) for Nazrul Geeti songs from the Nazrul
Institute's published "নজরুল-সঙ্গীত স্বরলিপি" notation volumes and saves it
additively onto the matching documents in the nazrulgeeti_songs Firestore
collection. This never touches geetabitan_songs (Rabindra Sangeet) — see
docs/nazrul_swaralipi_research.md for the full research behind this script.

SOURCE DATA:
  Of the Nazrul Institute's full swaralipi series (59+ volumes), only 3 are
  freely digitized on their e-library: volumes 34, 35, 36. Their PDFs are
  scanned page images (no text layer — confirmed via PyMuPDF) hosted on a
  public Oracle object-storage bucket that is NOT reachable by curl/requests
  from this environment (egress proxy returns 403) — they were downloaded
  once via the Claude Browser pane and saved locally. This script works
  entirely from those local PDF files; it does no network fetching of the
  source PDFs itself.

  Expected local paths (already present after the one-time browser download):
    domains/geetabitan/data/nazrul_swaralipi_pdfs/nazrul_swaralipi_vol34.pdf
    domains/geetabitan/data/nazrul_swaralipi_pdfs/nazrul_swaralipi_vol35.pdf
    domains/geetabitan/data/nazrul_swaralipi_pdfs/nazrul_swaralipi_vol36.pdf

HOW IT WORKS:
  1. Render each PDF page to an image with PyMuPDF (no OCR text layer exists).
  2. Ask Gemini Vision to read the page and return JSON: whether the page
     starts a new song (and if so, its title) and the sargam/swaralipi
     notation text visible on the page.
  3. Group consecutive pages into one song wherever a page doesn't start a
     new title (songs often span 2-4 pages in these volumes).
  4. Match each extracted song title against the nazrulgeeti_songs Firestore
     collection (prefix query on `title`, same pattern as the Rabindra
     Sangeet nltr_swaralipi_scraper.py, with Gemini disambiguation when the
     prefix matches more than one doc).
  5. Save additively: notation_text, notation_source, notation_volume,
     notation_pdf_pages — new fields only, never overwriting existing song
     fields, never touching geetabitan_songs.

USAGE:
  pip install pymupdf

  # Dry run — volume 36, first 10 pages
  DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \\
  python -m domains.geetabitan.ingestion.nazrul_swaralipi_scraper \\
    --volume 36 --limit 10 --dry-run

  # One full volume
  DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \\
  python -m domains.geetabitan.ingestion.nazrul_swaralipi_scraper --volume 36

  # All 3 available volumes, resuming from checkpoint
  DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \\
  python -m domains.geetabitan.ingestion.nazrul_swaralipi_scraper --volume all --resume
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from google import genai
from google.genai import types as genai_types
from google.cloud import firestore as _firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from domains.geetabitan.config import NAZRUL_FIRESTORE_COLLECTION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "nazrul_swaralipi_pdfs"

VOLUME_INFO = {
    34: {
        "pdf": PDF_DIR / "nazrul_swaralipi_vol34.pdf",
        "label": "৩৪তম খণ্ড",
        "url": "https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/n/axvjbnqprylg/b/V2Ministry/o/office-nazrulinstitute/2024/12/526be5389766445e91ec8855d39cc4f9.pdf",
    },
    35: {
        "pdf": PDF_DIR / "nazrul_swaralipi_vol35.pdf",
        "label": "৩৫তম খণ্ড",
        "url": "https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/n/axvjbnqprylg/b/V2Ministry/o/office-nazrulinstitute/2024/12/c433936ceda7432988cc1287769d63f5.pdf",
    },
    36: {
        "pdf": PDF_DIR / "nazrul_swaralipi_vol36.pdf",
        "label": "৩৬তম খণ্ড",
        "url": "https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/n/axvjbnqprylg/b/V2Ministry/o/office-nazrulinstitute/2024/12/4550e16d16564d95b4a1d2c75802a65a.pdf",
    },
}

CHECKPOINT = Path("/tmp/nazrul_swaralipi_checkpoint.json")


def get_songs_db():
    """Connect directly to the geetabitan-db Firestore database (same DB as
    Rabindra Sangeet — different collection: NAZRUL_FIRESTORE_COLLECTION)."""
    db_name = os.environ.get("AUTH_FIRESTORE_DATABASE",
              os.environ.get("FIRESTORE_DATABASE", "geetabitan-db"))
    project = os.environ.get("GCP_PROJECT_ID",
              os.environ.get("GOOGLE_CLOUD_PROJECT", "bdas-493785"))
    return _firestore.AsyncClient(project=project, database=db_name)


_gem = None
def gemini():
    global _gem
    if not _gem:
        _gem = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))
    return _gem


# ── PDF rendering ──────────────────────────────────────────────────────────

def render_page_png(pdf_path: Path, page_index: int, dpi: int = 200) -> bytes:
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_index]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


def page_count(pdf_path: Path) -> int:
    doc = fitz.open(str(pdf_path))
    try:
        return doc.page_count
    finally:
        doc.close()


# ── Gemini Vision OCR ──────────────────────────────────────────────────────

OCR_PROMPT = """\
This is one page from a published স্বরলিপি (swaralipi — Indian musical
notation) book of Nazrul Geeti (Kazi Nazrul Islam's songs), from the Nazrul
Institute's official notation series. Each song entry has a Bengali title
heading, record-label/artist/raga/taal metadata, and sargam notation lines
(Bengali sargam: সা রে গ মা পা ধা নি, with octave marks and beat separators).
A song may span multiple pages — only the FIRST page of a song shows its
title heading; continuation pages have no title.

Look at this page and respond with ONLY a JSON object, no other text:
{
  "is_new_song": true or false,       // true only if this page shows a song TITLE heading
  "title": "exact Bengali title text, or null if is_new_song is false",
  "has_notation": true or false,       // true if any sargam/swaralipi notation is visible
  "notation": "the notation text on this page, or empty string if none"
}

If this page is front matter (cover, foreword, table of contents, notation
conventions) with no song title and no notation, respond:
{"is_new_song": false, "title": null, "has_notation": false, "notation": ""}
"""


async def ocr_page(png_bytes: bytes) -> dict:
    b64 = base64.standard_b64encode(png_bytes).decode()
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: gemini().models.generate_content(
            model="gemini-2.5-flash",
            contents=[{
                "parts": [
                    {"inline_data": {"mime_type": "image/png", "data": b64}},
                    {"text": OCR_PROMPT},
                ]
            }],
            config=genai_types.GenerateContentConfig(
                temperature=0.1, max_output_tokens=4096,
                response_mime_type="application/json",
            ),
        ))
        text = (res.text or "").strip()
        data = json.loads(text)
        return {
            "is_new_song": bool(data.get("is_new_song")),
            "title": data.get("title") or None,
            "has_notation": bool(data.get("has_notation")),
            "notation": data.get("notation") or "",
        }
    except Exception as e:
        logger.warning(f"  Gemini OCR error: {e}")
        return {"is_new_song": False, "title": None, "has_notation": False, "notation": ""}


# ── Firestore match ─────────────────────────────────────────────────────────

def clean_extracted_title(title: str) -> str:
    """Strip OCR artifacts that aren't part of the real song title: trailing
    artist/singer credits in parens (e.g. "গান-শিরোনাম (ফিরোজা)"), bracketed
    annotations, and trailing punctuation."""
    t = title.strip()
    while True:
        new_t = re.sub(r"\s*[\(\uFF08\[][^\)\uFF09\]]*[\)\uFF09\]]\s*$", "", t)
        if new_t == t:
            break
        t = new_t
    t = re.sub(r"[।,.!?॥\s\-–—]+$", "", t).strip()
    return t


async def _query_prefix(db, prefix: str) -> list:
    candidates = []
    query = db.collection(NAZRUL_FIRESTORE_COLLECTION) \
        .where(filter=FieldFilter("title", ">=", prefix)) \
        .where(filter=FieldFilter("title", "<", prefix + "￿")) \
        .limit(10)
    async for doc in query.stream():
        candidates.append((doc.id, doc.to_dict()))
    return candidates


async def find_in_firestore(title: str) -> Optional[tuple[str, dict]]:
    """Match an extracted swaralipi book title to a nazrulgeeti_songs doc by
    its `title` field (prefix query), same pattern as the Rabindra Sangeet
    scraper's first_line matching. Tries a progressively shorter prefix
    (handles OCR noise in the trailing chars of the match window) before
    giving up."""
    db = get_songs_db()
    clean = clean_extracted_title(title)
    if not clean:
        return None

    # Try multiple normalizations of compound-word punctuation: sources
    # disagree on whether "অরুণ-রাঙা" is hyphenated, space-separated, or
    # joined with no separator at all — try all three before giving up.
    variants = [clean]
    if "-" in clean or "–" in clean or "—" in clean:
        spaced = re.sub(r"[-–—]+", " ", clean)
        spaced = re.sub(r"\s+", " ", spaced).strip()
        joined = re.sub(r"[-–—]+", "", clean)
        for v in (spaced, joined):
            if v and v not in variants:
                variants.append(v)

    candidates = []
    for v in variants:
        for plen in (8, 6, 4):
            if len(v) < plen:
                continue
            prefix = v[:plen]
            candidates = await _query_prefix(db, prefix)
            if candidates:
                break
        if candidates:
            break

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    ctitles = [d.get("title", "") for _, d in candidates]
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: gemini().models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                f"Song title from a swaralipi book: '{clean}'\n"
                f"Which stored title best matches?\n"
                + "\n".join(f"{i+1}. {t}" for i, t in enumerate(ctitles))
                + f"\nReply with only a number 1-{len(ctitles)} or 0 if none match."
            ),
        ))
        idx = int((res.text or "0").strip()) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]
    except Exception:
        return candidates[0]

    return None


# ── Checkpoint ───────────────────────────────────────────────────────────────

def load_checkpoint() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {}

def save_checkpoint(cp: dict):
    CHECKPOINT.write_text(json.dumps(cp))


# ── Main pipeline ────────────────────────────────────────────────────────────

async def process_volume(
    volume: int, dry_run: bool, limit: Optional[int], resume: bool, stats: dict
):
    info = VOLUME_INFO[volume]
    pdf_path = info["pdf"]
    if not pdf_path.exists():
        logger.error(f"PDF not found: {pdf_path} — skipping volume {volume}")
        return

    total_pages = page_count(pdf_path)
    n_pages = min(limit, total_pages) if limit else total_pages
    logger.info(f"\n{'='*55}\nVolume {volume} ({info['label']}) — {n_pages}/{total_pages} pages")

    cp = load_checkpoint() if resume else {}
    vol_key = str(volume)
    cp.setdefault(vol_key, {"done_pages": [], "songs": {}})
    done_pages = set(cp[vol_key]["done_pages"])
    songs = cp[vol_key]["songs"]  # title -> {"notation": str, "pages": [int]}

    current_title = None

    for i in range(n_pages):
        if i in done_pages:
            # Rebuild current_title continuity on resume by re-OCR'ing is
            # avoided — on resume we just continue grouping fresh from the
            # next un-done page onward.
            continue

        logger.info(f"  page {i+1}/{n_pages}")
        png = render_page_png(pdf_path, i)
        result = await ocr_page(png)

        if result["is_new_song"] and result["title"]:
            current_title = result["title"]
            songs.setdefault(current_title, {"notation": "", "pages": []})

        if current_title and result["has_notation"] and result["notation"]:
            songs[current_title]["notation"] += ("\n" if songs[current_title]["notation"] else "") + result["notation"]
            songs[current_title]["pages"].append(i + 1)

        done_pages.add(i)
        cp[vol_key]["done_pages"] = sorted(done_pages)
        cp[vol_key]["songs"] = songs
        save_checkpoint(cp)

    logger.info(f"  Extracted {len(songs)} song(s) from volume {volume}")

    for title, data in songs.items():
        if not data["notation"]:
            continue
        match = await find_in_firestore(title)
        if not match:
            logger.warning(f"  No Firestore match for: {title[:40]}")
            stats["no_match"] += 1
            continue

        doc_id, doc_data = match
        logger.info(f"  Matched '{title[:30]}' → {doc_data.get('title','')[:30]} ({doc_id})")

        if not dry_run:
            db = get_songs_db()
            await db.collection(NAZRUL_FIRESTORE_COLLECTION).document(doc_id).update({
                "notation_text":      data["notation"],
                "notation_source":    f"Nazrul Institute নজরুল-সংগীত স্বরলিপি {info['label']} (OCR by Gemini)",
                "notation_volume":    volume,
                "notation_pdf_url":   info["url"],
                "notation_pdf_pages": data["pages"],
            })
            logger.info(f"  ✓ Saved → {doc_id}")
        else:
            logger.info(f"  [DRY-RUN] Would save → {doc_id} ({len(data['notation'])} chars, pages {data['pages']})")

        stats["ingested"] += 1


async def run(volumes: list[int], dry_run: bool, limit: Optional[int], resume: bool):
    stats = {"ingested": 0, "no_match": 0}
    for v in volumes:
        await process_volume(v, dry_run, limit, resume, stats)
    logger.info(f"\n{'='*55}\nFinal stats: {stats}")


async def main():
    from dotenv import load_dotenv
    load_dotenv(os.environ.get("DOTENV_FILE", ".env.geetabitan"), override=True)

    p = argparse.ArgumentParser(description="Nazrul Geeti swaralipi scraper (Nazrul Institute volumes)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--volume", default="all", help="34, 35, 36, or all")
    p.add_argument("--limit", type=int, default=None, help="limit pages per volume (for testing)")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()

    volumes = [34, 35, 36] if args.volume == "all" else [int(args.volume)]
    await run(volumes, args.dry_run, args.limit, args.resume)


if __name__ == "__main__":
    asyncio.run(main())
