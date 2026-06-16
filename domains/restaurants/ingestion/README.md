# Restaurant Ingestion

This pipeline builds the restaurant recommender data used by the
`restaurants` ADK domain.

## Environment

Set a Postgres URL with `pgvector`, `pg_trgm`, and `pgcrypto` available:

```bash
export RESTAURANTS_DATABASE_URL="postgresql://user:password@localhost:5432/restaurants"
export DOMAIN=restaurants
export PYTHONPATH=$(pwd)
```

Embeddings also require the existing Gemini configuration:

```bash
export GOOGLE_API_KEY="..."
```

## Commands

## Convenience Scripts

Run from the repo root.

```bash
# Apply schema
bash domains/restaurants/ingestion/scripts/01_schema.sh

# Discover Greater Seattle restaurants by genre
bash domains/restaurants/ingestion/scripts/02_places_greater_seattle.sh

# Scrape menus from discovered restaurant websites
bash domains/restaurants/ingestion/scripts/03_bulk_menus.sh

# Scrape menus using Google Chrome / Playwright for JavaScript-heavy sites
MENU_DISCOVERY_MODE=browser MENU_FETCH_MODE=browser \
bash domains/restaurants/ingestion/scripts/03_bulk_menus.sh

# Embed saved menu items
bash domains/restaurants/ingestion/scripts/05_embeddings.sh

# Verify counts and sample rows
bash domains/restaurants/ingestion/scripts/06_verify.sh

# Ingest manually curated menu URLs
bash domains/restaurants/ingestion/scripts/07_manual_menus.sh

# Import human-reviewed menu item CSV/JSON
bash domains/restaurants/ingestion/scripts/08_curated_menus.sh

# Export open curation queue for manual review
bash domains/restaurants/ingestion/scripts/09_export_curation.sh

# Run the main Greater Seattle pipeline
bash domains/restaurants/ingestion/scripts/run_greater_seattle_pipeline.sh
```

You can override script defaults:

```bash
RADIUS_MILES=5 \
PLACE_TYPES=indian_restaurant \
bash domains/restaurants/ingestion/scripts/02_places_greater_seattle.sh

LIMIT=50 bash domains/restaurants/ingestion/scripts/03_bulk_menus.sh

MENU_DISCOVERY_MODE=browser \
MENU_FETCH_MODE=browser \
LIMIT=50 \
bash domains/restaurants/ingestion/scripts/03_bulk_menus.sh

ENV_FILE=.env.restaurants \
PYTHON_BIN=python \
bash domains/restaurants/ingestion/scripts/run_greater_seattle_pipeline.sh
```

Browser mode requires Playwright and Chrome:

```bash
pip install playwright
python -m playwright install chrome
```

PDF menu ingestion requires:

```bash
pip install pypdf
```

Image menu OCR requires Python packages plus the system `tesseract` binary:

```bash
pip install pillow pytesseract
brew install tesseract
```

## Manual Menu URLs

When bulk scraping fails and you find the correct menu URL manually, add it to:

```text
domains/restaurants/data/manual_menu_urls.json
```

Start from this template:

```bash
cp domains/restaurants/data/manual_menu_urls.example.json \
   domains/restaurants/data/manual_menu_urls.json
```

Format:

```json
{
  "menus": [
    {
      "restaurant_id": "restaurant-uuid-from-db",
      "restaurant_name": "Optional Name",
      "menu_url": "https://restaurant.com/real-menu-url",
      "cuisine": ["seafood"],
      "meal": ["lunch", "dinner"]
    }
  ]
}
```

Find restaurant IDs:

```sql
select id, name, website_url
from restaurants
where name ilike '%elliott%'
limit 10;
```

Run manual menu ingestion:

```bash
MENU_FETCH_MODE=browser \
MANUAL_MENU_SOURCE=domains/restaurants/data/manual_menu_urls.json \
bash domains/restaurants/ingestion/scripts/07_manual_menus.sh
```

Manual PDF menus are also supported:
Manual PDF and image menus are also supported:

```json
{
  "menus": [
    {
      "restaurant_id": "restaurant-uuid-from-db",
      "restaurant_name": "Optional Name",
      "file_path": "/absolute/path/to/menu.pdf",
      "menu_url": "https://restaurant.com/menu.pdf",
      "cuisine": ["american"],
      "meal": ["lunch", "dinner"]
    }
  ]
}
```

## Curation Queue

Failed bulk menu scrapes are logged to `menu_scrape_attempts` and restaurants
that still have no parsed menu are added to `menu_curation_queue`.

Export open curation tasks:

```bash
bash domains/restaurants/ingestion/scripts/09_export_curation.sh
```

This writes:

```text
domains/restaurants/data/curation_queue.csv
```

Use that CSV to decide which menu URLs/PDFs need manual review.

## Curated Menu Import

When you have verified menu items manually, import them as trusted data.

Create:

```bash
cp domains/restaurants/data/curated_menu_items.example.csv \
   domains/restaurants/data/curated_menu_items.csv
```

Then edit rows and run:

```bash
CURATED_MENU_SOURCE=domains/restaurants/data/curated_menu_items.csv \
bash domains/restaurants/ingestion/scripts/08_curated_menus.sh
```

Curated imports use `source_type=curated` and `extraction_confidence=1.0` by
default.

Apply schema:

```bash
python -m domains.restaurants.ingestion.run_ingestion --only schema
```

Ingest seeded restaurants and menu items:

```bash
python -m domains.restaurants.ingestion.run_ingestion \
  --only restaurants \
  --source domains/restaurants/data/sample_restaurants.json
```

Scrape one official menu URL into an existing restaurant:

```bash
python -m domains.restaurants.ingestion.run_ingestion \
  --only menu-url \
  --restaurant-id 4ca42224-9e5a-56f9-8327-812a536246d2 \
  --menu-url https://example.com/menu \
  --cuisine indian \
  --meal dinner
```

Ingest reviews:

```bash
python -m domains.restaurants.ingestion.run_ingestion \
  --only reviews \
  --reviews-source domains/restaurants/data/sample_reviews.json
```

Discover restaurants from Google Places around Greater Seattle:

```bash
python -m domains.restaurants.ingestion.run_ingestion \
  --only places \
  --location greater-seattle \
  --radius-miles 60
```

The Google Places Nearby Search API accepts a maximum circle radius of 50,000
meters, so the ingestion job covers the 60-mile area with multiple overlapping
tiles and deduplicates by Google place ID.

You can also use the convenience script:

```bash
domains/restaurants/ingestion/ingest_greater_seattle.sh --schema
```

Cheap smoke test:

```bash
domains/restaurants/ingestion/ingest_greater_seattle.sh \
  --radius-miles 5 \
  --place-types indian_restaurant
```

Broader pass using every default Google place type:

```bash
domains/restaurants/ingestion/ingest_greater_seattle.sh --full
```

Embed missing menu items:

```bash
python -m domains.restaurants.ingestion.run_ingestion --only embeddings --limit 100
```

Run the default pipeline:

```bash
python -m domains.restaurants.ingestion.run_ingestion \
  --source domains/restaurants/data/sample_restaurants.json \
  --reviews-source domains/restaurants/data/sample_reviews.json
```

## Source Formats

Restaurant JSON can be either a list or an object with a `restaurants` key.
Each restaurant may include a `menu_items` list.

Review JSON can be either a list or an object with a `reviews` key. Each
review must include `restaurant_id`.

CSV files are also accepted for restaurant and review seed ingestion.
