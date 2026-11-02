"""
domains/geetabitan/tools/song_tools.py
Song retrieval and summary tools.
"""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from typing import Literal

from src.adar.db import direct_query, get_documents_by_field, get_db, vector_search
from domains.geetabitan.config import (
    FIRESTORE_COLLECTION,
    NAZRUL_FIRESTORE_COLLECTION,
)
from domains.geetabitan.data.raag_metadata import TAAL_DATA

Composer = Literal["rabindra", "nazrul"]

_COMPOSER_COLLECTIONS: dict[str, str] = {
    "rabindra": FIRESTORE_COLLECTION,
    "nazrul": NAZRUL_FIRESTORE_COLLECTION,
}


def _collection_for(composer: Composer = "rabindra") -> str:
    """Firestore collection for a composer. Defaults to today's only
    collection, so every existing (no-argument) call site is unaffected."""
    return _COMPOSER_COLLECTIONS.get(composer, FIRESTORE_COLLECTION)


def _other_composer(composer: Composer) -> Composer:
    return "nazrul" if composer == "rabindra" else "rabindra"


# ── Taal lookup — case-insensitive fallback ───────────────────────────────────

def _taal_meta(taal: str) -> dict:
    """Look up taal metadata, case-insensitive, so 'Dadra' matches 'দাদরা'."""
    return TAAL_DATA.get(taal) or next(
        (v for k, v in TAAL_DATA.items() if k.lower() == taal.lower()), {}
    )


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace("\u200c", "").replace("\u200d", "")
    return re.sub(r"\s+", " ", text).strip()


def _compact_bengali(text: str) -> str:
    return re.sub(r"[^\w\u0980-\u09ff]+", "", _normalize_text(text).lower())


def _clean_song_query(query: str) -> str:
    """Remove analysis/request words so title resolution sees the song phrase."""
    text = _normalize_text(query)
    text = re.sub(r"\[song_id:([^\]]+)\]", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsong_id\b\s*[:=]\s*", "", text, flags=re.IGNORECASE)
    for phrase in (
        "গানের প্রেক্ষাপট বলো", "গানের প্রেক্ষাপট", "প্রেক্ষাপট বলো",
        "প্রেক্ষাপট", "গানের অর্থ বলো", "গানের অর্থ", "অর্থ বলো", "অর্থ",
        "আবেগ বলো", "আবেগ", "চিত্রকল্প বলো", "চিত্রকল্প", "সারসংক্ষেপ",
        "summary", "context", "meaning", "emotion", "imagery", "song",
    ):
        text = text.replace(phrase, " ")
    return _normalize_text(text.strip(" ।.!?\"'‘’“”"))


def _doc_id_from_doc(doc: dict) -> str:
    return doc.get("doc_id") or doc.get("firestore_id") or doc.get("id") or ""


@lru_cache(maxsize=1)
def _local_songs() -> tuple[dict, ...]:
    data_path = Path(__file__).resolve().parents[1] / "data" / "songs.json"
    try:
        with data_path.open(encoding="utf-8") as f:
            songs = json.load(f)
    except Exception:
        return ()
    return tuple(s for s in songs if isinstance(s, dict))


def _find_local_song(query: str) -> dict | None:
    query_key = _compact_bengali(query)
    if not query_key:
        return None

    best_prefix = None
    for song in _local_songs():
        fields = (
            song.get("title", ""),
            song.get("first_line", ""),
            song.get("lyrics_full", ""),
        )
        keys = [_compact_bengali(value) for value in fields if value]
        if any(query_key == key for key in keys):
            return dict(song)
        if not best_prefix and any(key.startswith(query_key) for key in keys):
            best_prefix = song
        if not best_prefix and any(query_key in key for key in keys):
            best_prefix = song
    return dict(best_prefix) if best_prefix else None


# ── Internal: fetch one doc by its Firestore document ID ─────────────────────

async def _get_doc_by_id(doc_id: str, composer: Composer = "rabindra") -> dict | None:
    try:
        db  = get_db()
        doc = await db.collection(_collection_for(composer)).document(doc_id).get()
    except Exception:
        return None
    if not doc.exists:
        # song_id alone doesn't say which catalog it came from — fall back
        # to the other composer's collection before giving up.
        other = _other_composer(composer)
        try:
            doc = await db.collection(_collection_for(other)).document(doc_id).get()
        except Exception:
            return None
        if not doc.exists:
            return None
    data = doc.to_dict()
    data["doc_id"] = doc.id
    data.pop("embedding", None)
    return data


async def _resolve_song_doc(song_id_or_query: str, composer: Composer = "rabindra") -> dict | None:
    """Resolve a Firestore ID, visible title, first line, or user query to a song."""
    raw = _normalize_text(song_id_or_query)
    if not raw:
        return None

    marker = re.search(r"\[song_id:([^\]]+)\]", raw, flags=re.IGNORECASE)
    if marker:
        raw = marker.group(1).strip()

    doc = await _get_doc_by_id(raw, composer)
    if doc:
        return doc

    query = _clean_song_query(raw)
    if not query:
        return None

    collection = _collection_for(composer)

    for field in ("title", "first_line"):
        matches = await get_documents_by_field(
            collection=collection,
            field=field,
            value=query,
            limit=1,
        )
        if matches:
            return matches[0]

    if composer == "rabindra":
        # The local JSON cache only mirrors the original Rabindra Sangeet
        # catalog — Nazrul Geeti always resolves via Firestore.
        local_match = _find_local_song(query)
        if local_match:
            local_id = _doc_id_from_doc(local_match)
            firestore_doc = await _get_doc_by_id(local_id, composer) if local_id else None
            return firestore_doc or local_match

    matches = await vector_search(
        collection=collection,
        query=query,
        top_k=1,
    )
    return matches[0] if matches else None


# ── Lyrics formatter ──────────────────────────────────────────────────────────

def _format_lyrics(doc: dict) -> str:
    """
    Format full lyrics with proper stanza breaks and refrain indentation.

    Each stanza is separated by a blank line.
    Refrain lines (short lines ending with – or containing হায়/রে) are indented.
    """
    stanzas = doc.get("stanzas", [])
    if not stanzas:
        raw = doc.get("lyrics_full", "")
        if not raw:
            return ""
        # Split on double newlines if stanzas weren't stored separately
        stanzas = [s.strip() for s in raw.split("\n\n") if s.strip()]

    formatted_stanzas = []
    for stanza in stanzas:
        lines = stanza.split("\n")
        formatted_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Indent refrain-style lines: short lines or those ending with –
            is_refrain = (
                line.endswith("–") or line.endswith("-")
                or "হায় রে" in line
                or "মরি হায়" in line
                or (len(line) < 30 and not line.endswith("।"))
            )
            formatted_lines.append(f"   {line}" if is_refrain else line)
        formatted_stanzas.append("\n".join(formatted_lines))

    return "\n\n".join(formatted_stanzas)


# ── Song card formatter ───────────────────────────────────────────────────────

def _song_card(doc: dict) -> str:
    """Format a song as a structured card with metadata header and full lyrics."""
    tm      = _taal_meta(doc.get("taal", ""))
    raag    = doc.get("raag", "") or "—"
    taal    = doc.get("taal", "") or "—"
    beats   = tm.get("beats", "")
    beats_str = f" | {beats} মাত্রা" if beats else ""
    song_id = _doc_id_from_doc(doc)

    # Rabindra Sangeet is organized by পর্যায় (paryay); Nazrul Geeti docs
    # carry সংকলন (category/book name) instead — show whichever applies.
    if doc.get("source") == "nazrul":
        group_label, group_value = "সংকলন", doc.get("category", "—")
    else:
        group_label, group_value = "পর্যায়", doc.get("paryay", "—")

    lines = [
        f"[song_id:{song_id}]" if song_id else "",
        "─────────────────────────────",
        f"🎵 **{doc['title']}**",
        "─────────────────────────────",
        f"{group_label}: {group_value}  |  রাগ: {raag}  |  তাল: {taal}{beats_str}",
        "",
        _format_lyrics(doc),
    ]
    return "\n".join(line for line in lines if line)


# ── Song retrieval tools ──────────────────────────────────────────────────────

async def get_song_by_title(title: str, composer: Composer = "rabindra") -> str:
    """Fetch a song (Rabindra Sangeet by default, or Nazrul Geeti when
    composer="nazrul") by title, first line, or close query.
    Returns complete song with formatted lyrics."""
    doc = await _resolve_song_doc(title, composer)
    if doc:
        return _song_card(doc)
    return (
        f"'{title}' শিরোনামে সরাসরি কোনো গান পাওয়া যায়নি। "
        f"vector_search_songs দিয়ে খোঁজার চেষ্টা করুন।"
    )


async def get_full_song(song_id: str, composer: Composer = "rabindra") -> str:
    """Retrieve complete formatted lyrics of a song by its song_id."""
    doc = await _get_doc_by_id(song_id, composer)
    if not doc:
        return "গান পাওয়া যায়নি। অনুগ্রহ করে গানের নাম দিয়ে আবার খুঁজুন।"
    return _song_card(doc)


async def get_songs_by_paryay(paryay: str) -> str:
    """List all songs in a Geetabitan Paryay section."""
    results = await direct_query(
        collection=FIRESTORE_COLLECTION,
        filters={"paryay": paryay},
        limit=500,
    )
    if not results:
        return f"'{paryay}' পর্যায়ে কোনো গান পাওয়া যায়নি।"

    lines = [
        f"- **{r['title']}** | রাগ: {r.get('raag', '—')} | "
        f"তাল: {r.get('taal', '—')}"
        for r in results[:25]
    ]
    suffix = (
        f"\n\n_(মোট {len(results)}টি গান। নির্দিষ্ট গান দেখতে গানের নাম বলুন।)_"
        if len(results) > 25 else ""
    )
    return f"**{paryay}** পর্যায়ের গানসমূহ:\n" + "\n".join(lines) + suffix


async def get_songs_by_category(category: str) -> str:
    """List all Nazrul Geeti songs in a given book/collection (সংকলন),
    e.g. 'বুলবুল', 'সন্ধ্যা' — the Nazrul equivalent of get_songs_by_paryay."""
    results = await direct_query(
        collection=NAZRUL_FIRESTORE_COLLECTION,
        filters={"category": category},
        limit=500,
    )
    if not results:
        return f"'{category}' সংকলনে কোনো গান পাওয়া যায়নি।"

    lines = [
        f"- **{r['title']}** | রাগ: {r.get('raag', '—')} | "
        f"তাল: {r.get('taal', '—')}"
        for r in results[:25]
    ]
    suffix = (
        f"\n\n_(মোট {len(results)}টি গান। নির্দিষ্ট গান দেখতে গানের নাম বলুন।)_"
        if len(results) > 25 else ""
    )
    return f"**{category}** সংকলনের গানসমূহ:\n" + "\n".join(lines) + suffix


async def get_song_stanza(song_id: str, stanza_number: int, composer: Composer = "rabindra") -> str:
    """Get a specific stanza (স্তবক) of a song. stanza_number is 1-based."""
    doc = await _get_doc_by_id(song_id, composer)
    if not doc:
        return "গান পাওয়া যায়নি।"
    stanzas = doc.get("stanzas", [])
    if not stanzas:
        lyrics = doc.get("lyrics_full", doc.get("excerpt", ""))
        if lyrics:
            return lyrics
        return "এই গানের স্তবক পাওয়া যায়নি।"
    idx = stanza_number - 1
    if idx < 0 or idx >= len(stanzas):
        return f"স্তবক {stanza_number} পাওয়া যায়নি। এই গানে {len(stanzas)}টি স্তবক আছে।"
    return f"**স্তবক {stanza_number}:**\n\n{stanzas[idx]}"


async def list_raags() -> str:
    """List all raags with arohi, aborohi, vadi, samvadi and mood — as a markdown table."""
    from domains.geetabitan.data.raag_metadata import RAAG_DATA, TAAL_DATA
    raags = {k: v for k, v in RAAG_DATA.items() if k not in TAAL_DATA}
    rows  = []
    for name, meta in raags.items():
        rows.append(
            f"| {name} | {meta.get('time','—')} | {meta.get('mood','—')} "
            f"| {meta.get('arohi','—')} | {meta.get('aborohi','—')} "
            f"| {meta.get('vadi','—')} |"
        )
    table = (
        "## গীতবিতানে প্রচলিত রাগসমূহ\n\n"
        "| রাগ | সময় | মেজাজ | আরোহী | অবরোহী | বাদী |\n"
        "|---|---|---|---|---|---|\n"
        + "\n".join(rows)
        + f"\n\n_মোট {len(raags)}টি রাগ। যেকোনো রাগের বিস্তারিত জানতে রাগের নাম বলুন।_"
    )
    return table


async def list_taals() -> str:
    """List all taals with beats, vibhag, bols and mood — as a markdown table."""
    from domains.geetabitan.data.raag_metadata import TAAL_DATA
    rows = []
    for name, meta in TAAL_DATA.items():
        # Replace | with · so vibhag separators don't break markdown table columns
        bols = (meta.get("bols", "—") or "—").replace("|", "·")
        rows.append(
            f"| {name} | {meta.get('beats','—')} | "
            f"{meta.get('vibhag','—')} | {meta.get('tempo','—')} | "
            f"{meta.get('mood','—')} | {bols} |"
        )
    table = (
        "## গীতবিতানে প্রচলিত তালসমূহ\n\n"
        "| তাল | মাত্রা | বিভাগ | গতি | মেজাজ | বোল |\n"
        "|---|---|---|---|---|---|\n"
        + "\n".join(rows)
        + f"\n\n_মোট {len(TAAL_DATA)}টি তাল। যেকোনো তালের বিস্তারিত জানতে তালের নাম বলুন।_"
    )
    return table


async def _search_youtube(query: str, max_results: int = 5) -> list[dict]:
    """Search YouTube Data API v3. Returns [{title, videoId, channel}].
    Falls back to empty list if YOUTUBE_API_KEY is not set or request fails."""
    import os, httpx
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "q": query,
                    "type": "video",
                    "maxResults": max_results,
                    "key": api_key,
                    "relevanceLanguage": "bn",
                },
            )
            if not r.is_success:
                return []
            items = r.json().get("items", [])
            return [
                {
                    "title":   item["snippet"]["title"],
                    "videoId": item["id"]["videoId"],
                    "channel": item["snippet"]["channelTitle"],
                    "url":     f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                }
                for item in items
            ]
    except Exception:
        return []


async def get_youtube_url(song_id: str, composer: Composer = "rabindra") -> str:
    """Search YouTube for actual videos of this song. Returns direct watch links
    when videos are found, plus singer-specific search links as fallback."""
    import urllib.parse
    doc = await _get_doc_by_id(song_id, composer)
    if not doc:
        return "গান পাওয়া যায়নি।"

    # The doc itself says which catalog it's from — trust that over the
    # caller's composer guess (a bare song_id alone doesn't encode it).
    is_nazrul = doc.get("source") == "nazrul"

    first_line = doc.get("first_line", doc.get("title", ""))
    title      = doc.get("title", "")
    display    = first_line or title

    genre_bn = "নজরুলগীতি" if is_nazrul else "রবীন্দ্রসঙ্গীত"
    genre_en = "Nazrul Geeti" if is_nazrul else "Rabindra Sangeet"

    # ── Search YouTube for actual videos ──────────────────────────────────
    results_bn = await _search_youtube(f"{display} {genre_bn}", max_results=8)
    results_en = await _search_youtube(f"{title} {genre_en}", max_results=5) if not results_bn else []
    results    = results_bn or results_en

    # Deduplicate by videoId
    seen, unique = set(), []
    for r in results:
        if r["videoId"] not in seen:
            seen.add(r["videoId"])
            unique.append(r)

    lines = [f"## {display} — YouTube-এ শুনুন\n"]

    # ── Section 1: Actual videos found ────────────────────────────────────
    if unique:
        lines.append("### ✅ YouTube-এ পাওয়া ভিডিও\n")
        lines.append("| # | শিরোনাম | চ্যানেল | লিংক |")
        lines.append("|---|---|---|---|")
        for i, v in enumerate(unique, 1):
            safe_title = v["title"].replace("|", "\\|")
            safe_ch    = v["channel"].replace("|", "\\|")
            lines.append(f"| {i} | {safe_title} | {safe_ch} | [▶ দেখুন]({v['url']}) |")
        lines.append("")
    else:
        lines.append("_YouTube-এ এই গানের সরাসরি ভিডিও এখনো যাচাই করা সম্ভব হয়নি।"
                     " নিচের শিল্পী-ভিত্তিক অনুসন্ধান ব্যবহার করুন।_\n")

    # ── Section 2: Singer-specific search links ───────────────────────────
    RABINDRA_SINGERS = [
        ("সুচিত্রা মিত্র",        "Suchitra Mitra",          "লেজেন্ডারি"),
        ("দেবব্রত বিশ্বাস",       "Debabrata Biswas",         "লেজেন্ডারি"),
        ("কণিকা বন্দ্যোপাধ্যায়",  "Kanika Bandyopadhyay",    "লেজেন্ডারি"),
        ("হেমন্ত মুখোপাধ্যায়",    "Hemanta Mukhopadhyay",    "লেজেন্ডারি"),
        ("শ্রেয়া গুহঠাকুরতা",     "Shreya Guhathakurta",     "সমসাময়িক"),
        ("ইমন চক্রবর্তী",         "Iman Chakraborty",         "সমসাময়িক"),
        ("লোপামুদ্রা মিত্র",       "Lopamudra Mitra",          "সমসাময়িক"),
        ("শ্রাবণী সেন",           "Srabani Sen",              "সমসাময়িক"),
        ("জয়তী চক্রবর্তী",        "Jayati Chakraborty",       "সমসাময়িক"),
        ("রেজওয়ানা চৌধুরী বন্যা", "Rezwana Chowdhury Bonna", "সমসাময়িক"),
        ("লগ্নজিতা ভট্টাচার্য",    "Lagnajita Bhattacharya",  "সমসাময়িক"),
        ("সাহানা বাজপেয়ী",        "Sahana Bajpaie",           "সমসাময়িক"),
        ("শ্রেয়া ঘোষাল",          "Shreya Ghoshal",           "ক্রসওভার"),
    ]

    NAZRUL_SINGERS = [
        ("ফিরোজা বেগম",          "Firoza Begum",             "লেজেন্ডারি"),
        ("আব্বাসউদ্দীন আহমেদ",    "Abbasuddin Ahmed",         "লেজেন্ডারি"),
        ("সোহরাব হোসেন",         "Sohrab Hossain",            "লেজেন্ডারি"),
        ("খালিদ হোসেন",          "Khalid Hossain",            "লেজেন্ডারি"),
        ("ইন্দ্রাণী সেন",         "Indrani Sen",                "সমসাময়িক"),
        ("মঞ্জু দত্ত",            "Manju Dutta",                "সমসাময়িক"),
        ("নাশিদ কামাল",          "Nashid Kamal",               "সমসাময়িক"),
        ("সুজিত মুস্তফা",         "Sujit Mustafa",              "সমসাময়িক"),
    ]

    SINGERS = NAZRUL_SINGERS if is_nazrul else RABINDRA_SINGERS

    lines.append("### 🎵 শিল্পী অনুযায়ী অনুসন্ধান\n")
    lines.append("| শিল্পী | ধরন | YouTube অনুসন্ধান |")
    lines.append("|---|---|---|")
    for bn, en, cat in SINGERS:
        q   = urllib.parse.quote(f"{title} {en} {genre_en}")
        url = f"https://www.youtube.com/results?search_query={q}"
        lines.append(f"| {bn} | {cat} | [🔍 খুঁজুন]({url}) |")

    lines.append("\n_সরাসরি ভিডিও লিংক — নতুন ট্যাবে খোলে।_")
    return "\n".join(lines)


def _looks_like_generic_youtube_request(query: str) -> bool:
    text = (query or "").strip().lower()
    if not text:
        return True
    generic_terms = (
        "youtube", "ইউটিউব", "play", "listen", "শুন", "শোন",
        "গান", "song", "এখান", "একটি", "একটা",
    )
    has_specific_title_hint = any(
        marker in text for marker in ("'", "\"", "‘", "’", "“", "”")
    )
    if has_specific_title_hint:
        return False
    return any(term in text for term in generic_terms) and len(text) <= 80


async def _find_song_for_youtube(query: str, composer: Composer = "rabindra") -> dict | None:
    query = (query or "").strip()
    collection = _collection_for(composer)

    if query:
        if not _looks_like_generic_youtube_request(query):
            exact = await get_documents_by_field(
                collection=collection,
                field="title",
                value=query,
                limit=1,
            )
            if exact:
                return exact[0]

        matches = await vector_search(
            collection=collection,
            query=query,
            top_k=1,
        )
        if matches:
            return matches[0]

    fallback_titles = (
        ("বাগিচায় বুলবুলি তুই", "কারার ঐ লৌহকপাট", "মোরা ঝঞ্জার মতো উদ্দাম")
        if composer == "nazrul"
        else ("আমার সোনার বাংলা", "যদি তোর ডাক শুনে কেউ না আসে", "আনন্দধারা বহিছে ভুবনে")
    )
    for title in fallback_titles:
        exact = await get_documents_by_field(
            collection=collection,
            field="title",
            value=title,
            limit=1,
        )
        if exact:
            return exact[0]

    matches = await vector_search(
        collection=collection,
        query=query or ("জনপ্রিয় নজরুলগীতি" if composer == "nazrul" else "জনপ্রিয় রবীন্দ্রসঙ্গীত"),
        top_k=1,
    )
    return matches[0] if matches else None


async def play_youtube_song(query: str = "", composer: Composer = "rabindra") -> str:
    """Find a requested or representative song (Rabindra Sangeet by default,
    Nazrul Geeti when composer="nazrul") and return YouTube links.

    This hides internal Firestore IDs from the assistant response while still
    allowing a direct play/listen request to resolve a song and produce links.
    """
    doc = await _find_song_for_youtube(query, composer)
    if not doc:
        return "YouTube-এ চালানোর মতো গান খুঁজে পাওয়া যায়নি। অনুগ্রহ করে গানের নামটি বলুন।"

    song_id = doc.get("doc_id") or doc.get("id")
    if not song_id:
        title = doc.get("title", "")
        if title:
            exact = await get_documents_by_field(
                collection=_collection_for(composer),
                field="title",
                value=title,
                limit=1,
            )
            song_id = exact[0].get("doc_id") if exact else None

    if not song_id:
        return "গানটি পাওয়া গেছে, কিন্তু YouTube লিংক তৈরির জন্য দরকারি তথ্য পাওয়া যায়নি।"

    return await get_youtube_url(song_id, composer)


async def get_song_summary(song_id: str, composer: Composer = "rabindra") -> str:
    """Return the full pre-generated summary — context, meaning, emotion, imagery."""
    doc = await _resolve_song_doc(song_id, composer)
    if not doc:
        return "গান পাওয়া যায়নি। অনুগ্রহ করে গানের নাম দিয়ে আবার চেষ্টা করুন।"
    summary = doc.get("summary")
    if not summary:
        return (
            f"'{doc['title']}'-এর জন্য এখনো সারসংক্ষেপ তৈরি হয়নি। "
            f"summarize_aspect tool দিয়ে এখনই তৈরি করতে পারি।"
        )
    return (
        f"### {doc['title']} — সারসংক্ষেপ\n\n"
        f"📜 **প্রেক্ষাপট:**\n{summary.get('context', '')}\n\n"
        f"💡 **অর্থ:**\n{summary.get('meaning', '')}\n\n"
        f"🎭 **আবেগ:**\n{summary.get('emotion', '')}\n\n"
        f"🖼 **চিত্রকল্প:**\n{summary.get('imagery', '')}"
    )


async def summarize_aspect(song_id: str, aspect: str, composer: Composer = "rabindra") -> str:
    """Return or generate one aspect of a song summary.
    song_id can be a Firestore song_id, a [song_id:...] marker, or a song title/query.
    aspect: context | meaning | emotion | imagery | all"""
    doc = await _resolve_song_doc(song_id, composer)
    if not doc:
        return "গান পাওয়া যায়নি। অনুগ্রহ করে গানের নাম দিয়ে আবার চেষ্টা করুন।"

    cached    = doc.get("summary", {})
    label_map = {
        "context": "প্রেক্ষাপট",
        "meaning": "অর্থ",
        "emotion": "আবেগ",
        "imagery": "চিত্রকল্প",
    }

    if aspect == "all":
        if cached:
            return await get_song_summary(song_id, composer)
    elif cached.get(aspect):
        return (
            f"**{doc['title']}** — {label_map.get(aspect, aspect)}:\n\n"
            f"{cached[aspect]}"
        )

    # The doc's own 'source' decides which summarizer prompt applies, so a
    # Nazrul doc gets the Nazrul-scholar prompt even without composer="nazrul".
    if doc.get("source") == "nazrul":
        from domains.geetabitan.ingestion.nazrul_summarizer import generate_and_store_summary
    else:
        from domains.geetabitan.ingestion.geetabitan_summarizer import generate_and_store_summary
    summary = await generate_and_store_summary(doc)

    if aspect == "all":
        return await get_song_summary(song_id, composer)

    return (
        f"**{doc['title']}** — {label_map.get(aspect, aspect)}:\n\n"
        f"{summary.get(aspect, 'পাওয়া যায়নি।')}"
    )


async def get_palta_url(name: str, kind: str = "raag") -> str:
    """Return YouTube search URLs for palta/exercise practice for a raag or taal."""
    import urllib.parse

    def yt(query: str) -> str:
        return f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"

    if kind == "taal":
        rows = [
            f"| পল্টা — থেকা | তাল · Bengali | [▶ শুনুন]({yt(f'{name} taal theka tabla')}) |",
            f"| পল্টা — কায়দা | তাল · Hindi | [▶ শুনুন]({yt(f'{name} taal palta kaida tabla')}) |",
            f"| তাল পরিচয় | বাংলায় | [▶ শুনুন]({yt(f'{name} তাল পল্টা রবীন্দ্রসঙ্গীত')}) |",
            f"| Tabla practice | English | [▶ শুনুন]({yt(f'{name} taal tabla practice lesson')}) |",
        ]
        title = f"{name} তালের পল্টা — YouTube-এ শুনুন"
    else:
        rows = [
            f"| আলাপ ও পল্টা | বাংলায় | [▶ শুনুন]({yt(f'{name} রাগ পল্টা আলাপ রবীন্দ্রসঙ্গীত')}) |",
            f"| Alaap & Palta | Hindi lesson | [▶ শুনুন]({yt(f'{name} raag palta alaap lesson')}) |",
            f"| পল্টা — সরগম | Sargam exercise | [▶ শুনুন]({yt(f'{name} raag sargam palta exercise vocal')}) |",
            f"| Bandish practice | Hindustani | [▶ শুনুন]({yt(f'{name} raag bandish practice hindustani classical')}) |",
        ]
        title = f"{name} রাগের পল্টা — YouTube-এ শুনুন"

    return (
        f"## {title}\n\n"
        f"| ধরন | ভাষা | লিংক |\n"
        f"|---|---|---|\n"
        + "\n".join(rows)
        + "\n\n_লিংকে ক্লিক করলে YouTube-এ সরাসরি খোঁজা হবে।_"
    )
