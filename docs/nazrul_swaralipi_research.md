# Nazrul Geeti Swaralipi (স্বরলিপি) — Nazrul Institute Research Findings

**Date:** 2026-11-01
**Scope:** Research only — no Firestore writes, no changes to the Rabindra
Sangeet collection/pipeline, no ingestion code written yet. This documents
what is and isn't available from the Nazrul Institute (government cultural
institute, `nazrulinstitute.gov.bd`) for sourcing স্বরলিপি (musical notation)
for the Nazrul Geeti songs already ingested into ADAR Sursangam, and
recommends a concrete next step.

## TL;DR

The Nazrul Institute has published an official swaralipi (notation) series
analogous to Rabindra Sangeet's ~65-volume *Swarabitan*, spanning **at least
59 numbered volumes** plus several specialized sub-series. Of all of that,
**only 3 volumes (34, 35, 36) are freely digitized and web-accessible** as
PDFs on the Institute's public e-library. The rest exist only as physical
books sold through the Institute's own sales counter — there is no API or
bulk digital access to them from this source. The 3 available volumes are
confirmed genuine, authoritative notation (not just lyrics) and are directly
downloadable, no login required. Recommended next step: build a Gemini
Vision OCR ingestion pipeline for these 3 volumes now (mirroring the
existing Rabindra Sangeet `nltr_swaralipi_scraper.py` pattern), accept
partial coverage as the practical ceiling for now, and treat the remaining
~56 volumes as a separate, later sourcing problem (physical purchase/scan,
or other archives — not yet researched).

## 1. How the catalog was enumerated

The Institute's e-library listing (`/pages/elibraries?page=N&page_size=M`)
is server-rendered with **no stable sort order** — the same entries reappear
under different serial numbers across different page requests, which makes
naive sequential pagination unreliable for a full catalog pull. Requesting
a single page with `page_size` larger than the true total (e.g.
`page_size=1300` against a true total of 1231) returns the complete,
deduplicated dataset deterministically in one call. That method confirmed:

- **1231 unique e-library entries** (by href/ID), **1203 unique titles**
  (26 titles appear 2-3 times under different IDs/editions).
- The overwhelming majority of these are individual **song lyric pages**
  (each with an embedded lyrics PDF) — not notation.
- Exactly **3 of the 1231 entries** are different in kind: full published
  **swaralipi notation books**.

## 2. The 3 digitized swaralipi volumes

| Volume | E-library page | PDF (public, no auth) |
|---|---|---|
| ৩৪তম খণ্ড (34th) | `/pages/elibraries/নজরুল-সংগীত-স্বরলিপি-৩৪তম-খণ্ড-c9ec28-695b96f8a31054345f104954` | `https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/n/axvjbnqprylg/b/V2Ministry/o/office-nazrulinstitute/2024/12/<vol34>.pdf` (resolve from the e-library page) |
| ৩৫তম খণ্ড (35th) | `/pages/elibraries/নজরুল-সংগীত-স্বরলিপি-৩৫তম-খণ্ড-a24b59-695b96f3a31054345f104950` | same host/bucket pattern |
| ৩৬তম খণ্ড (36th) | `/pages/elibraries/নজরুল-সংগীত-স্বরলিপি-৩৬তম-খণ্ড-cf5c6b-695b96fba31054345f104957` | `https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/n/axvjbnqprylg/b/V2Ministry/o/office-nazrulinstitute/2024/12/4550e16d16564d95b4a1d2c75802a65a.pdf` (99 pages, visually confirmed) |

Visual inspection of Volume 36's PDF confirmed it is genuine, authoritative
notation, not lyrics with layout artifacts:
- A foreword explicitly citing Rabindra Sangeet's *Swarabitan* as the
  notation-methodology precedent ("আকারমাত্রিক স্বরলিপি অনুসরণ পদ্ধতি" —
  akar-matrik notation system).
- Several pages of notation-convention rules.
- Genuine sargam/swara notation lines per song (e.g.
  `পা - - - - -মপা - - গা -মা -ধপা...`) with record-label/artist/raga/taal
  metadata attached to each song.

All three PDFs are hosted on a **public** Oracle Cloud object-storage
bucket (`V2Ministry`, host `objectstorage.ap-dcc-gazipur-1.oraclecloud15.com`)
— no `nazrulinstitute.gov.bd` login needed to fetch them.

## 3. True scope of the official series (why coverage is partial)

The Institute's own "প্রকাশনা তালিকা ২০২৫" (Publication List 2025) PDF catalog
(`https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/n/axvjbnqprylg/b/V2Ministry/o/office-nazrulinstitute/2024/12/4bc6530763974e4aafcef08107cc6c7a.pdf`)
lists the full "নজরুল-সঙ্গীত স্বরলিপিকার" series as spanning **at least 59
numbered volumes**, comparable in scale to Rabindra Sangeet's Swarabitan,
plus specialized sub-series:
- অর্বাচীন নজরুল সঙ্গীত স্বরলিপি (compiled by Asit Roy)
- ছোটদের নজরুল সঙ্গীত স্বরলিপি (children's volumes, 3 parts)
- নজরুল-স্বরলিপি (compiled by Kazi Nazrul Islam himself)
- বেলুকা and নবরাগ (compiled by Jagat Ghatak)

All of these are sold as physical books (৳৬০–৩০০ each) through the
Institute's "প্রকাশনা বিক্রয় কেন্দ্র" (Publication Sales Center). **Only the
3 volumes above are freely digitized** — the other ~56+ volumes and all the
sub-series are physical-purchase-only and not scrapable from this source.

## 4. Technical constraints discovered

- Neither this cloud workspace's shell nor a shell on the user's own
  computer can reach `nazrulinstitute.gov.bd` or the Oracle object-storage
  host directly (both egress proxies return 403). All data retrieval from
  this site has to go through an in-page browser fetch (same-origin,
  already-loaded page) — there is no way to `curl`/`wget` these PDFs
  directly from either sandbox.
- Chrome's built-in PDF viewer exposes no text layer, so any extraction
  pipeline for these PDFs needs image/OCR-based processing — consistent
  with the existing Rabindra Sangeet notation pipeline, which already uses
  Gemini Vision OCR rather than text extraction.

## 5. Recommended next step

Build `domains/geetabitan/ingestion/nazrul_swaralipi_scraper.py`, mirroring
the existing `nltr_swaralipi_scraper.py` pattern:
1. Fetch the 3 volume PDFs (via the browser pane, since that's the only
   path with egress to this host) and save them locally.
2. OCR each page with Gemini Vision (`google.genai`), extracting per-song
   notation blocks.
3. Match extracted songs by title/first-line against the existing
   `nazrulgeeti_songs` Firestore collection.
4. Store results **additively** — new fields only (e.g. `notation_text`,
   `notation_source`) — never touching existing Rabindra Sangeet data or
   fields, consistent with the project's standing constraint.
5. Accept that this covers only a fraction of the full catalog; log
   unmatched/uncovered songs so coverage gaps are visible rather than
   silently assumed complete.

**Open question for later (not blocking):** how to extend coverage beyond
these 3 volumes — physically purchasing and scanning the remaining ~56
volumes, or checking other archives (e.g. Bangla Academy) for digitized
copies. Not yet researched; flagged here rather than acted on.

## 6. Update — ingestion script built, PDFs acquired, blocked on network egress

Since the sections above were written:

- The 3 volume PDFs were downloaded (via the Claude Browser pane — the only
  path with egress to the Oracle object-storage host) and saved locally at
  `domains/geetabitan/data/nazrul_swaralipi_pdfs/nazrul_swaralipi_vol{34,35,36}.pdf`
  (5.6 MB, 6.6 MB, 5.2 MB — 102, 100, 99 pages respectively).
- `domains/geetabitan/ingestion/nazrul_swaralipi_scraper.py` was written and
  compiles cleanly: it renders each page with PyMuPDF (confirmed — these
  PDFs have no text layer, scan images only), OCRs it with Gemini Vision to
  extract the song title (when a page starts a new song) and notation text,
  groups multi-page songs, matches titles against `nazrulgeeti_songs` by
  prefix query (Gemini-disambiguated on multiple matches), and saves
  additively (`notation_text`, `notation_source`, `notation_volume`,
  `notation_pdf_url`, `notation_pdf_pages`) — never touching existing fields
  or the Rabindra Sangeet collection.
- **Blocked on execution**: both the cloud sandbox and the local Mac sandbox
  that this session can run commands in have their outbound network
  restricted to an allowlist that does not include
  `generativelanguage.googleapis.com` (Gemini API) or `firestore.googleapis.com`
  — both return `403` at the egress proxy. This is an account/org-level
  "Capabilities" setting (Settings → Capabilities on claude.ai), not
  something fixable from within the session.

**To actually run the ingestion**, one of:
1. Add `generativelanguage.googleapis.com` and `firestore.googleapis.com` to
   the allowed domains under Settings → Capabilities, then re-run this
   script from this session.
2. Run it from a normal terminal with GCP access (the same `.env.geetabitan`
   config this project's other ingestion scripts already use):
   ```
   DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \
   python -m domains.geetabitan.ingestion.nazrul_swaralipi_scraper --volume all --resume
   ```
   Test first with `--volume 36 --limit 10 --dry-run`.

## 7. Raag/taal backfill — switched to a human-review pipeline

Most of the 618 songs in `nazrulgeeti_songs` are missing `raag`/`taal`
entirely (confirmed: 0/618 had either field set). **nazrulgeeti.org**
("the world's largest Nazrulgeeti portal") publishes raag, taal, and often
a swaralipi image for its ~2,138-song catalog — see the per-song HTML
structure notes below — but automatic title matching against our 618-song
catalog has real limits (differing hyphenation, word order, OCR-style
noise), so rather than auto-writing matched guesses, the pipeline now
produces a reviewable file instead of writing directly:

1. **`nazrul_raag_taal_fetch.py`** — pure scrape (requests + bs4 only, no
   Firestore/Gemini). Crawls nazrulgeeti.org's full song list, parses each
   song's `রাগ ও তাল` accordion panel (`রাগঃ ...` / `তালঃ ...`) and its
   `স্বরলিপি` panel's image URL if present, by HTML element ID (not
   rendered text — robust against incidental keyword mentions in lyrics).
   Writes `domains/geetabitan/data/nazrulgeeti_org_raw.json`. Must be run
   from a normal terminal (nazrulgeeti.org is blocked by the sandbox egress
   policy, same as the other GCP/external hosts in this project).

2. **`nazrul_raag_taal_match_candidates.py`** — pure local computation (no
   network at all). Loads the local `nazrul_songs.json` catalog and the
   step-1 scrape, fuzzy-matches each local song's title and first_line
   against every scraped title (bigram pre-filter + difflib ratio, trying
   hyphen/punctuation-normalized variants of both sides), and writes
   `domains/geetabitan/data/nazrul_raag_taal_review.csv`: one row per local
   song with its top 3 candidate matches, scores, raag/taal/swaralipi URL,
   and a blank `status` column. Each row's Firestore document ID is
   precomputed locally using the exact same formula `nazrul_embedder.py`
   used originally (`md5("nazrul_song_{id}_{title}")`), so step 3 needs no
   fuzzy Firestore query at all.

3. **Human review** (manual): open the CSV, mark `status` = `y` on rows to
   approve (rows with `suggested=y`, score ≥ 0.85, are pre-flagged as
   likely-correct but still require explicit approval), correct
   `candidate_1`'s `raag`/`taal`/title by hand or swap in an `alt2`/`alt3`
   candidate's values where wrong, leave `status` blank to skip a row.

4. **`nazrul_raag_taal_ingest.py`** — reads the reviewed CSV, writes
   `raag`/`taal`/`nazrulgeeti_org_swaralipi_image_url` for every approved
   row directly to its precomputed Firestore doc ID. Additive by default
   (only fills empty fields; `--force` to overwrite). Must run from a
   terminal with Firestore access.
