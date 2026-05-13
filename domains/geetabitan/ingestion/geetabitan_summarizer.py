"""
domains/geetabitan/ingestion/geetabitan_summarizer.py
Generates context / meaning / emotion / imagery summaries for each song
using Gemini and caches the result in the Firestore document.

At ingestion: called by run_ingestion.py --only summaries
At query time: called by summarize_aspect() tool if cache is missing.
"""

import asyncio
import json

from google.cloud import firestore
from google import genai

from src.adar.db import get_db   # reuse — already reads FIRESTORE_DATABASE
from domains.geetabitan.config import FIRESTORE_COLLECTION, SUMMARY_LYRICS_CHAR_LIMIT

_client: genai.Client | None = None

SUMMARY_MODEL = "gemini-2.5-flash"

SUMMARY_PROMPT = """\
তুমি রবীন্দ্রসঙ্গীতের একজন বিশেষজ্ঞ পণ্ডিত।

নিচের গানটি মনোযোগ দিয়ে পড়ো এবং বাংলায় JSON আকারে ঠিক এই ৪টি ক্ষেত্র পূরণ করো।

গানের শিরোনাম : {title}
পর্যায়        : {paryay}
রাগ            : {raag}
তাল            : {taal}

গানের কথা:
{lyrics}

শুধু এই JSON-টি রিটার্ন করো — কোনো preamble, markdown বা backtick ছাড়া:
{{
  "context":  "ঐতিহাসিক ও জীবনীমূলক প্রেক্ষাপট — কখন, কেন এবং কোন পরিস্থিতিতে লেখা হয়েছিল (২–৩ বাক্য)",
  "meaning":  "গানের আক্ষরিক ও রূপক অর্থ — কবি কী বলতে চেয়েছেন (২–৩ বাক্য)",
  "emotion":  "আবেগের স্তর — কোন অনুভূতি জাগায়, শ্রোতার উপর কী প্রভাব ফেলে (১–২ বাক্য)",
  "imagery":  "প্রধান চিত্রকল্প ও প্রতীক — কোন ছবি বা রূপক ব্যবহার হয়েছে (১–২ বাক্য)"
}}"""


def _init():
    global _client
    if _client is None:
        import os
        _client = genai.Client(api_key=os.environ.get('GOOGLE_API_KEY', ''))


async def generate_and_store_summary(song: dict, force: bool = False) -> dict:
    """Generate a summary for one song and cache it in Firestore.
    Skips generation if a valid cached summary already exists (unless force=True).
    Returns the summary dict."""
    _init()

    firestore_id = song.get("firestore_id") or song.get("id")
    db           = get_db()
    doc_ref      = db.collection(FIRESTORE_COLLECTION).document(firestore_id)
    doc          = await doc_ref.get()

    if doc.exists:
        existing = doc.to_dict().get("summary", {})
        if existing.get("context") and not force:
            return existing  # serve cached

    # Build prompt
    prompt = SUMMARY_PROMPT.format(
        title  = song.get("title",  ""),
        paryay = song.get("paryay", ""),
        raag   = song.get("raag",   ""),
        taal   = song.get("taal",   ""),
        lyrics = (song.get("lyrics_full") or "")[:SUMMARY_LYRICS_CHAR_LIMIT],
    )

    response = _client.models.generate_content(
        model    = SUMMARY_MODEL,
        contents = prompt,
    )
    raw = response.text.strip()
    # Strip any accidental markdown fences
    raw = raw.lstrip("```json").lstrip("```").rstrip("```").strip()

    try:
        summary = json.loads(raw)
    except json.JSONDecodeError:
        summary = {
            "context":  "",
            "meaning":  raw,
            "emotion":  "",
            "imagery":  "",
        }

    summary["generated_at"] = firestore.SERVER_TIMESTAMP
    summary["model"]        = SUMMARY_MODEL

    await doc_ref.update({"summary": summary})
    return summary


async def summarize_all(songs: list[dict], force: bool = False, delay: float = 0.5):
    """Run summarization for every song with a small delay to respect rate limits."""
    total = len(songs)
    print(f"Generating summaries for {total} songs …")
    for i, song in enumerate(songs):
        try:
            await generate_and_store_summary(song, force=force)
        except Exception as exc:
            print(f"  ERROR song {song.get('id')}: {exc}")
        await asyncio.sleep(delay)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{total} done")
    print("Summary generation complete.")