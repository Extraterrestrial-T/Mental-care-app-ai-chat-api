#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:=mental-479910}"
: "${REGION:=us-central1}"
: "${SERVICE_NAME:=care-qwen3-32b}"
: "${SERVICE_ACCOUNT_ADDRESS:=care-llm-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
: "${MODEL_BUCKET:=lecunbuckett}"
# Do not inherit model or image values from earlier deployments in Cloud Shell.
# The dense 32B checkpoint avoids vLLM 0.8.5's BitsAndBytes MoE limitation.
MODEL_DIRECTORY="qwen3-32b-bnb-4bit-v1"
MODEL_PATH="/models/${MODEL_DIRECTORY}"
MODEL_ID="unsloth/Qwen3-32B-bnb-4bit"
IMAGE="docker.io/vllm/vllm-openai@sha256:6cf9808ca8810fc6c3fd0451c2e7784fb224590d81f7db338e7eaf3c02a33d33"

gcloud storage ls "gs://${MODEL_BUCKET}/${MODEL_DIRECTORY}/config.json" \
  --project="$PROJECT_ID" >/dev/null

# The vLLM image entrypoint is the OpenAI API server. Pass API server arguments
# directly; do not add the `vllm serve` subcommand.
CONTAINER_ARGS=(
  "--model=$MODEL_PATH"
  "--served-model-name=$MODEL_ID"
  "--host=0.0.0.0"
  "--port=8080"
  "--dtype=bfloat16"
  "--quantization=bitsandbytes"
  "--load-format=bitsandbytes"
  "--max-model-len=1024"
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
