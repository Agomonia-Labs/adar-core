#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

"$PYTHON_BIN" -m domains.restaurants.ingestion.verify_ingestion

