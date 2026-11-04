# Phase 2 Action Plan — Atulprasad Sen & Dwijendralal Roy

Additive extension of Geetabitan/Sursangam past Rabindra Sangeet, Nazrul Geeti, and Rajanikanta Sen. Written after confirming the exact wiring pattern against the current codebase (`domains/geetabitan/config.py`, `song_tools.py`, `search_tools.py`, `api/routes/music.py`, `agents_config.geetabitan.json`, `infra/create_geetabitan_indexes.sh`, and the `rajanikanta_*` ingestion scripts).

**Standing rules this plan obeys throughout:** Rabindra Sangeet and Nazrul Geeti collections/pipelines are never touched. Every change is additive (new constants, new dict entries, new files) — nothing existing is removed or restructured. No Firestore writes happen until a human has reviewed the extracted song data. No raag/taal/category value is invented — fields with no confirmed source stay blank, exactly like Rajanikanta's `raag_mood` is intentionally omitted today.

## The established pattern (confirmed from the Rajanikanta precedent)

Adding a composer always touches the same eleven places. This plan instantiates this checklist twice, once per poet.

1. `domains/geetabitan/data/<slug>_raw.json` — raw scraped/extracted data, one new file.
2. `domains/geetabitan/config.py` — append `<SLUG>_FIRESTORE_COLLECTION`, `<SLUG>_EMBED_TEXT_TEMPLATE`, `<SLUG>_CATEGORY_LIST` (only if the poet has his own book/category scheme).
3. `domains/geetabitan/ingestion/<slug>_lyrics_loader.py` — new file: raw JSON → canonical JSON, same shape as `rajanikanta_lyrics_loader.py` (MD5 dedup id, `MIN_LYRICS_CHARS` filter, a docstring stating exactly what's confirmed vs. missing).
4. `domains/geetabitan/ingestion/<slug>_embedder.py` — new file: `embed_and_store()` / `embed_all()`, identical Firestore document shape to `rajanikanta_embedder.py` (768-dim `gemini-embedding-001`, same field set, raag fields blank where unconfirmed).
5. `domains/geetabitan/ingestion/<slug>_summarizer.py` — new file: Gemini context/meaning/emotion/imagery generator with a persona prompt suited to that poet (mirrors `rajanikanta_summarizer.py`).
6. `domains/geetabitan/ingestion/run_ingestion.py` — add `step_<slug>_load/_embed/_summarize()` plus four new `--only` choices: `<slug>-load`, `<slug>-embed`, `<slug>-summaries`, `<slug>`.
7. `domains/geetabitan/tools/song_tools.py` — additive touches only: extend the `Composer` Literal; extend `CATEGORY_ORGANIZED_COMPOSERS` (if applicable); extend `_COMPOSER_COLLECTIONS`; extend `_other_composers()`'s order tuple; add a `GENRE_NAMES` entry and a `<SLUG>_SINGERS` list + `SINGERS` dict entry inside `get_youtube_url`; add a `DEFAULT_YOUTUBE_QUERY` entry; add 2–3 well-known title hints to `_find_song_for_youtube`; add an `elif doc_source == "<slug>"` branch in `summarize_aspect` importing the new summarizer.
8. `domains/geetabitan/tools/search_tools.py` — add the no-results message (in `vector_search_songs`), the raag-usage label tuple (in `describe_raag`), and the `COUNT_LABELS` entry (in `describe_taal`).
9. `api/routes/music.py` — add the collection to the `COLLECTIONS` list, a `GENRE_NAMES` entry, a `<SLUG>_SINGERS` list, and a `singers` dict entry.
10. `src/adar/agents/agents_config.geetabitan.json` — two additive instruction blocks (one appended to the orchestrator's routing instruction, one to `song_agent`'s), each gated on the user explicitly naming the composer — same shape as the existing নজরুলগীতি/রজনীকান্ত "সংযোজন" blocks, each ending with "অন্যথায় উপরের সব নিয়ম ... অপরিবর্তিত।"
11. `infra/create_geetabitan_indexes.sh` — one new line in the `COLLECTIONS` array: `"<slug>_songs:<grouping_field>"`.

Everything below instantiates this for each poet, plus the composer-specific data-sourcing work that has to happen *before* step 1 can be written.

---

## Part A — Atulprasad Sen (আতুলপ্রসাদ সেন)

**Data status (from Phase 1):** workable now. `onushilon.org`'s 205-song numbered corpus gives real lyrics for the bulk of his catalog; `milansagar.com`'s `kobi_9/atulprasad_sen` essay corroborates the biography. Raag/taal metadata is sparse (confirmed on roughly 6% of songs) — treated as optional per song, exactly like Rajanikanta.

**One open item before step 2 can be written:** Rajanikanta's `CATEGORY_LIST` is his own five published books (বাণী, কল্যাণী, …). Phase 1 did not pin down whether Atulprasad has an equivalent self-published book/collection scheme that onushilon.org or milansagar.com label per song. Two honest paths, your call:

- **Path A1 (one more short research pass):** check onushilon.org's own section headers and milansagar's essay for a book/collection grouping. If one exists and is cleanly labeled per song, it becomes `ATULPRASAD_CATEGORY_LIST` and Atulprasad joins `CATEGORY_ORGANIZED_COMPOSERS`, same as Rajanikanta.
- **Path A2 (ship without category grouping):** if no clean per-song book label exists, Atulprasad simply doesn't join `CATEGORY_ORGANIZED_COMPOSERS` — `get_songs_by_category` isn't offered for him, exactly how notation isn't offered for Nazrul/Rajanikanta today. Users still get title lookup, raag/taal lookup (where known), and vector search. This is a legitimate, smaller scope, not a workaround.

### Atulprasad step-by-step

0. **Extract the raw corpus.** Same slow path as Rajanikanta: `onushilon.org` and `milansagar.com` are both blocked by this project's egress allowlist for `requests`/`curl`, so extraction has to run as same-origin `fetch()` calls inside a real browser (the Browser pane), batched to avoid the ~45s timeout seen before. Output: `domains/geetabitan/data/atulprasad_onushilon_raw.json`, one entry per song (title, first_line, raag_taal where present, lyrics, source url) — this is a **data file for your review**, not an ingest.
1. Resolve the Path A1/A2 category question above.
2. `config.py` — add `ATULPRASAD_FIRESTORE_COLLECTION = "atulprasad_songs"`, `ATULPRASAD_EMBED_TEXT_TEMPLATE` (with or without `সংকলন:` depending on A1/A2), and `ATULPRASAD_CATEGORY_LIST` if A1.
3. `atulprasad_lyrics_loader.py` — normalize raw → canonical, same `MIN_LYRICS_CHARS` filter and dedup approach as Rajanikanta's loader, with an honest docstring on exact coverage (X of 205 songs have usable lyrics, Y have raag/taal).
4. `atulprasad_embedder.py`, `atulprasad_summarizer.py` — mirror Rajanikanta's files exactly, swap in the Atulprasad persona for the summarizer prompt (known for উদাসী/বিষাদ-tinted lyrics and setting Bengali words to Scottish/Western folk tunes — this is the one biographical detail worth putting in the prompt, since it's actually distinctive of his songwriting).
5. `run_ingestion.py` — add the four `atulprasad-*` steps.
6–11. The `song_tools.py` / `search_tools.py` / `music.py` / `agents_config.geetabitan.json` / `infra` touches listed in the checklist above, with `GENRE_NAMES["atulprasad"] = ("আতুলপ্রসাদের গান", "Atul Prasad Sangeet")` and a singer list (e.g. Rezwana Chowdhury Bonna, Sagar Sen — confirm against whatever Phase 1's sources actually named rather than guessing a canon here).

This composer is close to a straight repeat of the Rajanikanta build — no architectural unknowns, just the one category question above.

---

## Part B — Dwijendralal Roy (দ্বিজেন্দ্রলাল রায়)

**Data status:** harder — no single site plays the role milansagar+onushilon played for Rajanikanta/Atulprasad. The concrete, tiered sourcing plan (already laid out, repeated here for completeness):

- **Tier 1 — bulk lyrics.** `archive.org/details/in.ernet.dli.2015.458180` ("Dwijendralal-rachanasambhar," 1965, ed. Pramathanath Bishi), confirmed **Public Domain**, ~845K OCR'd characters covering his five major plays (সীতা, সাজাহান, চন্দ্রগুপ্ত, মেবার পতন, রাণা প্রতাপ সিংহ). Songs are embedded in dialogue, OCR is rough — needs a human-reviewed extraction pass, not an automatic scrape.
- **Tier 2 — category skeleton.** musicgoln.com + kaliokalam.com converge on: হাসির গান, প্রেমের গান, স্বদেশি গান, নাটকের গান (sub-divided by the specific play), ভক্তিমূলক গান, plus musicgoln's additional রাগভিত্তিক/শাস্ত্রীয় and শিশু ও শিক্ষামূলক buckets. This becomes `DWIJENDRALAL_CATEGORY_LIST` and the master title checklist (Tier 1 songs merge in where titles match; everything else stays a title+category stub pending a lyrics source — never backfilled with guessed text).
- **Tier 3 — raag/taal.** kaliokalam.com's essay states only ~132 of ~500 songs have confirmed notation. Populate `raag`/`taal` only where a named source states it directly; leave the rest blank, same pattern as Rajanikanta/Atulprasad.
- **Tier 4 — manual-only, not automatable from here:** the British Library's EAP261 "early Bengali drama" digital archive is real and browsable but CAPTCHA-gated (I can't pass it); Nitai Ghatak's notation book exists only as physical/microfilm holdings at CRL/UPenn; Bangla Akademi's 2008 "দ্বিজেন্দ্রগীতি সমগ্র" is the definitive modern edition but copyrighted and not freely digitized. Any of these would raise coverage further, but they need you, not me — flagged here as optional upgrades, not blockers.

### Dwijendralal step-by-step

0. **Extraction pass (the real work).** Two parallel sub-tasks, both producing review files, no ingest:
   - 0a. Pull Tier 1's OCR text from archive.org, split by play, extract candidate song stanzas (verse-like line breaks, scattered রাগ/তাল/গীতি markers) into `domains/geetabitan/data/dwijendralal_plays_raw.json`. This needs your eyes on each candidate before it counts as a real song — OCR noise means some "candidates" will be prose, not lyrics.
   - 0b. Pull Tier 2's title/category index from musicgoln.com (+ kaliokalam.com's essay for the raag/taal subset) into `domains/geetabitan/data/dwijendralal_index_raw.json`.
   - 0c. Merge 0a into 0b by title match, same conservative "never override, only fill gaps" rule used for Rajanikanta's onushilon merge. Present the merged, flagged draft to you before touching step 2.
1. `config.py` — `DWIJENDRALAL_FIRESTORE_COLLECTION = "dwijendralal_songs"`, `DWIJENDRALAL_EMBED_TEXT_TEMPLATE`, `DWIJENDRALAL_CATEGORY_LIST` from Tier 2.
2. `dwijendralal_lyrics_loader.py` — normalize the merged file, with a docstring stating the real split: how many songs have confirmed lyrics (from the 5 plays) vs. title+category stub only, and how many have confirmed raag/taal vs. none.
3. `dwijendralal_embedder.py`, `dwijendralal_summarizer.py` — mirror Rajanikanta's files; the summarizer persona should reflect what's actually distinctive (satirical হাসির গান alongside patriotic স্বদেশি গান and historical-play songs, rather than a generic "poet" framing).
4. `run_ingestion.py` — add the four `dwijendralal-*` steps.
5–10. Same `song_tools.py` / `search_tools.py` / `music.py` / `agents_config.geetabitan.json` / `infra` touches as the checklist, with `GENRE_NAMES["dwijendralal"] = ("দ্বিজেন্দ্রগীতি", "Dwijendrageeti")`.

---

## Suggested order of work

1. Atulprasad step 0 (extraction) — fastest path to a 4th working composer, validates the pattern once more with real data already in hand.
2. Resolve the Atulprasad category question (A1 vs A2) once the extraction is in front of you.
3. Wire Atulprasad end-to-end (steps 2–11), review the merged data, run ingestion.
4. Start Dwijendralal's extraction (0a/0b/0c) in parallel or after — this is the longer, more judgment-heavy piece since it's OCR extraction + human curation rather than a clean scrape.
5. Wire Dwijendralal end-to-end once its data draft is approved.

Nothing in steps 2 onward for either poet runs until you've reviewed the corresponding data file — that review is the explicit gate before any `embed_and_store()` call touches Firestore.
