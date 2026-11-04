"""
domains/geetabitan/ingestion/dwijendralal_summarizer.py
Generates context / meaning / emotion / imagery summaries for each
Dwijendralal Roy song using Gemini and caches the result in the Firestore
document — same shape as geetabitan_summarizer.py / nazrul_summarizer.py /
rajanikanta_summarizer.py / atulprasad_summarizer.py, but with a prompt
suited to Dwijendralal Roy: a পঞ্চকবি known primarily as a playwright and
social satirist, whose songs mostly survive as interpolated numbers inside
his historical/patriotic plays (সাজাহান, চন্দ্রগুপ্ত, মেবার পতন, রাণা প্রতাপ
সিংহ) rather than as freestanding lyrics — so context for one of his songs
usually means the dramatic moment and character singing it, not just a
biographical note about the poet.

At ingestion: called by run_ingestion.py --only dwijendralal-summaries
At query time: called by summarize_aspect() tool when the resolved song's
'source' field is "dwijendralal".
"""

import asyncio
import json

from google.cloud import firestore
from google import genai

from src.adar.db import get_db
from domains.geetabitan.config import DWIJENDRALAL_FIRESTORE_COLLECTION, SUMMARY_LYRICS_CHAR_LIMIT

_client: genai.Client | None = None

SUMMARY_MODEL = "gemini-2.5-flash"

SUMMARY_PROMPT = """\
তুমি দ্বিজেন্দ্রলাল রায়ের (দ্বিজেন্দ্রগীতি) নাটক ও গানের একজন বিশেষজ্ঞ পণ্ডিত।

এই গানটি দ্বিজেন্দ্রলালের "{category}" নাটকের অন্তর্ভুক্ত একটি সংগীত — তাঁর
অধিকাংশ গানের মতোই এটি কোনো নাটকীয় মুহূর্তে কোনো চরিত্রের কণ্ঠে গীত হয়েছে,
স্বতন্ত্র গীতিকবিতা নয়। নিচের গানটি মনোযোগ দিয়ে পড়ো এবং বাংলায় JSON আকারে
ঠিক এই ৪টি ক্ষেত্র পূরণ করো।

নাটক           : {category}
গানের শিরোনাম : {title}
রাগ            : {raag}
তাল            : {taal}

গানের কথা:
{lyrics}

শুধু এই JSON-টি রিটার্ন করো — কোনো preamble, markdown বা backtick ছাড়া:
{{
  "context":  "নাটকীয় ও ঐতিহাসিক প্রেক্ষাপট — নাটকের কোন পর্বে, কোন চরিত্রের মুখে এই গান, এবং কেন (২–৩ বাক্য)",
  "meaning":  "গানের আক্ষরিক ও রূপক অর্থ — চরিত্রটি কী বলতে চায় (২–৩ বাক্য)",
  "emotion":  "আবেগের স্তর — কোন অনুভূতি জাগায়, শ্রোতার উপর কী প্রভাব ফেলে (১–২ বাক্য)",
  "imagery":  "প্রধান চিত্রকল্প ও প্রতীক — কোন ছবি বা রূপক ব্যবহার হয়েছে (১–২ বাক্য)"
}}"""


def _init():
    global _client
    if _client is None:
        import os
        _client = genai.Client(api_key=os.environ.get('GOOGLE_API_KEY', ''))


async def generate_and_store_summary(song: dict, force: bool = False) -> dict:
    """Generate a summary for one Dwijendralal Roy song and cache it in
    Firestore. Skips generation if a valid cached summary already exists
    (unless force=True). Returns the summary dict."""
    _init()

    firestore_id = song.get("firestore_id") or song.get("id")
    db           = get_db()
    doc_ref      = db.collection(DWIJENDRALAL_FIRESTORE_COLLECTION).document(firestore_id)
    doc          = await doc_ref.get()

    if doc.exists:
        existing = doc.to_dict().get("summary", {})
        if existing.get("context") and not force:
            return existing  # serve cached

    prompt = SUMMARY_PROMPT.format(
        title    = song.get("title",    ""),
        category = song.get("category", ""),
        raag     = song.get("raag",     ""),
        taal     = song.get("taal",     ""),
        lyrics   = (song.get("lyrics_full") or "")[:SUMMARY_LYRICS_CHAR_LIMIT],
    )

    response = _client.models.generate_content(
        model    = SUMMARY_MODEL,
        contents = prompt,
    )
    raw = response.text.strip()
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
    """Run summarization for every Dwijendralal Roy song with a small delay
    to respect rate limits."""
    total = len(songs)
    print(f"Generating summaries for {total} Dwijendralal Roy songs …")
    for i, song in enumerate(songs):
        try:
            await generate_and_store_summary(song, force=force)
        except Exception as exc:
            print(f"  ERROR song {song.get('id')}: {exc}")
        await asyncio.sleep(delay)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{total} done")
    print("Dwijendralal Roy summary generation complete.")
