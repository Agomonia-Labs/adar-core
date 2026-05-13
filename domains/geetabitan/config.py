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
