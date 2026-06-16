#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

LIMIT="${LIMIT:-100}"

"$PYTHON_BIN" -m domains.restaurants.ingestion.run_ingestion \
  --only embeddings \
  --limit "$LIMIT"

