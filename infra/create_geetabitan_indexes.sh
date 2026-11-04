#!/bin/bash
# infra/create_geetabitan_indexes.sh
# Creates the Firestore database and all composite + vector indexes
# needed for Geetabitan — across all composer collections (Rabindra
# Sangeet, Nazrul Geeti, Rajanikanta Sen, Atulprasad Sen). Run once
# before the first ingestion of a given collection; safe to re-run
# (gcloud reports ALREADY_EXISTS for indexes that were already created
# and continues).

set -uo pipefail
PROJECT="bdas-493785"
DB="geetabitan-db"
REGION="us-central1"

# Rabindra Sangeet is grouped by "paryay"; Nazrul Geeti and Rajanikanta
# Sen are grouped by "category" (see CATEGORY_ORGANIZED_COMPOSERS in
# domains/geetabitan/tools/song_tools.py). Each entry is
# "<collection>:<grouping-field>".
#
# Atulprasad Sen uses "paryay" too (same field name/shape as Rabindra's
# grouping field, since he isn't in CATEGORY_ORGANIZED_COMPOSERS — see
# atulprasad_lyrics_loader.py's docstring), but it's confirmed on only
# 4 of his 205 songs. The paryay/raag and paryay/taal composite indexes
# below are still created for consistency with every other composer and
# because gcloud index creation is cheap and idempotent, but they'll see
# little real use until/unless more Atulprasad paryay data turns up —
# this is a known, accepted trade-off, not an oversight.
COLLECTIONS=(
    "geetabitan_songs:paryay"
    "nazrulgeeti_songs:category"
    "rajanikanta_songs:category"
    "atulprasad_songs:paryay"
    # Dwijendralal Roy's songs are grouped by category too (the play each
    # song was written for -- see DWIJENDRALAL_CATEGORY_LIST in config.py).
    "dwijendralal_songs:category"
)

#echo "1. Creating Firestore database: ${DB} …"
#gcloud firestore databases create \
#    --database="${DB}" \
#    --location="${REGION}" \
#    --project="${PROJECT}"

for entry in "${COLLECTIONS[@]}"; do
    COL="${entry%%:*}"
    GROUP_FIELD="${entry##*:}"

    echo ""
    echo "=== ${COL} (grouped by ${GROUP_FIELD}) ==="

    echo "2. Creating composite indexes on ${COL} …"

    # raag + grouping field — get_songs_by_raag filtered by paryay/category
    gcloud firestore indexes composite create \
        --collection-group="${COL}" \
        --field-config field-path=raag,order=ASCENDING \
        --field-config field-path="${GROUP_FIELD}",order=ASCENDING \
        --database="${DB}" --project="${PROJECT}"

    # taal + grouping field — get_songs_by_taal filtered by paryay/category
    gcloud firestore indexes composite create \
        --collection-group="${COL}" \
        --field-config field-path=taal,order=ASCENDING \
        --field-config field-path="${GROUP_FIELD}",order=ASCENDING \
        --database="${DB}" --project="${PROJECT}"

    # raag + taal — cross-filter queries
    gcloud firestore indexes composite create \
        --collection-group="${COL}" \
        --field-config field-path=raag,order=ASCENDING \
        --field-config field-path=taal,order=ASCENDING \
        --database="${DB}" --project="${PROJECT}"

    # grouping field only — get_songs_by_paryay / get_songs_by_category
    gcloud firestore indexes composite create \
        --collection-group="${COL}" \
        --field-config field-path="${GROUP_FIELD}",order=ASCENDING \
        --field-config field-path=title,order=ASCENDING \
        --database="${DB}" --project="${PROJECT}"

    # title — get_song_by_title
    gcloud firestore indexes composite create \
        --collection-group="${COL}" \
        --field-config field-path=title,order=ASCENDING \
        --database="${DB}" --project="${PROJECT}"

    echo ""
    echo "3. Creating vector search index (768-dim Gemini embeddings) on ${COL} …"
    gcloud firestore indexes composite create \
        --collection-group="${COL}" \
        --field-config field-path=embedding,vector-config='{"dimension":"768","flat":{}}' \
        --database="${DB}" --project="${PROJECT}"
done

echo ""
echo "✅ All indexes requested for: ${COLLECTIONS[*]}"
echo "   (ALREADY_EXISTS for any index means a previous run already created it — safe to ignore.)"
echo "   They may take a few minutes to build."
echo "   Check status: gcloud firestore indexes list --database=${DB} --project=${PROJECT}"
