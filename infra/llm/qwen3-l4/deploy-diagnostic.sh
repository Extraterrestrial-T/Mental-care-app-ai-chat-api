#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:=mental-479910}"
: "${REGION:=us-central1}"
: "${SERVICE_NAME:=care-qwen3-14b-diagnostic}"
: "${SERVICE_ACCOUNT_ADDRESS:=care-llm-sa@${PROJECT_ID}.iam.gserviceaccount.com}"

IMAGE="docker.io/vllm/vllm-openai@sha256:6cf9808ca8810fc6c3fd0451c2e7784fb224590d81f7db338e7eaf3c02a33d33"
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
