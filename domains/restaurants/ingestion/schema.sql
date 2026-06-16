create extension if not exists vector;
create extension if not exists pg_trgm;
create extension if not exists pgcrypto;

create table if not exists restaurants (
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

create table if not exists menu_items (
  id uuid primary key,
  restaurant_id uuid references restaurants(id) on delete cascade,
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
  last_seen_at timestamptz default now(),
  embedding vector(768),
  search_tsv tsvector,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists menu_sources (
  id uuid primary key default gen_random_uuid(),
  restaurant_id uuid references restaurants(id) on delete cascade,
  source_url text not null,
  source_type text not null default 'website',
  status text not null default 'pending',
  confidence numeric(3,2),
  notes text,
  discovered_by text default 'system',
  last_checked_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (restaurant_id, source_url)
);

create table if not exists menu_scrape_attempts (
  id uuid primary key default gen_random_uuid(),
  restaurant_id uuid references restaurants(id) on delete cascade,
  source_url text not null,
  source_type text,
  fetch_mode text,
  status text not null,
  http_status integer,
  items_found integer default 0,
  prices_found integer default 0,
  error text,
  attempted_at timestamptz default now()
);

create table if not exists menu_curation_queue (
  id uuid primary key default gen_random_uuid(),
  restaurant_id uuid references restaurants(id) on delete cascade,
  source_url text,
  reason text not null,
  status text not null default 'open',
  priority integer default 2,
  details jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (restaurant_id, source_url, reason)
);

create table if not exists price_observations (
  id uuid primary key default gen_random_uuid(),
  menu_item_id uuid references menu_items(id) on delete cascade,
  restaurant_id uuid references restaurants(id) on delete cascade,
  price numeric(10,2),
  currency text default 'USD',
  source_url text,
  observed_at timestamptz default now(),
  confidence numeric(3,2),
  unique (menu_item_id, price, source_url, observed_at)
);

create table if not exists reviews (
  id uuid primary key,
  restaurant_id uuid references restaurants(id) on delete cascade,
  source text,
  external_review_id text,
  rating numeric(2,1),
  text text,
  review_date date,
  embedding vector(768),
  search_tsv tsvector,
  created_at timestamptz default now()
);

create table if not exists review_summaries (
  id uuid primary key default gen_random_uuid(),
  restaurant_id uuid references restaurants(id) on delete cascade,
  menu_item_id uuid references menu_items(id) on delete set null,
  summary text,
  positive_signals text[] default '{}',
  negative_signals text[] default '{}',
  value_signal numeric(3,2),
  freshness_at timestamptz default now()
);

create table if not exists menu_feedback (
  id uuid primary key default gen_random_uuid(),
  restaurant_id uuid references restaurants(id) on delete cascade,
  menu_item_id uuid references menu_items(id) on delete set null,
  feedback_type text not null,
  user_message text,
  suggested_name text,
  suggested_price numeric(10,2),
  suggested_source_url text,
  status text not null default 'open',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists restaurants_lat_lng_idx on restaurants (latitude, longitude);
create index if not exists restaurants_cuisine_idx on restaurants using gin (cuisine_tags);
create index if not exists restaurants_meal_idx on restaurants using gin (meal_tags);
create index if not exists restaurants_name_trgm_idx on restaurants using gin (normalized_name gin_trgm_ops);

create index if not exists menu_items_search_idx on menu_items using gin (search_tsv);
create index if not exists menu_items_name_trgm_idx on menu_items using gin (normalized_name gin_trgm_ops);
create index if not exists menu_items_price_idx on menu_items (price);
create index if not exists menu_items_restaurant_idx on menu_items (restaurant_id);
create index if not exists menu_sources_restaurant_idx on menu_sources (restaurant_id);
create index if not exists menu_sources_status_idx on menu_sources (status);
create index if not exists menu_scrape_attempts_restaurant_idx on menu_scrape_attempts (restaurant_id);
create index if not exists menu_curation_queue_status_idx on menu_curation_queue (status, priority);
create index if not exists menu_feedback_status_idx on menu_feedback (status, feedback_type);

create index if not exists reviews_search_idx on reviews using gin (search_tsv);

do $$
begin
  if not exists (
    select 1 from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where c.relname = 'menu_items_embedding_idx'
      and n.nspname = 'public'
  ) then
    create index menu_items_embedding_idx
      on menu_items using hnsw (embedding vector_cosine_ops);
  end if;

  if not exists (
    select 1 from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where c.relname = 'reviews_embedding_idx'
      and n.nspname = 'public'
  ) then
    create index reviews_embedding_idx
      on reviews using hnsw (embedding vector_cosine_ops);
  end if;
end $$;
