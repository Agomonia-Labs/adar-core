#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

REVIEWS_SOURCE="${REVIEWS_SOURCE:-domains/restaurants/data/sample_reviews.json}"

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
  --only reviews \
  --reviews-source "$REVIEWS_SOURCE"

