#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

LIMIT="${LIMIT:-25}"
MAX_MENU_PAGES="${MAX_MENU_PAGES:-3}"
REFRESH_FLAG="${REFRESH_FLAG:-}"
export MENU_DISCOVERY_MODE="${MENU_DISCOVERY_MODE:-http}"
export MENU_FETCH_MODE="${MENU_FETCH_MODE:-http}"

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
  --only bulk-menus \
  --limit "$LIMIT" \
  --max-menu-pages "$MAX_MENU_PAGES" \
  $REFRESH_FLAG
