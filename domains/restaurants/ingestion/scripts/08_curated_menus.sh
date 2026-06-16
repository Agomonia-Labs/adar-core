#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

CURATED_MENU_SOURCE="${CURATED_MENU_SOURCE:-domains/restaurants/data/curated_menu_items.csv}"

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
  --only curated-menus \
  --curated-menu-source "$CURATED_MENU_SOURCE"

