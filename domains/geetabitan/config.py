"""
domains/geetabitan/config.py
Domain-level constants for Geetabitan. Imported by tools and ingestion.
"""

# Firestore
FIRESTORE_COLLECTION = "geetabitan_songs"

# Embedding text template — includes raag_mood so fuzzy queries
# like "করুণ রাগের গান" hit the right songs via vector search
EMBED_TEXT_TEMPLATE = (
    "{title} "
    "{first_line} "
    "পর্যায়: {paryay} "
    "রাগ: {raag} "
    "তাল: {taal} "
    "মেজাজ: {raag_mood}"
)

# Valid Geetabitan paryay (section) names
PARYAY_LIST = [
    "পূজা",
    "স্বদেশ",
    "প্রেম",
    "প্রকৃতি",
    "বিচিত্র",
    "আনুষ্ঠানিক",
]

# Max lyrics chars sent to Gemini for summary generation
SUMMARY_LYRICS_CHAR_LIMIT = 2000

# ---------------------------------------------------------------------------
# Nazrul Geeti (Kazi Nazrul Islam) — additive only. Rabindra Sangeet constants
# above are untouched and remain the default/source-of-truth behavior.
# ---------------------------------------------------------------------------

# Firestore — separate collection, never mixed with Rabindra Sangeet docs
NAZRUL_FIRESTORE_COLLECTION = "nazrulgeeti_songs"

# Embedding text template — same shape as EMBED_TEXT_TEMPLATE, but Nazrul's
# own organizing concept (book/collection name, e.g. "বুলবুল", "সন্ধ্যা") takes
# the place of paryay, since Nazrul Geeti isn't organized by Tagore's paryay
# scheme.
NAZRUL_EMBED_TEXT_TEMPLATE = (
    "{title} "
    "{first_line} "
    "সংকলন: {category} "
    "রাগ: {raag} "
    "তাল: {taal} "
    "মেজাজ: {raag_mood}"
)

# Nazrul Geeti book/collection names (his own categorization, not paryay) —
# backfilled from the Nazrul Institute's published catalog where confirmed.
NAZRUL_CATEGORY_LIST = [
    "বুলবুল",
    "সন্ধ্যা",
    "জুলফিকার",
    "বিষের বাঁশি",
    "চোখের চাতক",
    "চন্দ্রবিন্দু",
    "সুর-সাকী",
    "বনগীতি",
    "গুল-বাগিচা",
    "গীতি-শতদল",
    "সুরলিপি",
    "নজরুল স্বরলিপি",
]

# ---------------------------------------------------------------------------
# Rajanikanta Sen (রজনীকান্ত সেন, পঞ্চকবি) — additive only. Rabindra Sangeet
# and Nazrul Geeti constants above are untouched.
# ---------------------------------------------------------------------------

# Firestore — separate collection, never mixed with Rabindra or Nazrul docs
RAJANIKANTA_FIRESTORE_COLLECTION = "rajanikanta_songs"

# Embedding text template — same shape as NAZRUL_EMBED_TEXT_TEMPLATE. Rajanikanta
# Sen's songs are organized by his own books (সংকলন), not Tagore's paryay scheme,
# and don't carry a documented "mood" per raag the way geetabitan.com's Rabindra
# data does, so raag_mood is omitted here rather than guessed.
RAJANIKANTA_EMBED_TEXT_TEMPLATE = (
    "{title} "
    "{first_line} "
    "সংকলন: {category} "
    "রাগ: {raag} "
    "তাল: {taal}"
)

# Rajanikanta Sen's own song collections (his books, not paryay) — বাণী (1902),
# কল্যাণী (1905), অভয়া (1910), আনন্দময়ী (1910, agomoni-bijoya), শেষ দান (1927,
# posthumous, written in his final illness). বিশ্রাম / অমৃত / সদ্ভাব কুসুম are
# pure poetry (কবিতা) collections with no raag/taal and are intentionally
# excluded — this app is about songs, not his general poetry.
RAJANIKANTA_CATEGORY_LIST = [
    "বাণী",
    "কল্যাণী",
    "অভয়া",
    "আনন্দময়ী",
    "শেষ দান",
]

# ---------------------------------------------------------------------------
# Atulprasad Sen (অতুলপ্রসাদ সেন, পঞ্চকবি) — additive only. Rabindra Sangeet,
# Nazrul Geeti and Rajanikanta Sen constants above are untouched.
# ---------------------------------------------------------------------------

# Firestore — separate collection, never mixed with the other composers' docs
ATULPRASAD_FIRESTORE_COLLECTION = "atulprasad_songs"

# Embedding text template. Unlike Nazrul/Rajanikanta, Atulprasad does NOT get
# a category/সংকলন line here: his onushilon.org corpus only labels a
# book/পর্যায় grouping on 4 of 205 songs (see atulprasad_lyrics_loader.py's
# docstring) — too sparse to serve as a real grouping field, so he isn't
# added to CATEGORY_ORGANIZED_COMPOSERS in song_tools.py and this template
# stays shaped like RAJANIKANTA_EMBED_TEXT_TEMPLATE (no raag_mood either —
# not a confirmed source for him).
ATULPRASAD_EMBED_TEXT_TEMPLATE = (
    "{title} "
    "{first_line} "
    "রাগ: {raag} "
    "তাল: {taal}"
)

# ---------------------------------------------------------------------------
# Dwijendralal Roy (দ্বিজেন্দ্রলাল রায়, পঞ্চকবি) — additive only. Rabindra
# Sangeet, Nazrul Geeti, Rajanikanta Sen and Atulprasad Sen constants above
# are untouched.
# ---------------------------------------------------------------------------

# Firestore — separate collection, never mixed with the other composers' docs
DWIJENDRALAL_FIRESTORE_COLLECTION = "dwijendralal_songs"

# Embedding text template — same shape as NAZRUL/RAJANIKANTA_EMBED_TEXT_TEMPLATE.
# Dwijendralal's songs (mostly interpolated numbers inside his plays) are
# organized by the play they were written for (category = play name), not
# by Tagore's paryay scheme. raag_mood is omitted — not a confirmed source
# for him, same reasoning as Rajanikanta.
DWIJENDRALAL_EMBED_TEXT_TEMPLATE = (
    "{title} "
    "{first_line} "
    "নাটক: {category} "
    "রাগ: {raag} "
    "তাল: {taal}"
)

# Dwijendralal Roy's plays that are confirmed (as of the first ingestion
# pass) to contain songs in the primary-source 1965 anthology
# (archive.org in.ernet.dli.2015.458180) — সীতা (continuous rhymed verse,
# no song/prose boundary) and মন্ত্র (a philosophical poem, not a play)
# contributed no songs and are intentionally excluded rather than padded
# in. This list will grow only when a future ingestion pass confirms more
# plays' songs — never guessed ahead of the data.
DWIJENDRALAL_CATEGORY_LIST = [
    "সাজাহান",
    "চন্দ্রগুপ্ত",
    "মেবার পতন",
    "রাণা প্রতাপ সিংহ",
]
