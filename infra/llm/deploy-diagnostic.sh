#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:=mental-479910}"
: "${REGION:=us-central1}"
: "${DIAGNOSTIC_SERVICE_NAME:=care-llm-diagnostic}"
: "${IMAGE:=europe-west4-docker.pkg.dev/${PROJECT_ID}/care-images/vllm-gemma4-cu124:9b4e839}"

# Cloud Run treats commas in --args as separators. Keep this probe free of commas.
DIAG_SCRIPT='set -e
python3 -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.device_count())"
exec python3 -m http.server 8080'

gcloud beta run deploy "$DIAGNOSTIC_SERVICE_NAME" \
  --image="$IMAGE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --execution-environment=gen2 \
  --no-allow-unauthenticated \
  --cpu=4 \
  --memory=16Gi \
  --gpu=1 \
  --gpu-type=nvidia-l4 \
  --no-gpu-zonal-redundancy \
  --no-cpu-throttling \
  --min-instances=0 \
  --max-instances=1 \
  --concurrency=1 \
  --command=/bin/bash \
  --args="-c,$DIAG_SCRIPT"

gcloud beta run services logs read "$DIAGNOSTIC_SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --limit=100
