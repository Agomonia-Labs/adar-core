#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

bash "$SCRIPT_DIR/01_schema.sh"
bash "$SCRIPT_DIR/02_places_greater_seattle.sh"
bash "$SCRIPT_DIR/03_bulk_menus.sh"
bash "$SCRIPT_DIR/09_export_curation.sh"
bash "$SCRIPT_DIR/05_embeddings.sh"
bash "$SCRIPT_DIR/06_verify.sh"
