#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env.restaurants}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file not found: $ENV_FILE" >&2
  echo "Create one with: cp .env.restaurants.example .env.restaurants" >&2
  exit 1
fi

export DOTENV_FILE="$ENV_FILE"
export DOMAIN="${DOMAIN:-restaurants}"
export PYTHONPATH="${PYTHONPATH:-$(pwd)}"

PYTHON_BIN="${PYTHON_BIN:-python}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

