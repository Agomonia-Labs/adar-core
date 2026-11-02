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
