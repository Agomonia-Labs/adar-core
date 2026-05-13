"""
domains/geetabitan/tools/search_tools.py
Vector search, raag/taal filtering, and musical metadata tools.
"""

import unicodedata

from src.adar.db import vector_search, direct_query
from domains.geetabitan.config import FIRESTORE_COLLECTION
from domains.geetabitan.data.raag_metadata import RAAG_DATA, TAAL_DATA
from domains.geetabitan.tools.song_tools import _song_card, _taal_meta


def _normalize_bengali(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return text.replace("\u200c", "").replace("\u200d", "").strip()


async def vector_search_songs(query: str) -> str:
    """Search Geetabitan for Tagore songs matching a Bengali query.
    Returns top 3 matching songs with full formatted lyrics."""
    query   = _normalize_bengali(query)
    results = await vector_search(
        collection=FIRESTORE_COLLECTION,
        query=query,
        top_k=3,
    )
    if not results:
        return "দুঃখিত, এই প্রশ্নের সাথে মেলে এমন কোনো গান গীতবিতানে পাওয়া যায়নি।"

    parts = [_song_card(r) for r in results]
    return "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n".join(parts)


async def get_songs_by_raag(raag: str, paryay: str = None) -> str:
    """List all Tagore songs in a given raag (রাগ).
    Optionally filter by paryay. Shows song title and taal for each result."""
    filters: dict = {"raag": raag}
    if paryay:
        filters["paryay"] = paryay

    results = await direct_query(
        collection=FIRESTORE_COLLECTION,
        filters=filters,
        limit=30,
    )
    if not results:
        return f"'{raag}' রাগে কোনো গান পাওয়া যায়নি।"

    meta   = RAAG_DATA.get(raag, {})
    header = (
        f"**{raag}** রাগ — {meta.get('mood', '')}\n"
        f"সময়: {meta.get('time', '—')} | পরিবার: {meta.get('family', '—')}\n\n"
        f"এই রাগে **{len(results)}টি** গান:\n"
    )
    lines = [
        f"- **{r['title']}** ({r.get('paryay', '')}) | "
        f"তাল: {r.get('taal', '—')} — song_id: `{r.get('doc_id', r.get('id', ''))}`"
        for r in results
    ]
    return header + "\n".join(lines)


async def get_songs_by_taal(taal: str, paryay: str = None) -> str:
    """List all Tagore songs in a given taal (তাল).
    Optionally filter by paryay. Shows song title and raag for each result."""
    filters: dict = {"taal": taal}
    if paryay:
        filters["paryay"] = paryay

    results = await direct_query(
        collection=FIRESTORE_COLLECTION,
        filters=filters,
        limit=30,
    )
    if not results:
        return f"'{taal}' তালে কোনো গান পাওয়া যায়নি।"

    meta   = TAAL_DATA.get(taal, {})
    header = (
        f"**{taal}** তাল — {meta.get('beats', '?')} মাত্রা "
        f"({meta.get('vibhag', '')}) | {meta.get('feel', '')}\n\n"
        f"এই তালে **{len(results)}টি** গান:\n"
    )
    lines = [
        f"- **{r['title']}** ({r.get('paryay', '')}) | "
        f"রাগ: {r.get('raag', '—')} — song_id: `{r.get('doc_id', r.get('id', ''))}`"
        for r in results
    ]
    return header + "\n".join(lines)


async def describe_raag(raag: str) -> str:
    """Return musical description of a raag — family, time of day, mood,
    common taals, and count of Tagore songs that use it."""
    meta = RAAG_DATA.get(raag)
    if not meta:
        return (
            f"'{raag}' রাগের তথ্য পাওয়া যায়নি। "
            f"সঠিক বানান নিশ্চিত করুন বা অন্য রাগের নাম দিন।"
        )
    all_results = await direct_query(
        collection=FIRESTORE_COLLECTION,
        filters={"raag": raag},
        limit=500,
    )
    count = len(all_results)
    return (
        f"## {raag}\n\n"
        f"**পরিবার:** {meta['family']}\n"
        f"**পরিবেশনের সময়:** {meta['time']}\n"
        f"**মেজাজ:** {meta['mood']}\n"
        f"**প্রচলিত তাল:** {', '.join(meta.get('beats_common', []))}\n"
        f"**গীতবিতানে গান:** {count}টি\n\n"
        f"{meta.get('description', '')}\n\n"
        f"এই রাগের গান দেখতে চাইলে বলুন।"
    )


async def describe_taal(taal: str) -> str:
    """Return musical description of a taal — beat count, vibhag, tempo,
    feel, and count of Tagore songs that use it."""
    meta = _taal_meta(taal)
    if not meta:
        return (
            f"'{taal}' তালের তথ্য পাওয়া যায়নি। "
            f"সঠিক বানান নিশ্চিত করুন বা অন্য তালের নাম দিন।"
        )
    all_results = await direct_query(
        collection=FIRESTORE_COLLECTION,
        filters={"taal": taal},
        limit=500,
    )
    count = len(all_results)
    return (
        f"## {taal}\n\n"
        f"**মাত্রা:** {meta.get('beats', '?')}\n"
        f"**বিভাগ:** {meta.get('vibhag', '—')}\n"
        f"**গতি:** {meta.get('tempo', '—')}\n"
        f"**অনুভূতি:** {meta.get('feel', '—')}\n"
        f"**গীতবিতানে গান:** {count}টি\n\n"
        f"{meta.get('description', '')}\n\n"
        f"এই তালের গান দেখতে চাইলে বলুন।"
    )