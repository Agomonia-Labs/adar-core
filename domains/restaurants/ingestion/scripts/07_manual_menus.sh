#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

MANUAL_MENU_SOURCE="${MANUAL_MENU_SOURCE:-domains/restaurants/data/manual_menu_urls.json}"
export MENU_DISCOVERY_MODE="${MENU_DISCOVERY_MODE:-http}"
export MENU_FETCH_MODE="${MENU_FETCH_MODE:-http}"

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
  --only manual-menus \
  --manual-menu-source "$MANUAL_MENU_SOURCE"

