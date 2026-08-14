#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:=mental-479910}"
: "${REGION:=us-central1}"
: "${SERVICE_NAME:=care-qwen3-gptq}"
: "${SERVICE_ACCOUNT_ADDRESS:=care-llm-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
: "${MODEL_BUCKET:=lecunbuckett}"
# Do not inherit model or image values from earlier deployments in Cloud Shell.
# vLLM 0.9.1 supports the Qwen3 GPTQ MoE checkpoint; vLLM 0.8.5 does not
# initialize the BitsAndBytes MoE quantizer and fails with quant_method=None.
MODEL_DIRECTORY="qwen3-30b-a3b-gptq-int4-v1"
MODEL_PATH="/models/${MODEL_DIRECTORY}"
MODEL_ID="Qwen/Qwen3-30B-A3B-GPTQ-Int4"
IMAGE="europe-west4-docker.pkg.dev/${PROJECT_ID}/care-images/vllm-qwen3-gptq-cu124:v0.9.1"

gcloud storage ls "gs://${MODEL_BUCKET}/${MODEL_DIRECTORY}/config.json" \
  --project="$PROJECT_ID" >/dev/null

# The vLLM image entrypoint is the OpenAI API server. Pass API server arguments
# directly; do not add the `vllm serve` subcommand.
CONTAINER_ARGS=(
  "--model=$MODEL_PATH"
  "--served-model-name=$MODEL_ID"
  "--host=0.0.0.0"
  "--port=8080"
  "--dtype=half"
  "--quantization=gptq"
  "--load-format=safetensors"
  "--max-model-len=2048"
  "--max-num-seqs=1"
  "--max-num-batched-tokens=2048"
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
