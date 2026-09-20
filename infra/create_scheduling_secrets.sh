#!/bin/bash
# infra/create_scheduling_secrets.sh
# Creates GCP Secret Manager secrets for the Scheduling domain.
# Run once before the first deploy.
#
# Deliberately NOT created here — reused from existing shared secrets
# (see infra/deploy-scheduling.sh's --set-secrets for the full mapping):
#   google-api-key, gmail-user, gmail-app-password, from-email,
#   geetabitan-tts-api-key, geetabitan-speech-api-key
# Stripe uses the shared stripe-secret-key plus scheduling-specific webhook
# and recurring Price identifiers.

set -euo pipefail
PROJECT="bdas-493785"

echo "Creating Scheduling secrets in project ${PROJECT} …"

gcloud secrets describe scheduling-jwt-secret --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud secrets create scheduling-jwt-secret \
    --data-file=<(openssl rand -hex 32) --project="${PROJECT}"

gcloud secrets describe scheduling-api-key --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud secrets create scheduling-api-key \
    --data-file=<(openssl rand -hex 32) --project="${PROJECT}"

gcloud secrets describe scheduling-admin-email --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud secrets create scheduling-admin-email --project="${PROJECT}"
gcloud secrets describe scheduling-admin-password --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud secrets create scheduling-admin-password --project="${PROJECT}"

for secret in \
  scheduling-stripe-webhook-secret \
  scheduling-stripe-price-monthly \
  scheduling-stripe-price-yearly; do
  gcloud secrets describe "$secret" --project="${PROJECT}" >/dev/null 2>&1 || \
    gcloud secrets create "$secret" --replication-policy=automatic --project="${PROJECT}"
done

# Observability (Phase 3 of the build plan) — not created automatically:
# create the "scheduling" database/schema on the existing adar-pgdev Cloud
# SQL instance first (the same instance restaurants/geetabitan already use,
# see infra/deploy-scheduling.sh), then:
#   gcloud secrets create scheduling-trace-db-url --project="${PROJECT}" \
#     --data-file=<(echo -n "postgresql://USER:PASSWORD@HOST:5432/DBNAME")
# Leave it uncreated (and OTEL_ENABLED=false) to keep this deploy's
# observability inert.

echo ""
echo "Secrets created. Now fill in the empty ones:"
echo "  gcloud secrets versions add scheduling-admin-email    --data-file=<(echo -n 'you@example.com')"
echo "  gcloud secrets versions add scheduling-admin-password --data-file=<(echo -n 'yourpassword')"
echo "  gcloud secrets versions add scheduling-stripe-webhook-secret --data-file=<(echo -n 'whsec_...')"
echo "  gcloud secrets versions add scheduling-stripe-price-monthly --data-file=<(echo -n 'price_...')"
echo "  gcloud secrets versions add scheduling-stripe-price-yearly  --data-file=<(echo -n 'price_...')"
