#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

CUISINE="${CUISINE:-thai}"
LIMIT="${LIMIT:-10}"
MAX_MENU_PAGES="${MAX_MENU_PAGES:-6}"
MENU_TEST_OUTPUT="${MENU_TEST_OUTPUT:-domains/restaurants/data/menu_source_test.csv}"

export MENU_DISCOVERY_MODE="${MENU_DISCOVERY_MODE:-browser}"
export MENU_FETCH_MODE="${MENU_FETCH_MODE:-browser}"

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
  --only test-menus \
  --cuisine "$CUISINE" \
  --limit "$LIMIT" \
  --max-menu-pages "$MAX_MENU_PAGES" \
  --menu-test-output "$MENU_TEST_OUTPUT"
