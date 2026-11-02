"""
domains/geetabitan/ingestion/nazrul_raag_taal_match_candidates.py

STEP 2 of 3 in the raag/taal backfill pipeline (fetch -> match -> ingest).

Pure local computation — no network, no Firestore, no Gemini. Loads your
local song catalog (domains/geetabitan/data/nazrul_songs.json, 618 songs —
the same source nazrul_embedder.py loaded into Firestore) and the raw
scraped data from step 1 (nazrulgeeti_org_raw.json), fuzzy-matches each
local song's title/first_line against every scraped song's title (bigram
pre-filter + difflib ratio, trying hyphen/punctuation-normalized variants of
both sides), and writes a CSV of candidate matches for human review.

Nothing is written to Firestore by this script. You (or whoever reviews)
edit the output CSV directly: fix a wrong candidate_1_title by pasting in
one of the alt columns (or anything else you find on nazrulgeeti.org
yourself), and put "y" in the `status` column for every row you approve.
Rows you leave blank or mark "n" are skipped by step 3.

The Firestore document ID for each local song is computed here the exact
same way nazrul_embedder.py computed it when it originally wrote the doc
(md5 of "nazrul_song_{id}_{title}") — so step 3 can update the right doc
directly by ID, with no fuzzy Firestore query needed at all.

USAGE:
  python -m domains.geetabitan.ingestion.nazrul_raag_taal_match_candidates

Output: domains/geetabitan/data/nazrul_raag_taal_review.csv
"""

import csv
import hashlib
import json
import logging
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOCAL_SONGS_PATH = DATA_DIR / "nazrul_songs.json"
SCRAPED_PATH = DATA_DIR / "nazrulgeeti_org_raw.json"
OUT_CSV = DATA_DIR / "nazrul_raag_taal_review.csv"

SCORE_THRESHOLD = 0.45  # below this, don't bother suggesting a candidate at all


def firestore_doc_id(song_id: str, title: str) -> str:
    """Exactly matches nazrul_embedder.py's embed_and_store() doc_id formula."""
    return hashlib.md5(f"nazrul_song_{song_id}_{title}".encode("utf-8")).hexdigest()


def normalize(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[-–—]+", " ", s)
    s = re.sub(r"[।,.!?॥'\"‘’“”()\[\]]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def bigrams(s: str) -> set:
    s = s.replace(" ", "")
    return {s[i:i+2] for i in range(len(s) - 1)} or {s}


def ratio(a: str, b: str) -> float:
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def best_candidates(query: str, scraped: list[dict], scraped_bigrams: list[set], top_n: int = 3) -> list[tuple[float, dict]]:
    qn = normalize(query)
    qb = bigrams(qn)
    # Phase 1: cheap Jaccard pre-filter to shortlist ~30 candidates
    jaccard_scores = []
    for i, sb in enumerate(scraped_bigrams):
        inter = len(qb & sb)
        if inter == 0:
            continue
        union = len(qb | sb)
        jaccard_scores.append((inter / union, i))
    jaccard_scores.sort(reverse=True)
    shortlist = jaccard_scores[:40]

    # Phase 2: precise ratio on the shortlist
    scored = []
    for _, i in shortlist:
        cand = scraped[i]
        r = ratio(qn, normalize(cand["title"]))
        scored.append((r, cand))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_n]


def main():
    local_songs = json.loads(LOCAL_SONGS_PATH.read_text(encoding="utf-8"))
    scraped = json.loads(SCRAPED_PATH.read_text(encoding="utf-8"))
    logger.info(f"Local catalog: {len(local_songs)} songs. Scraped: {len(scraped)} songs.")

    scraped_bigrams = [bigrams(normalize(s["title"])) for s in scraped]

    rows = []
    no_candidate_count = 0
    for i, song in enumerate(local_songs):
        if (i + 1) % 100 == 0:
            logger.info(f"  matched {i+1}/{len(local_songs)}")

        cands = best_candidates(song["title"], scraped, scraped_bigrams, top_n=3)
        # Also try matching on first_line in case it scores better than title
        if song.get("first_line"):
            cands_fl = best_candidates(song["first_line"], scraped, scraped_bigrams, top_n=3)
            combined = {id(c): (sc, c) for sc, c in cands}
            for sc, c in cands_fl:
                key = id(c)
                if key not in combined or sc > combined[key][0]:
                    combined[key] = (sc, c)
            cands = sorted(combined.values(), key=lambda x: x[0], reverse=True)[:3]

        while len(cands) < 3:
            cands.append((0.0, {"title": "", "raag": "", "taal": "", "swaralipi_image_url": "", "href": ""}))

        top_score, top = cands[0]
        if top_score < SCORE_THRESHOLD:
            no_candidate_count += 1

        fid = firestore_doc_id(song["id"], song["title"])
        rows.append({
            "status": "",
            "suggested": "y" if top_score >= 0.85 else "",
            "best_score": f"{top_score:.2f}",
            "song_id": song["id"],
            "firestore_id": fid,
            "our_title": song["title"],
            "our_first_line": (song.get("first_line") or "")[:60],
            "candidate_1_title": top["title"],
            "raag": top.get("raag", ""),
            "taal": top.get("taal", ""),
            "swaralipi_image_url": top.get("swaralipi_image_url", ""),
            "source_href": top.get("href", ""),
            "alt2_title": cands[1][1]["title"],
            "alt2_score": f"{cands[1][0]:.2f}",
            "alt2_raag": cands[1][1].get("raag", ""),
            "alt2_taal": cands[1][1].get("taal", ""),
            "alt3_title": cands[2][1]["title"],
            "alt3_score": f"{cands[2][0]:.2f}",
            "alt3_raag": cands[2][1].get("raag", ""),
            "alt3_taal": cands[2][1].get("taal", ""),
        })

    # Sort so the easiest-to-approve (high-confidence) rows come first,
    # and the genuinely-uncertain ones are grouped at the end for closer review.
    rows.sort(key=lambda r: float(r["best_score"]), reverse=True)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"\nWrote {len(rows)} rows to {OUT_CSV}")
    logger.info(f"  high-confidence (score>=0.85, pre-marked 'suggested'): {sum(1 for r in rows if r['suggested'])}")
    logger.info(f"  below threshold ({SCORE_THRESHOLD}, likely no real match): {no_candidate_count}")


if __name__ == "__main__":
    main()
