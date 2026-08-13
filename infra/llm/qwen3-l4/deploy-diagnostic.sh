#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:=mental-479910}"
: "${REGION:=us-central1}"
: "${SERVICE_NAME:=care-qwen3-gptq-diagnostic}"
: "${SERVICE_ACCOUNT_ADDRESS:=care-llm-sa@${PROJECT_ID}.iam.gserviceaccount.com}"

IMAGE="europe-west4-docker.pkg.dev/${PROJECT_ID}/care-images/vllm-qwen3-gptq-cu128-compat:v0.9.1"
DIAGNOSTIC_COMMAND='set -e; python3 -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.device_count()); assert torch.cuda.is_available(); assert torch.cuda.device_count() == 1"; exec python3 -m http.server 8080'

gcloud beta run deploy "$SERVICE_NAME" \
  --image="$IMAGE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --execution-environment=gen2 \
  --no-allow-unauthenticated \
  --command=/bin/bash \
  --args="-c,$DIAGNOSTIC_COMMAND" \
  --cpu=4 \
  --memory=16Gi \
  --gpu=1 \
  --gpu-type=nvidia-l4 \
  --no-gpu-zonal-redundancy \
  --no-cpu-throttling \
  --min-instances=0 \
  --max-instances=1 \
  --concurrency=1 \
  --timeout=1400 \
  --service-account="$SERVICE_ACCOUNT_ADDRESS" \
  --startup-probe=tcpSocket.port=8080,initialDelaySeconds=0,failureThreshold=24,timeoutSeconds=1,periodSeconds=10

gcloud beta run services logs read "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --limit=50
