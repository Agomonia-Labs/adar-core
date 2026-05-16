"""
domains/geetabitan/tools/song_tools.py
Song retrieval and summary tools.
"""

from src.adar.db import direct_query, get_documents_by_field, get_db
from domains.geetabitan.config import FIRESTORE_COLLECTION
from domains.geetabitan.data.raag_metadata import TAAL_DATA


# ── Taal lookup — case-insensitive fallback ───────────────────────────────────

def _taal_meta(taal: str) -> dict:
    """Look up taal metadata, case-insensitive, so 'Dadra' matches 'দাদরা'."""
    return TAAL_DATA.get(taal) or next(
        (v for k, v in TAAL_DATA.items() if k.lower() == taal.lower()), {}
    )


# ── Internal: fetch one doc by its Firestore document ID ─────────────────────

async def _get_doc_by_id(doc_id: str) -> dict | None:
    db  = get_db()
    doc = await db.collection(FIRESTORE_COLLECTION).document(doc_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["doc_id"] = doc.id
    data.pop("embedding", None)
    return data


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
    song_id = doc.get("doc_id", doc.get("id", ""))
    raag    = doc.get("raag", "") or "—"
    taal    = doc.get("taal", "") or "—"
    beats   = tm.get("beats", "")
    beats_str = f" | {beats} মাত্রা" if beats else ""

    lines = [
        f"[song_id:{song_id}]",
        "─────────────────────────────",
        f"🎵 **{doc['title']}**",
        "─────────────────────────────",
        f"পর্যায়: {doc.get('paryay', '—')}  |  রাগ: {raag}  |  তাল: {taal}{beats_str}",
        "",
        _format_lyrics(doc),
    ]
    return "\n".join(lines)


# ── Song retrieval tools ──────────────────────────────────────────────────────

async def get_song_by_title(title: str) -> str:
    """Fetch a Tagore song by its Bengali title (exact match).
    Returns complete song with formatted lyrics."""
    results = await get_documents_by_field(
        collection=FIRESTORE_COLLECTION,
        field="title",
        value=title,
        limit=1,
    )
    if results:
        return _song_card(results[0])
    return (
        f"'{title}' শিরোনামে সরাসরি কোনো গান পাওয়া যায়নি। "
        f"vector_search_songs দিয়ে খোঁজার চেষ্টা করুন।"
    )


async def get_full_song(song_id: str) -> str:
    """Retrieve complete formatted lyrics of a song by its song_id."""
    doc = await _get_doc_by_id(song_id)
    if not doc:
        return "গান পাওয়া যায়নি। song_id টি সঠিক কিনা যাচাই করুন।"
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
        f"[song_id:{r.get('doc_id', r.get('id', ''))}] "
        f"- **{r['title']}** | রাগ: {r.get('raag', '—')} | "
        f"তাল: {r.get('taal', '—')}"
        for r in results[:25]
    ]
    suffix = (
        f"\n\n_(মোট {len(results)}টি গান। নির্দিষ্ট গান দেখতে গানের নাম বলুন।)_"
        if len(results) > 25 else ""
    )
    return f"**{paryay}** পর্যায়ের গানসমূহ:\n" + "\n".join(lines) + suffix


async def get_song_stanza(song_id: str, stanza_number: int) -> str:
    """Get a specific stanza (স্তবক) of a song. stanza_number is 1-based."""
    doc = await _get_doc_by_id(song_id)
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



    """List all raags with arohi, aborohi, vadi, samvadi and mood."""
    from domains.geetabitan.data.raag_metadata import RAAG_DATA, TAAL_DATA
    raags = {k: v for k, v in RAAG_DATA.items() if k not in TAAL_DATA}
    lines = ["## গীতবিতানে প্রচলিত রাগসমূহ\n"]
    for name, meta in raags.items():
        arohi   = meta.get("arohi",   "—")
        aborohi = meta.get("aborohi", "—")
        vadi    = meta.get("vadi",    "—")
        samvadi = meta.get("samvadi", "—")
        komal   = meta.get("komal",   "")
        entry = (
            f"### {name}\n"
            f"**সময়:** {meta.get('time','—')} | **মেজাজ:** {meta.get('mood','—')}\n"
            f"**আরোহী:** {arohi}\n"
            f"**অবরোহী:** {aborohi}\n"
            f"**বাদী:** {vadi} | **সমবাদী:** {samvadi}"
        )
        if komal and komal != "—":
            entry += f" | **কোমল:** {komal}"
        lines.append(entry)
    lines.append(f"\n_মোট {len(raags)}টি রাগ। যেকোনো রাগের গান দেখতে রাগের নাম বলুন।_")
    return "\n\n".join(lines)


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
        bols = meta.get("bols", "—") or "—"
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


async def get_youtube_url(song_id: str) -> str:
    """Search YouTube for actual videos of this song. Returns direct watch links
    when videos are found, plus singer-specific search links as fallback."""
    import urllib.parse
    doc = await _get_doc_by_id(song_id)
    if not doc:
        return "গান পাওয়া যায়নি।"

    first_line = doc.get("first_line", doc.get("title", ""))
    title      = doc.get("title", "")
    display    = first_line or title

    # ── Search YouTube for actual videos ──────────────────────────────────
    results_bn = await _search_youtube(f"{display} রবীন্দ্রসঙ্গীত", max_results=8)
    results_en = await _search_youtube(f"{title} Rabindra Sangeet", max_results=5) if not results_bn else []
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
    SINGERS = [
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

    lines.append("### 🎵 শিল্পী অনুযায়ী অনুসন্ধান\n")
    lines.append("| শিল্পী | ধরন | YouTube অনুসন্ধান |")
    lines.append("|---|---|---|")
    for bn, en, cat in SINGERS:
        q   = urllib.parse.quote(f"{title} {en} Rabindra Sangeet")
        url = f"https://www.youtube.com/results?search_query={q}"
        lines.append(f"| {bn} | {cat} | [🔍 খুঁজুন]({url}) |")

    lines.append("\n_সরাসরি ভিডিও লিংক — নতুন ট্যাবে খোলে।_")
    return "\n".join(lines)


async def get_song_summary(song_id: str) -> str:
    """Return the full pre-generated summary — context, meaning, emotion, imagery."""
    doc = await _get_doc_by_id(song_id)
    if not doc:
        return "গান পাওয়া যায়নি।"
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


async def summarize_aspect(song_id: str, aspect: str) -> str:
    """Return or generate one aspect of a song summary.
    aspect: context | meaning | emotion | imagery | all"""
    doc = await _get_doc_by_id(song_id)
    if not doc:
        return "গান পাওয়া যায়নি।"

    cached    = doc.get("summary", {})
    label_map = {
        "context": "প্রেক্ষাপট",
        "meaning": "অর্থ",
        "emotion": "আবেগ",
        "imagery": "চিত্রকল্প",
    }

    if aspect == "all":
        if cached:
            return await get_song_summary(song_id)
    elif cached.get(aspect):
        return (
            f"**{doc['title']}** — {label_map.get(aspect, aspect)}:\n\n"
            f"{cached[aspect]}"
        )

    from domains.geetabitan.ingestion.geetabitan_summarizer import generate_and_store_summary
    summary = await generate_and_store_summary(doc)

    if aspect == "all":
        return await get_song_summary(song_id)

    return (
        f"**{doc['title']}** — {label_map.get(aspect, aspect)}:\n\n"
        f"{summary.get(aspect, 'পাওয়া যায়নি।')}"
    )