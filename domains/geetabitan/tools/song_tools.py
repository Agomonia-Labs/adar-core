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
    """Get a specific stanza (স্তবক). stanza_number is 1-based."""
    doc = await _get_doc_by_id(song_id)
    if not doc:
        return "গান পাওয়া যায়নি।"
    stanzas = doc.get("stanzas", [])
    total   = len(stanzas)
    if not stanzas:
        return "এই গানের স্তবক আলাদাভাবে সংরক্ষিত নেই। get_full_song ব্যবহার করুন।"
    if stanza_number < 1 or stanza_number > total:
        return f"এই গানে মোট {total}টি স্তবক আছে। ১ থেকে {total}-এর মধ্যে সংখ্যা দিন।"
    return (
        f"**{doc['title']}** — {stanza_number}নং স্তবক (মোট {total}টি):\n\n"
        f"{stanzas[stanza_number - 1]}"
    )


# ── Summary tools ─────────────────────────────────────────────────────────────

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