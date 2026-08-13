#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:=mental-479910}"
: "${REGION:=us-central1}"
: "${CACHE_JOB_NAME:=cache-qwen3-30b-a3b}"
: "${SERVICE_ACCOUNT_ADDRESS:=care-llm-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
: "${MODEL_BUCKET:=lecunbuckett}"
# Do not inherit a model ID or cache prefix from an earlier deployment. The
# original prefix was populated with Gemma files before this job was isolated.
MODEL_ID="unsloth/Qwen3-30B-A3B-bnb-4bit"
MODEL_DIRECTORY="qwen3-30b-a3b-bnb-4bit-v2"

# This job avoids Cloud Run's 240-second service startup-probe limit. It writes
# a complete Hugging Face snapshot to Cloud Storage before the inference service
# mounts that directory read-only.
CACHE_COMMAND='pip install --no-cache-dir "huggingface_hub==0.32.0" && huggingface-cli download "$MODEL_ID" --max-workers 1 --local-dir "/models/$MODEL_DIRECTORY"'

gcloud beta run jobs deploy "$CACHE_JOB_NAME" \
  --image=python:3.11-slim \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --command=/bin/sh \
  --args="-c,$CACHE_COMMAND" \
  --task-timeout=3600 \
  --max-retries=0 \
  --cpu=2 \
  --memory=8Gi \
  --service-account="$SERVICE_ACCOUNT_ADDRESS" \
  --add-volume="mount-path=/models,type=cloud-storage,bucket=$MODEL_BUCKET,readonly=false" \
  --set-env-vars="HF_HOME=/models/.cache/huggingface,MODEL_ID=$MODEL_ID,MODEL_DIRECTORY=$MODEL_DIRECTORY" \
  --set-secrets="HF_TOKEN=hf-token:latest"

gcloud beta run jobs execute "$CACHE_JOB_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --wait
