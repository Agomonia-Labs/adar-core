#!/bin/bash
# infra/deploy-geetabitan.sh
# Builds the Geetabitan Docker image and deploys to Cloud Run.
# ARCL deployment (deploy.sh) is completely unaffected.
#
# Prerequisites:
#   1. gcloud auth login && gcloud auth configure-docker us-central1-docker.pkg.dev
#   2. GCP secrets created (run infra/create_geetabitan_secrets.sh first)
#   3. Firestore geetabitan-db created + vector index built
#   4. Cloud SQL database created:
#        gcloud sql connect adar-pgdev --user=postgres
#        CREATE DATABASE geetabitan_sessions;
#        CREATE USER geetabitan_user WITH PASSWORD '...';
#        GRANT ALL PRIVILEGES ON DATABASE geetabitan_sessions TO geetabitan_user;
#
# Usage:
#   bash infra/deploy-geetabitan.sh

set -euo pipefail

PROJECT_ID="bdas-493785"
REGION="us-central1"
REGISTRY="us-central1-docker.pkg.dev/${PROJECT_ID}/adar"
IMAGE="${REGISTRY}/geetabitan-api:latest"
SERVICE="adar-geetabitan-api"
SA="adar-sa@${PROJECT_ID}.iam.gserviceaccount.com"
SQL_INSTANCE="${PROJECT_ID}:${REGION}:adar-pgdev"

# ── Session DB URL ────────────────────────────────────────────────────────────
# Fetch DB password from Secret Manager so it never appears as a plain
# env var in the deploy command (avoids zsh glob issues with ? character).
# Falls back to SQLite if the secret doesn't exist yet.
# Using SQLite for sessions — JWT tokens are stateless so session resets on
# container restart don't affect logged-in users (token is in the browser).
# Switch to Cloud SQL only if you need persistent cross-instance sessions.
SESSION_DB_URL="sqlite+aiosqlite:////tmp/geetabitan_sessions.db"
echo "✓ Using SQLite for sessions"

echo "▶ Building Geetabitan image …"
docker build \
    --platform linux/amd64 \
    -f Dockerfile.geetabitan \
    -t "${IMAGE}" \
    .

echo "▶ Pushing image …"
docker push "${IMAGE}"

echo "▶ Deploying Cloud Run service: ${SERVICE} …"
gcloud run deploy "${SERVICE}" \
    --image              "${IMAGE}" \
    --region             "${REGION}" \
    --platform           managed \
    --allow-unauthenticated \
    --min-instances      0 \
    --max-instances      3 \
    --memory             1Gi \
    --cpu                1 \
    --port               8040 \
    --service-account    "${SA}" \
    --add-cloudsql-instances "${SQL_INSTANCE}" \
    --set-env-vars        "APP_NAME=adar-geetabitan-api,APP_ENV=production,GCP_PROJECT_ID=${PROJECT_ID},DOMAIN=geetabitan,FIRESTORE_DATABASE=geetabitan-db,AUTH_FIRESTORE_DATABASE=geetabitan-db,ADK_MODEL=gemini-2.5-flash,EVAL_ENABLED=true,SESSION_DB_URL=${SESSION_DB_URL}" \
    --set-secrets         "GOOGLE_API_KEY=google-api-key:latest,GEETABITAN_API_KEY=geetabitan-api-key:latest,JWT_SECRET=geetabitan-jwt-secret:latest,ADMIN_EMAIL=geetabitan-admin-email:latest,ADMIN_PASSWORD=geetabitan-admin-password:latest,STRIPE_SECRET_KEY=stripe-secret-key:latest,STRIPE_WEBHOOK_SECRET=geetabitan-stripe-webhook-secret:latest,STRIPE_PRICE_BASIC=geetabitan-stripe-price-basic:latest,STRIPE_PRICE_STANDARD=geetabitan-stripe-price-standard:latest,STRIPE_PRICE_UNLIMITED=geetabitan-stripe-price-unlimited:latest,FRONTEND_URL=geetabitan-frontend-url:latest,GEETABITAN_TTS_API_KEY=geetabitan-tts-api-key:latest,GEETABITAN_SPEECH_API_KEY=geetabitan-speech-api-key:latest"

echo ""
URL=$(gcloud run services describe "${SERVICE}" \
  --region="${REGION}" \
  --format="value(status.url)")
echo "✅ Deployed: ${URL}"
echo ""
echo "Smoke test:"
echo "  curl ${URL}/health"
echo ""
echo "Custom domain (if not already mapped):"
echo "  gcloud beta run domain-mappings create \\"
echo "    --service ${SERVICE} \\"
echo "    --domain  geetabitan.adar.agomoniai.com \\"
echo "    --region  ${REGION}"