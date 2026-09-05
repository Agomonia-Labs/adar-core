#!/bin/bash
# infra/deploy-scheduling.sh
# Builds and deploys the Scheduling API to Cloud Run.
#
# Prerequisites:
#   1. gcloud auth login && gcloud auth configure-docker us-central1-docker.pkg.dev
#   2. GCP secrets created — run infra/create_scheduling_secrets.sh first
#   3. Firestore database adar-scheduling-db created:
#        gcloud firestore databases create --database=adar-scheduling-db \
#          --location=us-central1 --type=firestore-native --project=bdas-493785
#   4. A practice seeded into that database (run_ingestion.py) — see the
#      "First deploy only" note below.
#
# Reuses existing shared secrets rather than creating scheduling-specific
# copies: google-api-key (Gemini), gmail-user / gmail-app-password / from-email
# (booking-confirmation + OTP emails), geetabitan-tts-api-key /
# geetabitan-speech-api-key (voice — same Google Cloud API keys every other
# domain's voice mode already uses; the env var names are geetabitan-named
# but the code checks them for every domain, see api/main.py).
#
# SCHEDULING_DEFAULT_PRACTICE_ID below is a real deploy parameter, not a
# separate manual step — every deploy sets it explicitly (via
# --update-env-vars, so nothing else you've set on the service gets
# clobbered), so it can never again silently go missing after a redeploy the
# way it did when this was a one-off `gcloud run services update` command
# run by hand once and never again. The default is the practice_id
# run_ingestion.py printed for the seeded "Riverside Family Medicine" demo
# data. When you seed a real practice, either edit the default below or pass
# SCHEDULING_DEFAULT_PRACTICE_ID as an override (see Usage).
#
# Usage:
#   bash infra/deploy-scheduling.sh
#
# Optional overrides:
#   PROJECT_ID=your-project REGION=us-central1 SERVICE=adar-scheduling-api \
#   SCHEDULING_DEFAULT_PRACTICE_ID=<practice_id> \
#   bash infra/deploy-scheduling.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-bdas-493785}"
REGION="${REGION:-us-central1}"
REGISTRY="${REGISTRY:-${REGION}-docker.pkg.dev/${PROJECT_ID}/adar}"
IMAGE="${IMAGE:-${REGISTRY}/scheduling-api:latest}"
SERVICE="${SERVICE:-adar-scheduling-api}"
SA="${SA:-adar-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
SCHEDULING_DEFAULT_PRACTICE_ID="${SCHEDULING_DEFAULT_PRACTICE_ID:-e1WJrKlyup70ocTA5yGY}"

# ── Observability (off by default — see the observability plan doc) ────────
# To turn on: point OTEL_EXPORTER_OTLP_ENDPOINT at the shared Collector
# adar-rag already deploys ("docintel-otel-collector"), e.g.:
#   OTEL_ENDPOINT="$(gcloud run services describe docintel-otel-collector \
#     --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
#   OTEL_ENABLED=true bash infra/deploy-scheduling.sh
# TRACE_DB_URL (Postgres trace store, Phase 3 of the plan) is a separate,
# still-open provisioning decision — pass it as an override the same way
# once a Cloud SQL instance/schema exists, ideally via --update-secrets
# rather than plaintext env vars.
OTEL_ENABLED="${OTEL_ENABLED:-false}"
OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-}"
# Reuses the SAME Cloud SQL instance restaurants/geetabitan already attach
# via --add-cloudsql-instances below (see infra/deploy-restaurants.sh /
# deploy-geetabitan.sh) — no new instance needed, just a new database/schema
# on it for the trace tables. TRACE_DB_URL itself is a secret (see
# infra/create_scheduling_secrets.sh), not a plaintext env var, once real.
SQL_INSTANCE="${SQL_INSTANCE:-${PROJECT_ID}:${REGION}:adar-pgdev}"

echo "Building Scheduling image..."
docker build \
  --platform linux/amd64 \
  -f Dockerfile \
  -t "${IMAGE}" \
  .

echo "Pushing image..."
docker push "${IMAGE}"

echo "Deploying Cloud Run service: ${SERVICE}..."
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 3 \
  --memory 1Gi \
  --cpu 1 \
  --port 8040 \
  --service-account "${SA}" \
  --update-env-vars "APP_NAME=adar-scheduling-api,APP_ENV=production,GCP_PROJECT_ID=${PROJECT_ID},DOMAIN=scheduling,FIRESTORE_DATABASE=adar-scheduling-db,AUTH_FIRESTORE_DATABASE=adar-scheduling-db,ADK_MODEL=gemini-2.5-flash,EVAL_ENABLED=true,BILLING_ENABLED=false,SESSION_DB_URL=sqlite+aiosqlite:////tmp/scheduling_sessions.db,FRONTEND_URL=https://scheduling.adar.agomoniai.com,SCHEDULING_DEFAULT_PRACTICE_ID=${SCHEDULING_DEFAULT_PRACTICE_ID},OTEL_ENABLED=${OTEL_ENABLED},OTEL_SERVICE_NAME=adar-core-scheduling,OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT}" \
  --add-cloudsql-instances "${SQL_INSTANCE}" \
  --update-secrets "GOOGLE_API_KEY=google-api-key:latest,JWT_SECRET=scheduling-jwt-secret:latest,ADMIN_EMAIL=scheduling-admin-email:latest,ADMIN_PASSWORD=scheduling-admin-password:latest,SCHEDULING_API_KEY=scheduling-api-key:latest,GMAIL_USER=gmail-user:latest,GMAIL_APP_PASSWORD=gmail-app-password:latest,NOTIFY_FROM_EMAIL=from-email:latest,GEETABITAN_TTS_API_KEY=geetabitan-tts-api-key:latest,GEETABITAN_SPEECH_API_KEY=geetabitan-speech-api-key:latest,TRACE_DB_URL=scheduling-trace-db-url:latest"

URL=$(gcloud run services describe "${SERVICE}" \
  --region "${REGION}" \
  --format "value(status.url)")

echo ""
echo "Deployed: ${URL}"
echo ""
echo "Smoke test:"
echo "  curl ${URL}/health"
echo ""
echo "Currently deployed with SCHEDULING_DEFAULT_PRACTICE_ID=${SCHEDULING_DEFAULT_PRACTICE_ID}"
echo ""
echo "Seeding a different/real practice? Run ingestion, then redeploy with the"
echo "printed ID as an override — no separate 'services update' step needed:"
echo "  DOMAIN=scheduling PYTHONPATH=\$(pwd) GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json \\"
echo "    python -m domains.scheduling.ingestion.run_ingestion --file <your-practice.json>"
echo "  SCHEDULING_DEFAULT_PRACTICE_ID=<printed practice_id> bash infra/deploy-scheduling.sh"
echo "  # (or just edit the default at the top of this script so you don't have"
echo "  #  to pass the override every time)"
echo ""
echo "Custom domain (if not already mapped):"
echo "  gcloud beta run domain-mappings create \\"
echo "    --service ${SERVICE} \\"
echo "    --domain  api.scheduling.adar.agomoniai.com \\"
echo "    --region  ${REGION}"
