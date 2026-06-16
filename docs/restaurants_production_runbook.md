# Restaurant Recommender Production Runbook

## Local Development

Backend:

```bash
cd /Users/brajadas/project/adar-core
DOTENV_FILE=.env.restaurants PYTHONPATH=$(pwd) python api/main.py
```

Frontend:

```bash
cd /Users/brajadas/project/adar-core/ui
npm install
npm run dev -- --mode restaurants
```

Open the Vite URL, usually `http://localhost:5173`.

## Ingestion

```bash
bash domains/restaurants/ingestion/scripts/01_schema.sh
bash domains/restaurants/ingestion/scripts/02_places_greater_seattle.sh

MENU_DISCOVERY_MODE=browser MENU_FETCH_MODE=browser LIMIT=50 MAX_MENU_PAGES=8 \
bash domains/restaurants/ingestion/scripts/03_bulk_menus.sh

bash domains/restaurants/ingestion/scripts/09_export_curation.sh
```

Review `domains/restaurants/data/curation_queue.csv`, then add manual URLs,
PDFs, images, or curated CSV rows:

```bash
bash domains/restaurants/ingestion/scripts/07_manual_menus.sh
bash domains/restaurants/ingestion/scripts/08_curated_menus.sh
LIMIT=500 bash domains/restaurants/ingestion/scripts/05_embeddings.sh
bash domains/restaurants/ingestion/scripts/06_verify.sh
```

## Required Environment

Backend `.env.restaurants`:

```bash
DOMAIN=restaurants
APP_ENV=development
PORT=8040
GOOGLE_API_KEY=
GOOGLE_PLACES_API_KEY=
RESTAURANTS_DATABASE_URL=postgresql://adar:adar12@localhost:5432/restaurants
SESSION_DB_URL=sqlite+aiosqlite:///./restaurants_sessions.db
JWT_SECRET=change-me
EVAL_ENABLED=false
```

Frontend `ui/.env.restaurants`:

```bash
VITE_DOMAIN=restaurants
VITE_API_URL=http://localhost:8040
VITE_API_KEY=
```

## User Workflow

Users can ask:

- Find Indian restaurants near Seattle.
- Compare pad thai prices near Bellevue.
- Find Thai dinner under $25 for 2 people.
- Which seafood restaurants have menu items and good reviews?

## Production Notes

- Treat scraped prices as estimates unless `source_type=curated`.
- Keep `menu_curation_queue` operational; do not rely only on automation.
- Re-run Places discovery weekly/monthly.
- Re-run menu scraping for high-traffic restaurants weekly.
- Use curated imports for important launch restaurants.
