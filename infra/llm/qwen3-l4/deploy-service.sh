#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:=mental-479910}"
: "${REGION:=us-central1}"
: "${SERVICE_NAME:=care-qwen3}"
: "${SERVICE_ACCOUNT_ADDRESS:=care-llm-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
: "${MODEL_BUCKET:=lecunbuckett}"
# Do not inherit model or image values from earlier Gemma deployments in the
# Cloud Shell. This script deploys one specific, pinned Qwen runtime.
MODEL_DIRECTORY="qwen3-30b-a3b-bnb-4bit-v2"
MODEL_PATH="/models/${MODEL_DIRECTORY}"
MODEL_ID="unsloth/Qwen3-30B-A3B-bnb-4bit"
IMAGE="docker.io/vllm/vllm-openai@sha256:6cf9808ca8810fc6c3fd0451c2e7784fb224590d81f7db338e7eaf3c02a33d33"

gcloud storage ls "gs://${MODEL_BUCKET}/${MODEL_DIRECTORY}/config.json" \
  --project="$PROJECT_ID" >/dev/null

# The image entrypoint is the `vllm` CLI, so `serve` must be its first argument.
CONTAINER_ARGS=(
  "serve"
  "$MODEL_PATH"
  "--served-model-name=$MODEL_ID"
  "--host=0.0.0.0"
  "--port=8080"
  "--dtype=bfloat16"
  "--quantization=bitsandbytes"
  "--load-format=bitsandbytes"
  "--max-model-len=2048"
  "--max-num-seqs=1"
  "--max-num-batched-tokens=2048"
  "--gpu-memory-utilization=0.92"
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
