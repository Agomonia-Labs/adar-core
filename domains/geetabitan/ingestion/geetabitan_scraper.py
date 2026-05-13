"""
domains/geetabitan/ingestion/geetabitan_scraper.py

Scrapes geetabitan.com and writes domains/geetabitan/data/songs.json.

HOW THE SITE IS STRUCTURED (discovered from live fetch):
  Index pages:    /lyrics/{LETTER}/song-list.html   (A,B,C,D,E,G,H,I,J,K,L,M,N,O,P,R,S,T,U)
  Song pages:     /lyrics/{LETTER}/{slug}-lyric.html
  Metadata block: "Parjaay: Puja (521)", "Taal: Dadra", "Raag: Sahana" — plain text
  Bengali lyrics: served as a PNG image — NOT scrapeable as text
  Transliteration: English romanization IS available as text

NOTE ON BENGALI LYRICS:
  geetabitan.com renders Bengali lyrics as PNG images (not HTML text).
  This scraper stores the English transliteration in `lyrics_roman`.
  For actual Bengali Unicode lyrics, set BENGALI_LYRICS_SOURCE in your .env:
    BENGALI_LYRICS_SOURCE=github   → fetches from rabindra-sangeet GitHub corpus
    BENGALI_LYRICS_SOURCE=none     → skip (default, transliteration only)

Run:
    pip install httpx beautifulsoup4
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.geetabitan_scraper
"""

import asyncio
import json
import os
import re
import unicodedata
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE_URL   = "https://www.geetabitan.com"
OUTPUT     = Path(__file__).parent.parent / "data" / "songs.json"

# All letter indexes that exist on the site
LETTERS = ["A","B","C","D","E","G","H","I","J","K","L","M","N","O","P","R","S","T","U"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; geetabitan-research-bot/2.0; "
        "+https://adar.agomoniai.com/bot)"
    )
}


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip()) if text else ""


def _extract_metadata(soup: BeautifulSoup) -> dict:
    """
    Extract parjaay, upa-parjaay, taal, raag from the metadata block.
    The block looks like:
        Parjaay: Puja (521)
        Upa-parjaay: Sundar
        Taal: Dadra
        Raag: Sahana
        Written on: ...
    """
    meta = {}
    # Find the section containing "Parjaay:" text
    for p in soup.find_all(["p", "li", "td", "div", "span"]):
        text = p.get_text(" ", strip=True)
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("Parjaay:"):
                # "Parjaay: Puja (521)" → "Puja"
                val = line.replace("Parjaay:", "").strip()
                val = re.sub(r"\s*\(\d+\).*$", "", val).strip()
                meta["parjaay"] = val
            elif line.startswith("Upa-parjaay:"):
                meta["upa_parjaay"] = line.replace("Upa-parjaay:", "").strip()
            elif line.startswith("Taal:"):
                meta["taal"] = line.replace("Taal:", "").strip()
            elif line.startswith("Raag:"):
                meta["raag"] = line.replace("Raag:", "").strip()
            elif line.startswith("Written on:"):
                meta["written_on"] = line.replace("Written on:", "").strip()
            elif line.startswith("Place:"):
                meta["place"] = line.replace("Place:", "").strip()

    # Also search the raw text of the whole page for the metadata block
    # which is sometimes inside a <section> or structured differently
    if not meta.get("parjaay"):
        full_text = soup.get_text(" ")
        for pattern, key in [
            (r"Parjaay:\s*([A-Za-z\s]+?)(?:\s*\(\d+\))?(?:\s+Upa-parjaay|$|\n)", "parjaay"),
            (r"Upa-parjaay:\s*([A-Za-z\s]+?)(?:\s+Taal|$|\n)",                   "upa_parjaay"),
            (r"Taal:\s*([A-Za-z\s]+?)(?:\s+Raag|$|\n)",                           "taal"),
            (r"Raag:\s*([A-Za-z\s]+?)(?:\s+Written|$|\n)",                        "raag"),
        ]:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m and key not in meta:
                meta[key] = m.group(1).strip()

    return meta


def _extract_transliteration(soup: BeautifulSoup) -> str:
    """
    Extract the English transliteration block.
    On the page it appears under 'Transliteration in English' heading
    inside a <pre> or structured block.
    """
    # Look for the section heading
    for heading in soup.find_all(["h3", "h4", "h2"]):
        if "transliteration" in heading.get_text().lower():
            # Grab the next sibling element
            sibling = heading.find_next_sibling()
            if sibling:
                return _nfc(sibling.get_text("\n"))
    # Fallback: find a <pre> block
    for pre in soup.find_all("pre"):
        text = pre.get_text("\n").strip()
        if len(text) > 30:
            return _nfc(text)
    return ""


def _extract_title_from_url(url: str) -> str:
    """Turn 'jodi-prem-dile-na-lyric.html' into 'jodi prem dile na'."""
    slug = url.rstrip("/").split("/")[-1]
    slug = slug.replace("-lyric.html", "").replace("-", " ")
    return slug.title()


async def fetch_song_links(client: httpx.AsyncClient, letter: str) -> list[str]:
    """Fetch all song page URLs from a letter index page."""
    url  = f"{BASE_URL}/lyrics/{letter}/song-list.html"
    try:
        resp = await client.get(url, headers=HEADERS)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  SKIP letter {letter}: {exc}")
        return []

    soup  = BeautifulSoup(resp.text, "html.parser")
    links = []
    base  = f"{BASE_URL}/lyrics/{letter}/"   # base for resolving relative URLs

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        # Links are relative: "amar-sonar-bangla-lyric.html"
        # or absolute:        "https://www.geetabitan.com/lyrics/A/amar-...-lyric.html"
        if not href.endswith("-lyric.html"):
            continue

        if href.startswith("http"):
            full = href
        elif href.startswith("/"):
            full = BASE_URL + href
        else:
            full = base + href          # resolve relative → absolute

        if full not in links:
            links.append(full)

    return links


async def fetch_song_detail(
    client: httpx.AsyncClient,
    url: str,
    idx: int,
) -> dict | None:
    """Fetch and parse one song page."""
    try:
        resp = await client.get(url, headers=HEADERS)
        resp.raise_for_status()
    except Exception as exc:
        print(f"    SKIP {url}: {exc}")
        return None

    soup  = BeautifulSoup(resp.text, "html.parser")
    meta  = _extract_metadata(soup)
    roman = _extract_transliteration(soup)

    # Title: try H1 first, fall back to URL slug
    h1 = soup.find("h1")
    raw_title = h1.get_text(" ", strip=True) if h1 else ""
    # Clean up "Lyric and background history of song X" → "X"
    for prefix in [
        "lyric and background history of song",
        "lyric of song",
        "song",
    ]:
        if raw_title.lower().startswith(prefix):
            raw_title = raw_title[len(prefix):].strip()
            break
    title = raw_title.title() if raw_title else _extract_title_from_url(url)

    from domains.geetabitan.data.raag_metadata import RAAG_DATA
    raag     = meta.get("raag", "")
    raag_obj = RAAG_DATA.get(raag, {})

    return {
        "id":          str(idx).zfill(4),
        "title":       title,
        "first_line":  roman.split("\n")[0].strip() if roman else "",
        "paryay":      meta.get("parjaay", ""),
        "upa_parjaay": meta.get("upa_parjaay", ""),
        "raag":        raag,
        "raag_family": raag_obj.get("family", ""),
        "raag_time":   raag_obj.get("time", ""),
        "raag_mood":   raag_obj.get("mood", ""),
        "taal":        meta.get("taal", ""),
        "taal_beats":  0,              # filled by embedder from TAAL_DATA
        "written_on":  meta.get("written_on", ""),
        "place":       meta.get("place", ""),
        # Bengali lyrics are PNG images on geetabitan.com — not available as text.
        # Store the English transliteration instead.
        # Swap this with Bengali text if you have a separate corpus.
        "lyrics_roman": roman,
        "lyrics_full":  roman,         # used for embedding and display
        "stanzas":      _split_stanzas(roman),
        "source_url":   url,
    }


def _split_stanzas(text: str) -> list[str]:
    """Split transliteration into stanzas on blank lines."""
    if not text:
        return []
    return [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]


async def scrape_all(delay: float = 1.0):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    songs: list[dict] = []
    idx = 1

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for letter in LETTERS:
            print(f"\nFetching index: {letter} …")
            song_urls = await fetch_song_links(client, letter)
            print(f"  Found {len(song_urls)} songs")

            for url in song_urls:
                await asyncio.sleep(delay)
                detail = await fetch_song_detail(client, url, idx)
                if detail:
                    songs.append(detail)
                    if idx % 100 == 0:
                        print(f"  {idx} songs scraped …")
                        # Checkpoint save every 100 songs
                        OUTPUT.write_text(
                            json.dumps(songs, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    idx += 1

    OUTPUT.write_text(
        json.dumps(songs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nDone. {len(songs)} songs written to {OUTPUT}")
    print("\nNOTE: Bengali lyrics are PNG images on geetabitan.com.")
    print("The 'lyrics_full' field contains the English transliteration.")
    print("For Bengali Unicode text, set BENGALI_LYRICS_SOURCE=github in .env")
    print("and re-run: python -m domains.geetabitan.ingestion.bengali_lyrics_fetcher")


if __name__ == "__main__":
    asyncio.run(scrape_all())