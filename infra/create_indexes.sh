#!/usr/bin/env bash
# create_indexes.sh
# Run once to create Firestore vector indexes.
# Uses 768 dimensions (gemini-embedding-001 with output_dimensionality=768).
# Firestore max is 2048. Takes 5-10 minutes per index to build.
#
# Usage: ./create_indexes.sh YOUR_PROJECT_ID YOUR_DATABASE_NAME
# Example: ./create_indexes.sh bdas-493785 tigers-arcl

PROJECT_ID=${1:-"your-project-id"}
DATABASE=${2:-"tigers-arcl"}

echo "Creating Firestore vector indexes for project: $PROJECT_ID, database: $DATABASE"

COLLECTIONS=(arcl_rules arcl_faq arcl_players arcl_teams arcl_player_seasons)

for COLLECTION in "${COLLECTIONS[@]}"; do
  echo "Creating index for $COLLECTION..."
  gcloud firestore indexes composite create \
    --project="$PROJECT_ID" \
    --database="$DATABASE" \
    --collection-group="$COLLECTION" \
    --query-scope=COLLECTION \
    --field-config='vector-config={"dimension":"768","flat": "{}"},field-path=embedding'
done

echo ""
echo "Done. Monitor progress at:"
echo "https://console.firebase.google.com/project/$PROJECT_ID/firestore/indexes"