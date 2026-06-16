#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Ingest Greater Seattle restaurants into the restaurant recommender database.

Usage:
  domains/restaurants/ingestion/ingest_greater_seattle.sh [options]

Options:
  --env-file PATH          Env file to load. Default: .env.restaurants
  --radius-miles N         Discovery radius around Seattle. Default: 60
  --tile-radius-miles N    Google Places tile radius. Default: 25
  --place-types LIST       Comma-separated Google place types.
  --full                   Use the full default place type list from Python ingestion.
  --schema                 Apply schema before discovery.
  --embeddings             Run menu embeddings after discovery.
  --help                   Show this help.

Default place types:
  indian_restaurant,thai_restaurant,italian_restaurant,american_restaurant,
  chinese_restaurant,japanese_restaurant,mexican_restaurant,korean_restaurant,
  vietnamese_restaurant,fast_food_restaurant

Examples:
  # Cheap smoke test
  domains/restaurants/ingestion/ingest_greater_seattle.sh \
    --radius-miles 5 \
    --place-types indian_restaurant

  # Recommended genre discovery pass
  domains/restaurants/ingestion/ingest_greater_seattle.sh --schema

  # Broader discovery using all configured place types
  domains/restaurants/ingestion/ingest_greater_seattle.sh --full
EOF
}

ENV_FILE=".env.restaurants"
RADIUS_MILES="60"
TILE_RADIUS_MILES="25"
PLACE_TYPES="indian_restaurant,thai_restaurant,italian_restaurant,american_restaurant,chinese_restaurant,japanese_restaurant,mexican_restaurant,korean_restaurant,vietnamese_restaurant,fast_food_restaurant"
APPLY_SCHEMA="false"
RUN_EMBEDDINGS="false"
USE_FULL="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="${2:?--env-file requires a path}"
      shift 2
      ;;
    --radius-miles)
      RADIUS_MILES="${2:?--radius-miles requires a value}"
      shift 2
      ;;
    --tile-radius-miles)
      TILE_RADIUS_MILES="${2:?--tile-radius-miles requires a value}"
      shift 2
      ;;
    --place-types)
      PLACE_TYPES="${2:?--place-types requires a comma-separated list}"
      shift 2
      ;;
    --full)
      USE_FULL="true"
      shift
      ;;
    --schema)
      APPLY_SCHEMA="true"
      shift
      ;;
    --embeddings)
      RUN_EMBEDDINGS="true"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file not found: $ENV_FILE" >&2
  echo "Create one with: cp .env.restaurants.example .env.restaurants" >&2
  exit 1
fi

export DOTENV_FILE="$ENV_FILE"
export DOMAIN="${DOMAIN:-restaurants}"
export PYTHONPATH="${PYTHONPATH:-$(pwd)}"

PYTHON_BIN="${PYTHON_BIN:-python}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

if [[ "$APPLY_SCHEMA" == "true" ]]; then
  echo "==> Applying restaurant schema"
  "$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion --only schema
fi

echo "==> Discovering Greater Seattle restaurants"
echo "    radius: ${RADIUS_MILES} miles"
echo "    tile radius: ${TILE_RADIUS_MILES} miles"
if [[ "$USE_FULL" == "true" ]]; then
  echo "    place types: full default list from Python ingestion"
  "$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
    --only places \
    --location greater-seattle \
    --radius-miles "$RADIUS_MILES" \
    --tile-radius-miles "$TILE_RADIUS_MILES"
else
  echo "    place types: ${PLACE_TYPES}"
  "$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
    --only places \
    --location greater-seattle \
    --radius-miles "$RADIUS_MILES" \
    --tile-radius-miles "$TILE_RADIUS_MILES" \
    --place-types "$PLACE_TYPES"
fi

if [[ "$RUN_EMBEDDINGS" == "true" ]]; then
  echo "==> Embedding missing menu items"
  "$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion --only embeddings
fi

echo "==> Done"

