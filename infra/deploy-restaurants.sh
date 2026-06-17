#!/bin/bash
# infra/deploy-restaurants.sh
# Builds and deploys the Restaurant Recommender API to Cloud Run.
#
# Prerequisites:
#   1. gcloud auth login
#   2. gcloud auth configure-docker us-central1-docker.pkg.dev
#   3. Artifact Registry repository exists: us-central1-docker.pkg.dev/<project>/adar
#   4. A production Postgres database is available with restaurant schema applied.
#   5. A production Postgres session database is available for ADK sessions.
#   6. Secret Manager contains the required restaurant secrets listed below.
#
# Usage:
#   bash infra/deploy-restaurants.sh
#
# Optional overrides:
#   PROJECT_ID=your-project REGION=us-central1 SERVICE=adar-restaurants-api \
#   SQL_INSTANCE=your-project:us-central1:your-sql-instance \
#   bash infra/deploy-restaurants.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-bdas-493785}"
REGION="${REGION:-us-central1}"
REGISTRY="${REGISTRY:-${REGION}-docker.pkg.dev/${PROJECT_ID}/adar}"
IMAGE="${IMAGE:-${REGISTRY}/restaurants-api:latest}"
SERVICE="${SERVICE:-adar-restaurants-api}"
SA="${SA:-adar-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
SQL_INSTANCE="${SQL_INSTANCE:-${PROJECT_ID}:${REGION}:adar-pgdev}"

echo "Building Restaurant Recommender image..."
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
  --memory 2Gi \
  --cpu 1 \
  --port 8040 \
  --service-account "${SA}" \
  --add-cloudsql-instances "${SQL_INSTANCE}" \
  --set-env-vars "APP_NAME=adar-restaurants-api,APP_ENV=production,GCP_PROJECT_ID=${PROJECT_ID},DOMAIN=restaurants,AUTH_FIRESTORE_DATABASE=tigers-arcl,ADK_MODEL=gemini-2.5-flash,EVAL_ENABLED=true,BILLING_ENABLED=false" \
  --set-secrets "GOOGLE_API_KEY=google-api-key:latest,RESTAURANTS_DATABASE_URL=restaurants-database-url:latest,SESSION_DB_URL=restaurants-session-db-url:latest,RESTAURANTS_API_KEY=restaurants-api-key:latest,JWT_SECRET=restaurants-jwt-secret:latest,ADMIN_EMAIL=restaurants-admin-email:latest,ADMIN_PASSWORD=restaurants-admin-password:latest,FRONTEND_URL=restaurants-frontend-url:latest,GOOGLE_PLACES_API_KEY=restaurants-google-places-api-key:latest,STRIPE_SECRET_KEY=stripe-secret-key:latest,STRIPE_WEBHOOK_SECRET=restaurants-stripe-webhook-secret:latest,STRIPE_PRICE_RESTAURANTS=stripe-price-restaurants:latest"

URL=$(gcloud run services describe "${SERVICE}" \
  --region "${REGION}" \
  --format "value(status.url)")

echo ""
echo "Deployed: ${URL}"
echo ""
echo "Smoke test:"
echo "  curl ${URL}/health"
