"""Domain-level constants for the restaurant recommender."""

RESTAURANT_DOMAIN = "restaurants"

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM = 768

DEFAULT_RADIUS_MILES = 5
DEFAULT_RESULT_LIMIT = 10

CUISINE_TAGS = [
    "american",
    "asian",
    "barbecue",
    "breakfast",
    "indian",
    "chinese",
    "japanese",
    "korean",
    "thai",
    "vietnamese",
    "mexican",
    "italian",
    "mediterranean",
    "middle_eastern",
    "seafood",
    "spanish",
    "vegan",
    "vegetarian",
    "fast_food",
]

MEAL_TAGS = [
    "breakfast",
    "brunch",
    "lunch",
    "dinner",
    "late_night",
]

SERVICE_TYPES = [
    "dine_in",
    "takeout",
    "delivery",
    "fast_food",
    "casual",
    "fine_dining",
]
