#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

CURATION_EXPORT_PATH="${CURATION_EXPORT_PATH:-domains/restaurants/data/curation_queue.csv}"

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
  --only export-curation \
  --curation-export-path "$CURATION_EXPORT_PATH"

