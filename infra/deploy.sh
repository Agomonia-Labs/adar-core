#!/bin/bash
set -euo pipefail

PROJECT_ID="bdas-493785"
REGION="us-central1"
SERVICE="adar-arcl-api"
SA="adar-sa@${PROJECT_ID}.iam.gserviceaccount.com"
SQL_INSTANCE="${PROJECT_ID}:${REGION}:adar-pgdev"
TRACE_DB_SECRET="${TRACE_DB_SECRET:-scheduling-trace-db-url}"

echo "Building Docker image..."
docker build --platform linux/amd64 \
  -t "us-central1-docker.pkg.dev/${PROJECT_ID}/adar/arcl-api:latest" \
  .

echo "Pushing to Artifact Registry..."
docker push "us-central1-docker.pkg.dev/${PROJECT_ID}/adar/arcl-api:latest"

echo "Deploying to Cloud Run..."
gcloud run deploy "${SERVICE}" \
  --image "us-central1-docker.pkg.dev/${PROJECT_ID}/adar/arcl-api:latest" \
  --region "${REGION}" \
  --platform managed \
  --service-account "${SA}" \
  --add-cloudsql-instances "${SQL_INSTANCE}" \
  --update-env-vars "ARCL_GUEST_ACCESS_ENABLED=${ARCL_GUEST_ACCESS_ENABLED:-true},ARCL_GUEST_VOICE_ENABLED=${ARCL_GUEST_VOICE_ENABLED:-true}" \
  --update-secrets "TRACE_DB_URL=${TRACE_DB_SECRET}:latest"

echo "Done."
