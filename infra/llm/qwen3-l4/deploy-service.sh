#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:=mental-479910}"
: "${REGION:=us-central1}"
: "${SERVICE_NAME:=care-qwen3-14b}"
: "${SERVICE_ACCOUNT_ADDRESS:=care-llm-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
: "${MODEL_BUCKET:=lecunbuckett}"
# Do not inherit model or image values from earlier deployments in Cloud Shell.
# The dense 14B checkpoint leaves usable KV-cache capacity on a single L4.
MODEL_DIRECTORY="qwen3-14b-bnb-4bit-v1"
MODEL_PATH="/models/${MODEL_DIRECTORY}"
MODEL_ID="unsloth/Qwen3-14B-bnb-4bit"
IMAGE="europe-west4-docker.pkg.dev/${PROJECT_ID}/care-images/vllm-qwen3-startup-proxy:v0.8.5-cu124"

gcloud storage ls "gs://${MODEL_BUCKET}/${MODEL_DIRECTORY}/config.json" \
  --project="$PROJECT_ID" >/dev/null

# The proxy keeps Cloud Run's public port open while vLLM loads from GCS FUSE.
# It forwards requests to the private vLLM server once that server is ready.
CONTAINER_ARGS=(
  "--model=$MODEL_PATH"
  "--served-model-name=$MODEL_ID"
  "--dtype=bfloat16"
  "--quantization=bitsandbytes"
  "--load-format=bitsandbytes"
  "--max-model-len=4096"
  "--max-num-seqs=1"
  "--max-num-batched-tokens=1024"
  "--gpu-memory-utilization=0.90"
  "--enforce-eager"
)

gcloud beta run deploy "$SERVICE_NAME" \
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
  --timeout=1400 \
  --service-account="$SERVICE_ACCOUNT_ADDRESS" \
  --add-volume="mount-path=/models,type=cloud-storage,bucket=$MODEL_BUCKET,readonly=true" \
  --set-env-vars="HF_HOME=/tmp/huggingface" \
  --startup-probe=tcpSocket.port=8080,initialDelaySeconds=0,failureThreshold=24,timeoutSeconds=1,periodSeconds=10 \
  --args="$(IFS=','; echo "${CONTAINER_ARGS[*]}")"
