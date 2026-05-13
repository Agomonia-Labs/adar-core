"""
domains/geetabitan/ingestion/swaralipi_ocr.py

OCR pipeline for Swaralipi (স্বরলিপি) books.

PROCESS:
  1. Reads PDF pages from a Swaralipi book (local file or URL)
  2. Sends each page to Gemini Vision to extract notation text
  3. Matches each notation to a song in Firestore by title
  4. Stores notation_text, notation_source, notation_page in the song doc

USAGE:
  # Single PDF file
  PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.swaralipi_ocr \
    --pdf /path/to/swaralipi_book.pdf \
    --source "গীতবিতান স্বরলিপি ১ম খণ্ড"

  # Directory of image files (JPG/PNG scans)
  PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.swaralipi_ocr \
    --images /path/to/scans/ \
    --source "রবীন্দ্র স্বরলিপি ৩য় খণ্ড"

  # Dry run (shows OCR output without saving)
  PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.swaralipi_ocr \
    --pdf /path/to/book.pdf --dry-run

REQUIREMENTS:
  pip install pymupdf pillow google-generativeai
"""

import asyncio
import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

from google import genai
from google.genai import types as genai_types

from src.adar.db import get_db
from domains.geetabitan.config import FIRESTORE_COLLECTION


# ── Gemini client ─────────────────────────────────────────────────────────────

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))
    return _client


# ── OCR prompt ────────────────────────────────────────────────────────────────

OCR_PROMPT = """এটি একটি রবীন্দ্রসঙ্গীত স্বরলিপি বইয়ের পৃষ্ঠা।

এই পৃষ্ঠা থেকে নিম্নলিখিত তথ্য বের করো:

১. গানের নাম (শিরোনাম) — বাংলায়
২. সম্পূর্ণ স্বরলিপি — সা রে গ মা পা ধা নি সহ সমস্ত নোট
৩. তাল ও রাগের নাম যদি উল্লেখ থাকে

JSON ফরম্যাটে উত্তর দাও:
{
  "title": "গানের নাম",
  "notation": "সম্পূর্ণ স্বরলিপি টেক্সট",
  "raag": "রাগের নাম বা খালি string",
  "taal": "তালের নাম বা খালি string",
  "has_notation": true/false
}

যদি পৃষ্ঠায় স্বরলিপি না থাকে তাহলে has_notation: false দাও।
শুধু JSON দাও, কোনো ব্যাখ্যা নয়।"""


async def ocr_page(image_bytes: bytes, mime: str = "image/jpeg") -> dict:
    """Send one page image to Gemini and extract notation."""
    b64 = base64.standard_b64encode(image_bytes).decode()
    try:
        response = _get_client().models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                {
                    "parts": [
                        {"inline_data": {"mime_type": mime, "data": b64}},
                        {"text": OCR_PROMPT},
                    ]
                }
            ],
        )
        text = response.text.strip()
        # Strip markdown code fences if present
        text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:
        print(f"    OCR error: {e}")
        return {"has_notation": False, "error": str(e)}


# ── PDF → pages ───────────────────────────────────────────────────────────────

def pdf_to_images(pdf_path: str, dpi: int = 150) -> list[tuple[int, bytes]]:
    """Convert PDF pages to JPEG bytes. Returns [(page_num, bytes), ...]"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("ERROR: Install pymupdf → pip install pymupdf")
        sys.exit(1)

    doc    = fitz.open(pdf_path)
    pages  = []
    matrix = fitz.Matrix(dpi / 72, dpi / 72)

    for i, page in enumerate(doc):
        pix  = page.get_pixmap(matrix=matrix)
        img  = pix.tobytes("jpeg")
        pages.append((i + 1, img))
        print(f"  Converted page {i + 1}/{len(doc)}")

    doc.close()
    return pages


def images_from_dir(img_dir: str) -> list[tuple[int, bytes]]:
    """Load image files from a directory. Returns [(page_num, bytes), ...]"""
    exts  = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    files = sorted(
        p for p in Path(img_dir).iterdir()
        if p.suffix.lower() in exts
    )
    pages = []
    for i, f in enumerate(files):
        pages.append((i + 1, f.read_bytes()))
        print(f"  Loaded {f.name}")
    return pages


# ── Title matching ────────────────────────────────────────────────────────────

async def find_song_doc(title: str) -> tuple[str, dict] | None:
    """
    Find the Firestore song document by title.
    Tries exact match first, then uses Gemini to match approximately.
    Returns (doc_id, data) or None.
    """
    db = get_db()

    # 1. Exact match
    async for doc in db.collection(FIRESTORE_COLLECTION) \
            .where("title", "==", title).limit(1).stream():
        return doc.id, doc.to_dict()

    # 2. Fuzzy: search for songs whose title starts with the first 5 chars
    prefix = title[:5] if len(title) >= 5 else title
    candidates = []
    async for doc in db.collection(FIRESTORE_COLLECTION) \
            .where("title", ">=", prefix) \
            .where("title", "<", prefix + "\uffff") \
            .limit(10).stream():
        candidates.append((doc.id, doc.to_dict()))

    if not candidates:
        return None

    # 3. Ask Gemini to pick the best match
    candidate_titles = [d["title"] for _, d in candidates]
    prompt = (
        f"OCR থেকে পাওয়া শিরোনাম: '{title}'\n"
        f"নিচের তালিকা থেকে সবচেয়ে কাছের মিল কোনটি?\n"
        + "\n".join(f"{i+1}. {t}" for i, t in enumerate(candidate_titles))
        + "\n\nশুধু সংখ্যা দাও (1-" + str(len(candidate_titles)) + "), বা 0 যদি কোনো মিল না থাকে।"
    )
    try:
        resp = _get_client().models.generate_content(
            model="gemini-2.5-flash", contents=prompt
        )
        idx = int(resp.text.strip()) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]
    except Exception:
        pass

    return None


# ── Main ingestion ────────────────────────────────────────────────────────────

async def ingest_swaralipi(
    pages: list[tuple[int, bytes]],
    source: str,
    dry_run: bool = False,
    delay: float = 1.0,
    mime: str = "image/jpeg",
):
    """OCR each page and save notation to Firestore."""
    db          = get_db()
    total       = len(pages)
    ingested    = 0
    not_found   = 0
    no_notation = 0

    print(f"\nOCR processing {total} pages …\n")

    for page_num, img_bytes in pages:
        print(f"Page {page_num}/{total} — OCR …")
        result = await ocr_page(img_bytes, mime)

        if not result.get("has_notation", False):
            print(f"  → No notation found")
            no_notation += 1
            await asyncio.sleep(delay)
            continue

        title    = result.get("title", "").strip()
        notation = result.get("notation", "").strip()

        if not title or not notation:
            print(f"  → Missing title or notation")
            no_notation += 1
            continue

        print(f"  → Title: {title}")
        print(f"  → Notation preview: {notation[:60]}…")

        if dry_run:
            print(f"  [DRY RUN] Would save to Firestore")
            ingested += 1
            await asyncio.sleep(delay)
            continue

        # Match to Firestore song
        match = await find_song_doc(title)
        if not match:
            print(f"  → ⚠ No matching song in Firestore for: {title}")
            not_found += 1
            await asyncio.sleep(delay)
            continue

        doc_id, data = match
        print(f"  → Matched: {data['title']} (id: {doc_id})")

        # Save notation fields
        update = {
            "notation_text":   notation,
            "notation_source": source,
            "notation_page":   page_num,
        }
        if result.get("raag"):
            update["notation_raag"] = result["raag"]
        if result.get("taal"):
            update["notation_taal"] = result["taal"]

        await db.collection(FIRESTORE_COLLECTION).document(doc_id).update(update)
        print(f"  ✓ Saved notation")
        ingested += 1
        await asyncio.sleep(delay)

    print(f"\n{'='*40}")
    print(f"Done.")
    print(f"  Ingested:    {ingested}")
    print(f"  No notation: {no_notation}")
    print(f"  Not found:   {not_found}")
    if not dry_run and not_found > 0:
        print(f"\n  Tip: unmatched songs may need manual title correction.")


# ── CLI ───────────────────────────────────────────────────────────────────────

async def main():
    from dotenv import load_dotenv
    env_file = os.environ.get("DOTENV_FILE", ".env.geetabitan")
    load_dotenv(env_file, override=True)

    parser = argparse.ArgumentParser(
        description="OCR Swaralipi books and ingest into Geetabitan Firestore"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf",    help="Path to PDF file")
    group.add_argument("--images", help="Directory of image scans")

    parser.add_argument("--source",  required=True,
                        help="Book name e.g. 'গীতবিতান স্বরলিপি ১ম খণ্ড'")
    parser.add_argument("--dry-run", action="store_true",
                        help="OCR and print output without saving to Firestore")
    parser.add_argument("--dpi",   type=int, default=150,
                        help="DPI for PDF rendering (default 150)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Delay between API calls in seconds (default 1.0)")
    parser.add_argument("--pages", type=str, default=None,
                        help="Page range e.g. '1-50' or '10,20,30'")
    args = parser.parse_args()

    # Load pages
    if args.pdf:
        print(f"Converting PDF: {args.pdf}")
        pages = pdf_to_images(args.pdf, dpi=args.dpi)
    else:
        print(f"Loading images from: {args.images}")
        pages = images_from_dir(args.images)

    # Filter page range if specified
    if args.pages:
        if "-" in args.pages:
            start, end = map(int, args.pages.split("-"))
            pages = [(n, b) for n, b in pages if start <= n <= end]
        else:
            nums  = set(map(int, args.pages.split(",")))
            pages = [(n, b) for n, b in pages if n in nums]
        print(f"Filtered to {len(pages)} pages")

    await ingest_swaralipi(
        pages    = pages,
        source   = args.source,
        dry_run  = args.dry_run,
        delay    = args.delay,
    )


if __name__ == "__main__":
    asyncio.run(main())