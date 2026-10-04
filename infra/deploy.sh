#!/bin/bash
set -euo pipefail

PROJECT_ID="bdas-493785"
REGION="us-central1"
SERVICE="adar-arcl-api"
SA="adar-sa@${PROJECT_ID}.iam.gserviceaccount.com"
SQL_INSTANCE="${PROJECT_ID}:${REGION}:adar-pgdev"
TRACE_DB_SECRET="${TRACE_DB_SECRET:-scheduling-trace-db-url}"
# Mobile app now supports self-service account creation (no more
# guest-only mode) -- ARCL still has real Stripe billing wired up
# (register() defaults new accounts to "pending_payment" when this is
# true, see api/routes/auth.py), but there's no in-app way to pay yet
# (no Stripe checkout, no IAP), so a mobile signup would otherwise be
# stuck unable to use the app it just created an account in. Turning
# billing off here makes every new account (including App Store
# reviewer's) land "active" immediately -- a deliberate product choice,
# not just an App Review workaround, so this also applies to real
# customers who sign up from the app. Flip back to true (or omit) once
# an in-app payment path exists.
BILLING_ENABLED="${BILLING_ENABLED:-false}"
# App Store reviewer account -- skips OTP entirely for this email so App
# Review can sign in with just email+password (no inbox access), same
# mechanism as ADAR Front Desk (infra/deploy-scheduling.sh).
MFA_BYPASS_EMAILS="${MFA_BYPASS_EMAILS:-applereview@agomoniai.com}"

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
  --update-env-vars "ARCL_GUEST_ACCESS_ENABLED=${ARCL_GUEST_ACCESS_ENABLED:-true},ARCL_GUEST_VOICE_ENABLED=${ARCL_GUEST_VOICE_ENABLED:-true},BILLING_ENABLED=${BILLING_ENABLED},MFA_BYPASS_EMAILS=${MFA_BYPASS_EMAILS}" \
  --update-secrets "TRACE_DB_URL=${TRACE_DB_SECRET}:latest"

echo "Done."
