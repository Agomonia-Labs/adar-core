# Restaurant Recommender Domain Design

This design extends the existing ADAR domain pattern used by `arcl` and
`geetabitan`.

The goal is to add a new `restaurants` domain that recommends restaurant foods
with price comparison, menu-aware matching, review signals, and location-based
ranking.

## Fit With Current Repo

The current platform already has the right domain shape:

- `DOMAIN` selects the active domain.
- `src/adar/agents/agents.py` loads `src/adar/agents/agents_config.{DOMAIN}.json`.
- Tool names in agent config map to callables from `domains.{DOMAIN}.tools.TOOL_REGISTRY`.
- FastAPI starts one ADK orchestrator through `build_agents()`.
- ADK session state is already handled by `DatabaseSessionService`.

For this domain, run with:

```bash
DOMAIN=restaurants PYTHONPATH=$(pwd) python api/main.py
```

## New Files

```text
src/adar/agents/agents_config.restaurants.json
domains/restaurants/
  __init__.py
  config.py
  tools/
    __init__.py
    search_tools.py
    restaurant_tools.py
    menu_tools.py
    pricing_tools.py
    review_tools.py
  ingestion/
    __init__.py
    menu_scraper.py
    menu_parser.py
    restaurant_ingest.py
    embedder.py
```

## Agent Topology

```text
restaurant_orchestrator
  intent_agent
  discovery_agent
  menu_agent
  pricing_agent
  review_agent
  ranking_agent
```

The orchestrator should route by user intent:

| User need | Agent |
|---|---|
| Location, cuisine, meal type, budget, party size extraction | `intent_agent` |
| Restaurant search near a location | `discovery_agent` |
| Menu item search, menu scraping, menu freshness | `menu_agent` |
| Cheapest item, total estimate, price comparison | `pricing_agent` |
| Review summary, dish mentions, complaint patterns | `review_agent` |
| Final recommendation ranking and explanation | `ranking_agent` |

## Data Store

Use Postgres with pgvector and full-text search. The local ingestion path
stores latitude and longitude directly so PostGIS setup does not block
development; PostGIS can be added later for production-grade geo indexing.

Do not use the existing Firestore vector helper for this domain. ARCL and
Geetabitan use Firestore vectors today, but restaurant recommendations need
location filtering, relational joins, price history, and hybrid search.
Postgres is a better fit.

Recommended extensions:

```sql
create extension if not exists vector;
create extension if not exists pg_trgm;
```

## Tables

```sql
create table restaurants (
  id uuid primary key,
  name text not null,
  normalized_name text not null,
  website_url text,
  phone text,
  address text,
  city text,
  region text,
  postal_code text,
  country text default 'US',
  latitude double precision,
  longitude double precision,
  rating numeric(2,1),
  review_count integer default 0,
  price_level integer,
  service_types text[] default '{}',
  cuisine_tags text[] default '{}',
  meal_tags text[] default '{}',
  source_refs jsonb default '[]',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table menu_items (
  id uuid primary key,
  restaurant_id uuid references restaurants(id),
  name text not null,
  normalized_name text not null,
  description text,
  category text,
  cuisine_tags text[] default '{}',
  meal_tags text[] default '{}',
  dietary_tags text[] default '{}',
  price numeric(10,2),
  currency text default 'USD',
  portion_size text,
  serves_qty numeric,
  availability text,
  source_url text,
  source_type text,
  extraction_confidence numeric(3,2),
  last_seen_at timestamptz,
  embedding vector(768),
  search_tsv tsvector generated always as (
    to_tsvector(
      'english',
      coalesce(name, '') || ' ' ||
      coalesce(description, '') || ' ' ||
      coalesce(category, '') || ' ' ||
      array_to_string(cuisine_tags, ' ') || ' ' ||
      array_to_string(meal_tags, ' ') || ' ' ||
      array_to_string(dietary_tags, ' ')
    )
  ) stored
);

create table price_observations (
  id uuid primary key,
  menu_item_id uuid references menu_items(id),
  restaurant_id uuid references restaurants(id),
  price numeric(10,2),
  currency text default 'USD',
  source_url text,
  observed_at timestamptz default now(),
  confidence numeric(3,2)
);

create table reviews (
  id uuid primary key,
  restaurant_id uuid references restaurants(id),
  source text,
  external_review_id text,
  rating numeric(2,1),
  text text,
  review_date date,
  embedding vector(768),
  search_tsv tsvector generated always as (
    to_tsvector('english', coalesce(text, ''))
  ) stored
);

create table review_summaries (
  id uuid primary key,
  restaurant_id uuid references restaurants(id),
  menu_item_id uuid references menu_items(id),
  summary text,
  positive_signals text[] default '{}',
  negative_signals text[] default '{}',
  value_signal numeric(3,2),
  freshness_at timestamptz default now()
);
```

Indexes:

```sql
create index restaurants_lat_lng_idx on restaurants (latitude, longitude);
create index restaurants_cuisine_idx on restaurants using gin (cuisine_tags);
create index restaurants_meal_idx on restaurants using gin (meal_tags);

create index menu_items_embedding_idx
  on menu_items using hnsw (embedding vector_cosine_ops);
create index menu_items_search_idx on menu_items using gin (search_tsv);
create index menu_items_price_idx on menu_items (price);
create index menu_items_restaurant_idx on menu_items (restaurant_id);

create index reviews_embedding_idx
  on reviews using hnsw (embedding vector_cosine_ops);
create index reviews_search_idx on reviews using gin (search_tsv);
```

## Hybrid Search

Use one tool for hybrid menu search so agents do not manually compose SQL.

Inputs:

```json
{
  "query": "chicken tikka masala",
  "location": "Jersey City, NJ",
  "radius_miles": 5,
  "cuisine_tags": ["Indian"],
  "meal_tags": ["dinner"],
  "max_price": 20,
  "party_size": 4,
  "limit": 10
}
```

Search strategy:

1. Embed the query with the same Gemini embedding model already used in
   `src/adar/db.py`.
2. Use pgvector cosine distance for semantic match.
3. Use Postgres full-text search and trigram similarity for keyword match.
4. Apply deterministic filters: location radius, cuisine, meal, price, open status.
5. Blend scores in SQL or Python:

```text
hybrid_score =
  0.50 semantic_score
+ 0.25 keyword_score
+ 0.10 cuisine_match
+ 0.10 freshness_score
+ 0.05 price_presence_score
```

For exact item queries, increase keyword weight. For broad requests like
"good spicy Indian dinner", increase semantic and review weights.

## Ranking

The final recommendation score should be deterministic:

```text
recommendation_score =
  0.25 menu_match
+ 0.20 price_value
+ 0.20 review_quality
+ 0.15 distance_convenience
+ 0.10 menu_freshness
+ 0.10 user_preference_match
```

The ranking agent may explain and tune intent, but it should call a deterministic
ranking tool for the final score.

## Menu Scraping

Menu ingestion should prefer official and structured sources:

1. Official website menu URL.
2. JSON-LD / schema.org restaurant or menu data.
3. HTML menu sections.
4. PDF menu parsing.
5. OCR for image menus.
6. Approved third-party sources only when terms allow.

Every extracted price needs:

- `source_url`
- `source_type`
- `last_seen_at`
- `extraction_confidence`

Freshness tiers:

| Tier | Rule |
|---|---|
| Fresh | seen within 7 days |
| Acceptable | seen within 30 days |
| Stale | older than 30 days |
| Unknown | no timestamp or low-confidence source |

## Tool Contracts

Keep tools narrow and structured. Agent instructions should choose tools;
tools should do deterministic data work.

| Tool | Purpose |
|---|---|
| `parse_food_request` | Extract location, cuisine, menu item, quantity, budget, meal type |
| `find_restaurants` | Geo and category search |
| `hybrid_search_menu_items` | pgvector + keyword menu search |
| `compare_menu_prices` | Comparable menu item and total-cost comparison |
| `get_restaurant_reviews` | Review snippets and aggregate signals |
| `summarize_review_signals` | Dish-level review summary |
| `check_menu_freshness` | Determine whether scraping is needed |
| `scrape_restaurant_menu` | Fetch and parse a menu from allowed sources |
| `rank_recommendations` | Deterministic scoring and sorting |

## Example Response

```text
Best match: Curry House

Why:
- Chicken tikka masala is $14.99, lowest among the matched nearby Indian menus.
- Estimated total for 4 is $59.96 before tax, tip, and delivery fees.
- Reviews frequently mention large portions and good naan.
- Menu was verified from the restaurant website 2 days ago.

Price comparison:
| Restaurant | Item | Price | Distance | Rating | Menu freshness |
|---|---:|---:|---:|---:|---|
| Curry House | Chicken tikka masala | $14.99 | 1.8 mi | 4.5 | Fresh |
| Delhi Kitchen | Chicken tikka masala | $16.50 | 2.4 mi | 4.4 | Acceptable |
| Masala Grill | Chicken tikka masala | $18.00 | 1.1 mi | 4.6 | Fresh |
```

## Incremental Implementation Plan

1. Add `restaurants` domain scaffold and `agents_config.restaurants.json`.
2. Add Postgres connection helper for restaurant domain.
3. Add schema migration SQL for restaurants, menus, prices, and reviews.
4. Implement `parse_food_request` with a deterministic Pydantic output model.
5. Implement `find_restaurants` using latitude/longitude radius filtering.
6. Implement `hybrid_search_menu_items` with pgvector + full-text search.
7. Implement `compare_menu_prices` and `rank_recommendations`.
8. Add menu scraping pipeline for official websites.
9. Add review ingestion and summary tools.
10. Add tests using seeded restaurants and menus.
