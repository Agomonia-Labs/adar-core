#!/bin/bash
# infra/create_geetabitan_secrets.sh
# Creates GCP Secret Manager secrets for Geetabitan.
# Run once before the first deploy.
# google-api-key is shared with ARCL — not recreated here.

set -euo pipefail
PROJECT="bdas-493785"

echo "Creating Geetabitan secrets in project ${PROJECT} …"

gcloud secrets create geetabitan-api-key \
    --data-file=<(openssl rand -hex 32) --project="${PROJECT}"

gcloud secrets create geetabitan-jwt-secret \
    --data-file=<(openssl rand -hex 32) --project="${PROJECT}"

gcloud secrets create geetabitan-admin-email      --project="${PROJECT}"
gcloud secrets create geetabitan-admin-password   --project="${PROJECT}"

gcloud secrets create geetabitan-stripe-webhook-secret  --project="${PROJECT}"
gcloud secrets create geetabitan-stripe-price-basic     --project="${PROJECT}"
gcloud secrets create geetabitan-stripe-price-standard  --project="${PROJECT}"
gcloud secrets create geetabitan-stripe-price-unlimited --project="${PROJECT}"

gcloud secrets create geetabitan-frontend-url \
    --data-file=<(echo -n "https://geetabitan.adar.agomoniai.com") \
    --project="${PROJECT}"

echo ""
echo "Secrets created. Now fill in the empty ones:"
echo "  gcloud secrets versions add geetabitan-admin-email    --data-file=<(echo -n 'you@example.com')"
echo "  gcloud secrets versions add geetabitan-admin-password --data-file=<(echo -n 'yourpassword')"
echo "  gcloud secrets versions add geetabitan-stripe-*       --data-file=<(echo -n 'sk_...')"
