#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

CUISINE="${CUISINE:-thai}"
LIMIT="${LIMIT:-25}"
MAX_MENU_PAGES="${MAX_MENU_PAGES:-8}"
MIN_PRICES="${MIN_PRICES:-1}"
MAX_URLS="${MAX_URLS:-}"
MENU_TEST_OUTPUT="${MENU_TEST_OUTPUT:-domains/restaurants/data/${CUISINE}_menu_source_test.csv}"

export MENU_DISCOVERY_MODE="${MENU_DISCOVERY_MODE:-browser}"
export MENU_FETCH_MODE="${MENU_FETCH_MODE:-browser}"
export MENU_BROWSER_OCR_FALLBACK="${MENU_BROWSER_OCR_FALLBACK:-true}"

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
  --only test-menus \
  --cuisine "$CUISINE" \
  --limit "$LIMIT" \
  --max-menu-pages "$MAX_MENU_PAGES" \
  --menu-test-output "$MENU_TEST_OUTPUT"

INGEST_ARGS=(
  --only ingest-tested-menus
  --menu-test-output "$MENU_TEST_OUTPUT"
  --min-prices "$MIN_PRICES"
  --cuisine "$CUISINE"
)
if [[ -n "$MAX_URLS" ]]; then
  INGEST_ARGS+=(--max-urls "$MAX_URLS")
fi

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion "${INGEST_ARGS[@]}"

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
  --only embeddings
