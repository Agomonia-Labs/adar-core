#!/bin/bash
# infra/create_geetabitan_indexes.sh
# Creates the Firestore database and all composite + vector indexes
# needed for Geetabitan. Run once before the first ingestion.

set -euo pipefail
PROJECT="bdas-493785"
DB="geetabitan-db"
REGION="us-central1"
COL="geetabitan_songs"


#echo "1. Creating Firestore database: ${DB} …"
#gcloud firestore databases create \
#    --database="${DB}" \
#    --location="${REGION}" \
#    --project="${PROJECT}"

echo ""
echo "2. Creating composite indexes on ${COL} …"

# raag + paryay — get_songs_by_raag filtered by paryay
gcloud firestore indexes composite create \
    --collection-group="${COL}" \
    --field-config field-path=raag,order=ASCENDING \
    --field-config field-path=paryay,order=ASCENDING \
    --database="${DB}" --project="${PROJECT}"

# taal + paryay — get_songs_by_taal filtered by paryay
gcloud firestore indexes composite create \
    --collection-group="${COL}" \
    --field-config field-path=taal,order=ASCENDING \
    --field-config field-path=paryay,order=ASCENDING \
    --database="${DB}" --project="${PROJECT}"

# raag + taal — cross-filter queries
gcloud firestore indexes composite create \
    --collection-group="${COL}" \
    --field-config field-path=raag,order=ASCENDING \
    --field-config field-path=taal,order=ASCENDING \
    --database="${DB}" --project="${PROJECT}"

# paryay only — get_songs_by_paryay
gcloud firestore indexes composite create \
    --collection-group="${COL}" \
    --field-config field-path=paryay,order=ASCENDING \
    --field-config field-path=title,order=ASCENDING \
    --database="${DB}" --project="${PROJECT}"

# title — get_song_by_title
gcloud firestore indexes composite create \
    --collection-group="${COL}" \
    --field-config field-path=title,order=ASCENDING \
    --database="${DB}" --project="${PROJECT}"

echo ""
echo "3. Creating vector search index (768-dim Gemini embeddings) …"
gcloud firestore indexes composite create \
    --collection-group="${COL}" \
    --field-config field-path=embedding,vector-config='{"dimension":"768","flat":{}}' \
    --database="${DB}" --project="${PROJECT}"

echo ""
echo "✅ All indexes created. They may take a few minutes to build."
echo "   Check status: gcloud firestore indexes list --database=${DB} --project=${PROJECT}"
