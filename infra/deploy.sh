#!/bin/bash
set -e
echo "Building Docker image..."
docker build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest \
  .

echo "Pushing to Artifact Registry..."
docker push us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest

echo "Deploying to Cloud Run..."
gcloud run deploy adar-arcl-api \
  --image us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest \
  --region us-central1

echo "Done."
