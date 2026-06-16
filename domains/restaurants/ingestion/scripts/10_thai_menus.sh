#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

LIMIT="${LIMIT:-25}"
MAX_MENU_PAGES="${MAX_MENU_PAGES:-6}"

export MENU_DISCOVERY_MODE="${MENU_DISCOVERY_MODE:-browser}"
export MENU_FETCH_MODE="${MENU_FETCH_MODE:-browser}"

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
  --only menus \
  --cuisine thai \
  --limit "$LIMIT" \
  --max-menu-pages "$MAX_MENU_PAGES"
