#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

RESTAURANT_NAME="${RESTAURANT_NAME:-}"
WEBSITE_URL="${WEBSITE_URL:-}"
LINK_OUTPUT="${LINK_OUTPUT:-domains/restaurants/data/website_links.csv}"

export MENU_DISCOVERY_MODE="${MENU_DISCOVERY_MODE:-browser}"

ARGS=(--only inspect-links --link-output "$LINK_OUTPUT")
if [[ -n "$WEBSITE_URL" ]]; then
  ARGS+=(--website-url "$WEBSITE_URL")
elif [[ -n "$RESTAURANT_NAME" ]]; then
  ARGS+=(--restaurant-name "$RESTAURANT_NAME")
else
  echo "Set WEBSITE_URL or RESTAURANT_NAME" >&2
  exit 1
fi

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion "${ARGS[@]}"
