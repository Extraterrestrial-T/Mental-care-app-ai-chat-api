#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:=mental-479910}"
: "${REGION:=us-central1}"
: "${SERVICE_NAME:=care-llm}"
: "${SERVICE_ACCOUNT_ADDRESS:=care-llm-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
: "${MODEL_BUCKET:=lecunbuckett}"
: "${MODEL_ID:=unsloth/gemma-4-31B-it-unsloth-bnb-4bit}"
: "${IMAGE:=europe-west4-docker.pkg.dev/${PROJECT_ID}/care-images/vllm-gemma4-cu124:9b4e839}"

CONTAINER_ARGS=(
  "serve"
  "$MODEL_ID"
  "--host=0.0.0.0"
  "--port=8080"
  "--dtype=half"
  "--quantization=bitsandbytes"
  "--load-format=bitsandbytes"
  "--max-model-len=4096"
  "--max-num-seqs=1"
  "--max-num-batched-tokens=3072"
  "--gpu-memory-utilization=0.95"
  "--disable-uvicorn-access-log"
)

gcloud beta run deploy "$SERVICE_NAME" \
  --image="$IMAGE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --execution-environment=gen2 \
  --no-allow-unauthenticated \
  --command=vllm \
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
  --add-volume="mount-path=/models,type=cloud-storage,bucket=$MODEL_BUCKET,readonly=false" \
  --set-env-vars="HF_HOME=/models,TRANSFORMERS_CACHE=/models" \
  --set-secrets="HF_TOKEN=hf-token:latest" \
  --startup-probe=tcpSocket.port=8080,initialDelaySeconds=240,failureThreshold=10,timeoutSeconds=240,periodSeconds=240 \
  --args="$(IFS=','; echo "${CONTAINER_ARGS[*]}")"
