"""
api/routes/music.py — Music listening feature for Geetabitan.

GET /api/music/youtube/{song_id}
  Returns YouTube search URLs for the song (Suchitra Mitra + other singers).
"""
import logging
import urllib.parse

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/music", tags=["music"])

SINGERS = [
    # ── Legendary ──────────────────────────────────────────────────────────
    ("সুচিত্রা মিত্র",          "Suchitra Mitra"),
    ("দেবব্রত বিশ্বাস",         "Debabrata Biswas"),
    ("কণিকা বন্দ্যোপাধ্যায়",    "Kanika Bandyopadhyay"),
    ("হেমন্ত মুখোপাধ্যায়",      "Hemanta Mukhopadhyay"),
    # ── Contemporary ───────────────────────────────────────────────────────
    ("শ্রেয়া গুহঠাকুরতা",       "Shreya Guhathakurta"),
    ("ইমন চক্রবর্তী",           "Iman Chakraborty"),
    ("লোপামুদ্রা মিত্র",         "Lopamudra Mitra"),
    ("শ্রাবণী সেন",             "Srabani Sen"),
    ("জয়তী চক্রবর্তী",          "Jayati Chakraborty"),
    ("রেজওয়ানা চৌধুরী বন্যা",   "Rezwana Chowdhury Bonna"),
    ("লগ্নজিতা ভট্টাচার্য",      "Lagnajita Bhattacharya"),
    ("সাহানা বাজপেয়ী",          "Sahana Bajpaie"),
    # ── Outside traditional — Bollywood crossover ──────────────────────────
    ("শ্রেয়া ঘোষাল",            "Shreya Ghoshal"),
]

# Nazrul Geeti has its own singer canon — different from Rabindra Sangeet's.
NAZRUL_SINGERS = [
    # ── Legendary ──────────────────────────────────────────────────────────
    ("ফিরোজা বেগম",            "Firoza Begum"),
    ("আব্বাসউদ্দীন আহমেদ",      "Abbasuddin Ahmed"),
    ("সোহরাব হোসেন",           "Sohrab Hossain"),
    ("খালিদ হোসেন",            "Khalid Hossain"),
    # ── Contemporary ───────────────────────────────────────────────────────
    ("ইন্দ্রাণী সেন",           "Indrani Sen"),
    ("মঞ্জু দত্ত",              "Manju Dutta"),
    ("নাশিদ কামাল",            "Nashid Kamal"),
    ("সুজিত মুস্তফা",           "Sujit Mustafa"),
]

# Rajanikanta Sen has its own singer canon too.
RAJANIKANTA_SINGERS = [
    # ── Legendary ──────────────────────────────────────────────────────────
    ("সুমিত্রা সেন",            "Sumitra Sen"),
    # ── Contemporary ───────────────────────────────────────────────────────
    ("শ্রাবণী সেন",             "Srabani Sen"),
    ("লোপামুদ্রা মিত্র",         "Lopamudra Mitra"),
    ("রেজওয়ানা চৌধুরী বন্যা",   "Rezwana Chowdhury Bonna"),
]


@router.get("/youtube/{song_id}")
async def get_youtube_links(song_id: str):
    """
    Return YouTube search links for a song — one per major singer.
    No API key required. Looks the song up in the Rabindra Sangeet
    collection first (unchanged default), then Nazrul Geeti, then
    Rajanikanta Sen — a song_id alone doesn't say which catalog it
    came from.
    """
    from src.adar.db import get_db
    from domains.geetabitan.config import (
        FIRESTORE_COLLECTION,
        NAZRUL_FIRESTORE_COLLECTION,
        RAJANIKANTA_FIRESTORE_COLLECTION,
    )

    # A song_id alone doesn't say which catalog it came from — check Rabindra
    # (unchanged default) first, then the other collections in turn.
    db = get_db()
    COLLECTIONS = [
        ("rabindra",     FIRESTORE_COLLECTION),
        ("nazrul",       NAZRUL_FIRESTORE_COLLECTION),
        ("rajanikanta",  RAJANIKANTA_FIRESTORE_COLLECTION),
    ]
    doc = None
    source = "rabindra"
    for candidate_source, collection in COLLECTIONS:
        doc = await db.collection(collection).document(song_id).get()
        if doc.exists:
            source = candidate_source
            break
    if doc is None or not doc.exists:
        raise HTTPException(status_code=404, detail="Song not found")

    d          = doc.to_dict()
    source     = d.get("source", source)
    first_line = d.get("first_line", d.get("title", ""))
    title_rom  = d.get("title", "")   # Roman title from Geetabitan
    raag       = d.get("raag", "")

    GENRE_NAMES = {
        "nazrul":      ("নজরুলগীতি",      "Nazrul Geeti"),
        "rajanikanta": ("রজনীকান্তের গান", "Rajanikanta Sangeet"),
    }
    genre_bn, genre_en = GENRE_NAMES.get(source, ("রবীন্দ্রসঙ্গীত", "Rabindra Sangeet"))
    singers = {
        "nazrul":      NAZRUL_SINGERS,
        "rajanikanta": RAJANIKANTA_SINGERS,
    }.get(source, SINGERS)

    links = []
    for bn_name, en_name in singers:
        q_bn = urllib.parse.quote(f"{first_line} {bn_name} {genre_bn}")
        q_en = urllib.parse.quote(f"{en_name} {title_rom} {genre_en}")
        links.append({
            "singer_bn":  bn_name,
            "singer_en":  en_name,
            "youtube_bn": f"https://www.youtube.com/results?search_query={q_bn}",
            "youtube_en": f"https://www.youtube.com/results?search_query={q_en}",
        })

    # Spotify search (no API key needed — web search URL)
    q_sp = urllib.parse.quote(f"{title_rom} {genre_en}")
    spotify_url = f"https://open.spotify.com/search/{q_sp}"

    return {
        "song_id":    song_id,
        "first_line": first_line,
        "title":      title_rom,
        "raag":       raag,
        "youtube":    links,
        "spotify":    spotify_url,
    }