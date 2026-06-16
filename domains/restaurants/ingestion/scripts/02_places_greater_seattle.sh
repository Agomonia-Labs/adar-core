#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

RADIUS_MILES="${RADIUS_MILES:-60}"
TILE_RADIUS_MILES="${TILE_RADIUS_MILES:-25}"
PLACE_TYPES="${PLACE_TYPES:-indian_restaurant,thai_restaurant,italian_restaurant,american_restaurant,chinese_restaurant,japanese_restaurant,mexican_restaurant,korean_restaurant,vietnamese_restaurant,fast_food_restaurant}"

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
  --only places \
  --location greater-seattle \
  --radius-miles "$RADIUS_MILES" \
  --tile-radius-miles "$TILE_RADIUS_MILES" \
  --place-types "$PLACE_TYPES"

