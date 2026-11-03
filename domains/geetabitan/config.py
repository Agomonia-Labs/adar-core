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
