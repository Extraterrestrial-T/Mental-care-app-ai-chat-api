#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:=mental-479910}"
: "${REGION:=us-central1}"
: "${SERVICE_NAME:=care-qwen3}"
: "${MODEL_ID:=unsloth/Qwen3-30B-A3B-bnb-4bit}"

SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --format='value(status.url)')"
IDENTITY_TOKEN="$(gcloud auth print-identity-token)"

curl --fail-with-body -sS "$SERVICE_URL/v1/models" \
  -H "Authorization: Bearer $IDENTITY_TOKEN"
echo

curl --fail-with-body -sS "$SERVICE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $IDENTITY_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(cat <<JSON
{
  "model": "$MODEL_ID",
  "messages": [
    {"role": "system", "content": "Respond briefly and clearly."},
    {"role": "user", "content": "Say hello in one sentence."}
  ],
  "max_tokens": 64,
  "temperature": 0.2,
  "chat_template_kwargs": {"enable_thinking": false}
}
JSON
)"
echo
