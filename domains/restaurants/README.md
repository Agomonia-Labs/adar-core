# Adar Restaurant Recommender

Restaurant Recommender is the `restaurants` ADK domain in this repo. It answers grounded questions about restaurants, cuisines, menu items, prices, reviews, addresses, and dataset coverage.

The existing root `README.md` is intentionally left for Geetabitan and other apps. This file is the restaurant-specific app README.

## What It Does

- Finds restaurants by location, cuisine, genre, rating, distance, and menu coverage.
- Compares menu item prices across restaurants, for example `pad thai near Bothell` or `chicken tikka masala near Seattle`.
- Shows deterministic restaurant inventory, including restaurants with menus and restaurants without menus.
- Retrieves restaurant details such as address, phone, website, rating, review count, and menu item count.
- Uses hybrid menu retrieval with keyword match plus pgvector embeddings.
- Uses Google ADK orchestration with restaurant-specific subagents and tools.
- Supports voice input, auth, Stripe billing hooks, response evaluation, and the shared React UI.

## Architecture

```mermaid
flowchart TD
  UI["React/Vite UI\nDOMAIN=restaurants"] --> API["FastAPI API\napi/main.py"]
  API --> ADK["Google ADK Runner"]
  ADK --> ORCH["restaurant_orchestrator"]
  ORCH --> DISC["discovery_agent"]
  ORCH --> MENU["menu_agent"]
  ORCH --> PRICE["pricing_agent"]
  ORCH --> REVIEW["review_agent"]
  ORCH --> RANK["ranking_agent"]
  API --> FALLBACK["Deterministic restaurant fallback router"]
  DISC --> PG["Postgres\nrestaurants, menu_items, reviews"]
  MENU --> PG
  PRICE --> PG
  REVIEW --> PG
  INGEST["Restaurant ingestion scripts"] --> PG
  INGEST --> PLACES["Google Places API"]
  INGEST --> WEB["Restaurant websites / PDFs / screenshots / curated files"]
```

## Agents And Tools

The active ADK config is:

```text
src/adar/agents/agents_config.restaurants.json
```

Current restaurant agents:

- `restaurant_orchestrator`: decides intent, uses conversation context, and routes to the right subagent.
- `intent_agent`: parses cuisine, location, dish, quantity, budget, and constraints.
- `discovery_agent`: restaurant search, counts, lists, genre summaries, restaurant details, dataset coverage.
- `menu_agent`: single-restaurant menus, menu item search, scraping, freshness checks.
- `pricing_agent`: price comparison for a specific dish/menu item.
- `review_agent`: review retrieval and review signal summaries.
- `ranking_agent`: recommendation ranking.

Current restaurant tool package:

```text
domains/restaurants/tools
```

Important tools:

- `parse_food_request`
- `find_restaurants`
- `list_restaurants`
- `count_restaurants`
- `get_restaurant_details`
- `restaurant_genre_summary`
- `get_restaurant_menu`
- `hybrid_search_menu_items`
- `compare_menu_prices`
- `get_restaurant_reviews`
- `summarize_review_signals`
- `rank_recommendations`

## Required Environment

Create a local restaurant env file:

```bash
cp .env.restaurants.example .env.restaurants
```

Minimum local values:

```bash
DOMAIN=restaurants
APP_NAME=adar-restaurants-api
APP_ENV=development
PORT=8040
GOOGLE_API_KEY=...
GOOGLE_PLACES_API_KEY=...
RESTAURANTS_DATABASE_URL=postgresql://adar:adar12@localhost:5432/restaurants
SESSION_DB_URL=sqlite+aiosqlite:///./restaurants_sessions.db
AUTH_FIRESTORE_DATABASE=tigers-arcl
JWT_SECRET=change-me-in-local-dev
FRONTEND_URL=http://localhost:5173
EVAL_ENABLED=true
```

Use SQLite only for local development. Production should use a shared Postgres `SESSION_DB_URL` so ADK sessions and conversation state survive Cloud Run restarts and work across multiple instances.

Production should set `AUTH_FIRESTORE_DATABASE=tigers-arcl` as a Cloud Run env var unless you intentionally move auth teams to another Firestore database.

Production should use Secret Manager for:

- `GOOGLE_API_KEY`
- `GOOGLE_PLACES_API_KEY`
- `RESTAURANTS_DATABASE_URL`
- `SESSION_DB_URL`
- `RESTAURANTS_API_KEY`
- `JWT_SECRET`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`
- `FRONTEND_URL`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_RESTAURANTS`

## Local Postgres

The simplest local database uses the checked-in Docker Compose file:

```bash
docker compose -f docker-compose.restaurants.yml up -d
```

This starts:

```text
postgresql://adar:adar12@localhost:5432/restaurants
```

Apply schema:

```bash
DOTENV_FILE=.env.restaurants DOMAIN=restaurants PYTHONPATH=$(pwd) \
bash domains/restaurants/ingestion/scripts/01_schema.sh
```

The restaurant schema expects these Postgres extensions:

- `vector` from pgvector
- `pg_trgm`
- `pgcrypto`

## Local Backend

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

DOTENV_FILE=.env.restaurants DOMAIN=restaurants PYTHONPATH=$(pwd) \
python api/main.py
```

Health check:

```bash
curl http://localhost:8040/health
```

## Local Frontend

Create or update `ui/.env.restaurants`:

```bash
VITE_DOMAIN=restaurants
VITE_API_URL=http://localhost:8040
```

Run:

```bash
cd ui
npm install
npm run dev -- --mode restaurants
```

Open:

```text
http://localhost:5173
```

Restaurant product demo:

```text
http://localhost:5173/demo.restaurants.html
```

The demo is a standalone narrated product walkthrough with browser voice synthesis and an interactive microphone panel for sample restaurant questions.

## Total Ingestion Process

Run these commands from the repo root after `.env.restaurants` is configured.

1. Apply schema.

```bash
bash domains/restaurants/ingestion/scripts/01_schema.sh
```

2. Discover restaurants in Greater Seattle.

```bash
bash domains/restaurants/ingestion/scripts/02_places_greater_seattle.sh
```

Useful overrides:

```bash
RADIUS_MILES=60 bash domains/restaurants/ingestion/scripts/02_places_greater_seattle.sh
PLACE_TYPES=thai_restaurant bash domains/restaurants/ingestion/scripts/02_places_greater_seattle.sh
PLACE_TYPES=indian_restaurant bash domains/restaurants/ingestion/scripts/02_places_greater_seattle.sh
```

3. Scrape menus from discovered websites.

```bash
bash domains/restaurants/ingestion/scripts/03_bulk_menus.sh
```

For JavaScript-heavy websites, use browser mode:

```bash
MENU_DISCOVERY_MODE=browser MENU_FETCH_MODE=browser \
bash domains/restaurants/ingestion/scripts/03_bulk_menus.sh
```

4. Test alternate menu extraction for difficult sites.

```bash
bash domains/restaurants/ingestion/scripts/11_test_menu_alternates.sh
```

5. Inspect website links when menu discovery fails.

```bash
bash domains/restaurants/ingestion/scripts/12_inspect_links.sh
```

6. Add manually found menu URLs.

Edit:

```text
domains/restaurants/data/manual_menu_urls.json
```

Then run:

```bash
bash domains/restaurants/ingestion/scripts/07_manual_menus.sh
```

7. Import trusted curated menu rows when scraping is unreliable.

Edit:

```text
domains/restaurants/data/curated_menu_items.csv
```

Then run:

```bash
bash domains/restaurants/ingestion/scripts/08_curated_menus.sh
```

8. Generate embeddings for hybrid search.

```bash
bash domains/restaurants/ingestion/scripts/05_embeddings.sh
```

9. Verify ingestion.

```bash
bash domains/restaurants/ingestion/scripts/06_verify.sh
```

10. Run the automated menu pipeline.

```bash
bash domains/restaurants/ingestion/scripts/13_auto_menu_pipeline.sh
```

11. Run the full Greater Seattle pipeline.

```bash
bash domains/restaurants/ingestion/scripts/run_greater_seattle_pipeline.sh
```

The lower-level ingestion reference is here:

```text
domains/restaurants/ingestion/README.md
```

## Browser, PDF, And OCR Requirements

Browser menu extraction:

```bash
pip install playwright
python -m playwright install chrome
```

PDF menu extraction:

```bash
pip install pypdf
```

Image or screenshot OCR:

```bash
pip install pillow pytesseract
brew install tesseract
```

Use curated import when website scraping, browser extraction, PDF parsing, or OCR cannot reliably produce clean menu rows.

## Dataset QA Commands

Ask these questions in the UI after ingestion:

```text
How many Indian restaurants do you have in the system?
Show me all Italian restaurants near Kirkland.
Show Indian restaurants that have menu items in the system.
Show Indian restaurants without menu items.
Show address and rating for Taste of India and Bai Tong Thai.
Show Taste of India restaurant menu.
Compare chicken tikka masala prices near Seattle.
Show price comparison of pad thai noodles in Bothell, Kirkland, Bellevue.
Which Thai restaurant has the cheapest tom yum soup near Bothell?
Find American fast food options near Seattle.
```

Expected behavior:

- Restaurant inventory questions should use restaurant list/count/detail tools.
- Menu questions should use menu tools.
- Specific dish price comparisons should use pricing tools.
- Follow-up requests such as `show their addresses` or `show in tabular format` should use recent session context.

## Backend Deployment

### Production Session Database

Do not use SQLite for `SESSION_DB_URL` in Cloud Run production. Cloud Run `/tmp` storage is ephemeral and per instance, so SQLite sessions can disappear after restarts and are not shared when Cloud Run scales out.

Create a Postgres database for ADK sessions:

```sql
CREATE DATABASE restaurants_sessions;
CREATE USER restaurants_session_user WITH PASSWORD 'strong-password';
GRANT ALL PRIVILEGES ON DATABASE restaurants_sessions TO restaurants_session_user;
```

For Cloud SQL Unix socket connectivity, the secret value should look like this:

```text
postgresql+asyncpg://restaurants_session_user:strong-password@/restaurants_sessions?host=/cloudsql/PROJECT_ID:REGION:INSTANCE
```

Store it in Secret Manager:

```bash
printf '%s' 'postgresql+asyncpg://restaurants_session_user:strong-password@/restaurants_sessions?host=/cloudsql/PROJECT_ID:REGION:INSTANCE' | \
gcloud secrets create restaurants-session-db-url --data-file=-
```

Create production secrets first. The default deploy script expects these Secret Manager names:

```text
google-api-key
restaurants-google-places-api-key
restaurants-database-url
restaurants-session-db-url
restaurants-api-key
restaurants-jwt-secret
restaurants-admin-email
restaurants-admin-password
restaurants-frontend-url
stripe-secret-key
restaurants-stripe-webhook-secret
stripe-price-restaurants
```

Example secret creation:

```bash
printf '%s' 'postgresql://user:password@host:5432/restaurants' | \
gcloud secrets create restaurants-database-url --data-file=-
```

Deploy:

```bash
bash infra/deploy-restaurants.sh
```

Optional overrides:

```bash
PROJECT_ID=bdas-493785 \
REGION=us-central1 \
SERVICE=adar-restaurants-api \
SQL_INSTANCE=bdas-493785:us-central1:adar-pgdev \
bash infra/deploy-restaurants.sh
```

Smoke test:

```bash
curl https://YOUR_RESTAURANTS_API_URL/health
```

## Frontend Deployment

Build the restaurant UI:

```bash
cd ui
VITE_DOMAIN=restaurants VITE_API_URL=https://YOUR_RESTAURANTS_API_URL npm run build
```

The restaurant Firebase Hosting site for project `bdas-493785` is:

```text
restaurants-adar
```

The local Firebase target should map `restaurants` to that site ID:

```bash
firebase target:apply hosting restaurants restaurants-adar --project bdas-493785
```

The checked-in `ui/.firebaserc` already contains this mapping:

```text
restaurants (restaurants-adar)
```

Deploy only the restaurant target:

```bash
firebase deploy --only hosting:restaurants
```

The restaurant product demo is deployed with the same Firebase Hosting site:

```text
https://restaurants-adar.web.app/demo.restaurants.html
https://restaurants.adar.agomoniai.com/demo.restaurants.html
```

If `ui/firebase.json` does not yet contain a `restaurants` hosting target, add one that uses `dist` as `public` and rewrites `**` to `/index.html`.

Do not map the target to `restaurants-adar.web.app`. Firebase target mappings use the Hosting site ID, not the default URL. If deploy fails with:

```text
Error: could not find site "restaurants-adar.web.app" for project "bdas-493785"
```

Run:

```bash
firebase target:apply hosting restaurants restaurants-adar --project bdas-493785
firebase target --project bdas-493785
```

### Custom Domain

The production restaurant UI should be served from:

```text
https://restaurants.adar.agomoniai.com
```

Firebase Hosting custom domains are configured from the Firebase console, then verified with DNS records in Route53.

1. Deploy the restaurant Hosting site first.

```bash
cd ui
VITE_DOMAIN=restaurants VITE_API_URL=https://YOUR_RESTAURANTS_API_URL npm run build
firebase deploy --only hosting:restaurants
```

2. In Firebase Console, open:

```text
Project: bdas-493785
Hosting site: restaurants-adar
Custom domains
Add custom domain
```

3. Add this domain:

```text
restaurants.adar.agomoniai.com
```

4. In AWS Route53, open the hosted zone for:

```text
adar.agomoniai.com
```

5. Add the DNS records Firebase shows in the custom domain wizard.

For a subdomain in Route53, use the subdomain label as the record name:

```text
restaurants
```

Do not include `https://` in DNS records. Do not use `restaurants-adar.web.app` as the custom domain.

Firebase normally asks for records like these, but always copy the exact values from the Firebase wizard:

```text
TXT  restaurants  firebase-verification-value-from-console
A    restaurants  199.36.158.100
```

If Firebase provides AAAA records, add those too. If Route53 already has a CNAME, A, or AAAA record for `restaurants`, remove the conflicting record before verification.

6. Wait for DNS propagation and SSL provisioning.

Firebase can take a few hours, and sometimes up to 24 hours, to verify ownership and provision SSL. Keep the Firebase TXT verification record in Route53 after setup so Firebase can renew SSL certificates.

7. Verify DNS from your terminal:

```bash
dig restaurants.adar.agomoniai.com TXT
dig restaurants.adar.agomoniai.com A
```

8. After Firebase shows the domain as connected, open:

```text
https://restaurants.adar.agomoniai.com
```

## Production Checklist

- Production Postgres is reachable from Cloud Run.
- Production `SESSION_DB_URL` uses Postgres, not SQLite.
- Restaurant schema is applied.
- Menu embeddings are generated for rows that should participate in hybrid search.
- Secret Manager contains all required secrets.
- Restaurant API CORS includes `https://restaurants.adar.agomoniai.com`.
- Google Places API is enabled for ingestion keys.
- Gemini API key is active and not leaked.
- Speech-to-text key is allowed to call `speech.googleapis.com` if cloud STT fallback is needed.
- Stripe env is configured before enabling restaurant billing.
- Frontend `VITE_API_URL` points to the deployed restaurant API.
- Firebase custom domain `restaurants.adar.agomoniai.com` is connected to Hosting site `restaurants-adar`.
- Response evaluation labels are English for the restaurant app.

## Troubleshooting

`extension "vector" is not available`

Install pgvector for your Postgres server, or use the checked-in Docker Compose service based on `pgvector/pgvector:pg16`.

`extension "postgis" is not available`

The current restaurant pipeline does not require PostGIS for normal operation. If an older schema migration still asks for PostGIS, update to the current schema scripts and rerun `01_schema.sh`.

`role "adar" does not exist`

Create the database role or use the Docker Compose database URL exactly:

```text
postgresql://adar:adar12@localhost:5432/restaurants
```

Google Places returns `403 Forbidden`

Enable the Places API for the key, check API restrictions, billing, and make sure `GOOGLE_PLACES_API_KEY` is set in `.env.restaurants`.

Gemini returns `503 UNAVAILABLE`

Retry the failed ingestion or chat request. The service can return transient errors.

Speech-to-text returns `API_KEY_SERVICE_BLOCKED`

Enable Speech-to-Text for that key or use a key whose restrictions allow `speech.googleapis.com`.

Production registration fails

First redeploy the restaurant API after CORS or auth env changes:

```bash
bash infra/deploy-restaurants.sh
```

The production browser origin must be in `api/main.py` CORS origins:

```text
https://restaurants.adar.agomoniai.com
https://restaurants-adar.web.app
```

The restaurant Cloud Run service should also set:

```text
DOMAIN=restaurants
AUTH_FIRESTORE_DATABASE=tigers-arcl
FRONTEND_URL=https://restaurants.adar.agomoniai.com
```

If registration still fails, check Cloud Run logs for `/api/auth/register`:

```bash
gcloud run services logs read adar-restaurants-api \
  --region us-central1 \
  --project bdas-493785 \
  --limit 100
```

Common causes are missing Firestore permissions for the Cloud Run service account, wrong `AUTH_FIRESTORE_DATABASE`, or a CORS preflight rejection from an unlisted frontend origin.

Price comparison returns restaurant lists instead of prices

Verify the dish exists in `menu_items`, has a numeric price, and embeddings have been generated. Then test deterministic pricing with a query such as:

```text
Compare chicken tikka masala prices near Seattle.
```
