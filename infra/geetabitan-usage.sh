#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-bdas-493785}"
SERVICE_NAME="${SERVICE_NAME:-adar-geetabitan-api}"
MAX_RESULTS="${MAX_RESULTS:-100000}"
REPORT_TIMEZONE="${REPORT_TIMEZONE:-America/Los_Angeles}"

command -v gcloud >/dev/null || {
  echo "gcloud is required." >&2
  exit 1
}

base_filter="resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND httpRequest.requestUrl:\"/api/geetabitan/guest/\" AND NOT httpRequest.requestMethod=\"OPTIONS\""

printf '%-12s %10s %10s %10s %10s %10s\n' \
  "Window" "API hits" "Sessions" "Questions" "Voice" "Errors"
printf '%-12s %10s %10s %10s %10s %10s\n' \
  "------------" "----------" "----------" "----------" "----------" "----------"

report_window() {
  local label="$1"
  local freshness="$2"
  local rows

  rows="$(
    gcloud logging read "$base_filter" \
      --project="$PROJECT_ID" \
      --freshness="$freshness" \
      --limit="$MAX_RESULTS" \
      --format='value(httpRequest.requestMethod,httpRequest.requestUrl,httpRequest.status)'
  )"

  awk -F '\t' -v label="$label" '
    NF {
      hits++
      if ($2 ~ /\/api\/geetabitan\/guest\/session$/ && $1 == "POST") sessions++
      if ($2 ~ /\/api\/geetabitan\/guest\/chat$/ && $1 == "POST") questions++
      if ($2 ~ /\/api\/geetabitan\/guest\/(tts|stt)$/ && $1 == "POST") voice++
      if (($3 + 0) >= 400) errors++
    }
    END {
      printf "%-12s %10d %10d %10d %10d %10d\n", label, hits, sessions, questions, voice, errors
    }
  ' <<< "$rows"
}

report_window "Last hour" "1h"
report_window "Last day" "24h"
report_window "Last week" "7d"
report_window "Last month" "30d"

daily_rows="$(mktemp)"
trap 'rm -f "$daily_rows"' EXIT
gcloud logging read "$base_filter" \
  --project="$PROJECT_ID" \
  --freshness="8d" \
  --limit="$MAX_RESULTS" \
  --format='value(timestamp,httpRequest.requestMethod,httpRequest.requestUrl,httpRequest.status)' \
  > "$daily_rows"

printf '\nDaily breakdown for the last 7 calendar days (%s)\n' "$REPORT_TIMEZONE"
python3 - "$REPORT_TIMEZONE" "$daily_rows" <<'PY'
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

timezone = ZoneInfo(sys.argv[1])
rows_path = Path(sys.argv[2])
today = datetime.now(timezone).date()
days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
totals = defaultdict(lambda: {
    "hits": 0,
    "sessions": 0,
    "questions": 0,
    "voice": 0,
    "errors": 0,
})

for row in rows_path.read_text(encoding="utf-8").splitlines():
    fields = row.split("\t")
    if len(fields) < 4:
        continue
    timestamp, method, url, status = fields[:4]
    try:
        occurred_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        day = occurred_at.astimezone(timezone).date()
        status_code = int(status)
    except (TypeError, ValueError):
        continue
    if day not in days:
        continue
    values = totals[day]
    values["hits"] += 1
    if method == "POST" and url.endswith("/api/geetabitan/guest/session"):
        values["sessions"] += 1
    if method == "POST" and url.endswith("/api/geetabitan/guest/chat"):
        values["questions"] += 1
    if method == "POST" and url.endswith(("/api/geetabitan/guest/tts", "/api/geetabitan/guest/stt")):
        values["voice"] += 1
    if status_code >= 400:
        values["errors"] += 1

print(f'{"Date":<12} {"API hits":>10} {"Sessions":>10} {"Questions":>10} {"Voice":>10} {"Errors":>10}')
print(f'{"------------":<12} {"----------":>10} {"----------":>10} {"----------":>10} {"----------":>10} {"----------":>10}')
for day in days:
    values = totals[day]
    print(
        f'{day.isoformat():<12} {values["hits"]:>10} {values["sessions"]:>10} '
        f'{values["questions"]:>10} {values["voice"]:>10} {values["errors"]:>10}'
    )
PY

cat <<'EOF'

Cloud Monitoring metrics (data is collected from the metric creation time):
  logging.googleapis.com/user/adar_geetabitan_api_hits
  logging.googleapis.com/user/adar_geetabitan_sessions
  logging.googleapis.com/user/adar_geetabitan_questions
  logging.googleapis.com/user/adar_geetabitan_voice_requests

The report counts API activity, not unique people. Use GA4 after linking the
Firebase project to measure page visitors, approximate country, and retention.
EOF
