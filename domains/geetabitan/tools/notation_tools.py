"""
domains/geetabitan/tools/notation_tools.py

Two notation tools:
1. get_notation_link  — returns geetabitan.com PDF/image link for a song
2. get_notation_text  — returns OCR'd swaralipi text if ingested from books
"""

import re
from src.adar.db import get_db, direct_query
from domains.geetabitan.config import FIRESTORE_COLLECTION


# ── Slug helpers ──────────────────────────────────────────────────────────────

def _title_to_slug(title: str) -> str:
    """
    Convert a Bengali or romanized title to geetabitan.com slug.
    e.g. "Amar Sonar Bangla" → "amar-sonar-bangla"
    """
    import unicodedata
    # Normalize unicode
    title = unicodedata.normalize("NFC", title.lower().strip())
    # Replace spaces and underscores with hyphens
    title = re.sub(r"[\s_]+", "-", title)
    # Remove characters that aren't alphanumeric, hyphen, or Bengali
    title = re.sub(r"[^\w\-\u0980-\u09FF]", "", title)
    # Collapse multiple hyphens
    title = re.sub(r"-+", "-", title).strip("-")
    return title


def _source_url_to_slug(source_url: str) -> str:
    """Extract slug from stored source_url."""
    if not source_url:
        return ""
    name = source_url.rstrip("/").split("/")[-1]
    return name.replace("-lyric.html", "")


def _first_letter(slug: str) -> str:
    """Get the uppercase first letter for the URL path."""
    if not slug:
        return "A"
    return slug[0].upper()


# ── Tool 1: notation link ─────────────────────────────────────────────────────

async def get_notation_link(song_id: str) -> str:
    """
    Return swaralipi links for a song.
    Checks for NLTR-scraped notation first, then falls back to geetabitan.com links.
    """
    db  = get_db()
    doc = await db.collection(FIRESTORE_COLLECTION).document(song_id).get()
    if not doc.exists:
        return "গান পাওয়া যায়নি। song_id টি সঠিক কিনা যাচাই করুন।"

    data  = doc.to_dict()
    title = data.get("title", "")

    result = [f"## {title} — স্বরলিপি", ""]

    # If OCR'd or scraped notation text exists — show it first
    local = data.get("notation_text", "")
    if local:
        src  = data.get("notation_source", "")
        page = data.get("notation_page", "")
        result += [
            f"### স্বরলিপি ({src})" + (f" · পৃষ্ঠা {page}" if page else ""),
            "",
            local,
            "",
            "---",
        ]

    # NLTR link if available
    nltr_url = data.get("nltr_url", "")
    if nltr_url:
        result += [
            "### রবীন্দ্র রচনাবলী (NLTR) থেকে:",
            f"🔗 {nltr_url}",
            "",
        ]

    # geetabitan.com fallback links
    source_url = data.get("source_url", "")
    slug = _source_url_to_slug(source_url) or _title_to_slug(title)
    if slug:
        letter = _first_letter(slug)
        notation_page = (
            f"https://www.geetabitan.com/lyrics/rs-{letter.lower()}/"
            f"{slug}-notation-download.html"
        )
        notation_png = (
            f"https://www.geetabitan.com/lyrics/baani-pdf-{letter.lower()}/"
            f"{slug}.png"
        )
        result += [
            "### গীতবিতান.কম থেকে:",
            f"📄 **নোটেশন পেজ:** {notation_page}",
            f"🖼 **স্বরলিপি ছবি:** {notation_png}",
        ]

    if len(result) <= 2:
        result.append("এই গানের স্বরলিপি এখনো সংগ্রহ করা হয়নি।")

    return "\n".join(result)


# ── Tool 2: OCR notation text ─────────────────────────────────────────────────

async def get_notation_text(song_id: str) -> str:
    """
    Return OCR'd swaralipi text for a song if available from ingested books.
    Returns a message prompting to ingest if not yet available.
    """
    db  = get_db()
    doc = await db.collection(FIRESTORE_COLLECTION).document(song_id).get()
    if not doc.exists:
        return "গান পাওয়া যায়নি।"

    data    = doc.to_dict()
    title   = data.get("title", "")
    notation = data.get("notation_text", "")

    if not notation:
        return (
            f"'{title}' গানের স্বরলিপি এখনো সংগ্রহ করা হয়নি। "
            f"স্বরলিপি বই থেকে OCR করা হলে এখানে দেখা যাবে।\n\n"
            f"এখন গীতবিতান.কম থেকে লিংক পেতে বলুন: "
            f"get_notation_link দিয়ে খুঁজুন।"
        )

    source = data.get("notation_source", "স্বরলিপি বই")
    page   = data.get("notation_page", "")
    page_str = f" · পৃষ্ঠা {page}" if page else ""

    return (
        f"## {title} — স্বরলিপি\n"
        f"_{source}{page_str}_\n\n"
        f"{notation}"
    )